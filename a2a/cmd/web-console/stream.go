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

// POST /api/chat/stream: one turn, with a live status line while it runs.
//
// It takes the same request and applies the same checks as POST /api/chat.
// It calls Hermes' POST /api/sessions/{id}/chat/stream and relays a reduced
// SSE stream to the page: `status` events carrying one short plain-text line
// ("Running kubectl_get: pods -n x"), then one `reply` event with the full
// reply, or one `error` event in /api/chat's error shape. Tool arguments and
// full previews are not forwarded; each line is collapsed and cut here.
//
// The handler reads Hermes' stream to its end before it sends the reply.
// Closing it early would read to Hermes as a client disconnect and interrupt
// the run.

package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"unicode/utf8"
)

const (
	contentTypeEventStream = "text/event-stream"

	// The events the page reads.
	eventStatus = "status"
	eventReply  = "reply"
	eventError  = "error"

	// The Hermes events the relay reads; see _handle_session_chat_stream in
	// hermes-agent's gateway/platforms/api_server.py.
	hermesRunStarted         = "run.started"
	hermesToolStarted        = "tool.started"
	hermesToolCompleted      = "tool.completed"
	hermesToolFailed         = "tool.failed"
	hermesToolProgress       = "tool.progress"
	hermesAssistantDelta     = "assistant.delta"
	hermesAssistantCompleted = "assistant.completed"
	hermesEventError         = "error"
	hermesDone               = "done"
	// hermesThinkingTool is the tool name Hermes gives reasoning progress.
	hermesThinkingTool = "_thinking"

	sseEventPrefix = "event:"
	sseDataPrefix  = "data:"
	sseComment     = ":"
	sseKeepalive   = ": keepalive\n\n"

	// statusFragmentRunes bounds a tool preview or a reasoning excerpt
	// inside a status line, and statusLineRunes the whole line.
	statusFragmentRunes = 120
	statusLineRunes     = 160

	statusSending  = "Sending your message to the agent"
	statusStarted  = "The agent started working"
	statusWriting  = "Writing the reply"
	errNoReply     = "The agent's stream ended without a reply."
	errStreamWrite = "the browser closed the stream"
)

// hermesStreamEvent is the part of a Hermes stream event's data the relay
// reads.
type hermesStreamEvent struct {
	ToolName string `json:"tool_name"`
	Preview  string `json:"preview"`
	Delta    string `json:"delta"`
	Content  string `json:"content"`
	Message  string `json:"message"`
}

type statusEvent struct {
	Text string `json:"text"`
}

// sseWriter writes events to the page and flushes each one.
type sseWriter struct {
	w  http.ResponseWriter
	rc *http.ResponseController
}

func (e *sseWriter) send(name string, v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	if _, err := fmt.Fprintf(e.w, "event: %s\ndata: %s\n\n", name, b); err != nil {
		return err
	}
	return e.rc.Flush()
}

func (e *sseWriter) keepalive() error {
	if _, err := io.WriteString(e.w, sseKeepalive); err != nil {
		return err
	}
	return e.rc.Flush()
}

func (s *server) handleChatStream(w http.ResponseWriter, r *http.Request) {
	sid, msg, agentSession, ok := s.beginTurn(w, r)
	if !ok {
		return
	}
	defer s.release(sid)

	ctx, cancel := context.WithTimeout(r.Context(), turnTimeout)
	defer cancel()

	w.Header().Set("Content-Type", contentTypeEventStream)
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)
	out := &sseWriter{w: w, rc: http.NewResponseController(w)}
	if out.send(eventStatus, statusEvent{Text: statusSending}) != nil {
		return
	}

	resp, err := s.openTurnStream(ctx, sid, msg)
	if errors.Is(err, errSessionNotFound) && !agentSession {
		// Same recovery as /api/chat: the agent pod lost the session. A
		// session the cluster opened is never recreated here.
		if err = s.createSession(ctx, sid); err == nil {
			resp, err = s.openTurnStream(ctx, sid, msg)
		}
	}
	if err != nil {
		_, body := turnFailure(err, sid)
		_ = out.send(eventError, body)
		return
	}
	defer drainAndClose(resp)

	reply, err := relayTurnStream(ctx, resp.Body, out)
	switch {
	case errors.Is(err, errBrowserGone):
		return
	case err != nil:
		_, body := turnFailure(err, sid)
		_ = out.send(eventError, body)
	default:
		_ = out.send(eventReply, chatResponse{SessionID: sid, Reply: reply})
	}
}

