#!/usr/bin/env python3
# agent_roster.py - Which specialist profiles exist, what each is for, and the
# host cluster & fleet scope identity they operate over.
#
# The Chat Agent needs this to pick an `assignee` before it delegates, and to
# answer static fleet/host scope questions or disambiguate "this cluster"
# without an extra roundtrip. Two consumers read it:
#
#   * ``router_server.py``'s ``list_agents`` MCP tool — the on-demand refresh
#     path, for when a named agent is missing or the injected roster is stale.
#   * the ``agent_roster`` plugin (``agents/chat/defaults/plugins/agent_roster``)
#     — injects the roster into every turn's context, so the common case costs
#     no tool call at all. Measured on the live deployment, calling the tool cost
#     a full LLM roundtrip (~6s of a ~17s acknowledgement) to re-read what is, in
#     the end, a directory listing.
#
# Both must describe the same fleet in the same words, which is the reason this
# lives in its own module rather than being duplicated into the plugin: a roster
# that disagrees with itself between the injected block and the tool is worse
# than either one alone.
#
# Everything here degrades rather than raises. The profiles live on a shared
# PVC, so an I/O or permission fault must not turn routing into a traceback.

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))
# Hermes stores each profile at $HERMES_HOME/profiles/<name> (persists on the data PVC).
PROFILES_BASE = HERMES_HOME / "profiles"
_DEFAULT_PROFILES_BASE = PROFILES_BASE
SCOPE_FILE = Path(os.environ.get("KUBEAGENTS_SCOPE_FILE", "/etc/kube-agents/scope.json"))
_DEFAULT_SCOPE_FILE = SCOPE_FILE
_MAX_NAME_LEN = 63

# The front door itself; never a valid delegation target.
SELF_PROFILE = "default"

EMPTY_ROSTER = "No specialist agents are currently available to route to."
# Discovery failed. Deliberately not EMPTY_ROSTER: an unreadable profiles
# directory must not be reported to the Chat Agent as an empty fleet.
UNKNOWN_ROSTER = (
    "The specialist roster could not be read right now. Do not conclude that no "
    "agents exist; retry, and say so plainly if it keeps failing."
)
NO_DESCRIPTION = "(no description provided)"


def log(msg: str) -> None:
    print(f"[AGENT-ROSTER] {msg}", file=sys.stderr)


def _cluster_profile_name(project: str, cluster: str, location: str) -> str:
    """Derive the canonical Cluster Agent profile name for a target GKE cluster."""
    raw = f"cluster-{project}-{cluster}-{location}".lower()
    name = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9-]+", "-", raw)).strip("-")
    if len(name) > _MAX_NAME_LEN:
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        name = f"{name[: _MAX_NAME_LEN - 9]}-{digest}"
    return name


def _parse_cluster_identity_text(text: str) -> dict[str, str] | None:
    """Extract ``cluster_identity: {project, cluster, location}`` from config.yaml text.

    Uses PyYAML when installed and falls back to a minimal stdlib block parser so
    this module remains usable in bare stdlib environments.
    """
    data: Any = None
    try:
        import yaml  # type: ignore[import-untyped]

        data = yaml.safe_load(text)
    except ImportError:
        data = None
    except Exception:
        return None

    if isinstance(data, dict):
        identity = data.get("cluster_identity")
        if isinstance(identity, dict):
            project = str(identity.get("project") or "").strip()
            cluster = str(identity.get("cluster") or "").strip()
            location = str(identity.get("location") or "").strip()
            if project and cluster and location:
                return {"project": project, "cluster": cluster, "location": location}
        return None

    # Stdlib fallback when PyYAML is not installed.
    in_block = False
    block_indent: int | None = None
    fields: dict[str, str] = {}
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if not in_block:
            if indent == 0 and re.match(r"^cluster_identity\s*:\s*$", stripped):
                in_block = True
                block_indent = None
            continue
        if indent == 0 or (block_indent is not None and indent < block_indent):
            break
        if block_indent is None:
            block_indent = indent
        m = re.match(r"^(project|cluster|location)\s*:\s*(.+?)\s*$", stripped)
        if m:
            val = m.group(2).strip().strip("'\"")
            if val:
                fields[m.group(1)] = val
    if all(k in fields for k in ("project", "cluster", "location")):
        return {
            "project": fields["project"],
            "cluster": fields["cluster"],
            "location": fields["location"],
        }
    return None


