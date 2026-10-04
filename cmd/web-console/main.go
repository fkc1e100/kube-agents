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

// Package main implements the lightweight, in-cluster POC Web Console for Kube-Agents.
// It exposes a responsive, Google Cloud-styled web chat interface and live incident
// feed by proxying in-cluster requests directly to Hermes API (:8642) and
// Session KV (:8699), eliminating external chat platform dependencies for customer POCs.
package main

import (
	"bytes"
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"
)

//go:embed static/*
var staticFS embed.FS

var (
	startTime = time.Now()

	// Configuration with sensible in-cluster defaults
	port            = getEnv("PORT", "8080")
	hermesURL       = strings.TrimRight(getEnv("HERMES_URL", "http://127.0.0.1:8642"), "/")
	sessionKVURL    = strings.TrimRight(getEnv("SESSION_KV_URL", "http://127.0.0.1:8699"), "/")
	litellmURL      = strings.TrimRight(getEnv("LITELLM_URL", "http://127.0.0.1:4000"), "/")
	sessionKVAPIKey = readSecretOrEnv("SESSION_KV_API_KEY", "/var/run/secrets/kubeagents/session_kv_api_key")
	apiServerKey    = readSecretOrEnv("API_SERVER_KEY", "/var/run/secrets/kubeagents/api_server_key")

	clusterName = getEnv("CLUSTER_NAME", "gke-cluster")
	projectID   = getEnv("PROJECT_ID", "gcp-project")
	location    = getEnv("LOCATION", "us-central1")

	// Global default session tracking
	sessionMu sync.Mutex
	sessionID = ""
)

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func readSecretOrEnv(envKey, secretFilePath string) string {
	if v := os.Getenv(envKey); v != "" {
		return strings.TrimSpace(v)
	}
	if b, err := os.ReadFile(secretFilePath); err == nil {
		return strings.TrimSpace(string(b))
	}
	return ""
}

type ServiceStatus struct {
	URL       string `json:"url"`
	Healthy   bool   `json:"healthy"`
	LatencyMs int64  `json:"latency_ms"`
	Message   string `json:"message,omitempty"`
}

type StatusResponse struct {
	Cluster   string        `json:"cluster"`
	Project   string        `json:"project"`
	Location  string        `json:"location"`
	UptimeSec int64         `json:"uptime_seconds"`
	Hermes    ServiceStatus `json:"hermes"`
	SessionKV ServiceStatus `json:"session_kv"`
	LiteLLM   ServiceStatus `json:"litellm"`
}

func probeService(url, path, authHeader string) ServiceStatus {
	t0 := time.Now()
	client := &http.Client{Timeout: 3 * time.Second}
	req, err := http.NewRequest("GET", url+path, nil)
	if err != nil {
		return ServiceStatus{URL: url, Healthy: false, Message: err.Error()}
	}
	if authHeader != "" {
		req.Header.Set("Authorization", authHeader)
	}
	resp, err := client.Do(req)
	latency := time.Since(t0).Milliseconds()
	if err != nil {
		return ServiceStatus{URL: url, Healthy: false, LatencyMs: latency, Message: err.Error()}
	}
	defer resp.Body.Close()
	healthy := resp.StatusCode >= 200 && resp.StatusCode < 400
	return ServiceStatus{
		URL:       url,
		Healthy:   healthy,
		LatencyMs: latency,
		Message:   fmt.Sprintf("HTTP %d", resp.StatusCode),
	}
}

func handleStatus(w http.ResponseWriter, r *http.Request) {
	hermesAuth := ""
	if apiServerKey != "" {
		hermesAuth = "Bearer " + apiServerKey
	}
	skvAuth := ""
	if sessionKVAPIKey != "" {
		skvAuth = "Bearer " + sessionKVAPIKey
	}

	status := StatusResponse{
		Cluster:   clusterName,
		Project:   projectID,
		Location:  location,
		UptimeSec: int64(time.Since(startTime).Seconds()),
		Hermes:    probeService(hermesURL, "/healthz", hermesAuth),
		SessionKV: probeService(sessionKVURL, "/healthz", skvAuth),
		LiteLLM:   probeService(litellmURL, "/health/ready", ""),
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(status)
}

func handleHealthz(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"status":         "ok",
		"uptime_seconds": int64(time.Since(startTime).Seconds()),
	})
}

type ChatRequest struct {
	Message   string `json:"message"`
	SessionID string `json:"session_id,omitempty"`
}

type ChatResponse struct {
	SessionID string `json:"session_id"`
	Reply     string `json:"reply"`
	Source    string `json:"source"`
	Thinking  string `json:"thinking,omitempty"`
	Error     string `json:"error,omitempty"`
}

func ensureHermesSession(client *http.Client) (string, error) {
	sessionMu.Lock()
	defer sessionMu.Unlock()
	if sessionID != "" {
		return sessionID, nil
	}

	req, err := http.NewRequest("POST", hermesURL+"/api/sessions", bytes.NewBuffer([]byte(`{}`)))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	if apiServerKey != "" {
		req.Header.Set("Authorization", "Bearer "+apiServerKey)
	}

	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	var res map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&res); err != nil {
		return "", err
	}

	if sid, ok := res["id"].(string); ok && sid != "" {
		sessionID = sid
		return sessionID, nil
	}
	if sid, ok := res["session_id"].(string); ok && sid != "" {
		sessionID = sid
		return sessionID, nil
	}

	// Fallback generated session ID
	sessionID = fmt.Sprintf("web-%d", time.Now().Unix())
	return sessionID, nil
}

