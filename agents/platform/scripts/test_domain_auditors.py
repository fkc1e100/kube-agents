#!/usr/bin/env python3
"""Unit tests for the #3285 single-pass cluster domain auditors:
- audit_certificates.py
- audit_storage.py
- audit_networking.py
- audit_network_policies.py
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import audit_certificates  # noqa: E402
import audit_network_policies  # noqa: E402
import audit_networking  # noqa: E402
import audit_storage  # noqa: E402


class TestAuditCertificates(unittest.TestCase):
    def test_absent_crds_with_tls_secrets_emits_clean_stop(self):
        def fake_run_cmd(args, env):
            return 0, "agentprofiles.kubeagents.x-k8s.io\n"

        def fake_run_kubectl_json(args, env):
            if "secrets" in args:
                return 0, {
                    "items": [
                        {
                            "metadata": {
                                "namespace": "kubeagents-system",
                                "name": "webhook-tls",
                                "creationTimestamp": "2026-10-14T10:00:00Z",
                            }
                        },
                        {
                            "metadata": {
                                "namespace": "default",
                                "name": "app-tls",
                                "creationTimestamp": "2026-10-15T10:00:00Z",
                            }
                        },
                    ]
                }
            return 0, {"items": []}

        buf = io.StringIO()
        with (
            mock.patch.object(audit_certificates, "run_cmd", side_effect=fake_run_cmd),
            mock.patch.object(audit_certificates, "run_kubectl_json", side_effect=fake_run_kubectl_json),
            contextlib.redirect_stdout(buf),
        ):
            rc = audit_certificates.audit_certificates()

        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("- **cert_manager_installed:** `false`", out)
        self.assertIn("2 secret(s) across 2 namespace(s) [default (1), kubeagents-system (1)]", out)
        self.assertIn(
            "CLEAN_AUDIT_STOP: YES — No expiring or failed certificates/issuers found; call kanban_complete immediately.",
            out,
        )

    def test_partial_crds_zero_objects_and_rbac_forbidden_secrets_emits_clean_stop(self):
        """Regression test for R6 P09 on hub clusters where only certificates & clusterissuers CRDs exist."""

        def fake_run_cmd(args, env):
            return 0, "certificates.cert-manager.io\nclusterissuers.cert-manager.io\n"

        def fake_run_kubectl_json(args, env):
            if "secrets" in args:
                return 1, {"stderr": 'Error from server (Forbidden): secrets is forbidden'}
            return 0, {"items": []}

        buf = io.StringIO()
        with (
            mock.patch.object(audit_certificates, "run_cmd", side_effect=fake_run_cmd),
            mock.patch.object(audit_certificates, "run_kubectl_json", side_effect=fake_run_kubectl_json),
            contextlib.redirect_stdout(buf),
        ):
            rc = audit_certificates.audit_certificates()

        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("- **cert_manager_installed:** `true`", out)
        self.assertIn("Partial CRD installation", out)
        self.assertIn("RBAC restricts cluster-wide Secret listing", out)
        self.assertIn(
            "CLEAN_AUDIT_STOP: YES — No expiring or failed certificates/issuers found; call kanban_complete immediately.",
            out,
        )

    def test_healthy_active_certs_and_issuers_emits_clean_stop(self):
        def fake_run_cmd(args, env):
            return 0, "\n".join(audit_certificates.CERT_MANAGER_CRDS)

        def fake_run_kubectl_json(args, env):
            if "certificates.cert-manager.io" in args:
                return 0, {
                    "items": [
                        {
                            "metadata": {"namespace": "kubeagents-system", "name": "serving-cert"},
                            "spec": {
                                "secretName": "webhook-certs",
                                "issuerRef": {"kind": "Issuer", "name": "selfsigned"},
                            },
                            "status": {
                                "notAfter": "2099-01-01T00:00:00Z",
                                "conditions": [{"type": "Ready", "status": "True", "reason": "Ready"}],
                            },
                        }
                    ]
                }
            if "issuers.cert-manager.io" in args:
                return 0, {
                    "items": [
                        {
                            "metadata": {"namespace": "kubeagents-system", "name": "selfsigned"},
                            "spec": {"selfSigned": {}},
                            "status": {"conditions": [{"type": "Ready", "status": "True", "reason": "IsReady"}]},
                        }
                    ]
                }
            return 0, {"items": []}

        buf = io.StringIO()
        with (
            mock.patch.object(audit_certificates, "run_cmd", side_effect=fake_run_cmd),
            mock.patch.object(audit_certificates, "run_kubectl_json", side_effect=fake_run_kubectl_json),
            contextlib.redirect_stdout(buf),
        ):
            rc = audit_certificates.audit_certificates()

        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("1 total (1 Ready, 0 Unready/Degraded)", out)
        self.assertIn("CLEAN_AUDIT_STOP: YES", out)

    def test_degraded_certificate_emits_clean_stop_no(self):
        def fake_run_cmd(args, env):
            return 0, "\n".join(audit_certificates.CERT_MANAGER_CRDS)

        def fake_run_kubectl_json(args, env):
            if "certificates.cert-manager.io" in args:
                return 0, {
                    "items": [
                        {
                            "metadata": {"namespace": "prod", "name": "broken-cert"},
                            "spec": {
                                "secretName": "broken-tls",
                                "issuerRef": {"kind": "ClusterIssuer", "name": "letsencrypt"},
                            },
                            "status": {
                                "conditions": [
                                    {
                                        "type": "Ready",
                                        "status": "False",
                                        "reason": "Issuing",
                                        "message": "Waiting for ACME challenge",
                                    }
                                ]
                            },
                        }
                    ]
                }
            return 0, {"items": []}

        buf = io.StringIO()
        with (
            mock.patch.object(audit_certificates, "run_cmd", side_effect=fake_run_cmd),
            mock.patch.object(audit_certificates, "run_kubectl_json", side_effect=fake_run_kubectl_json),
            contextlib.redirect_stdout(buf),
        ):
            rc = audit_certificates.audit_certificates()

        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Degraded Certificates Detected", out)
        self.assertIn("CLEAN_AUDIT_STOP: NO", out)
        self.assertIn("Waiting for ACME challenge", out)


class TestAuditStorage(unittest.TestCase):
    def test_healthy_storage_emits_clean_stop(self):
        def fake_run_kubectl_json(args, env):
            if "pvc" in args:
                return 0, {
                    "items": [
                        {
                            "metadata": {"namespace": "default", "name": "data-pvc"},
                            "spec": {
                                "volumeName": "pv-1",
                                "storageClassName": "standard-rwo",
                                "resources": {"requests": {"storage": "10Gi"}},
                            },
                            "status": {"phase": "Bound"},
                        }
                    ]
                }
            if "pv" in args:
                return 0, {
                    "items": [
                        {
                            "metadata": {"name": "pv-1"},
                            "spec": {
                                "capacity": {"storage": "10Gi"},
                                "persistentVolumeReclaimPolicy": "Delete",
                                "claimRef": {"namespace": "default", "name": "data-pvc"},
                            },
                            "status": {"phase": "Bound"},
                        }
                    ]
                }
            if "sc" in args:
                return 0, {
                    "items": [
                        {
                            "metadata": {
                                "name": "standard-rwo",
                                "annotations": {"storageclass.kubernetes.io/is-default-class": "true"},
                            },
                            "provisioner": "pd.csi.storage.gke.io",
                            "reclaimPolicy": "Delete",
                            "volumeBindingMode": "WaitForFirstConsumer",
                        }
                    ]
                }
            return 0, {"items": []}

        buf = io.StringIO()
        with (
            mock.patch.object(audit_storage, "run_kubectl_json", side_effect=fake_run_kubectl_json),
            contextlib.redirect_stdout(buf),
        ):
            rc = audit_storage.audit_storage()

        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Storage Audit Verdict: Clean & Fully Healthy", out)
        self.assertIn("CLEAN_AUDIT_STOP: YES", out)

    def test_degraded_storage_emits_stop_no(self):
        def fake_run_kubectl_json(args, env):
            if "pvc" in args:
                return 0, {
                    "items": [
                        {
                            "metadata": {"namespace": "default", "name": "stuck-pvc"},
                            "spec": {"storageClassName": "missing-sc"},
                            "status": {"phase": "Pending"},
                        }
                    ]
                }
            return 0, {"items": []}

        buf = io.StringIO()
        with (
            mock.patch.object(audit_storage, "run_kubectl_json", side_effect=fake_run_kubectl_json),
            contextlib.redirect_stdout(buf),
        ):
            rc = audit_storage.audit_storage()

        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Storage Audit Verdict: Degradation Detected", out)
        self.assertIn("CLEAN_AUDIT_STOP: NO", out)


class TestAuditNetworking(unittest.TestCase):
    def test_healthy_networking_emits_clean_stop(self):
        def fake_run_kubectl_json(args, env):
            if "svc" in args:
                return 0, {
                    "items": [
                        {
                            "metadata": {"namespace": "prod", "name": "frontend-lb"},
                            "spec": {
                                "type": "LoadBalancer",
                                "clusterIP": "10.0.0.10",
                                "ports": [{"port": 443, "targetPort": 8443, "protocol": "TCP"}],
                            },
                            "status": {"loadBalancer": {"ingress": [{"ip": "34.100.1.2"}]}},
                        }
                    ]
                }
            if "gateways.gateway.networking.k8s.io" in args:
                return 0, {
                    "items": [
                        {
                            "metadata": {"namespace": "prod", "name": "ext-gw"},
                            "spec": {"gatewayClassName": "gke-l7-global-external-managed"},
                            "status": {
                                "addresses": [{"value": "34.100.1.3"}],
                                "conditions": [{"type": "Programmed", "status": "True", "reason": "Programmed"}],
                            },
                        }
                    ]
                }
            return 0, {"items": []}

        buf = io.StringIO()
        with (
            mock.patch.object(audit_networking, "run_kubectl_json", side_effect=fake_run_kubectl_json),
            contextlib.redirect_stdout(buf),
        ):
            rc = audit_networking.audit_networking()

        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Networking Audit Verdict: Clean & Fully Programmed", out)
        self.assertIn("CLEAN_AUDIT_STOP: YES", out)

    def test_degraded_networking_emits_stop_no(self):
        def fake_run_kubectl_json(args, env):
            if "svc" in args:
                return 0, {
                    "items": [
                        {
                            "metadata": {"namespace": "prod", "name": "pending-lb"},
                            "spec": {"type": "LoadBalancer", "clusterIP": "10.0.0.11", "ports": []},
                            "status": {"loadBalancer": {}},
                        }
                    ]
                }
            return 0, {"items": []}

        buf = io.StringIO()
        with (
            mock.patch.object(audit_networking, "run_kubectl_json", side_effect=fake_run_kubectl_json),
            contextlib.redirect_stdout(buf),
        ):
            rc = audit_networking.audit_networking()

        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Networking Audit Verdict: Routing / VIP Degradation Detected", out)
        self.assertIn("CLEAN_AUDIT_STOP: NO", out)


class TestAuditNetworkPolicies(unittest.TestCase):
    def test_network_policies_summary_and_clean_stop(self):
        def fake_run_kubectl_json(args, env):
            if "ns" in args:
                return 0, {
                    "items": [
                        {"metadata": {"name": "default"}},
                        {"metadata": {"name": "kube-system"}},
                        {"metadata": {"name": "prod"}},
                    ]
                }
            if "networkpolicies" in args:
                return 0, {
                    "items": [
                        {
                            "metadata": {"namespace": "prod", "name": "deny-all"},
                            "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
                        }
                    ]
                }
            return 0, {"items": []}

        buf = io.StringIO()
        with (
            mock.patch.object(audit_network_policies, "run_kubectl_json", side_effect=fake_run_kubectl_json),
            contextlib.redirect_stdout(buf),
        ):
            rc = audit_network_policies.audit_network_policies()

        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("- **Total Namespaces:** 3", out)
        self.assertIn("- **Namespaces Protected by NetworkPolicies:** 1", out)
        self.assertIn("- **Namespaces Without NetworkPolicies:** 2", out)
        self.assertIn("CLEAN_AUDIT_STOP: YES", out)
        self.assertIn("default, kube-system", out)


if __name__ == "__main__":
    unittest.main()