def _read_cluster_identity(home: Path) -> dict[str, str] | None:
    """Read ``cluster_identity`` from ``<profile>/config.yaml``, degrading on any error."""
    cfg = home / "config.yaml"
    try:
        if not cfg.is_file():
            return None
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return _parse_cluster_identity_text(text)


def _summarize_soul(home: Path) -> str:
    """Fallback responsibilities: the first prose line of the profile's SOUL.md."""
    soul = home / "SOUL.md"
    # is_file() is inside the try: pathlib only swallows ENOENT/ENOTDIR/EBADF/ELOOP,
    # so a stat() that fails with EACCES or EIO on the shared PVC raises here too.
    try:
        if not soul.is_file():
            return ""
        lines = soul.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("---"):
            continue
        return s
    return ""


def _responsibilities(home: Path) -> str:
    """A one-shot description of what a profile is responsible for.

    Prefers an explicit CAPABILITIES.md (the routing contract a specialist
    advertises to the Chat Agent); falls back to the SOUL.md summary so a
    profile is still discoverable even without a capabilities file.
    """
    cap = home / "CAPABILITIES.md"
    try:
        text = cap.read_text(encoding="utf-8", errors="replace").strip() if cap.is_file() else ""
    except OSError:
        text = ""
    if text:
        return text
    return _summarize_soul(home)


def discover(base: Path | None = None) -> list[dict[str, Any]] | None:
    """Enumerate every routable specialist profile (all profiles except `default`).

    Degrades rather than raises. Errors are isolated per profile: one unreadable
    directory costs that one agent, not the whole roster.

    Returns ``None`` — distinct from ``[]`` — when the profiles directory itself
    could not be listed. "I could not read the fleet" and "there is no fleet"
    are different answers: the second is a fact the Chat Agent should act on,
    the first must not be reported as one.

    ``base`` defaults to the module-level ``PROFILES_BASE`` at call time rather
    than at import time, so a caller (or a test) that rebinds ``PROFILES_BASE``
    is still honoured.
    """
    root = PROFILES_BASE if base is None else base
    agents: list[dict[str, Any]] = []
    try:
        entries = sorted(root.iterdir()) if root.is_dir() else []
    except OSError as e:
        log(f"cannot list profiles at {root}: {e}")
        return None
    for p in entries:
        try:
            if not p.is_dir() or p.name == SELF_PROFILE:
                continue
            entry: dict[str, Any] = {
                "name": p.name,
                "responsibilities": _responsibilities(p),
            }
            identity = _read_cluster_identity(p)
            if identity is not None:
                entry["cluster_identity"] = identity
            agents.append(entry)
        except OSError as e:
            log(f"skipping unreadable profile {p.name}: {e}")
    return agents


def _read_host_identity(agents: list[dict[str, Any]] | None = None) -> dict[str, str] | None:
    """Read host cluster identity from environment variables and match its assignee."""
    cluster = os.environ.get("GKE_CLUSTER_NAME", "").strip()
    project = (
        os.environ.get("GKE_PROJECT_ID", "").strip()
        or os.environ.get("GCP_PROJECT_ID", "").strip()
    )
    location = os.environ.get("GKE_LOCATION", "").strip()
    if not (cluster or project or location):
        return None

    assignee = ""
    for a in agents or []:
        cid = a.get("cluster_identity")
        if not isinstance(cid, dict):
            continue
        if cluster and cid.get("cluster") != cluster:
            continue
        if project and cid.get("project") != project:
            continue
        if location and cid.get("location") != location:
            continue
        assignee = str(a.get("name") or "")
        project = project or str(cid.get("project") or "")
        cluster = cluster or str(cid.get("cluster") or "")
        location = location or str(cid.get("location") or "")
        break

    if not assignee and project and cluster and location:
        assignee = _cluster_profile_name(project, cluster, location)

    result: dict[str, str] = {}
    if cluster:
        result["cluster"] = cluster
    if project:
        result["project"] = project
    if location:
        result["location"] = location
    if assignee:
        result["assignee"] = assignee
    return result or None


