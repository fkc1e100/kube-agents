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
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHealthzEndpoint(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()

	handleHealthz(w, req)

	resp := w.Result()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected HTTP 200, got %d", resp.StatusCode)
	}

	var body map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("failed to decode JSON response: %v", err)
	}

	if body["status"] != "ok" {
		t.Errorf("expected status 'ok', got %v", body["status"])
	}
}

func TestStaticIndexServing(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.FileServer(http.FS(staticFS)).ServeHTTP(w, r)
			return
		}
		data, err := staticFS.ReadFile("static/index.html")
		if err != nil {
			http.Error(w, "Could not load web console template", http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write(data)
	})

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w := httptest.NewRecorder()

	mux.ServeHTTP(w, req)

	resp := w.Result()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected HTTP 200, got %d", resp.StatusCode)
	}

	html := w.Body.String()
	if !strings.Contains(html, "Kube-Agents") {
		t.Errorf("expected HTML to contain 'Kube-Agents'")
	}
	if !strings.Contains(html, "#1a73e8") {
		t.Errorf("expected HTML to contain Google Cloud blue color '#1a73e8'")
	}
}

func TestStatusEndpoint(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/api/status", nil)
	w := httptest.NewRecorder()

	handleStatus(w, req)

	resp := w.Result()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected HTTP 200, got %d", resp.StatusCode)
	}

	var status StatusResponse
	if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
		t.Fatalf("failed to decode StatusResponse: %v", err)
	}

	if status.Cluster == "" {
		t.Errorf("expected non-empty cluster name")
	}
}

func TestChatEndpointValidation(t *testing.T) {
	// 1. Method GET should be rejected
	reqGet := httptest.NewRequest(http.MethodGet, "/api/chat", nil)
	wGet := httptest.NewRecorder()
	handleChat(wGet, reqGet)
	if wGet.Result().StatusCode != http.StatusMethodNotAllowed {
		t.Errorf("expected 405 Method Not Allowed for GET, got %d", wGet.Result().StatusCode)
	}

	// 2. Empty message should be rejected
	payload, _ := json.Marshal(ChatRequest{Message: "   "})
	reqEmpty := httptest.NewRequest(http.MethodPost, "/api/chat", bytes.NewReader(payload))
	wEmpty := httptest.NewRecorder()
	handleChat(wEmpty, reqEmpty)
	if wEmpty.Result().StatusCode != http.StatusBadRequest {
		t.Errorf("expected 400 Bad Request for empty message, got %d", wEmpty.Result().StatusCode)
	}
}

func TestChatEndpointMockHermes(t *testing.T) {
	// Mock Hermes server
	mockHermes := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/sessions/") && strings.HasSuffix(r.URL.Path, "/chat") {
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]interface{}{
				"content":  "All 4 workloads in production namespace are healthy.",
				"thinking": "Inspecting deployment manifests and pod status.",
			})
			return
		}
		http.NotFound(w, r)
	}))
	defer mockHermes.Close()

	// Point hermesURL to mock
	origURL := hermesURL
	hermesURL = mockHermes.URL
	defer func() { hermesURL = origURL }()

	payload, _ := json.Marshal(ChatRequest{
		Message:   "Check cluster health",
		SessionID: "test-session-123",
	})
	req := httptest.NewRequest(http.MethodPost, "/api/chat", bytes.NewReader(payload))
	w := httptest.NewRecorder()

	handleChat(w, req)

	resp := w.Result()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected HTTP 200, got %d", resp.StatusCode)
	}

	var chatResp ChatResponse
	if err := json.NewDecoder(resp.Body).Decode(&chatResp); err != nil {
		t.Fatalf("failed to decode ChatResponse: %v", err)
	}

	if !strings.Contains(chatResp.Reply, "healthy") {
		t.Errorf("expected reply to contain 'healthy', got %q", chatResp.Reply)
	}
	if chatResp.Source != "hermes-agent" {
		t.Errorf("expected source 'hermes-agent', got %q", chatResp.Source)
	}
}
