#!/usr/bin/env python3
"""Unit tests for mesh_skew_check.py (Part of #2797)."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLATFORM_SCRIPTS_DIR = SCRIPT_DIR.parents[2] / "scripts"
for _dir in (SCRIPT_DIR, PLATFORM_SCRIPTS_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import command_policy  # noqa: E402
import mesh_skew_check as msc  # noqa: E402


def _istiod_deployment(
    name: str = "istiod-asm-119-5",
    namespace: str = "istio-system",
    image: str = "gcr.io/gke-release/asm/pilot:1.19.5-asm.1",
    rev: str = "asm-119-5",
    replicas: int = 2,
) -> dict:
    return {
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {"istio.io/rev": rev},
        },
        "spec": {
            "replicas": replicas,
            "template": {"spec": {"containers": [{"name": "discovery", "image": image}]}},
        },
    }


def _sidecar_pod(
    name: str = "auth-gw-7f9b",
    namespace: str = "payments",
    image: str = "gcr.io/gke-release/asm/proxyv2:1.20.4-asm.2",
    rev: str = "asm-120-4",
    *,
    native_sidecar: bool = False,
    oom_killed: bool = False,
    restart_count: int = 0,
    proxy_config: str | None = None,
    extra_labels: dict | None = None,
) -> dict:
    labels = {"istio.io/rev": rev, **(extra_labels or {})}
    annotations = {}
    if proxy_config is not None:
        annotations["proxy.istio.io/config"] = proxy_config
    proxy_container = {"name": "istio-proxy", "image": image}
    app_container = {"name": "app", "image": "example.invalid/app:1.0"}
    proxy_status: dict = {"name": "istio-proxy", "restartCount": restart_count}
    if oom_killed:
        proxy_status["lastState"] = {"terminated": {"reason": "OOMKilled", "exitCode": 137}}
    spec: dict = {"containers": [app_container]}
    status: dict = {"containerStatuses": []}
    if native_sidecar:
        spec["initContainers"] = [proxy_container]
        status["initContainerStatuses"] = [proxy_status]
    else:
        spec["containers"].append(proxy_container)
        status["containerStatuses"].append(proxy_status)
    return {
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": spec,
        "status": status,
    }


class VersionParsingTest(unittest.TestCase):
    def test_parses_asm_proxy_and_pilot_images(self):
        self.assertEqual(msc.parse_version_minor("gcr.io/gke-release/asm/proxyv2:1.20.4-asm.2")[0], (1, 20))
        self.assertEqual(msc.parse_version_minor("docker.io/istio/proxyv2:1.19.8-distroless@sha256:abc")[0], (1, 19))
        self.assertEqual(msc.parse_version_minor("asm-120-2")[0], (1, 20))
        self.assertEqual(msc.parse_version_minor("asm-119-5")[0], (1, 19))
        self.assertEqual(msc.parse_version_minor("1-20-4")[0], (1, 20))
        self.assertIsNone(msc.parse_version_minor("asm-managed-stable")[0])
        self.assertIsNone(msc.parse_version_minor("")[0])

    def test_parses_proxy_config_discovery_revision(self):
        cfg = "discoveryAddress: istiod-asm-119-5.istio-system.svc:15012"
        self.assertEqual(msc.parse_proxy_config_revision(cfg), "asm-119-5")
        self.assertEqual(msc.parse_proxy_config_revision("holdApplicationUntilProxyStarts: true"), "")


class AnalyzeMeshSkewTest(unittest.TestCase):
    def test_fsi_downgrade_scenario_joins_skew_nack_oom_and_503_uh(self):
        cps = msc.extract_control_plane_records(
            deployments=[_istiod_deployment(image="gcr.io/gke-release/asm/pilot:1.19.5-asm.1", rev="asm-119-5")],
        )
        sidecars = msc.extract_sidecar_records(
            [
                _sidecar_pod(
                    name="auth-gw-1",
                    namespace="auth",
                    image="gcr.io/gke-release/asm/proxyv2:1.20.4-asm.2",
                    rev="asm-120-4",
                    oom_killed=True,
                    restart_count=7,
                    proxy_config="discoveryAddress: istiod-asm-119-5.istio-system.svc:15012",
                ),
                _sidecar_pod(
                    name="notify-gw-1",
                    namespace="notify",
                    image="gcr.io/gke-release/asm/proxyv2:1.20.4-asm.2",
                    rev="asm-120-4",
                    native_sidecar=True,
                    oom_killed=True,
                    restart_count=4,
                ),
            ]
        )
        self.assertEqual(sidecars[0].proxy_config_rev, "asm-119-5")
        self.assertEqual(sidecars[1].container_kind, "initContainer")

        xds = msc.scan_xds_signals(
            proxy_logs={
                "auth/auth-gw-1": (
                    "2026-10-01T10:00:01Z warning envoy config gRPC config for "
                    "type.googleapis.com/envoy.config.listener.v3.Listener rejected: "
                    "Error adding/updating listener(s) 0.0.0.0_8080: Didn't find a registered "
                    "implementation for 'istio_authn'\n"
                )
                * 3
            },
            istiod_logs={
                "istio-system/istiod-asm-119-5-abc": (
                    "2026-10-01T10:00:01Z warn ads ADS:LDS: ACK ERROR auth-gw-1.auth NACK: "
                    "Didn't find a registered implementation for 'istio_authn'\n"
                )
            },
        )
        gw = msc.scan_gateway_503_uh(
            {
                "istio-ingress/istio-ingressgateway-xyz": (
                    '{"response_code":503,"response_flag":"UH","response_details":"no_healthy_upstream"}\n'
                )
            }
        )

        report = msc.analyze_mesh_skew(
            control_planes=cps,
            sidecars=sidecars,
            xds_nacks=xds,
            gateway_503=gw,
        )
        self.assertEqual(report["status"], msc.STATUS_FINDINGS)
        by_check = {f["check"]: f for f in report["findings"]}
        self.assertIn(msc.CHECK_CP_OLDER_THAN_SIDECAR, by_check)
        self.assertIn(msc.CHECK_ENVOY_XDS_NACK_LOOP, by_check)

        skew = by_check[msc.CHECK_CP_OLDER_THAN_SIDECAR]
        self.assertEqual(skew["severity"], msc.SEVERITY_CRITICAL)
        self.assertIn("1.19", skew["summary"])
        self.assertIn("1.20", skew["summary"])
        self.assertIn("release channel", skew["cause"])
        self.assertIn("Do not treat istio-proxy OOMKilled", skew["recommendation"])

        nack = by_check[msc.CHECK_ENVOY_XDS_NACK_LOOP]
        self.assertEqual(nack["severity"], msc.SEVERITY_CRITICAL)
        self.assertTrue(nack["evidence"]["istio_authn_seen"])
        self.assertEqual(nack["evidence"]["xds_types"], ["LDS"])
        self.assertEqual(nack["evidence"]["proxy_nack_count"], 3)
        self.assertEqual(nack["evidence"]["istiod_nack_count"], 1)
        self.assertEqual(nack["evidence"]["gateway_503_uh_count"], 1)
        self.assertEqual(len(nack["evidence"]["oom_sidecar_pods"]), 2)
        self.assertIn("release-channel", nack["cause"])

    def test_canary_upgrade_with_two_active_revisions_has_no_false_positive(self):
        cps = msc.extract_control_plane_records(
            deployments=[
                _istiod_deployment(
                    name="istiod-asm-119-5", image="gcr.io/gke-release/asm/pilot:1.19.5-asm.1", rev="asm-119-5"
                ),
                _istiod_deployment(
                    name="istiod-asm-120-4", image="gcr.io/gke-release/asm/pilot:1.20.4-asm.2", rev="asm-120-4"
                ),
            ]
        )
        sidecars = msc.extract_sidecar_records(
            [
                _sidecar_pod(name="old-1", namespace="ns-old", image="gcr.io/gke-release/asm/proxyv2:1.19.5-asm.1", rev="asm-119-5"),
                _sidecar_pod(name="new-1", namespace="ns-new", image="gcr.io/gke-release/asm/proxyv2:1.20.4-asm.2", rev="asm-120-4"),
            ]
        )
        report = msc.analyze_mesh_skew(control_planes=cps, sidecars=sidecars)
        self.assertEqual(report["status"], msc.STATUS_OK)
        self.assertEqual(report["findings"], [])

    def test_stale_webhook_does_not_override_active_deployment_control_plane(self):
        cps = msc.extract_control_plane_records(
            deployments=[
                _istiod_deployment(
                    name="istiod-asm-119-5", image="gcr.io/gke-release/asm/pilot:1.19.5-asm.1", rev="asm-119-5", replicas=0
                ),
                _istiod_deployment(
                    name="istiod-asm-120-4", image="gcr.io/gke-release/asm/pilot:1.20.4-asm.2", rev="asm-120-4", replicas=2
                ),
            ],
            mutating_webhooks=[
                {
                    "metadata": {
                        "name": "istio-sidecar-injector-asm-119-5",
                        "labels": {"istio.io/rev": "asm-119-5"},
                    }
                }
            ],
        )
        sidecars = msc.extract_sidecar_records(
            [_sidecar_pod(image="gcr.io/gke-release/asm/proxyv2:1.20.4-asm.2", rev="asm-120-4")]
        )
        report = msc.analyze_mesh_skew(control_planes=cps, sidecars=sidecars)
        self.assertEqual(report["status"], msc.STATUS_OK)
        self.assertEqual(report["findings"], [])

    def test_scans_rds_cds_eds_and_prometheus_metrics(self):
        xds = msc.scan_xds_signals(
            proxy_logs={
                "app/p1": "\n".join(
                    [
                        "gRPC config for type.googleapis.com/envoy.config.route.v3.RouteConfiguration rejected: bad route",
                        "gRPC config for type.googleapis.com/envoy.config.cluster.v3.Cluster rejected: bad cluster",
                        "gRPC config for type.googleapis.com/envoy.config.endpoint.v3.ClusterLoadAssignment rejected: bad eds",
                    ]
                )
            },
            metrics_text=(
                "# TYPE pilot_total_xds_rejects counter\n"
                'pilot_total_xds_rejects{type="lds"} 12\n'
                'pilot_xds_pushes{type="rds_rejected"} 4\n'
                'pilot_xds_pushes{type="rds"} 99\n'
            ),
        )
        self.assertEqual(xds.proxy_nack_count, 3)
        self.assertEqual(xds.metric_reject_total, 16.0)
        self.assertEqual(xds.xds_types, ["CDS", "EDS", "LDS", "RDS"])

    def test_offline_logs_only_bundle_reports_nacks_instead_of_no_mesh(self):
        xds = msc.scan_xds_signals(
            proxy_logs={
                "auth/auth-1": (
                    "gRPC config for type.googleapis.com/envoy.config.listener.v3.Listener rejected: "
                    "Didn't find a registered implementation for 'istio_authn'\n"
                )
            }
        )
        report = msc.analyze_mesh_skew(control_planes=[], sidecars=[], xds_nacks=xds)
        self.assertEqual(report["status"], msc.STATUS_FINDINGS)
        self.assertEqual(report["findings"][0]["check"], msc.CHECK_ENVOY_XDS_NACK_LOOP)

    def test_healthy_aligned_mesh_reports_ok(self):
        cps = msc.extract_control_plane_records(
            deployments=[_istiod_deployment(image="gcr.io/gke-release/asm/pilot:1.20.4-asm.2", rev="asm-120-4")]
        )
        sidecars = msc.extract_sidecar_records(
            [_sidecar_pod(image="gcr.io/gke-release/asm/proxyv2:1.20.4-asm.2", rev="asm-120-4")]
        )
        report = msc.analyze_mesh_skew(control_planes=cps, sidecars=sidecars)
        self.assertEqual(report["status"], msc.STATUS_OK)
        self.assertEqual(report["findings"], [])

    def test_no_mesh_cluster_reports_no_mesh_detected(self):
        report = msc.analyze_mesh_skew(control_planes=[], sidecars=[])
        self.assertEqual(report["status"], msc.STATUS_NO_MESH)
        self.assertEqual(report["findings"], [])

    def test_sidecars_lagging_by_two_minors_and_mixed_revisions_flagged(self):
        cps = msc.extract_control_plane_records(
            deployments=[_istiod_deployment(image="gcr.io/gke-release/asm/pilot:1.21.1-asm.1", rev="asm-121-1")]
        )
        sidecars = msc.extract_sidecar_records(
            [
                _sidecar_pod(name="p-old", namespace="orders", image="gcr.io/gke-release/asm/proxyv2:1.19.5-asm.1", rev="asm-119-5"),
                _sidecar_pod(name="p-new", namespace="orders", image="gcr.io/gke-release/asm/proxyv2:1.21.1-asm.1", rev="asm-121-1"),
            ]
        )
        report = msc.analyze_mesh_skew(control_planes=cps, sidecars=sidecars)
        by_check = {f["check"]: f for f in report["findings"]}
        self.assertIn(msc.CHECK_SIDECAR_LAG_SKEW, by_check)
        self.assertEqual(by_check[msc.CHECK_SIDECAR_LAG_SKEW]["severity"], msc.SEVERITY_MAJOR)
        self.assertIn(msc.CHECK_MIXED_SIDECAR_REVISIONS, by_check)
        self.assertEqual(by_check[msc.CHECK_MIXED_SIDECAR_REVISIONS]["severity"], msc.SEVERITY_MINOR)

    def test_managed_channel_cpr_without_numeric_version_adds_operator_note(self):
        cps = msc.extract_control_plane_records(
            deployments=[],
            control_plane_revisions=[
                {
                    "metadata": {
                        "name": "asm-managed-stable",
                        "namespace": "istio-system",
                        "labels": {"mesh.cloud.google.com/managed-cpr": "true"},
                    },
                    "spec": {"channel": "STABLE"},
                }
            ],
        )
        sidecars = msc.extract_sidecar_records(
            [_sidecar_pod(image="gcr.io/gke-release/asm/proxyv2:1.20.4-asm.2", rev="asm-managed-stable")]
        )
        report = msc.analyze_mesh_skew(control_planes=cps, sidecars=sidecars)
        self.assertEqual(report["status"], msc.STATUS_OK)
        self.assertTrue(any("gcloud container fleet mesh describe" in note for note in report["notes"]))

    def test_managed_channel_cpr_with_status_version_detects_downgrade(self):
        cps = msc.extract_control_plane_records(
            deployments=[],
            control_plane_revisions=[
                {
                    "metadata": {
                        "name": "asm-managed-stable",
                        "namespace": "istio-system",
                        "annotations": {"mesh.cloud.google.com/version": "1.19.6-asm.1"},
                    },
                    "spec": {"channel": "STABLE"},
                }
            ],
        )
        sidecars = msc.extract_sidecar_records(
            [_sidecar_pod(image="gcr.io/gke-release/asm/proxyv2:1.20.4-asm.2", rev="asm-managed-stable")]
        )
        report = msc.analyze_mesh_skew(control_planes=cps, sidecars=sidecars)
        self.assertEqual(report["status"], msc.STATUS_FINDINGS)
        self.assertEqual(report["findings"][0]["check"], msc.CHECK_CP_OLDER_THAN_SIDECAR)

    def test_unread_errors_mark_partial_unread_instead_of_ok(self):
        report = msc.analyze_mesh_skew(
            control_planes=[],
            sidecars=[],
            unread=["pods: output truncated by credential proxy"],
        )
        self.assertEqual(report["status"], msc.STATUS_UNREAD)
        self.assertEqual(len(report["unread"]), 1)


class CollectAndCliTest(unittest.TestCase):
    def test_every_kubectl_command_is_admitted_by_command_policy(self):
        calls: list[list[str]] = []

        def fake_run(argv: list[str], **_kwargs) -> msc.Run:
            calls.append(argv)
            if argv[:4] == ["kubectl", "get", "deployments", "-n"]:
                ns = argv[4]
                if ns == "istio-system":
                    return msc.Run(argv, 0, json.dumps({"items": [_istiod_deployment()]}), "", 0.01)
                return msc.Run(argv, 0, json.dumps({"items": []}), "", 0.01)
            if argv[:4] == ["kubectl", "get", msc.CPR_RESOURCE, "-n"]:
                return msc.Run(
                    argv, 1, "", "error: the server doesn't have a resource type \"controlplanerevisions\"", 0.01
                )
            if argv[:3] == ["kubectl", "get", "--raw"]:
                raw_path = argv[3]
                if raw_path.startswith("/apis/admissionregistration.k8s.io/"):
                    return msc.Run(argv, 0, json.dumps({"items": []}), "", 0.01)
                if raw_path == "/api/v1/pods?limit=500":
                    return msc.Run(
                        argv,
                        0,
                        json.dumps(
                            {
                                "metadata": {"continue": "page2"},
                                "items": [_sidecar_pod(name="auth-1", namespace="auth", oom_killed=True, restart_count=3)],
                            }
                        ),
                        "",
                        0.01,
                    )
                if raw_path == "/api/v1/pods?limit=500&continue=page2":
                    gw_pod = {
                        "metadata": {
                            "name": "istio-ingressgateway-1",
                            "namespace": "istio-system",
                            "labels": {"istio": "ingressgateway"},
                        },
                        "spec": {
                            "initContainers": [
                                {"name": "istio-proxy", "image": "gcr.io/gke-release/asm/proxyv2:1.20.4-asm.2"}
                            ],
                            "containers": [{"name": "app", "image": "example.invalid/gw:1"}],
                        },
                        "status": {"initContainerStatuses": [{"name": "istio-proxy", "restartCount": 0}]},
                    }
                    return msc.Run(argv, 0, json.dumps({"metadata": {}, "items": [gw_pod]}), "", 0.01)
            if argv[:2] == ["kubectl", "logs"]:
                pod = argv[2]
                if pod == "auth-1" and "--previous" in argv:
                    return msc.Run(
                        argv,
                        0,
                        "gRPC config for type.googleapis.com/envoy.config.listener.v3.Listener rejected: "
                        "Didn't find a registered implementation for 'istio_authn'\n",
                        "",
                        0.01,
                    )
                if pod == "istio-ingressgateway-1":
                    return msc.Run(
                        argv, 0, "[2026-10-01] \"GET /login HTTP/1.1\" 503 UH no_healthy_upstream\n", "", 0.01
                    )
                return msc.Run(argv, 0, "", "", 0.01)
            return msc.Run(argv, 1, "", f"unexpected command: {argv}", 0.01)

        report = msc.collect_and_analyze(run=fake_run)
        self.assertEqual(report["status"], msc.STATUS_FINDINGS)
        self.assertEqual(report["unread"], [])
        checks = {f["check"] for f in report["findings"]}
        self.assertEqual(checks, {msc.CHECK_CP_OLDER_THAN_SIDECAR, msc.CHECK_ENVOY_XDS_NACK_LOOP})
        # Every emitted kubectl command must be admitted by command_policy.
        for argv in calls:
            decision = command_policy.evaluate(argv)
            self.assertTrue(decision.allowed, f"command_policy refused {argv}: {decision}")
        # Gateway pod was already read in proxy_logs; it must NOT be fetched twice.
        gw_log_calls = [c for c in calls if c[:2] == ["kubectl", "logs"] and c[2] == "istio-ingressgateway-1"]
        self.assertEqual(len(gw_log_calls), 1)
        self.assertIn("istio-proxy", gw_log_calls[0])

    def test_collect_records_proxy_truncation_on_pods_and_previous_logs(self):
        def fake_run(argv: list[str], **_kwargs) -> msc.Run:
            if argv[:3] == ["kubectl", "get", "--raw"] and argv[3].startswith("/api/v1/pods"):
                return msc.Run(argv, 74, "", "credential proxy output truncated at 50KB", 0.01)
            return msc.Run(argv, 0, json.dumps({"items": []}), "", 0.01)

        report = msc.collect_and_analyze(run=fake_run, skip_logs=True)
        self.assertEqual(report["status"], msc.STATUS_UNREAD)
        self.assertTrue(any("truncated" in err for err in report["unread"]))

        # Also verify truncation on --previous log read is recorded in unread.
        def fake_prev_truncated(argv: list[str], **_kwargs) -> msc.Run:
            if argv[:4] == ["kubectl", "get", "deployments", "-n"] and argv[4] == "istio-system":
                return msc.Run(argv, 0, json.dumps({"items": [_istiod_deployment(image="gcr.io/gke-release/asm/pilot:1.20.4-asm.2", rev="asm-120-4")]}), "", 0.01)
            if argv[:3] == ["kubectl", "get", "--raw"] and argv[3].startswith("/api/v1/pods"):
                return msc.Run(argv, 0, json.dumps({"items": [_sidecar_pod(name="p1", oom_killed=True, restart_count=2)]}), "", 0.01)
            if argv[:2] == ["kubectl", "logs"] and "--previous" in argv:
                return msc.Run(argv, 74, "", "credential proxy output truncated at 50KB", 0.01)
            if argv[:2] == ["kubectl", "logs"]:
                return msc.Run(argv, 0, "", "", 0.01)
            return msc.Run(argv, 0, json.dumps({"items": []}), "", 0.01)

        prev_report = msc.collect_and_analyze(run=fake_prev_truncated)
        self.assertEqual(prev_report["status"], msc.STATUS_UNREAD)
        self.assertTrue(any("--previous" in err and "truncated" in err for err in prev_report["unread"]))

    def test_cli_input_json_and_exit_codes(self):
        bundle = {
            "deployments": [_istiod_deployment()],
            "pods": [_sidecar_pod(oom_killed=True, restart_count=2)],
            "proxy_logs": {
                "payments/auth-gw-7f9b": (
                    "gRPC config for type.googleapis.com/envoy.config.listener.v3.Listener rejected: "
                    "Didn't find a registered implementation for 'istio_authn'\n"
                )
            },
            "gateway_logs": {"istio-system/gw-1": 'response_flag: "UH" no_healthy_upstream\n'},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bundle.json"
            path.write_text(json.dumps(bundle), encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = msc.main(["--input-json", str(path), "--format", "json"])
            self.assertEqual(rc, msc.EXIT_FINDINGS)
            parsed = json.loads(buf.getvalue())
            self.assertEqual(parsed["status"], msc.STATUS_FINDINGS)

            text_buf = io.StringIO()
            with redirect_stdout(text_buf):
                rc_text = msc.main(["--input-json", str(path), "--format", "text"])
            self.assertEqual(rc_text, msc.EXIT_FINDINGS)
            self.assertIn("control-plane-older-than-sidecar", text_buf.getvalue())
            self.assertIn("envoy-xds-nack-loop", text_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