def _extract_projects_from_json(path: Path) -> list[str]:
    """Read project IDs from either ``scope.json`` or ``fleet_scope.json``."""
    try:
        if not path.is_file():
            return []
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(payload, dict):
        return []

    found: list[str] = []
    raw_projects = payload.get("projects")
    if isinstance(raw_projects, list):
        for item in raw_projects:
            if isinstance(item, str) and item.strip():
                found.append(item.strip())
            elif isinstance(item, dict):
                state = str(item.get("state") or "in-scope").strip().lower()
                if state == "excluded":
                    continue
                pid = str(item.get("id") or item.get("project") or "").strip()
                if pid:
                    found.append(pid)

    declared = payload.get("declared")
    if isinstance(declared, dict) and isinstance(declared.get("projects"), list):
        for item in declared["projects"]:
            if isinstance(item, str) and item.strip():
                found.append(item.strip())
    return found


def _read_scope_projects(
    base: Path | None = None,
    agents: list[dict[str, Any]] | None = None,
    host_identity: dict[str, str] | None = None,
) -> list[str]:
    """Collect all in-scope GCP project IDs from scope files, host env, and cluster profiles."""
    root = PROFILES_BASE if base is None else base
    projects: set[str] = set()

    # 1. Operator-mounted scope file (/etc/kube-agents/scope.json or KUBEAGENTS_SCOPE_FILE).
    # In unit tests that point `base` at a temp directory without setting
    # KUBEAGENTS_SCOPE_FILE or rebinding SCOPE_FILE, skip the host's /etc path
    # so tests remain hermetic.
    scope_path: Path | None = None
    if SCOPE_FILE != _DEFAULT_SCOPE_FILE:
        scope_path = SCOPE_FILE
    elif "KUBEAGENTS_SCOPE_FILE" in os.environ:
        env_scope = os.environ.get("KUBEAGENTS_SCOPE_FILE", "").strip()
        if env_scope:
            scope_path = Path(env_scope)
    elif root == _DEFAULT_PROFILES_BASE:
        scope_path = _DEFAULT_SCOPE_FILE

    if scope_path is not None:
        projects.update(_extract_projects_from_json(scope_path))

    # 2. Reconciled fleet_scope.json in the Hermes data root ($HERMES_HOME/fleet_scope.json).
    try:
        fleet_scope_path = root.parent / "fleet_scope.json"
        projects.update(_extract_projects_from_json(fleet_scope_path))
    except OSError:
        pass

    # 3. Host cluster project from environment.
    if host_identity and host_identity.get("project"):
        projects.add(host_identity["project"])

    # 4. Projects from discovered cluster agent profiles.
    for a in agents or []:
        cid = a.get("cluster_identity")
        if isinstance(cid, dict) and cid.get("project"):
            projects.add(str(cid["project"]))

    return sorted(projects)


def _format_fleet_and_host_section(
    agents: list[dict[str, Any]],
    base: Path | None = None,
    host_identity: dict[str, str] | None = None,
    scope_projects: list[str] | None = None,
) -> str:
    """Format the Host Cluster Identity and Fleet Clusters & GCP Projects in Scope block."""
    host = _read_host_identity(agents) if host_identity is None else host_identity
    projects = (
        _read_scope_projects(base=base, agents=agents, host_identity=host)
        if scope_projects is None
        else sorted(set(scope_projects))
    )

    cluster_entries: list[dict[str, Any]] = []
    seen_assignees: set[str] = set()
    for a in agents:
        cid = a.get("cluster_identity")
        if not isinstance(cid, dict):
            continue
        c_name = str(cid.get("cluster") or "").strip()
        c_proj = str(cid.get("project") or "").strip()
        c_loc = str(cid.get("location") or "").strip()
        assignee = str(a.get("name") or "").strip()
        if not (c_name and c_proj and c_loc and assignee):
            continue
        is_host = bool(
            host
            and (
                (host.get("assignee") and host["assignee"] == assignee)
                or (
                    host.get("cluster") == c_name
                    and (not host.get("project") or host.get("project") == c_proj)
                )
            )
        )
        cluster_entries.append(
            {
                "cluster": c_name,
                "project": c_proj,
                "location": c_loc,
                "assignee": assignee,
                "is_host": is_host,
            }
        )
        seen_assignees.add(assignee)

    if (
        host
        and host.get("cluster")
        and host.get("project")
        and host.get("location")
        and host.get("assignee")
        and host["assignee"] not in seen_assignees
        and any(a.get("name") == host["assignee"] for a in agents)
    ):
        cluster_entries.append(
            {
                "cluster": host["cluster"],
                "project": host["project"],
                "location": host["location"],
                "assignee": host["assignee"],
                "is_host": True,
            }
        )

    cluster_entries.sort(key=lambda e: (e["project"], e["cluster"], e["location"]))

    sections: list[str] = []
    if host:
        parts: list[str] = []
        if host.get("cluster"):
            parts.append(f"cluster={host['cluster']}")
        if host.get("project"):
            parts.append(f"project={host['project']}")
        if host.get("location"):
            parts.append(f"location={host['location']}")
        if host.get("assignee"):
            parts.append(f"assignee={host['assignee']}")
        if parts:
            sections.append(
                'Host Cluster Identity ("this cluster" / "this host cluster"):\n'
                f"- {', '.join(parts)}"
            )

    fleet_lines: list[str] = []
    if projects:
        fleet_lines.append(
            f"- GCP projects in scope ({len(projects)}): {', '.join(projects)}"
        )
    if cluster_entries:
        fleet_lines.append(f"- Managed GKE clusters ({len(cluster_entries)}):")
        for c in cluster_entries:
            suffix = ", host cluster" if c["is_host"] else ""
            fleet_lines.append(
                f"  - {c['cluster']} (project={c['project']}, "
                f"location={c['location']}, assignee={c['assignee']}{suffix})"
            )
    if fleet_lines:
        sections.append(
            "Fleet Clusters & GCP Projects in Scope:\n" + "\n".join(fleet_lines)
        )

    return "\n\n".join(sections)


