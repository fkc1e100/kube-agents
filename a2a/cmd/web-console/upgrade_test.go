/*
Copyright 2026 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

func TestUpgradeStartAndStatusLifecycle(t *testing.T) {
	var (
		mu      sync.Mutex
		podJSON map[string]any
		phase   = "Running"
		logs    = ">>> 1. Validating Upgrade Target & Environment <<<\n  ✓ Loaded install configuration\n>>> 4. Upgrading Kubernetes Operator (CRDs & Controller Manager) <<<\n"
	)

	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer sa-token" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/api/v1/namespaces/kubeagents-system/pods/kube-agents-upgrade-runner":
			if podJSON == nil {
				w.WriteHeader(http.StatusNotFound)
				fmt.Fprint(w, `{"message":"not found"}`)
				return
			}
			w.Header().Set("Content-Type", contentTypeJSON)
			meta, _ := podJSON["metadata"].(map[string]any)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"metadata": meta,
				"status": map[string]any{
					"phase":     phase,
					"startTime": "2026-10-15T22:00:00Z",
				},
			})
		case r.Method == http.MethodPost && r.URL.Path == "/api/v1/namespaces/kubeagents-system/pods":
			raw, _ := io.ReadAll(r.Body)
			_ = json.Unmarshal(raw, &podJSON)
			w.Header().Set("Content-Type", contentTypeJSON)
			w.WriteHeader(http.StatusCreated)
			_, _ = w.Write(raw)
		case r.Method == http.MethodGet && r.URL.Path == "/api/v1/namespaces/kubeagents-system/pods/kube-agents-upgrade-runner/log":
			w.Header().Set("Content-Type", "text/plain")
			fmt.Fprint(w, logs)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer api.Close()

	_, s := setupServer(t)
	s.cfg.PodNamespace = "kubeagents-system"
	s.cfg.ProjectID = "gca-gke-test"
	s.cfg.ClusterName = "ka-webconsole-pr2321"
	s.cfg.Location = "us-central1"
	s.cfg.ImageTag = "0.8.0"
	s.cfg.ChartVersion = "0.8.0"
	s.kube = &kubeClient{base: api.URL, token: "sa-token", client: api.Client()}
	h := s.routes()

	// 1. Status is initially idle.
	rec0 := serve(h, httptest.NewRequest(http.MethodGet, "http://localhost:8080/api/upgrade/status", nil))
	if rec0.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec0.Code, rec0.Body.String())
	}
	if st := decode[upgradeStatusResponse](t, rec0); st.State != "idle" {
		t.Fatalf("want idle, got %+v", st)
	}

	// 2. Start upgrade to 0.12.0.
	startReq := httptest.NewRequest(http.MethodPost, "http://localhost:8080/api/upgrade", strings.NewReader(`{"target":"0.12.0"}`))
	startReq.Header.Set("Content-Type", contentTypeJSON)
	startReq.Header.Set(consoleHeader, consoleHeaderValue)
	rec1 := serve(h, startReq)
	if rec1.Code != http.StatusAccepted {
		t.Fatalf("want 202, got %d: %s", rec1.Code, rec1.Body.String())
	}
	st1 := decode[upgradeStatusResponse](t, rec1)
	if st1.State != "running" || st1.Target != "0.12.0" || !strings.Contains(st1.Command, "0.12.0/upgrade.sh") {
		t.Fatalf("unexpected start response: %+v", st1)
	}

	// 3. Poll status while running.
	rec2 := serve(h, httptest.NewRequest(http.MethodGet, "http://localhost:8080/api/upgrade/status", nil))
	st2 := decode[upgradeStatusResponse](t, rec2)
	if st2.State != "running" || st2.Phase != "4. Upgrading Kubernetes Operator (CRDs & Controller Manager)" {
		t.Fatalf("unexpected running status: %+v", st2)
	}

	// 4. Transition pod to Succeeded and verify version update.
	mu.Lock()
	phase = "Succeeded"
	logs += ">>> 🎉 Upgrade to 0.12.0 Complete! <<<\n"
	mu.Unlock()

	rec3 := serve(h, httptest.NewRequest(http.MethodGet, "http://localhost:8080/api/upgrade/status", nil))
	st3 := decode[upgradeStatusResponse](t, rec3)
	if st3.State != "succeeded" || !strings.Contains(st3.Phase, "Upgrade to 0.12.0 Complete!") {
		t.Fatalf("unexpected succeeded status: %+v", st3)
	}
	if s.cfg.ImageTag != "0.12.0" || s.cfg.ChartVersion != "0.12.0" {
		t.Fatalf("server version was not updated after upgrade: ImageTag=%q ChartVersion=%q", s.cfg.ImageTag, s.cfg.ChartVersion)
	}
}

func TestAutoUpgradeToggleAndAutomaticTrigger(t *testing.T) {
	var (
		mu       sync.Mutex
		podJSON  map[string]any
		paAnn    = map[string]string{}
		runningV = "0.8.0"
	)

	gh := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", contentTypeJSON)
		_ = json.NewEncoder(w).Encode([]map[string]any{
			{
				"tag_name":     "v0.12.0",
				"html_url":     "https://github.com/gke-labs/kube-agents/releases/tag/v0.12.0",
				"published_at": "2026-10-16T01:00:00Z",
			},
		})
	}))
	defer gh.Close()

	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer sa-token" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/apis/kubeagents.x-k8s.io/v1alpha1/namespaces/kubeagents-system/platformagents/platform-agent":
			w.Header().Set("Content-Type", contentTypeJSON)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"metadata": map[string]any{
					"name":        "platform-agent",
					"namespace":   "kubeagents-system",
					"annotations": paAnn,
				},
				"spec": map[string]any{
					"deployment": map[string]any{
						"tag": runningV,
					},
				},
			})
		case r.Method == http.MethodPatch && r.URL.Path == "/apis/kubeagents.x-k8s.io/v1alpha1/namespaces/kubeagents-system/platformagents/platform-agent":
			var body struct {
				Metadata struct {
					Annotations map[string]string `json:"annotations"`
				} `json:"metadata"`
			}
			_ = json.NewDecoder(r.Body).Decode(&body)
			for k, v := range body.Metadata.Annotations {
				paAnn[k] = v
			}
			w.Header().Set("Content-Type", contentTypeJSON)
			_ = json.NewEncoder(w).Encode(map[string]any{"metadata": map[string]any{"annotations": paAnn}})
		case r.Method == http.MethodGet && r.URL.Path == "/api/v1/namespaces/kubeagents-system/pods/kube-agents-upgrade-runner":
			if podJSON == nil {
				w.WriteHeader(http.StatusNotFound)
				fmt.Fprint(w, `{"message":"not found"}`)
				return
			}
			w.Header().Set("Content-Type", contentTypeJSON)
			meta, _ := podJSON["metadata"].(map[string]any)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"metadata": meta,
				"status": map[string]any{
					"phase":     "Running",
					"startTime": "2026-10-16T10:00:00Z",
				},
			})
		case r.Method == http.MethodPost && r.URL.Path == "/api/v1/namespaces/kubeagents-system/pods":
			raw, _ := io.ReadAll(r.Body)
			_ = json.Unmarshal(raw, &podJSON)
			w.Header().Set("Content-Type", contentTypeJSON)
			w.WriteHeader(http.StatusCreated)
			_, _ = w.Write(raw)
		case r.Method == http.MethodGet && r.URL.Path == "/api/v1/namespaces/kubeagents-system/pods/kube-agents-upgrade-runner/log":
			w.Header().Set("Content-Type", "text/plain")
			fmt.Fprint(w, ">>> Downloading and executing release-pinned upgrade.sh (0.12.0) <<<\n")
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer api.Close()

	_, s := setupServer(t)
	s.cfg.PodNamespace = "kubeagents-system"
	s.cfg.PlatformAgentName = "platform-agent"
	s.cfg.ProjectID = "gca-gke-test"
	s.cfg.ClusterName = "ka-webconsole-pr2321"
	s.cfg.Location = "us-central1"
	s.cfg.ImageTag = "0.8.0"
	s.cfg.ChartVersion = "0.8.0"
	s.cfg.ReleaseCheck = true
	s.cfg.GitHubAPIBase = gh.URL
	s.githubClient = gh.Client()
	s.kube = &kubeClient{base: api.URL, token: "sa-token", client: api.Client()}
	h := s.routes()

	// 1. Initially auto_upgrade is false.
	rec0 := serve(h, httptest.NewRequest(http.MethodGet, "http://localhost:8080/api/upgrade/auto", nil))
	if rec0.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec0.Code, rec0.Body.String())
	}
	var autoResp struct {
		AutoUpgrade bool `json:"auto_upgrade"`
	}
	_ = json.Unmarshal(rec0.Body.Bytes(), &autoResp)
	if autoResp.AutoUpgrade {
		t.Fatalf("expected auto_upgrade false by default")
	}

	// 2. Enable auto_upgrade via POST /api/upgrade/auto; since 0.8.0 < 0.12.0, it immediately triggers the upgrade pod.
	enableReq := httptest.NewRequest(http.MethodPost, "http://localhost:8080/api/upgrade/auto", strings.NewReader(`{"enabled":true}`))
	enableReq.Header.Set("Content-Type", contentTypeJSON)
	enableReq.Header.Set(consoleHeader, consoleHeaderValue)
	rec1 := serve(h, enableReq)
	if rec1.Code != http.StatusOK {
		t.Fatalf("want 200, got %d: %s", rec1.Code, rec1.Body.String())
	}
	st1 := decode[upgradeStatusResponse](t, rec1)
	if !st1.AutoUpgrade || st1.State != "running" || st1.Target != "0.12.0" || st1.TriggeredBy != "auto" {
		t.Fatalf("expected auto-upgrade to trigger immediately for 0.12.0, got %+v", st1)
	}
	mu.Lock()
	persisted := paAnn[autoUpgradeAnnotation]
	mu.Unlock()
	if persisted != "true" {
		t.Fatalf("expected PlatformAgent annotation %s=true, got %q", autoUpgradeAnnotation, persisted)
	}

	// 3. Disable auto_upgrade and verify persistence.
	disableReq := httptest.NewRequest(http.MethodPost, "http://localhost:8080/api/upgrade/auto", strings.NewReader(`{"enabled":false}`))
	disableReq.Header.Set("Content-Type", contentTypeJSON)
	disableReq.Header.Set(consoleHeader, consoleHeaderValue)
	rec2 := serve(h, disableReq)
	st2 := decode[upgradeStatusResponse](t, rec2)
	if st2.AutoUpgrade {
		t.Fatalf("expected auto_upgrade false after disabling, got %+v", st2)
	}
}
