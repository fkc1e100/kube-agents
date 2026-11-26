# Internal Implementation Specifications

Deep behavioral edge-case specifications relocated out of the published `docs/site/` user pages so human-facing documentation stays concise while preserving exact contracts for contributors and AI coding agents.

## Operator & CRD internals
- [PlatformAgent harness configuration](platformagent-harness.md)
- [PlatformAgent scope, networking, and integrations](platformagent-scope-integrations.md)
- [PlatformAgent profile config propagation](platformagent-profile-config.md)

## ChatOps & upgrade internals
- [ChatOps: A2A gateway & conversations](chatops-a2a-gateway.md)
- [ChatOps: Proactive alerts](chatops-proactive-alerts.md)
- [Upgrading to the A2A stack & troubleshooting](upgrade-a2a-migration.md)

## Security, credential isolation & observability internals
- [Security: Kubernetes RBAC](security-rbac.md)
- [Security: Change control & safety](security-change-control.md)
- [Credential isolation: Pod anatomy](credential-isolation-pod-anatomy.md)
- [Credential isolation: Metadata denial & troubleshooting](credential-isolation-troubleshooting.md)
- [Observability: Exported telemetry catalog](observability-exports.md)