// openTurnStream starts a streamed turn. An error status arrives before the
// stream starts, as JSON, and maps to the same errors runTurn returns.
func (s *server) openTurnStream(ctx context.Context, sid, msg string) (*http.Response, error) {
	resp, err := s.hermes(ctx, http.MethodPost, "/api/sessions/"+url.PathEscape(sid)+"/chat/stream", map[string]string{"message": msg})
	if err != nil {
		return nil, err
	}
	if resp.StatusCode == http.StatusOK {
		return resp, nil
	}
	defer drainAndClose(resp)
	if resp.StatusCode == http.StatusNotFound {
		return nil, errSessionNotFound
	}
	return nil, &upstreamError{status: resp.StatusCode, detail: upstreamErrorDetail(resp)}
}

var errBrowserGone = errors.New(errStreamWrite)

// relayTurnStream reads Hermes' SSE stream until done or EOF, sends a status
// line for each event worth showing, and returns the reply from
// assistant.completed. An error event with no reply becomes the error.
func relayTurnStream(ctx context.Context, body io.Reader, out *sseWriter) (string, error) {
	scanner := bufio.NewScanner(body)
	scanner.Buffer(make([]byte, 0, bufio.MaxScanTokenSize), maxUpstreamBodyBytes)
	var (
		name, lastStatus, reply, upstreamMsg string
		data                                 []string
		haveReply, done                      bool
	)
	dispatch := func() error {
		defer func() { name, data = "", nil }()
		if name == "" && len(data) == 0 {
			return nil
		}
		var ev hermesStreamEvent
		_ = json.Unmarshal([]byte(strings.Join(data, "\n")), &ev)
		switch name {
		case hermesAssistantCompleted:
			reply, haveReply = ev.Content, true
			return nil
		case hermesEventError:
			upstreamMsg = ev.Message
			return nil
		case hermesDone:
			done = true
			return nil
		}
		text := statusLine(name, ev)
		if text == "" || text == lastStatus {
			return nil
		}
		lastStatus = text
		if out.send(eventStatus, statusEvent{Text: text}) != nil {
			return errBrowserGone
		}
		return nil
	}
	for !done && scanner.Scan() {
		line := scanner.Text()
		switch {
		case line == "":
			if err := dispatch(); err != nil {
				return "", err
			}
		case strings.HasPrefix(line, sseComment):
			if out.keepalive() != nil {
				return "", errBrowserGone
			}
		case strings.HasPrefix(line, sseEventPrefix):
			name = strings.TrimSpace(strings.TrimPrefix(line, sseEventPrefix))
		case strings.HasPrefix(line, sseDataPrefix):
			data = append(data, strings.TrimPrefix(strings.TrimPrefix(line, sseDataPrefix), " "))
		}
	}
	if !done {
		if err := dispatch(); err != nil {
			return "", err
		}
	}
	if err := scanner.Err(); err != nil && !haveReply {
		if ctx.Err() != nil {
			return "", ctx.Err()
		}
		return "", fmt.Errorf("agent stream broke off: %w", err)
	}
	if haveReply {
		return reply, nil
	}
	if ctx.Err() != nil {
		return "", ctx.Err()
	}
	if upstreamMsg != "" {
		return "", errors.New(upstreamMsg)
	}
	return "", errors.New(errNoReply)
}

// statusLine is the one-line status for a Hermes event, or "" for an event
// the page does not show.
func statusLine(name string, ev hermesStreamEvent) string {
	tool := clip(ev.ToolName, statusFragmentRunes)
	var line string
	switch name {
	case hermesRunStarted:
		line = statusStarted
	case hermesToolStarted:
		line = "Running " + tool
		if preview := clip(ev.Preview, statusFragmentRunes); preview != "" {
			line += ": " + preview
		}
	case hermesToolCompleted:
		line = "Finished " + tool
	case hermesToolFailed:
		line = tool + " failed"
	case hermesToolProgress:
		if ev.ToolName != hermesThinkingTool {
			return ""
		}
		thought := clip(ev.Delta, statusFragmentRunes)
		if thought == "" {
			return ""
		}
		line = "Thinking: " + thought
	case hermesAssistantDelta:
		line = statusWriting
	default:
		return ""
	}
	return clip(line, statusLineRunes)
}

// clip collapses whitespace runs to single spaces and cuts text to max
// runes, marking a cut with an ellipsis.
func clip(text string, max int) string {
	text = strings.Join(strings.Fields(text), " ")
	if utf8.RuneCountInString(text) <= max {
		return text
	}
	runes := []rune(text)
	return strings.TrimSpace(string(runes[:max])) + ellipsis
}
