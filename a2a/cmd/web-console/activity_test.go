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
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestClassifySession(t *testing.T) {
	console := sessionIDPrefix + strings.Repeat("a", 32)
	for _, tc := range []struct {
		id, source, title, want string
	}{
		{"k8s-evt-be3abad3", "api_server", "Triage k8s-evt-be3abad3", kindEventTriage},
		{"cron-policy-sweep", "api_server", "Triage cron-policy-sweep", kindScheduled},
		{console, "api_server", "Web console aaaa", kindConsole},
		{"20260101_x", "slack", "Why is web-7 crashlooping?", kindChat},
		{"20260101_y", "google_chat", "Deploy status", kindChat},
		// A chat session cannot become event triage by its title.
		{"20260101_z", "slack", "Triage k8s-evt-123", kindChat},
		{"api_123", "api_server", "Triage and resolve acme/toolkit#42", kindOther},
		{"orphan", "", "Triage k8s-evt-1", kindOther},
	} {
		if got := classifySession(tc.id, tc.source, tc.title); got != tc.want {
			t.Errorf("classifySession(%q, %q, %q) = %q, want %q", tc.id, tc.source, tc.title, got, tc.want)
		}
	}
}

func TestSummaryLine(t *testing.T) {
	if got := summaryLine("\n\n  first line  \nsecond"); got != "first line" {
		t.Errorf("summaryLine = %q", got)
	}
	long := strings.Repeat("é", summaryMaxRunes+10)
	got := summaryLine(long)
	if !strings.HasSuffix(got, ellipsis) || len([]rune(got)) != summaryMaxRunes+1 {
		t.Errorf("long line = %q (%d runes), want %d runes and an ellipsis", got, len([]rune(got)), summaryMaxRunes)
	}
}

func TestSummarySubjectPrefersTheTriageCardTitle(t *testing.T) {
	prompt := "A Kubernetes Warning event needs triage on GKE cluster 'c1'. The alert is posted.\n\n" +
		"Make exactly one `kanban_create` call:\n\n" +
		"- `assignee`: the `cluster-*` agent\n" +
		"- `title`: `Triage default/Pod/web-7 (BackOff) on c1`\n" +
		"- `body`: everything below"
	if got := summarySubject(prompt); got != "Triage default/Pod/web-7 (BackOff) on c1" {
		t.Errorf("summarySubject = %q, want the card title", got)
	}
	if got := summarySubject("Run the policy sweep\nmore"); got != "Run the policy sweep" {
		t.Errorf("summarySubject without a card title = %q, want the first line", got)
	}
}

type recentList struct {
	Sessions []recentSession `json:"sessions"`
}

func recentReq() *http.Request {
	return httptest.NewRequest(http.MethodGet, "http://localhost:8080/api/sessions/recent", nil)
}

func byID(list recentList) map[string]recentSession {
	out := map[string]recentSession{}
	for _, s := range list.Sessions {
		out[s.ID] = s
	}
	return out
}

func TestRecentSessionsSummarizesClusterSessionsOnly(t *testing.T) {
	fake, h := setup(t)
	fake.seed("k8s-evt-1", "api_server", "Triage k8s-evt-1")
	fake.seed("slack-1", "slack", "Why is web-7 crashlooping?")
	fake.mu.Lock()
	fake.post("k8s-evt-1", "user", "A Kubernetes Warning event needs triage on GKE cluster 'c1'.\nMore detail")
	fake.post("k8s-evt-1", "assistant", nil)
	fake.post("k8s-evt-1", "assistant", "Filed card t_1 to cluster-c1.\nIt will report in the thread.")
	fake.post("k8s-evt-1", "tool", "ok")
	fake.post("slack-1", "user", "private question")
	fake.post("slack-1", "assistant", "private answer")
	fake.mu.Unlock()

	rec := serve(h, recentReq())
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
	}
	if strings.Contains(rec.Body.String(), "private") {
		t.Errorf("a chat session's messages reached the list: %s", rec.Body.String())
	}
	got := byID(decode[recentList](t, rec))
	evt := got["k8s-evt-1"]
	if evt.Kind != kindEventTriage || evt.Summary == nil {
		t.Fatalf("event triage row = %+v, want kind and summary", evt)
	}
	if evt.Summary.Subject != "A Kubernetes Warning event needs triage on GKE cluster 'c1'." ||
		evt.Summary.Latest != "Filed card t_1 to cluster-c1." {
		t.Errorf("summary = %+v", *evt.Summary)
	}
	if chat := got["slack-1"]; chat.Kind != kindChat || chat.Summary != nil {
		t.Errorf("chat row = %+v, want kind chat and no summary", chat)
	}
	if n := fake.gets("slack-1"); n != 0 {
		t.Errorf("the console read a chat session's messages %d times", n)
	}
}