func handleChat(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req ChatRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid JSON body", http.StatusBadRequest)
		return
	}

	msg := strings.TrimSpace(req.Message)
	if msg == "" {
		http.Error(w, "Message cannot be empty", http.StatusBadRequest)
		return
	}

	client := &http.Client{Timeout: 90 * time.Second}
	sid := req.SessionID
	if sid == "" {
		var err error
		sid, err = ensureHermesSession(client)
		if err != nil {
			log.Printf("[web-console] Warning: could not initialize Hermes session: %v", err)
			sid = fmt.Sprintf("web-%d", time.Now().Unix())
		}
	}

	// 1. Send turn to Hermes API
	hermesPayload, _ := json.Marshal(map[string]interface{}{
		"content": msg,
		"role":    "user",
	})
	chatReq, err := http.NewRequest("POST", fmt.Sprintf("%s/api/sessions/%s/chat", hermesURL, sid), bytes.NewReader(hermesPayload))
	if err == nil {
		chatReq.Header.Set("Content-Type", "application/json")
		if apiServerKey != "" {
			chatReq.Header.Set("Authorization", "Bearer "+apiServerKey)
		}
		resp, chatErr := client.Do(chatReq)
		if chatErr == nil && resp.StatusCode >= 200 && resp.StatusCode < 300 {
			defer resp.Body.Close()
			var hermesResp map[string]interface{}
			if err := json.NewDecoder(resp.Body).Decode(&hermesResp); err == nil {
				reply := ""
				if content, ok := hermesResp["content"].(string); ok {
					reply = content
				} else if message, ok := hermesResp["message"].(string); ok {
					reply = message
				}
				thinking := ""
				if th, ok := hermesResp["thinking"].(string); ok {
					thinking = th
				}

				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(ChatResponse{
					SessionID: sid,
					Reply:     reply,
					Thinking:  thinking,
					Source:    "hermes-agent",
				})
				return
			}
		}
	}

	// 2. Direct LiteLLM fallback if Hermes is initializing
	litePayload, _ := json.Marshal(map[string]interface{}{
		"model": "model-default",
		"messages": []map[string]string{
			{"role": "system", "content": fmt.Sprintf("You are Kube-Agents, the autonomous Kubernetes fleet operations platform agent on GKE cluster '%s'. Provide direct, actionable operational analysis.", clusterName)},
			{"role": "user", "content": msg},
		},
		"temperature": 0.2,
	})
	liteReq, err := http.NewRequest("POST", litellmURL+"/chat/completions", bytes.NewReader(litePayload))
	if err == nil {
		liteReq.Header.Set("Content-Type", "application/json")
		resp, liteErr := client.Do(liteReq)
		if liteErr == nil && resp.StatusCode >= 200 && resp.StatusCode < 300 {
			defer resp.Body.Close()
			var comp struct {
				Choices []struct {
					Message struct {
						Content string `json:"content"`
					} `json:"message"`
				} `json:"choices"`
			}
			if err := json.NewDecoder(resp.Body).Decode(&comp); err == nil && len(comp.Choices) > 0 {
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(ChatResponse{
					SessionID: sid,
					Reply:     comp.Choices[0].Message.Content,
					Source:    "litellm-gateway",
				})
				return
			}
		}
	}

	// 3. Informative error if both in-cluster gateways are not yet ready
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusServiceUnavailable)
	_ = json.NewEncoder(w).Encode(ChatResponse{
		SessionID: sid,
		Reply:     "Kube-Agents runtime is currently initializing. The Hermes agent gateway and LiteLLM model proxy are starting up.",
		Source:    "bootstrap-notice",
		Error:     "agent_gateway_initializing",
	})
}

func handleIncidents(w http.ResponseWriter, r *http.Request) {
	client := &http.Client{Timeout: 5 * time.Second}
	req, err := http.NewRequest("GET", sessionKVURL+"/v1/incidents/recent", nil)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if sessionKVAPIKey != "" {
		req.Header.Set("Authorization", "Bearer "+sessionKVAPIKey)
	}

	resp, err := client.Do(req)
	if err != nil {
		// Fallback empty list rather than 500 so UI stays responsive
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]interface{}{"incidents": []interface{}{}, "count": 0})
		return
	}
	defer resp.Body.Close()

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	_, _ = io.Copy(w, resp.Body)
}

func handleTasks(w http.ResponseWriter, r *http.Request) {
	client := &http.Client{Timeout: 5 * time.Second}
	req, err := http.NewRequest("GET", sessionKVURL+"/v1/tasks?limit=20", nil)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if sessionKVAPIKey != "" {
		req.Header.Set("Authorization", "Bearer "+sessionKVAPIKey)
	}

	resp, err := client.Do(req)
	if err != nil {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]interface{}{"tasks": []interface{}{}, "count": 0})
		return
	}
	defer resp.Body.Close()

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	_, _ = io.Copy(w, resp.Body)
}

func main() {
	mux := http.NewServeMux()

	// Static UI assets
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

	// API endpoints
	mux.HandleFunc("/healthz", handleHealthz)
	mux.HandleFunc("/api/status", handleStatus)
	mux.HandleFunc("/api/chat", handleChat)
	mux.HandleFunc("/api/incidents", handleIncidents)
	mux.HandleFunc("/api/tasks", handleTasks)

	addr := ":" + port
	server := &http.Server{
		Addr:         addr,
		Handler:      mux,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 120 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	log.Printf("[web-console] Kube-Agents In-Cluster Web Console listening on %s (cluster: %s, project: %s)", addr, clusterName, projectID)

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("[web-console] Server error: %v", err)
		}
	}()

	<-stop
	log.Printf("[web-console] Shutting down gracefully...")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = server.Shutdown(ctx)
	log.Printf("[web-console] Server stopped.")
}
