#!/usr/bin/env python3
"""Read-only in-cluster Istio / Cloud Service Mesh skew and Envoy xDS NACK detector.

Inspects Kubernetes control-plane revisions (`istiod` Deployments and
`ControlPlaneRevision` resources in `istio-system`/`asm-system`, falling back to
`istio-sidecar-injector*` MutatingWebhookConfigurations when no active
control-plane resource is present), running `istio-proxy` sidecars (both regular
containers and native-sidecar initContainers, plus `istio.io/rev` and
`proxy.istio.io/config` metadata), `istio-proxy` `OOMKilled` (exit code 137)
restarts, Envoy xDS NACK logs and metrics (`LDS`/`RDS`/`CDS`/`EDS`, including
`istio_authn`), and ingress gateway HTTP 503 `UH` (`no_healthy_upstream`) access
logs.

Pure read-only `kubectl` (no GKE Hub API calls and no cluster mutations). All
cluster-wide reads page through `collector_run.paged_list` and all log reads are
bounded (`--tail=200`) to stay within the credential proxy's output cap.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Shared imports (collector_run + readiness_rules)
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_SCRIPT_DIRS = (
    "/opt/defaults/scripts",
    "/opt/data/scripts",
    *(
        [str(SCRIPT_DIR.parents[2] / "scripts")]
        if len(SCRIPT_DIR.parents) > 2
        else []
    ),
)
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
for _shared_dir in SHARED_SCRIPT_DIRS:
    if _shared_dir not in sys.path:
        sys.path.append(_shared_dir)

import collector_run  # noqa: E402
import readiness_rules  # noqa: E402

# ---------------------------------------------------------------------------
# Constants (declared at module top per .agents/rules/core_engineering.md)
# ---------------------------------------------------------------------------

KUBECTL_BIN = "kubectl"
KUBECTL_GET_VERB = "get"
KUBECTL_LOGS_VERB = "logs"
KUBECTL_NAMESPACE_FLAG = "-n"
KUBECTL_OUTPUT_FLAG = "-o"
KUBECTL_OUTPUT_JSON = "json"
KUBECTL_CONTAINER_FLAG = "-c"
KUBECTL_CONTEXT_FLAG = "--context"
KUBECTL_PREVIOUS_FLAG = "--previous"
KUBECTL_TAIL_FLAG_TEMPLATE = "--tail={lines}"
KUBECONFIG_ENV_KEY = "KUBECONFIG"

DEPLOYMENTS_RESOURCE = "deployments"
CPR_RESOURCE = "controlplanerevisions.mesh.cloud.google.com"
PODS_RESOURCE = "pods"
MWC_RESOURCE = "mutatingwebhookconfigurations"

DEFAULT_TIMEOUT_S = 30
LOG_TAIL_LINES = 200
MAX_SAMPLED_SIDECAR_LOG_PODS = 10
MAX_SAMPLED_ISTIOD_LOG_PODS = 4
MAX_SAMPLED_GATEWAY_LOG_PODS = 4
MAX_SAMPLE_LINES = 5
ERROR_EXCERPT_CHARS = 240
JSON_INDENT = 2

PROXY_TRUNCATION_MARKER = readiness_rules.PROXY_TRUNCATION_MARKER

SOURCE_DEPLOYMENT = "Deployment"
SOURCE_CPR = "ControlPlaneRevision"
SOURCE_MWC = "MutatingWebhookConfiguration"
AUTHORITATIVE_CP_SOURCES = frozenset({SOURCE_DEPLOYMENT, SOURCE_CPR})

CONTAINER_KIND_REGULAR = "container"
CONTAINER_KIND_INIT = "initContainer"
PROM_COMMENT_PREFIX = "#"
PROM_PUSHES_METRIC = "pilot_xds_pushes"
PROM_REJECTED_MARKER = "rejected"

MESH_CONTROL_PLANE_NAMESPACES = ("istio-system", "asm-system")
ISTIOD_NAME_PREFIX = "istiod"
INJECTOR_WEBHOOK_PREFIX = "istio-sidecar-injector"
ISTIO_PROXY_CONTAINER = "istio-proxy"
ISTIO_REV_LABEL = "istio.io/rev"
PROXY_CONFIG_ANNOTATION = "proxy.istio.io/config"
MANAGED_CPR_LABEL = "mesh.cloud.google.com/managed-cpr"
CPR_VERSION_ANNOTATIONS = (
    "mesh.cloud.google.com/version",
    "mesh.cloud.google.com/control-plane-version",
    "istio.io/version",
)
GATEWAY_LABEL_KEYS = (
    ("istio", "ingressgateway"),
    ("app", "istio-ingressgateway"),
)
GATEWAY_API_LABEL = "gateway.networking.k8s.io/gateway-name"

OOM_REASON = "OOMKilled"
OOM_EXIT_CODE = 137
MAX_SUPPORTED_SIDECAR_LAG_MINORS = 1

SEVERITY_CRITICAL = "critical"
SEVERITY_MAJOR = "major"
SEVERITY_MINOR = "minor"

CHECK_CP_OLDER_THAN_SIDECAR = "control-plane-older-than-sidecar"
CHECK_ENVOY_XDS_NACK_LOOP = "envoy-xds-nack-loop"
CHECK_SIDECAR_LAG_SKEW = "sidecar-older-than-control-plane-skew"
CHECK_MIXED_SIDECAR_REVISIONS = "mixed-sidecar-revisions"

STATUS_OK = "ok"
STATUS_FINDINGS = "findings"
STATUS_NO_MESH = "no-mesh-detected"
STATUS_UNREAD = "partial-unread"

FORMAT_TEXT = "text"
FORMAT_JSON = "json"
VALID_FORMATS = (FORMAT_TEXT, FORMAT_JSON)

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_READ_ERROR = 2

NOT_FOUND_MARKERS = (
    "the server could not find the requested resource",
    "the server doesn't have a resource type",
    "NotFound",
    "not found",
)

MANAGED_CHANNEL_REVISIONS = {
    "asm-managed-rapid": "RAPID",
    "asm-managed": "REGULAR",
    "asm-managed-regular": "REGULAR",
    "asm-managed-stable": "STABLE",
}

SEMVER_TAG_RE = re.compile(r"(?:^|[^0-9])v?(\d+)\.(\d+)(?:\.(\d+))?")
ASM_COMPACT_REV_RE = re.compile(r"(?:^|[-_/])asm-(\d)(\d{2})(?:-(\d+))?(?:$|[^0-9])", re.IGNORECASE)
DASH_REV_RE = re.compile(r"(?:^|[-_/])(\d+)-(\d+)(?:-(\d+))?(?:$|[^0-9])")
PROXY_CONFIG_DISCOVERY_RE = re.compile(r"discoveryAddress\s*:\s*([^\s,}\]]+)")
PROXY_CONFIG_REV_RE = re.compile(r"istiod-([a-z0-9-]+)\.(?:istio-system|asm-system)", re.IGNORECASE)

ENVOY_XDS_REJECT_RE = re.compile(
    r"gRPC config for type\.googleapis\.com/envoy\.config\."
    r"(?:listener\.v3\.Listener|route\.v3\.RouteConfiguration|"
    r"cluster\.v3\.Cluster|endpoint\.v3\.ClusterLoadAssignment)"
    r"\s+rejected:\s*(.*)",
    re.IGNORECASE,
)
ENVOY_XDS_TYPE_MAP = (
    ("envoy.config.listener.v3.Listener", "LDS"),
    ("envoy.config.route.v3.RouteConfiguration", "RDS"),
    ("envoy.config.endpoint.v3.ClusterLoadAssignment", "EDS"),
    ("envoy.config.cluster.v3.Cluster", "CDS"),
)
XDS_SHORT_TYPES = tuple(short for _, short in ENVOY_XDS_TYPE_MAP)
ISTIO_AUTHN_MARKER = "istio_authn"

ISTIOD_NACK_RE = re.compile(
    r"\bADS:(LDS|RDS|CDS|EDS):[^\n]*\b(?:NACK|rejected)\b|\bxds\b[^\n]*\b(?:NACK|rejected)\b",
    re.IGNORECASE,
)

PROM_XDS_REJECT_RE = re.compile(
    r"^(pilot_total_xds_rejects|pilot_xds_pushes|envoy_cluster_update_rejected)"
    r"(?:\{([^}]*)\})?\s+([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?\d+)?)\s*$"
)
PROM_METRIC_TYPE_RE = re.compile(r'type="([^"]+)"')

GATEWAY_503_UH_RE = re.compile(
    r'(?:"response_flag"\s*:\s*"UH"|response_flag:\s*"?UH"?|\b503\s+UH\b|\bno_healthy_upstream\b)',
    re.IGNORECASE,
)

PREFLIGHT_CHANNEL_WARNING = (
    "Managed Cloud Service Mesh follows the cluster's GKE release channel: switching a cluster "
    "from no release channel (static version) or a faster channel onto STABLE/REGULAR/RAPID can "
    "downgrade the managed mesh control plane below running istio-proxy sidecars, triggering "
    "unbounded Envoy xDS NACK loops, istio-proxy OOMKills, and ingress 503 UH no_healthy_upstream "
    "outages. Verify the target channel's managed mesh revision against running sidecars (and have "
    "an operator confirm with `gcloud container fleet mesh describe --project <host_project>`) "
    "before proposing or applying any release-channel change."
)

DO_NOT_RAISE_MEMORY_NOTE = (
    "Do not treat istio-proxy OOMKilled restarts as a memory-sizing issue while Envoy xDS NACK "
    "rejections are active: raising resources.limits.memory only delays OOMKill while the "
    "reject-and-retry loop continues leaking memory. Align the release channel / mesh control-plane "
    "revision at or above the sidecar minor version and roll affected workloads so sidecars match "
    "the active control plane."
)

# Bind shared runner names from collector_run (tested by test_collector_run.py).
Run = collector_run.Run
RunFn = Callable[..., Run]
paged_list = collector_run.paged_list
default_run = functools.partial(collector_run.default_run, timeout=DEFAULT_TIMEOUT_S)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlPlaneRecord:
    source: str
    namespace: str
    name: str
    revision: str
    minor: tuple[int, int] | None
    version_text: str
    managed_channel: str | None = None


@dataclass(frozen=True)
class SidecarRecord:
    namespace: str
    pod: str
    container_kind: str
    image: str
    minor: tuple[int, int] | None
    version_text: str
    rev_label: str
    proxy_config_rev: str
    restart_count: int
    oom_killed: bool
    last_exit_code: int | None


@dataclass
class XdsNackSummary:
    proxy_nack_count: int = 0
    istiod_nack_count: int = 0
    metric_reject_total: float = 0.0
    xds_types: list[str] = field(default_factory=list)
    istio_authn_seen: bool = False
    affected_pods: list[str] = field(default_factory=list)
    sample_lines: list[str] = field(default_factory=list)


@dataclass
class Gateway503Summary:
    uh_503_count: int = 0
    affected_pods: list[str] = field(default_factory=list)
    sample_lines: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    summary: str
    cause: str
    recommendation: str
    evidence: dict[str, Any]


# ---------------------------------------------------------------------------
# Version & metadata parsing
# ---------------------------------------------------------------------------


def format_minor(minor: tuple[int, int] | None) -> str:
    if minor is None:
        return "unknown"
    return f"{minor[0]}.{minor[1]}"


def parse_version_minor(text: str | None) -> tuple[tuple[int, int] | None, str]:
    """Parse an Istio/ASM image tag or revision string into ((major, minor), display)."""
    raw = (text or "").strip()
    if not raw:
        return None, ""
    candidate = raw.split("@", 1)[0]
    if "/" in candidate or ":" in candidate:
        last_segment = candidate.rsplit("/", 1)[-1]
        if ":" in last_segment:
            candidate = last_segment.rsplit(":", 1)[1]
        else:
            candidate = last_segment

    compact = ASM_COMPACT_REV_RE.search(candidate)
    if compact:
        return (int(compact.group(1)), int(compact.group(2))), candidate

    semver = SEMVER_TAG_RE.search(candidate)
    if semver:
        return (int(semver.group(1)), int(semver.group(2))), candidate

    dashed = DASH_REV_RE.search(candidate)
    if dashed:
        return (int(dashed.group(1)), int(dashed.group(2))), candidate

    return None, candidate


def parse_proxy_config_revision(annotation: str | None) -> str:
    """Extract a revision hint from `proxy.istio.io/config` discoveryAddress, if present."""
    raw = (annotation or "").strip()
    if not raw:
        return ""
    discovery = PROXY_CONFIG_DISCOVERY_RE.search(raw)
    if not discovery:
        return ""
    rev = PROXY_CONFIG_REV_RE.search(discovery.group(1))
    return rev.group(1) if rev else ""


def _managed_channel_for(revision: str) -> str | None:
    return MANAGED_CHANNEL_REVISIONS.get((revision or "").strip().lower())


# ---------------------------------------------------------------------------
# Resource extraction
# ---------------------------------------------------------------------------


def extract_control_plane_records(
    deployments: list[dict[str, Any]],
    control_plane_revisions: list[dict[str, Any]] | None = None,
    mutating_webhooks: list[dict[str, Any]] | None = None,
) -> list[ControlPlaneRecord]:
    """Extract active Istio / ASM control-plane records from Kubernetes objects."""
    records: list[ControlPlaneRecord] = []

    for dep in deployments or []:
        if not isinstance(dep, dict):
            continue
        meta = dep.get("metadata") or {}
        name = str(meta.get("name") or "")
        namespace = str(meta.get("namespace") or "")
        if not name.startswith(ISTIOD_NAME_PREFIX):
            continue
        spec = dep.get("spec") or {}
        replicas = spec.get("replicas")
        if isinstance(replicas, int) and replicas == 0:
            continue
        labels = meta.get("labels") or {}
        rev_label = str(labels.get(ISTIO_REV_LABEL) or "")
        containers = ((spec.get("template") or {}).get("spec") or {}).get("containers") or []
        image = ""
        for container in containers:
            if isinstance(container, dict) and container.get("image"):
                image = str(container["image"])
                break
        minor, version_text = parse_version_minor(image)
        if minor is None and rev_label:
            minor, version_text = parse_version_minor(rev_label)
        if minor is None:
            minor, version_text = parse_version_minor(name)
        records.append(
            ControlPlaneRecord(
                source=SOURCE_DEPLOYMENT,
                namespace=namespace,
                name=name,
                revision=rev_label or name,
                minor=minor,
                version_text=version_text or image or name,
                managed_channel=_managed_channel_for(rev_label or name),
            )
        )

    for cpr in control_plane_revisions or []:
        if not isinstance(cpr, dict):
            continue
        meta = cpr.get("metadata") or {}
        name = str(meta.get("name") or "")
        namespace = str(meta.get("namespace") or "")
        labels = meta.get("labels") or {}
        annotations = meta.get("annotations") or {}
        spec = cpr.get("spec") or {}
        status = cpr.get("status") or {}

        channel = str((spec.get("channel") or "")).upper() or _managed_channel_for(name)
        minor: tuple[int, int] | None = None
        version_text = ""

        candidates = [
            status.get("version"),
            status.get("controlPlaneVersion"),
            *(annotations.get(key) for key in CPR_VERSION_ANNOTATIONS),
            labels.get(ISTIO_REV_LABEL),
            name,
        ]
        for candidate in candidates:
            if not candidate:
                continue
            parsed, display = parse_version_minor(str(candidate))
            if parsed is not None:
                minor = parsed
                version_text = display
                break

        if not version_text:
            version_text = str(labels.get(MANAGED_CPR_LABEL) or name)

        records.append(
            ControlPlaneRecord(
                source=SOURCE_CPR,
                namespace=namespace,
                name=name,
                revision=str(labels.get(ISTIO_REV_LABEL) or name),
                minor=minor,
                version_text=version_text,
                managed_channel=channel or None,
            )
        )

    for mwc in mutating_webhooks or []:
        if not isinstance(mwc, dict):
            continue
        meta = mwc.get("metadata") or {}
        name = str(meta.get("name") or "")
        if not name.startswith(INJECTOR_WEBHOOK_PREFIX):
            continue
        labels = meta.get("labels") or {}
        rev_label = str(labels.get(ISTIO_REV_LABEL) or "")
        rev_source = rev_label or name
        minor, version_text = parse_version_minor(rev_source)
        records.append(
            ControlPlaneRecord(
                source=SOURCE_MWC,
                namespace="",
                name=name,
                revision=rev_source,
                minor=minor,
                version_text=version_text or rev_source,
                managed_channel=_managed_channel_for(rev_source),
            )
        )

    return records


def _container_status_map(statuses: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for entry in statuses or []:
        if isinstance(entry, dict) and entry.get("name"):
            mapping[str(entry["name"])] = entry
    return mapping


def _oom_details(status_entry: dict[str, Any] | None) -> tuple[int, bool, int | None]:
    if not isinstance(status_entry, dict):
        return 0, False, None
    restarts = int(status_entry.get("restartCount") or 0)
    oom = False
    last_exit: int | None = None
    for state_key in ("state", "lastState"):
        terminated = (status_entry.get(state_key) or {}).get("terminated") or {}
        if not isinstance(terminated, dict):
            continue
        reason = str(terminated.get("reason") or "")
        exit_code = terminated.get("exitCode")
        if isinstance(exit_code, int):
            last_exit = exit_code
        if reason == OOM_REASON or exit_code == OOM_EXIT_CODE:
            oom = True
    return restarts, oom, last_exit


def extract_sidecar_records(pods: list[dict[str, Any]]) -> list[SidecarRecord]:
    """Extract running/existing istio-proxy sidecars (regular + native initContainer)."""
    records: list[SidecarRecord] = []
    for pod in pods or []:
        if not isinstance(pod, dict):
            continue
        meta = pod.get("metadata") or {}
        spec = pod.get("spec") or {}
        status = pod.get("status") or {}
        namespace = str(meta.get("namespace") or "")
        pod_name = str(meta.get("name") or "")
        labels = meta.get("labels") or {}
        annotations = meta.get("annotations") or {}
        rev_label = str(labels.get(ISTIO_REV_LABEL) or "")
        proxy_config_rev = parse_proxy_config_revision(annotations.get(PROXY_CONFIG_ANNOTATION))

        status_pairs = (
            (CONTAINER_KIND_REGULAR, spec.get("containers") or [], _container_status_map(status.get("containerStatuses"))),
            (
                CONTAINER_KIND_INIT,
                spec.get("initContainers") or [],
                _container_status_map(status.get("initContainerStatuses")),
            ),
        )
        for kind, containers, status_by_name in status_pairs:
            for container in containers:
                if not isinstance(container, dict):
                    continue
                if str(container.get("name") or "") != ISTIO_PROXY_CONTAINER:
                    continue
                image = str(container.get("image") or "")
                minor, version_text = parse_version_minor(image)
                if minor is None and rev_label:
                    minor, version_text = parse_version_minor(rev_label)
                restarts, oom, exit_code = _oom_details(status_by_name.get(ISTIO_PROXY_CONTAINER))
                records.append(
                    SidecarRecord(
                        namespace=namespace,
                        pod=pod_name,
                        container_kind=kind,
                        image=image,
                        minor=minor,
                        version_text=version_text or image,
                        rev_label=rev_label,
                        proxy_config_rev=proxy_config_rev,
                        restart_count=restarts,
                        oom_killed=oom,
                        last_exit_code=exit_code,
                    )
                )
    return records


def is_ingress_gateway_pod(pod: dict[str, Any]) -> bool:
    """Return True if a pod is an Istio/ASM ingress gateway or Gateway API proxy."""
    meta = pod.get("metadata") or {}
    labels = meta.get("labels") or {}
    if not isinstance(labels, dict):
        return False
    for key, expected in GATEWAY_LABEL_KEYS:
        if str(labels.get(key) or "") == expected:
            return True
    return bool(labels.get(GATEWAY_API_LABEL))


def _pod_has_istio_proxy(pod: dict[str, Any]) -> bool:
    spec = pod.get("spec") or {}
    for key in ("containers", "initContainers"):
        for container in spec.get(key) or []:
            if isinstance(container, dict) and str(container.get("name") or "") == ISTIO_PROXY_CONTAINER:
                return True
    return False


# ---------------------------------------------------------------------------
# Log & metric scanning
# ---------------------------------------------------------------------------


def scan_xds_signals(
    proxy_logs: dict[str, str] | None = None,
    istiod_logs: dict[str, str] | None = None,
    metrics_text: str = "",
) -> XdsNackSummary:
    """Scan istio-proxy logs, istiod logs, and Prometheus metrics for Envoy xDS NACK loops."""
    summary = XdsNackSummary()
    seen_types: set[str] = set()
    affected: set[str] = set()

    for pod_key, text in (proxy_logs or {}).items():
        for line in (text or "").splitlines():
            match = ENVOY_XDS_REJECT_RE.search(line)
            if not match:
                continue
            summary.proxy_nack_count += 1
            affected.add(pod_key)
            for marker, short_type in ENVOY_XDS_TYPE_MAP:
                if marker in line:
                    seen_types.add(short_type)
                    break
            if ISTIO_AUTHN_MARKER in line:
                summary.istio_authn_seen = True
            if len(summary.sample_lines) < MAX_SAMPLE_LINES:
                summary.sample_lines.append(f"{pod_key}: {line.strip()[:ERROR_EXCERPT_CHARS]}")

    for pod_key, text in (istiod_logs or {}).items():
        for line in (text or "").splitlines():
            match = ISTIOD_NACK_RE.search(line)
            if not match:
                continue
            summary.istiod_nack_count += 1
            if match.group(1):
                seen_types.add(match.group(1).upper())
            if len(summary.sample_lines) < MAX_SAMPLE_LINES:
                summary.sample_lines.append(f"{pod_key}: {line.strip()[:ERROR_EXCERPT_CHARS]}")

    for line in (metrics_text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(PROM_COMMENT_PREFIX):
            continue
        match = PROM_XDS_REJECT_RE.match(stripped)
        if not match:
            continue
        metric_name, labels_str, value_str = match.group(1), match.group(2) or "", match.group(3)
        if metric_name == PROM_PUSHES_METRIC and PROM_REJECTED_MARKER not in labels_str.lower():
            continue
        try:
            value = float(value_str)
        except ValueError:
            continue
        if value <= 0:
            continue
        summary.metric_reject_total += value
        type_match = PROM_METRIC_TYPE_RE.search(labels_str)
        if type_match:
            raw_type = type_match.group(1).upper()
            for candidate in XDS_SHORT_TYPES:
                if candidate in raw_type:
                    seen_types.add(candidate)

    summary.xds_types = sorted(seen_types)
    summary.affected_pods = sorted(affected)
    return summary


def scan_gateway_503_uh(gateway_logs: dict[str, str] | None = None) -> Gateway503Summary:
    """Scan ingress gateway access logs for HTTP 503 UH / no_healthy_upstream errors."""
    summary = Gateway503Summary()
    affected: set[str] = set()
    for pod_key, text in (gateway_logs or {}).items():
        for line in (text or "").splitlines():
            if not GATEWAY_503_UH_RE.search(line):
                continue
            summary.uh_503_count += 1
            affected.add(pod_key)
            if len(summary.sample_lines) < MAX_SAMPLE_LINES:
                summary.sample_lines.append(f"{pod_key}: {line.strip()[:ERROR_EXCERPT_CHARS]}")
    summary.affected_pods = sorted(affected)
    return summary


# ---------------------------------------------------------------------------
# Core correlation & analysis
# ---------------------------------------------------------------------------


def _active_control_planes(control_planes: list[ControlPlaneRecord]) -> list[ControlPlaneRecord]:
    """Prefer Deployment / ControlPlaneRevision records; fall back to webhooks only when none exist."""
    authoritative = [cp for cp in control_planes if cp.source in AUTHORITATIVE_CP_SOURCES]
    return authoritative if authoritative else list(control_planes)


def _bound_control_plane_minor(
    sidecar: SidecarRecord,
    active_cps: list[ControlPlaneRecord],
) -> tuple[int, int] | None:
    """Resolve the control-plane minor bound to `sidecar` via proxy_config_rev or rev_label."""
    by_rev: dict[str, list[tuple[int, int]]] = defaultdict(list)
    by_channel: dict[str, list[tuple[int, int]]] = defaultdict(list)
    all_minors: list[tuple[int, int]] = []

    for cp in active_cps:
        if cp.minor is None:
            continue
        all_minors.append(cp.minor)
        if cp.revision:
            by_rev[cp.revision.lower()].append(cp.minor)
        if cp.managed_channel:
            by_channel[cp.managed_channel.upper()].append(cp.minor)

    if not all_minors:
        return None

    for candidate_rev in (sidecar.proxy_config_rev, sidecar.rev_label):
        key = (candidate_rev or "").strip().lower()
        if not key:
            continue
        if key in by_rev:
            return min(by_rev[key])
        channel = _managed_channel_for(key)
        if channel and channel in by_channel:
            return min(by_channel[channel])

    # Unbound sidecar (or its revision was removed after a channel downgrade): compare against
    # the active control plane(s). When only one active minor exists, that is the sole candidate;
    # when multiple active revisions exist and a sidecar matches none by label, compare against
    # the newest active control plane so canary migrations do not false-positive on the old CP.
    distinct = sorted(set(all_minors))
    if len(distinct) == 1:
        return distinct[0]
    return distinct[-1]


def analyze_mesh_skew(
    *,
    control_planes: list[ControlPlaneRecord],
    sidecars: list[SidecarRecord],
    xds_nacks: XdsNackSummary | None = None,
    gateway_503: Gateway503Summary | None = None,
    unread: list[str] | None = None,
) -> dict[str, Any]:
    """Correlate control-plane revisions, sidecar versions, xDS NACKs, OOMs, and 503 UH logs."""
    xds = xds_nacks or XdsNackSummary()
    gw = gateway_503 or Gateway503Summary()
    unread_list = list(unread or [])

    has_xds_nacks = (
        xds.proxy_nack_count > 0 or xds.istiod_nack_count > 0 or xds.metric_reject_total > 0
    )
    has_gateway_503 = gw.uh_503_count > 0

    if not control_planes and not sidecars and not unread_list and not has_xds_nacks and not has_gateway_503:
        return {
            "status": STATUS_NO_MESH,
            "control_planes": [],
            "sidecar_count": 0,
            "sidecar_minors": [],
            "oom_sidecars": [],
            "xds_nacks": asdict(xds),
            "gateway_503_uh": asdict(gw),
            "findings": [],
            "notes": ["No Istio or Cloud Service Mesh control-plane objects or istio-proxy sidecars detected."],
            "unread": [],
            "preflight_warning": PREFLIGHT_CHANNEL_WARNING,
        }

    findings: list[Finding] = []
    notes: list[str] = []

    active_cps = _active_control_planes(control_planes)
    cp_minors = sorted({cp.minor for cp in active_cps if cp.minor is not None})
    sidecar_minors = sorted({sc.minor for sc in sidecars if sc.minor is not None})
    oom_sidecars = [sc for sc in sidecars if sc.oom_killed]

    managed_channels_without_minor = sorted(
        {
            f"{cp.revision} ({cp.managed_channel})"
            for cp in active_cps
            if cp.minor is None and cp.managed_channel is not None
        }
    )
    if managed_channels_without_minor:
        notes.append(
            "Managed Cloud Service Mesh channel revision(s) present without a numeric in-cluster "
            f"istiod version ({', '.join(managed_channels_without_minor)}): run "
            "`gcloud container fleet mesh describe --project <host_project>` as an operator step "
            "to confirm the managed control-plane minor against running istio-proxy sidecars."
        )

    cp_older_than_sidecar = False
    if cp_minors and sidecars:
        newer_pairs: list[tuple[SidecarRecord, tuple[int, int]]] = []
        lagging_pairs: list[tuple[SidecarRecord, tuple[int, int]]] = []
        for sc in sidecars:
            if sc.minor is None:
                continue
            bound_cp = _bound_control_plane_minor(sc, active_cps)
            if bound_cp is None:
                continue
            if sc.minor > bound_cp:
                newer_pairs.append((sc, bound_cp))
            elif (
                sc.minor[0] < bound_cp[0]
                or (
                    sc.minor[0] == bound_cp[0]
                    and (bound_cp[1] - sc.minor[1]) > MAX_SUPPORTED_SIDECAR_LAG_MINORS
                )
            ):
                lagging_pairs.append((sc, bound_cp))

        if newer_pairs:
            cp_older_than_sidecar = True
            namespaces = sorted({sc.namespace for sc, _ in newer_pairs})
            newer_minors = sorted({format_minor(sc.minor) for sc, _ in newer_pairs})
            older_cp_minors = sorted({format_minor(cp_m) for _, cp_m in newer_pairs})
            cause = (
                f"Active mesh control plane ({', '.join(older_cp_minors)}) is older than "
                f"{len(newer_pairs)} running istio-proxy sidecar(s) ({', '.join(newer_minors)} "
                f"in namespace(s) {', '.join(namespaces)}). Managed Cloud Service Mesh follows the "
                "cluster's GKE release channel, so switching a cluster onto a slower channel (such "
                "as from no release channel to STABLE) downgrades the control plane while injected "
                "sidecars remain on the newer minor."
            )
            findings.append(
                Finding(
                    check=CHECK_CP_OLDER_THAN_SIDECAR,
                    severity=SEVERITY_CRITICAL,
                    summary=(
                        f"Mesh control plane {', '.join(older_cp_minors)} is older than running "
                        f"istio-proxy sidecars ({', '.join(newer_minors)})"
                    ),
                    cause=cause,
                    recommendation=DO_NOT_RAISE_MEMORY_NOTE,
                    evidence={
                        "control_plane_minors": older_cp_minors,
                        "newer_sidecar_minors": newer_minors,
                        "affected_namespaces": namespaces,
                        "affected_sidecar_count": len(newer_pairs),
                        "oom_sidecar_count": len(oom_sidecars),
                        "proxy_nack_count": xds.proxy_nack_count,
                        "istiod_nack_count": xds.istiod_nack_count,
                        "gateway_503_uh_count": gw.uh_503_count,
                    },
                )
            )

        if lagging_pairs:
            lag_namespaces = sorted({sc.namespace for sc, _ in lagging_pairs})
            lag_minors = sorted({format_minor(sc.minor) for sc, _ in lagging_pairs})
            ref_cp_minors = sorted({format_minor(cp_m) for _, cp_m in lagging_pairs})
            findings.append(
                Finding(
                    check=CHECK_SIDECAR_LAG_SKEW,
                    severity=SEVERITY_MAJOR,
                    summary=(
                        f"{len(lagging_pairs)} istio-proxy sidecar(s) ({', '.join(lag_minors)}) "
                        f"lag control plane {', '.join(ref_cp_minors)} by more than "
                        f"{MAX_SUPPORTED_SIDECAR_LAG_MINORS} minor"
                    ),
                    cause=(
                        "Injected sidecars more than one minor version behind their control plane "
                        "sit outside Istio/ASM's supported version skew policy."
                    ),
                    recommendation=(
                        "Verify namespace istio.io/rev labels and roll affected workloads so "
                        "injected sidecars match the active control-plane minor."
                    ),
                    evidence={
                        "control_plane_minors": ref_cp_minors,
                        "lagging_sidecar_minors": lag_minors,
                        "affected_namespaces": lag_namespaces,
                        "affected_sidecar_count": len(lagging_pairs),
                    },
                )
            )

    if has_xds_nacks:
        types_text = "/".join(xds.xds_types) if xds.xds_types else "xDS"
        parts = [
            f"Envoy {types_text} NACK rejections detected "
            f"(proxy logs: {xds.proxy_nack_count}, istiod logs: {xds.istiod_nack_count}, "
            f"metric rejects: {int(xds.metric_reject_total)})"
        ]
        if xds.istio_authn_seen:
            parts.append("including missing 'istio_authn' listener filter implementation")
        if oom_sidecars:
            parts.append(
                f"correlated with {len(oom_sidecars)} OOMKilled (exit {OOM_EXIT_CODE}) "
                "istio-proxy container(s)"
            )
        if gw.uh_503_count > 0:
            parts.append(
                f"and {gw.uh_503_count} ingress gateway HTTP 503 UH (no_healthy_upstream) entry/entries"
            )
        joined_summary = "; ".join(parts)

        if cp_older_than_sidecar:
            cause = (
                "The older mesh control plane is pushing xDS configuration that newer istio-proxy "
                "sidecars cannot parse, driving an unbounded push/NACK retry loop that leaks Envoy "
                "memory until istio-proxy is OOMKilled and ingress gateways return 503 UH "
                "no_healthy_upstream. Check for a recent GKE release-channel change that "
                "downgraded managed Cloud Service Mesh."
            )
        else:
            cause = (
                "Sustained Envoy xDS NACK rejections cause unbounded control-plane retries and "
                "Envoy memory growth leading to istio-proxy OOMKills and upstream 503 UH errors. "
                "Check control-plane vs sidecar revision skew (including managed ASM via "
                "`gcloud container fleet mesh describe --project <host_project>` when control-plane "
                "pods are Google-managed) and invalid EnvoyFilter/WasmPlugin configurations."
            )

        findings.append(
            Finding(
                check=CHECK_ENVOY_XDS_NACK_LOOP,
                severity=SEVERITY_CRITICAL,
                summary=joined_summary,
                cause=cause,
                recommendation=DO_NOT_RAISE_MEMORY_NOTE,
                evidence={
                    "xds_types": xds.xds_types,
                    "istio_authn_seen": xds.istio_authn_seen,
                    "proxy_nack_count": xds.proxy_nack_count,
                    "istiod_nack_count": xds.istiod_nack_count,
                    "metric_reject_total": xds.metric_reject_total,
                    "affected_proxy_pods": xds.affected_pods,
                    "oom_sidecar_pods": sorted({f"{sc.namespace}/{sc.pod}" for sc in oom_sidecars}),
                    "gateway_503_uh_count": gw.uh_503_count,
                    "gateway_503_pods": gw.affected_pods,
                    "sample_xds_lines": xds.sample_lines,
                    "sample_gateway_lines": gw.sample_lines,
                },
            )
        )
    elif has_gateway_503:
        notes.append(
            f"Ingress gateway logs show {gw.uh_503_count} HTTP 503 UH (no_healthy_upstream) "
            "entry/entries without sampled Envoy xDS NACK rejections; inspect upstream endpoints "
            "and gateway/sidecar logs."
        )

    minors_by_ns: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for sc in sidecars:
        if sc.minor is not None:
            minors_by_ns[sc.namespace].add(sc.minor)
    mixed_namespaces = {
        ns: [format_minor(m) for m in sorted(ms)]
        for ns, ms in sorted(minors_by_ns.items())
        if len(ms) > 1
    }
    if mixed_namespaces:
        findings.append(
            Finding(
                check=CHECK_MIXED_SIDECAR_REVISIONS,
                severity=SEVERITY_MINOR,
                summary=(
                    f"Mixed istio-proxy minor versions found in {len(mixed_namespaces)} "
                    f"namespace(s): {', '.join(mixed_namespaces)}"
                ),
                cause=(
                    "Workloads inside the same namespace were injected at different mesh minor "
                    "versions (for example, partial rollout after a control-plane or channel change)."
                ),
                recommendation=(
                    "Confirm the namespace istio.io/rev label points to the intended revision and "
                    "roll remaining workloads so all sidecars run the same minor version."
                ),
                evidence={"mixed_namespaces": mixed_namespaces},
            )
        )

    if findings:
        status = STATUS_FINDINGS
    elif unread_list:
        status = STATUS_UNREAD
    else:
        status = STATUS_OK

    return {
        "status": status,
        "control_planes": [
            {
                **asdict(cp),
                "minor": format_minor(cp.minor),
            }
            for cp in control_planes
        ],
        "sidecar_count": len(sidecars),
        "sidecar_minors": [format_minor(m) for m in sidecar_minors],
        "oom_sidecars": [
            {
                "namespace": sc.namespace,
                "pod": sc.pod,
                "image": sc.image,
                "minor": format_minor(sc.minor),
                "restart_count": sc.restart_count,
                "last_exit_code": sc.last_exit_code,
            }
            for sc in oom_sidecars
        ],
        "xds_nacks": asdict(xds),
        "gateway_503_uh": asdict(gw),
        "findings": [asdict(f) for f in findings],
        "notes": notes,
        "unread": unread_list,
        "preflight_warning": PREFLIGHT_CHANNEL_WARNING,
    }


# ---------------------------------------------------------------------------
# Live read-only kubectl collection (collector_run.paged_list + bounded logs)
# ---------------------------------------------------------------------------


def _kubectl_env(kubeconfig: str | None) -> dict[str, str] | None:
    if not kubeconfig:
        return None
    env = dict(os.environ)
    env[KUBECONFIG_ENV_KEY] = kubeconfig
    return env


def _with_context(argv: list[str], context: str | None) -> list[str]:
    if not context:
        return argv
    return [argv[0], KUBECTL_CONTEXT_FLAG, context, *argv[1:]]


def _fetch_namespaced_resource(
    resource: str,
    namespace: str,
    *,
    run: RunFn,
    env: dict[str, str] | None,
    context: str | None,
    optional: bool = False,
) -> tuple[list[dict[str, Any]], str | None]:
    argv = _with_context(
        [
            KUBECTL_BIN,
            KUBECTL_GET_VERB,
            resource,
            KUBECTL_NAMESPACE_FLAG,
            namespace,
            KUBECTL_OUTPUT_FLAG,
            KUBECTL_OUTPUT_JSON,
        ],
        context,
    )
    result = run(argv, env=env)
    label = f"{resource}/{namespace}"
    if PROXY_TRUNCATION_MARKER in (result.stderr or ""):
        return [], f"{label}: output truncated by credential proxy"
    if result.rc != 0:
        if optional and any(marker in (result.stderr or "") for marker in NOT_FOUND_MARKERS):
            return [], None
        detail = (result.stderr or "no stderr").strip().replace("\n", " ")[:ERROR_EXCERPT_CHARS]
        return [], f"{label}: kubectl failed (rc={result.rc}): {detail}"
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        return [], f"{label}: invalid JSON ({exc})"
    page_items = (payload or {}).get("items") or []
    return [item for item in page_items if isinstance(item, dict)], None


def _fetch_paged_collection(
    resource: str,
    *,
    run: RunFn,
    env: dict[str, str] | None,
    context: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    def _ctx_run(argv: list[str], **kwargs) -> Run:
        return run(_with_context(argv, context), **kwargs)

    items, result, _pages = paged_list(resource, run=_ctx_run, env=env)
    if PROXY_TRUNCATION_MARKER in (result.stderr or ""):
        return [], f"{resource}: output truncated by credential proxy"
    if items is None:
        detail = (result.stderr or "no stderr").strip().replace("\n", " ")[:ERROR_EXCERPT_CHARS]
        return [], f"{resource}: paged read failed (rc={result.rc}): {detail}"
    return [item for item in items if isinstance(item, dict)], None


def _fetch_container_logs(
    namespace: str,
    pod: str,
    container: str | None,
    *,
    previous: bool,
    run: RunFn,
    env: dict[str, str] | None,
    context: str | None,
) -> tuple[str, str | None]:
    argv = [
        KUBECTL_BIN,
        KUBECTL_LOGS_VERB,
        pod,
        KUBECTL_NAMESPACE_FLAG,
        namespace,
        KUBECTL_TAIL_FLAG_TEMPLATE.format(lines=LOG_TAIL_LINES),
    ]
    if container:
        argv.extend([KUBECTL_CONTAINER_FLAG, container])
    if previous:
        argv.append(KUBECTL_PREVIOUS_FLAG)
    result = run(_with_context(argv, context), env=env)
    suffix = " --previous" if previous else ""
    if PROXY_TRUNCATION_MARKER in (result.stderr or ""):
        return result.stdout or "", f"logs {namespace}/{pod}{suffix}: output truncated by credential proxy"
    if result.rc != 0:
        if previous:
            return "", None
        detail = (result.stderr or "no stderr").strip().replace("\n", " ")[:ERROR_EXCERPT_CHARS]
        return "", f"logs {namespace}/{pod}: rc={result.rc}: {detail}"
    return result.stdout or "", None


def collect_and_analyze(
    *,
    kubeconfig: str | None = None,
    context: str | None = None,
    run: RunFn | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    skip_logs: bool = False,
) -> dict[str, Any]:
    """Run read-only kubectl reads against the target cluster and analyze mesh skew/NACKs."""
    runner = run or functools.partial(default_run, timeout=timeout_s)
    env = _kubectl_env(kubeconfig)
    unread: list[str] = []

    deployments: list[dict[str, Any]] = []
    cprs: list[dict[str, Any]] = []
    for ns in MESH_CONTROL_PLANE_NAMESPACES:
        ns_deps, dep_err = _fetch_namespaced_resource(
            DEPLOYMENTS_RESOURCE, ns, run=runner, env=env, context=context, optional=True
        )
        if dep_err:
            unread.append(dep_err)
        deployments.extend(ns_deps)

        ns_cprs, cpr_err = _fetch_namespaced_resource(
            CPR_RESOURCE, ns, run=runner, env=env, context=context, optional=True
        )
        if cpr_err:
            unread.append(cpr_err)
        cprs.extend(ns_cprs)

    mwcs, mwc_err = _fetch_paged_collection(MWC_RESOURCE, run=runner, env=env, context=context)
    if mwc_err:
        unread.append(mwc_err)

    pods, pods_err = _fetch_paged_collection(PODS_RESOURCE, run=runner, env=env, context=context)
    if pods_err:
        unread.append(pods_err)

    control_planes = extract_control_plane_records(deployments, cprs, mwcs)
    sidecars = extract_sidecar_records(pods)

    proxy_logs: dict[str, str] = {}
    istiod_logs: dict[str, str] = {}
    gateway_logs: dict[str, str] = {}

    if not skip_logs and (control_planes or sidecars):
        ordered_sidecars = sorted(
            sidecars,
            key=lambda sc: (not sc.oom_killed, -sc.restart_count, sc.namespace, sc.pod),
        )
        for sc in ordered_sidecars[:MAX_SAMPLED_SIDECAR_LOG_PODS]:
            pod_key = f"{sc.namespace}/{sc.pod}"
            current_log, log_err = _fetch_container_logs(
                sc.namespace, sc.pod, ISTIO_PROXY_CONTAINER, previous=False, run=runner, env=env, context=context
            )
            if log_err:
                unread.append(log_err)
            prev_log = ""
            if sc.oom_killed or sc.restart_count > 0:
                prev_log, prev_err = _fetch_container_logs(
                    sc.namespace, sc.pod, ISTIO_PROXY_CONTAINER, previous=True, run=runner, env=env, context=context
                )
                if prev_err:
                    unread.append(prev_err)
            combined = "\n".join(chunk for chunk in (prev_log, current_log) if chunk)
            if combined:
                proxy_logs[pod_key] = combined

        istiod_pods = [
            pod
            for pod in pods
            if str((pod.get("metadata") or {}).get("namespace") or "") in MESH_CONTROL_PLANE_NAMESPACES
            and str((pod.get("metadata") or {}).get("name") or "").startswith(ISTIOD_NAME_PREFIX)
        ]
        for pod in istiod_pods[:MAX_SAMPLED_ISTIOD_LOG_PODS]:
            meta = pod.get("metadata") or {}
            ns = str(meta.get("namespace") or "")
            name = str(meta.get("name") or "")
            log_text, log_err = _fetch_container_logs(
                ns, name, None, previous=False, run=runner, env=env, context=context
            )
            if log_err:
                unread.append(log_err)
            if log_text:
                istiod_logs[f"{ns}/{name}"] = log_text

        gateway_pods = [pod for pod in pods if is_ingress_gateway_pod(pod)]
        for pod in gateway_pods[:MAX_SAMPLED_GATEWAY_LOG_PODS]:
            meta = pod.get("metadata") or {}
            ns = str(meta.get("namespace") or "")
            name = str(meta.get("name") or "")
            pod_key = f"{ns}/{name}"
            if pod_key in proxy_logs:
                gateway_logs[pod_key] = proxy_logs[pod_key]
                continue
            container_name = ISTIO_PROXY_CONTAINER if _pod_has_istio_proxy(pod) else None
            log_text, log_err = _fetch_container_logs(
                ns, name, container_name, previous=False, run=runner, env=env, context=context
            )
            if log_err:
                unread.append(log_err)
            if log_text:
                gateway_logs[pod_key] = log_text

    xds = scan_xds_signals(proxy_logs=proxy_logs, istiod_logs=istiod_logs)
    gw = scan_gateway_503_uh(gateway_logs=gateway_logs)
    return analyze_mesh_skew(
        control_planes=control_planes,
        sidecars=sidecars,
        xds_nacks=xds,
        gateway_503=gw,
        unread=unread,
    )


# ---------------------------------------------------------------------------
# Rendering & CLI
# ---------------------------------------------------------------------------


def render_text(report: dict[str, Any]) -> str:
    lines = [
        f"mesh-skew-check status: {report['status']}",
        f"control planes: {len(report['control_planes'])} | istio-proxy sidecars: {report['sidecar_count']} "
        f"(minors: {', '.join(report['sidecar_minors']) or 'none'}) | OOMKilled sidecars: {len(report['oom_sidecars'])}",
    ]
    for finding in report["findings"]:
        lines.append(f"[{finding['severity'].upper()}] {finding['check']}: {finding['summary']}")
        lines.append(f"  cause: {finding['cause']}")
        lines.append(f"  action: {finding['recommendation']}")
    for note in report["notes"]:
        lines.append(f"note: {note}")
    for err in report["unread"]:
        lines.append(f"unread: {err}")
    return "\n".join(lines)


def _load_input_json(path: str) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    control_planes = extract_control_plane_records(
        raw.get("deployments") or [],
        raw.get("control_plane_revisions") or [],
        raw.get("mutating_webhooks") or [],
    )
    sidecars = extract_sidecar_records(raw.get("pods") or [])
    xds = scan_xds_signals(
        proxy_logs=raw.get("proxy_logs") or {},
        istiod_logs=raw.get("istiod_logs") or {},
        metrics_text=str(raw.get("metrics_text") or ""),
    )
    gw = scan_gateway_503_uh(gateway_logs=raw.get("gateway_logs") or {})
    return analyze_mesh_skew(
        control_planes=control_planes,
        sidecars=sidecars,
        xds_nacks=xds,
        gateway_503=gw,
        unread=raw.get("unread") or [],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only in-cluster Istio/ASM sidecar-vs-control-plane skew and Envoy xDS NACK detector."
    )
    parser.add_argument("--kubeconfig", default=None, help="Path to per-target kubeconfig file.")
    parser.add_argument("--context", default=None, help="Kubernetes context name.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="Per-command timeout in seconds.")
    parser.add_argument("--skip-logs", action="store_true", help="Skip bounded pod log reads.")
    parser.add_argument("--input-json", default=None, help="Analyze a captured JSON bundle instead of calling kubectl.")
    parser.add_argument("--format", choices=VALID_FORMATS, default=FORMAT_TEXT, help="Output format.")
    args = parser.parse_args(argv)

    if args.input_json:
        report = _load_input_json(args.input_json)
    else:
        report = collect_and_analyze(
            kubeconfig=args.kubeconfig,
            context=args.context,
            timeout_s=args.timeout,
            skip_logs=args.skip_logs,
        )

    if args.format == FORMAT_JSON:
        print(json.dumps(report, indent=JSON_INDENT, sort_keys=True))
    else:
        print(render_text(report))

    if report["status"] == STATUS_FINDINGS:
        return EXIT_FINDINGS
    if report["status"] == STATUS_UNREAD:
        return EXIT_READ_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