func TestSummariesAreCachedPerMessageCount(t *testing.T) {
	fake, h := setup(t)
	fake.seed("cron-sweep", "api_server", "Triage cron-sweep")
	fake.mu.Lock()
	fake.post("cron-sweep", "user", "Run the policy sweep")
	fake.post("cron-sweep", "assistant", "No violations.")
	fake.mu.Unlock()

	serve(h, recentReq())
	first := fake.gets("cron-sweep")
	if first == 0 {
		t.Fatal("the first list did not read the session")
	}
	got := byID(decode[recentList](t, serve(h, recentReq())))
	if n := fake.gets("cron-sweep"); n != first {
		t.Errorf("a refresh with no new messages read Hermes again: %d reads, want %d", n, first)
	}
	if s := got["cron-sweep"].Summary; s == nil || s.Latest != "No violations." {
		t.Errorf("cached summary = %+v", s)
	}

	fake.mu.Lock()
	fake.post("cron-sweep", "assistant", "One violation found.")
	fake.mu.Unlock()
	got = byID(decode[recentList](t, serve(h, recentReq())))
	if n := fake.gets("cron-sweep"); n == first {
		t.Errorf("a new message did not refresh the summary")
	}
	if s := got["cron-sweep"].Summary; s == nil || s.Latest != "One violation found." {
		t.Errorf("refreshed summary = %+v", s)
	}
}

func transcriptReq(sid string) *http.Request {
	return httptest.NewRequest(http.MethodGet, "http://localhost:8080/api/sessions/"+sid+"/transcript", nil)
}

func TestTranscriptOpensClusterAndConsoleSessions(t *testing.T) {
	fake, h := setup(t)
	fake.seed("k8s-evt-1", "api_server", "Triage k8s-evt-1")
	fake.seed("cron-sweep", "api_server", "Triage cron-sweep")
	fake.mu.Lock()
	fake.post("k8s-evt-1", "user", "triage this")
	fake.post("k8s-evt-1", "assistant", nil)
	fake.post("k8s-evt-1", "tool", "pod list")
	lastEvt := fake.post("k8s-evt-1", "assistant", "filed a card")
	fake.post("cron-sweep", "user", "sweep")
	fake.mu.Unlock()
	turn := decode[chatResponse](t, serve(h, chatReq(`{"message":"check pods"}`)))

	evt := decode[transcriptResponse](t, serve(h, transcriptReq("k8s-evt-1")))
	if evt.Kind != kindEventTriage || len(evt.Messages) != 2 ||
		evt.Messages[0].Content != "triage this" || evt.Messages[1].Content != "filed a card" {
		t.Errorf("event triage transcript = %+v, want the two text rows oldest first", evt)
	}
	if evt.LatestID != lastEvt {
		t.Errorf("latest_id = %d, want %d", evt.LatestID, lastEvt)
	}
	if got := serve(h, transcriptReq("cron-sweep")); got.Code != http.StatusOK {
		t.Errorf("scheduled transcript: status %d", got.Code)
	}
	mine := decode[transcriptResponse](t, serve(h, transcriptReq(turn.SessionID)))
	if mine.Kind != kindConsole || len(mine.Messages) != 2 || mine.Messages[1].Content != turn.Reply {
		t.Errorf("console transcript = %+v", mine)
	}
}

func TestTranscriptKeepsTheNewestRows(t *testing.T) {
	fake, h := setup(t)
	fake.seed("k8s-evt-long", "api_server", "Triage k8s-evt-long")
	fake.mu.Lock()
	var last int64
	for i := 0; i < transcriptMaxRows+30; i++ {
		last = fake.post("k8s-evt-long", "assistant", "row")
	}
	fake.mu.Unlock()
	got := decode[transcriptResponse](t, serve(h, transcriptReq("k8s-evt-long")))
	if len(got.Messages) != transcriptMaxRows || got.Messages[len(got.Messages)-1].ID != last {
		t.Errorf("transcript holds %d rows ending at %d, want %d ending at %d",
			len(got.Messages), got.Messages[len(got.Messages)-1].ID, transcriptMaxRows, last)
	}
}

func TestTranscriptRefusesChatAndOtherSessions(t *testing.T) {
	fake, h := setup(t)
	fake.seed("slack-1", "slack", "Triage k8s-evt-9")
	fake.seed("api_42", "api_server", "Triage and resolve acme/toolkit#42")
	fake.mu.Lock()
	fake.post("slack-1", "user", "private question")
	fake.mu.Unlock()
	for _, sid := range []string{"slack-1", "api_42"} {
		rec := serve(h, transcriptReq(sid))
		if rec.Code != http.StatusForbidden {
			t.Errorf("%s: status %d, want 403", sid, rec.Code)
		}
		if got := decode[errorResponse](t, rec); got.Error != "transcript_not_allowed" {
			t.Errorf("%s: error %q", sid, got.Error)
		}
		if n := fake.gets(sid); n != 0 {
			t.Errorf("%s: a refused transcript read %d message pages", sid, n)
		}
	}
}

func TestTranscriptRefusesABadID(t *testing.T) {
	fake, h := setup(t)
	for _, sid := range []string{"a$b", "-x", "a%2Fb", "a%20b", strings.Repeat("a", 129)} {
		if rec := serve(h, transcriptReq(sid)); rec.Code != http.StatusBadRequest {
			t.Errorf("%q: status %d, want 400", sid, rec.Code)
		}
	}
	if fake.lastQuery != "" {
		t.Errorf("a refused ID reached Hermes")
	}
	if rec := serve(h, transcriptReq("k8s-evt-missing")); rec.Code != http.StatusNotFound {
		t.Errorf("unknown session: status %d, want 404", rec.Code)
	}
}
