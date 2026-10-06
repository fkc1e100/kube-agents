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

// The recent activity list: what kind each session is, a one-line summary for
// the kinds the cluster opened itself, and a read-only transcript.
//
// Content is shown only for sessions the cluster or this console opened: event
// triage, scheduled checks, and the console's own sessions. A Slack or Google
// Chat session is listed by title and never read. Both checks key on Hermes'
// session source, which only the ingress that created the session sets.

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

const (
	// Session kinds the page groups the list by.
	kindEventTriage = "event_triage"
	kindScheduled   = "scheduled"
	kindConsole     = "console"
	kindChat        = "chat"
	kindOther       = "other"

	// sourceAPIServer is the Hermes source of a session created through the
	// gateway API: the event watcher's triage sessions, scheduled checks, and
	// this console's. Slack and Google Chat sessions carry their own source.
	sourceAPIServer = "api_server"

	// The title prefixes session_kv_server.py gives the sessions it opens:
	// "Triage <session id>", where an event watcher session ID starts with
	// k8s-evt- and a scheduled check's with cron-.
	titlePrefixEventTriage = "Triage k8s-evt-"
	titlePrefixScheduled   = "Triage cron-"

	// summaryTimeout bounds the summaries one session list request computes.
	// A session not summarized in time is listed without one and tried again
	// on the next refresh.
	summaryTimeout = 4 * time.Second
	// summaryConcurrency bounds how many sessions are summarized at once,
	// each with up to two Hermes calls.
	summaryConcurrency = 4
	// summaryFirstPageLimit is how many of a session's oldest messages are
	// read to find its first user message.
	summaryFirstPageLimit = 5
	// summaryMaxRunes bounds the subject and latest lines.
	summaryMaxRunes = 140
	ellipsis        = "…"
	// summaryCacheMaxEntries bounds the summary cache. Past it, entries for
	// sessions the current request did not list are dropped. The recent list
	// and the two channels list different sessions, so a smaller cap would
	// evict one list's entries on every refresh of another.
	summaryCacheMaxEntries = 500

	// transcriptMaxRows is how many text rows a transcript returns, newest
	// kept, oldest first.
	transcriptMaxRows = 200
	transcriptTimeout = 10 * time.Second
)