def format_roster(
    agents: list[dict[str, Any]] | None,
    base: Path | None = None,
    host_identity: dict[str, str] | None = None,
    scope_projects: list[str] | None = None,
) -> str | None:
    """Render the roster the Chat Agent reads, or ``None`` if it is unknowable.

    Agents sharing an identical role description are grouped so the description
    is stated once instead of repeated verbatim per agent — every Cluster Agent
    is scaffolded from the same template, so a fleet of thirty would otherwise
    be thirty copies of one paragraph. Assignee names are always listed
    individually, because the name is the part the caller has to get exactly
    right.

    When host cluster environment variables, scope files, or per-cluster
    ``cluster_identity`` metadata are present, appends the structured Host
    Cluster Identity and Fleet Clusters & GCP Projects in Scope summary so the
    front door can answer static fleet/host identity questions directly and
    route "this cluster" requests to the host cluster agent without asking the
    user to disambiguate.

    ``None`` in (discovery failed) is ``None`` out; callers decide how to say
    "unknown", which is not the same thing as ``EMPTY_ROSTER``.
    """
    if agents is None:
        return None
    if not agents:
        return EMPTY_ROSTER

    groups: dict[str, list[str]] = {}
    # A missing description is an absence, not a shared role: grouping on the
    # placeholder would announce unrelated profiles as one interchangeable
    # fleet, and the "pick the one whose cluster you need" preamble would be a
    # lie about agents nothing is known of. Each gets its own line.
    undescribed: list[str] = []
    for a in agents:
        desc = a["responsibilities"]
        if desc:
            groups.setdefault(desc, []).append(a["name"])
        else:
            undescribed.append(a["name"])

    # Distinct specialists first, then the shared-role fleets — the front door routes to a
    # named specialist far more often than to a specific cluster. The undescribed trail
    # both: they are the least useful entries to route from.
    blocks: list[str] = []
    for desc, names in sorted(groups.items(), key=lambda kv: len(kv[1])):
        if len(names) == 1:
            blocks.append(f"- {names[0]}: {desc}")
            continue
        listed = "\n".join(f"  - {n}" for n in names)
        blocks.append(
            f"The following {len(names)} agents share one role — pick the one whose cluster "
            f"you need:\n{listed}\n  Shared role: {desc}"
        )
    blocks.extend(f"- {name}: {NO_DESCRIPTION}" for name in undescribed)

    fleet_section = _format_fleet_and_host_section(
        agents,
        base=base,
        host_identity=host_identity,
        scope_projects=scope_projects,
    )
    if fleet_section:
        blocks.append(fleet_section)

    return "\n\n".join(blocks)


def render(base: Path | None = None) -> str | None:
    """Discover and format in one call — what both consumers actually want.

    ``None`` means the roster could not be read at all. Both consumers treat
    that as "say nothing about the fleet" rather than "the fleet is empty".
    """
    return format_roster(discover(base), base=base)
