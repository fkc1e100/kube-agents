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
	"bufio"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// A turn as Hermes streams it: frames in the shapes
// _handle_session_chat_stream writes, with a keepalive comment between.
const hermesTurnStream = `event: run.started
data: {"user_message": {"role": "user", "content": "check pods"}, "seq": 1}

event: tool.progress
data: {"tool_name": "_thinking", "delta": "The user wants pod health.\n\n   I should   list pods   first."}

event: tool.started
data: {"tool_name": "kubectl_get", "preview": "pods -n   kubeagents-system", "args": {"token": "do-not-forward"}}

: keepalive

event: tool.completed
data: {"tool_name": "kubectl_get", "preview": "NAME READY STATUS\nweb-1 1/1 Running"}

event: assistant.delta
data: {"delta": "All "}

event: assistant.delta
data: {"delta": "pods "}

event: assistant.completed
data: {"content": "All pods are healthy.", "completed": true}

event: run.completed
data: {"completed": true}

event: done
data: {}

`

type relayed struct {
	name string
	data map[string]any
}

func readRelay(t *testing.T, body string) []relayed {
	t.Helper()
	var out []relayed
	var cur relayed
	scanner := bufio.NewScanner(strings.NewReader(body))
	for scanner.Scan() {
		line := scanner.Text()
		switch {
		case strings.HasPrefix(line, "event: "):
			cur.name = strings.TrimPrefix(line, "event: ")
		case strings.HasPrefix(line, "data: "):
			if err := json.Unmarshal([]byte(strings.TrimPrefix(line, "data: ")), &cur.data); err != nil {
				t.Fatalf("relay data %q: %v", line, err)
			}
		case line == "" && cur.name != "":
			out = append(out, cur)
			cur = relayed{}
		}
	}
	return out
}

func streamReq(body string) *http.Request {
	req := chatReq(body)
	req.URL.Path = "/api/chat/stream"
	return req
}

func TestChatStreamRelaysStatusAndReply(t *testing.T) {
	fake, h := setup(t)
	fake.mu.Lock()
	fake.stream = hermesTurnStream
	fake.mu.Unlock()

	rec := serve(h, streamReq(`{"message":"check pods"}`))
	if rec.Code != http.StatusOK || rec.Header().Get("Content-Type") != contentTypeEventStream {
		t.Fatalf("status %d, content type %q: %s", rec.Code, rec.Header().Get("Content-Type"), rec.Body.String())
	}
	if strings.Contains(rec.Body.String(), "do-not-forward") || strings.Contains(rec.Body.String(), "web-1") {
		t.Errorf("tool args or a completed preview reached the page: %s", rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), ": keepalive") {
		t.Errorf("the keepalive was not relayed")
	}
	events := readRelay(t, rec.Body.String())
	var statuses []string
	for _, e := range events[:len(events)-1] {
		if e.name != eventStatus {
			t.Fatalf("event %q before the reply, want only status events", e.name)
		}
		statuses = append(statuses, e.data["text"].(string))
	}
	want := []string{
		statusSending,
		statusStarted,
		"Thinking: The user wants pod health. I should list pods first.",
		"Running kubectl_get: pods -n kubeagents-system",
		"Finished kubectl_get",
		statusWriting,
	}
	if strings.Join(statuses, "|") != strings.Join(want, "|") {
		t.Errorf("status lines =\n%q\nwant\n%q", statuses, want)
	}
	last := events[len(events)-1]
	if last.name != eventReply || last.data["reply"] != "All pods are healthy." || !sessionIDPattern.MatchString(last.data["session_id"].(string)) {
		t.Errorf("final event = %+v, want the reply and the session", last)
	}
	sid := last.data["session_id"].(string)
	if !newServerClaimFree(t, h, sid) {
		t.Errorf("the session's in-flight claim was not released")
	}
}

// newServerClaimFree checks the claim is gone by running a second turn on the
// same session, which a held claim refuses with 409.
func newServerClaimFree(t *testing.T, h http.Handler, sid string) bool {
	t.Helper()
	return serve(h, chatReq(`{"message":"again","session_id":"`+sid+`"}`)).Code == http.StatusOK
}

func TestChatStreamRelaysAnUpstreamError(t *testing.T) {
	fake, h := setup(t)
	fake.mu.Lock()
	fake.stream = "event: run.started\ndata: {}\n\nevent: error\ndata: {\"message\": \"model quota exhausted\"}\n\nevent: done\ndata: {}\n\n"
	fake.mu.Unlock()
	events := readRelay(t, serve(h, streamReq(`{"message":"hi"}`)).Body.String())
	last := events[len(events)-1]
	if last.name != eventError || last.data["error"] != "agent_error" ||
		!strings.Contains(last.data["detail"].(string), "model quota exhausted") || last.data["session_id"] == "" {
		t.Errorf("final event = %+v, want an agent_error carrying the message and the session", last)
	}

	fake.mu.Lock()
	fake.streamCode = http.StatusTooManyRequests
	fake.mu.Unlock()
	events = readRelay(t, serve(h, streamReq(`{"message":"hi"}`)).Body.String())
	if last := events[len(events)-1]; last.name != eventError || last.data["error"] != "agent_busy" {
		t.Errorf("rate-limited stream: final event = %+v, want agent_busy", last)
	}
}