var (
	// transcriptIDPattern is the charset a transcript request may name. It
	// covers the IDs the event watcher, the scheduler and this console mint,
	// and refuses anything that could change the upstream path.
	transcriptIDPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`)

	// cardTitlePattern finds the card title an event triage prompt spells
	// out ("- `title`: `Triage ns/Kind/name (Reason) on cluster`"; see
	// _agent_query in session_kv_server.py). Every triage prompt opens with
	// the same sentence, so that title is the line that tells posts apart.
	cardTitlePattern = regexp.MustCompile("(?m)^- `title`: `([^`\n]+)`")

	// summaryKinds are the kinds the list reads content for.
	summaryKinds = map[string]bool{kindEventTriage: true, kindScheduled: true, kindConsole: true}
)

// classifySession sorts a session into the list's groups. The console's own
// IDs come first, then any session whose source is not the gateway API (a
// chat platform), so a Slack session can never be read as event triage
// because of its title. An empty source is unknown and lands in Other.
func classifySession(id, source, title string) string {
	switch {
	case sessionIDPattern.MatchString(id):
		return kindConsole
	case source == "":
		return kindOther
	case source != sourceAPIServer:
		return kindChat
	case strings.HasPrefix(title, titlePrefixEventTriage):
		return kindEventTriage
	case strings.HasPrefix(title, titlePrefixScheduled):
		return kindScheduled
	default:
		return kindOther
	}
}

// sessionSummary is the list row's subject and latest-reply lines.
//
// Replies counts the assistant rows with text among the session's newest
// messagesPageLimit messages, so it is exact for a short session and a floor
// for a long one.
type sessionSummary struct {
	Subject string `json:"subject"`
	Latest  string `json:"latest"`
	Replies int    `json:"replies"`
}

type summaryEntry struct {
	messageCount int
	summary      sessionSummary
}

// summaryCache maps a session ID to the summary computed at a message count.
// A refresh where the count has not moved costs no Hermes call.
type summaryCache struct {
	mu      sync.Mutex
	entries map[string]summaryEntry
}

// attachSummaries fills Summary on the sessions whose kind summaryKinds
// lists, from the cache where the message count still matches and from
// Hermes otherwise. Once the cache holds more than summaryCacheMaxEntries,
// entries for sessions this call did not list are dropped.
func (s *server) attachSummaries(parent context.Context, sessions []recentSession) {
	ctx, cancel := context.WithTimeout(parent, summaryTimeout)
	defer cancel()

	type job struct {
		index int
		count int
	}
	var jobs []job
	listed := map[string]bool{}
	s.summaries.mu.Lock()
	for i := range sessions {
		sess := &sessions[i]
		listed[sess.ID] = true
		if !summaryKinds[sess.Kind] || sess.MessageCount == nil {
			continue
		}
		if e, ok := s.summaries.entries[sess.ID]; ok && e.messageCount == *sess.MessageCount {
			sum := e.summary
			sess.Summary = &sum
			continue
		}
		jobs = append(jobs, job{index: i, count: *sess.MessageCount})
	}
	if len(s.summaries.entries) > summaryCacheMaxEntries {
		for id := range s.summaries.entries {
			if !listed[id] {
				delete(s.summaries.entries, id)
			}
		}
	}
	s.summaries.mu.Unlock()

	sem := make(chan struct{}, summaryConcurrency)
	var wg sync.WaitGroup
	for _, j := range jobs {
		wg.Add(1)
		go func() {
			defer wg.Done()
			select {
			case sem <- struct{}{}:
			case <-ctx.Done():
				return
			}
			defer func() { <-sem }()
			sid := sessions[j.index].ID
			sum, ok := s.summarize(ctx, sid)
			if !ok {
				return
			}
			sessions[j.index].Summary = &sum
			s.summaries.mu.Lock()
			s.summaries.entries[sid] = summaryEntry{messageCount: j.count, summary: sum}
			s.summaries.mu.Unlock()
		}()
	}
	wg.Wait()
}

// summarize reads a session's first user message and its last assistant
// message with text. ok is false when either read fails, so a failure is not
// cached as an empty summary.
func (s *server) summarize(ctx context.Context, sid string) (sessionSummary, bool) {
	var out sessionSummary
	first, failure := s.fetchMessagesPage(ctx, fmt.Sprintf("/api/sessions/%s/messages?order=oldest&limit=%d&offset=0",
		url.PathEscape(sid), summaryFirstPageLimit))
	if failure != nil {
		return out, false
	}
	for _, m := range first {
		if m.Role == roleUser && hasText(m) {
			out.Subject = summarySubject(*m.Content)
			break
		}
	}
	latest, failure := s.fetchMessagesPage(ctx, fmt.Sprintf("/api/sessions/%s/messages?order=latest&limit=%d&offset=0",
		url.PathEscape(sid), messagesPageLimit))
	if failure != nil {
		return out, false
	}
	for i := len(latest) - 1; i >= 0; i-- {
		if latest[i].Role != roleAssistant || !hasText(latest[i]) {
			continue
		}
		if out.Replies == 0 {
			out.Latest = summaryLine(*latest[i].Content)
		}
		out.Replies++
	}
	return out, true
}

// summarySubject is the card title a triage prompt names, or else the first
// line of the message.
func summarySubject(text string) string {
	if m := cardTitlePattern.FindStringSubmatch(text); m != nil {
		return summaryLine(m[1])
	}
	return summaryLine(text)
}

// summaryLine is the first non-blank line of a message, cut to
// summaryMaxRunes.
func summaryLine(text string) string {
	line := ""
	for _, l := range strings.Split(text, "\n") {
		if l = strings.TrimSpace(l); l != "" {
			line = l
			break
		}
	}
	if utf8.RuneCountInString(line) <= summaryMaxRunes {
		return line
	}
	runes := []rune(line)
	return strings.TrimSpace(string(runes[:summaryMaxRunes])) + ellipsis
}

// hermesSession is the part of Hermes' GET /api/sessions/{id} the transcript
// check reads: {"object": "hermes.session", "session": {...}}.
type hermesSession struct {
	ID     string `json:"id"`
	Source string `json:"source"`
	Title  string `json:"title"`
}

type transcriptResponse struct {
	SessionID string           `json:"session_id"`
	Title     string           `json:"title"`
	Kind      string           `json:"kind"`
	LatestID  int64            `json:"latest_id"`
	Messages  []sessionMessage `json:"messages"`
}

// handleTranscript returns the newest transcriptMaxRows text rows of a
// session, oldest first, for the kinds the page may open: the console's own
// sessions, and event triage or scheduled sessions the gateway API created.
// Every other session is refused with 403, after a lookup that reads only
// its source and title.
func (s *server) handleTranscript(w http.ResponseWriter, r *http.Request) {
	sid := r.PathValue("id")
	if !transcriptIDPattern.MatchString(sid) {
		writeError(w, http.StatusBadRequest, "invalid_session_id", "Session ID has characters a session ID does not use.")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), transcriptTimeout)
	defer cancel()
	sess, failure := s.lookupSession(ctx, sid)
	if failure != nil {
		writeError(w, failure.status, failure.code, failure.message)
		return
	}
	kind := classifySession(sid, sess.Source, sess.Title)
	if kind != kindConsole && kind != kindEventTriage && kind != kindScheduled {
		writeError(w, http.StatusForbidden, "transcript_not_allowed",
			"The console shows transcripts only for event triage, scheduled checks and its own sessions.")
		return
	}
	textRows := func(rows []hermesMessage) bool {
		n := 0
		for _, m := range rows {
			if hasText(m) {
				n++
			}
		}
		return n >= transcriptMaxRows
	}
	rows, failure := s.pageMessages(ctx, sid, 0, textRows)
	if failure != nil {
		writeError(w, failure.status, failure.code, failure.message)
		return
	}
	out := transcriptResponse{SessionID: sid, Title: sess.Title, Kind: kind, Messages: []sessionMessage{}}
	for _, m := range rows {
		if m.ID > out.LatestID {
			out.LatestID = m.ID
		}
		if hasText(m) {
			out.Messages = append(out.Messages, sessionMessage{ID: m.ID, Role: m.Role, Content: *m.Content, Timestamp: m.Timestamp})
		}
	}
	if len(out.Messages) > transcriptMaxRows {
		out.Messages = out.Messages[len(out.Messages)-transcriptMaxRows:]
	}
	writeJSON(w, http.StatusOK, out)
}

// lookupSession reads one session's metadata from Hermes.
func (s *server) lookupSession(ctx context.Context, sid string) (hermesSession, *upstreamFailure) {
	var out struct {
		Session hermesSession `json:"session"`
	}
	resp, err := s.hermes(ctx, http.MethodGet, "/api/sessions/"+url.PathEscape(sid), nil)
	if err != nil {
		return out.Session, &upstreamFailure{http.StatusBadGateway, "agent_unreachable", "Could not reach the agent gateway: " + err.Error()}
	}
	defer drainAndClose(resp)
	if resp.StatusCode == http.StatusNotFound {
		return out.Session, &upstreamFailure{http.StatusNotFound, "session_not_found", "The agent has no record of this session."}
	}
	if resp.StatusCode != http.StatusOK {
		return out.Session, &upstreamFailure{http.StatusBadGateway, "agent_error", upstreamErrorDetail(resp)}
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, maxUpstreamBodyBytes)).Decode(&out); err != nil {
		return out.Session, &upstreamFailure{http.StatusBadGateway, "agent_bad_response", "Agent gateway returned an unreadable session."}
	}
	return out.Session, nil
}