func TestChatStreamWithNoReplyIsAnError(t *testing.T) {
	fake, h := setup(t)
	fake.mu.Lock()
	fake.stream = "event: run.started\ndata: {}\n\n"
	fake.mu.Unlock()
	events := readRelay(t, serve(h, streamReq(`{"message":"hi"}`)).Body.String())
	if last := events[len(events)-1]; last.name != eventError || !strings.Contains(last.data["detail"].(string), errNoReply) {
		t.Errorf("final event = %+v", last)
	}
}

func TestChatStreamRecreatesAMissingSession(t *testing.T) {
	fake, h := setup(t)
	fake.mu.Lock()
	fake.stream = hermesTurnStream
	fake.mu.Unlock()
	sid := sessionIDPrefix + strings.Repeat("d", 32)
	events := readRelay(t, serve(h, streamReq(`{"message":"hi","session_id":"`+sid+`"}`)).Body.String())
	if last := events[len(events)-1]; last.name != eventReply || last.data["session_id"] != sid {
		t.Errorf("final event = %+v", last)
	}
	fake.mu.Lock()
	streams := fake.streams
	fake.mu.Unlock()
	if sessions, _ := fake.state(); !sessions[sid] || streams != 2 {
		t.Errorf("want the session recreated and the stream retried once; streams=%d", streams)
	}
}

func TestChatStreamRepliesIntoAnAgentSession(t *testing.T) {
	fake, h := setup(t)
	fake.seed("k8s-evt-x", "api_server", "Triage k8s-evt-x")
	fake.seed("slack-1", "slack", "Triage k8s-evt-x")
	fake.mu.Lock()
	fake.stream = hermesTurnStream
	fake.mu.Unlock()
	events := readRelay(t, serve(h, streamReq(`{"message":"hi","session_id":"k8s-evt-x"}`)).Body.String())
	if last := events[len(events)-1]; last.name != eventReply || last.data["session_id"] != "k8s-evt-x" {
		t.Errorf("final event = %+v", last)
	}
	if rec := serve(h, streamReq(`{"message":"hi","session_id":"slack-1"}`)); rec.Code != http.StatusForbidden {
		t.Errorf("chat platform session: status %d, want 403", rec.Code)
	}

	// A 404 from the turn itself ends the stream; the session is not recreated.
	fake.mu.Lock()
	fake.streamCode = http.StatusNotFound
	fake.mu.Unlock()
	events = readRelay(t, serve(h, streamReq(`{"message":"hi","session_id":"k8s-evt-x"}`)).Body.String())
	if last := events[len(events)-1]; last.name != eventError || last.data["error"] != "session_not_found" {
		t.Errorf("final event = %+v, want session_not_found", last)
	}
	if fake.createCount() != 0 {
		t.Errorf("an agent session was created or recreated (%d creates)", fake.createCount())
	}
}

func TestChatStreamKeepsTheChatGuards(t *testing.T) {
	fake, h := setup(t)
	noHeader := streamReq(`{"message":"hi"}`)
	noHeader.Header.Del(consoleHeader)
	if rec := serve(h, noHeader); rec.Code != http.StatusForbidden {
		t.Errorf("missing console header: status %d, want 403", rec.Code)
	}
	if rec := serve(h, streamReq(`{"message":"hi","session_id":"web-console-ABC"}`)); rec.Code != http.StatusBadRequest {
		t.Errorf("malformed console session: status %d, want 400", rec.Code)
	}
	if rec := serve(h, streamReq(`{"message":"hi","session_id":"k8s-evt-abc"}`)); rec.Code != http.StatusNotFound {
		t.Errorf("unknown agent session: status %d, want 404", rec.Code)
	}
	big := `{"message":"` + strings.Repeat("a", maxRequestBodyBytes+1) + `"}`
	if rec := serve(h, streamReq(big)); rec.Code != http.StatusRequestEntityTooLarge {
		t.Errorf("oversized body: status %d, want 413", rec.Code)
	}
	rebind := streamReq(`{"message":"hi"}`)
	rebind.Host = "rebind.attacker.example:8080"
	if rec := serve(h, rebind); rec.Code != http.StatusForbidden {
		t.Errorf("foreign Host: status %d, want 403", rec.Code)
	}
	fake.mu.Lock()
	streams := fake.streams
	fake.mu.Unlock()
	if streams != 0 {
		t.Errorf("a refused request reached Hermes")
	}

	// A turn in flight on a session refuses a streamed turn on it too.
	turn := decode[chatResponse](t, serve(h, chatReq(`{"message":"start"}`)))
	srv := newServer(config{})
	if !srv.claim(turn.SessionID) || srv.claim(turn.SessionID) {
		t.Fatal("claim does not hold")
	}
	rec := httptest.NewRecorder()
	srv.routes().ServeHTTP(rec, streamReq(`{"message":"x","session_id":"`+turn.SessionID+`"}`))
	if rec.Code != http.StatusConflict {
		t.Errorf("streamed turn on a busy session: status %d, want 409", rec.Code)
	}
}

func TestClip(t *testing.T) {
	if got := clip("  a \n\t b  ", statusFragmentRunes); got != "a b" {
		t.Errorf("clip = %q", got)
	}
	long := clip(strings.Repeat("x ", statusFragmentRunes), statusFragmentRunes)
	if !strings.HasSuffix(long, ellipsis) || len([]rune(long)) > statusFragmentRunes+1 {
		t.Errorf("clip long = %q", long)
	}
}
