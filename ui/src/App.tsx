import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { askGaffer, fetchPlayerCard, submitFeedback } from "./api";
import Landing from "./Landing";
import {
  appendMessage,
  deleteSession,
  loadActiveSessionId,
  loadSessions,
  newSession,
  saveActiveSessionId,
  saveSession,
} from "./storage";
import type { ChatSession, Message } from "./types";
import "./App.css";

const FPL_TEAM_ID_KEY = "gaffer_fpl_team_id";

function loadFplTeamId(): number | null {
  const raw = localStorage.getItem(FPL_TEAM_ID_KEY);
  const n = raw ? parseInt(raw, 10) : NaN;
  return isNaN(n) ? null : n;
}

function saveFplTeamId(id: number): void {
  localStorage.setItem(FPL_TEAM_ID_KEY, String(id));
}

// ── Onboarding modal ──────────────────────────────────────────────────────────

function FplTeamModal({
  onSave,
  onClose,
}: {
  onSave: (id: number) => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState("");
  const [err, setErr] = useState("");

  function handleSubmit() {
    const n = parseInt(value.trim(), 10);
    if (isNaN(n) || n <= 0) {
      setErr("Please enter a valid numeric team ID.");
      return;
    }
    saveFplTeamId(n);
    onSave(n);
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Your FPL Team ID</h2>
        <p className="modal-subtitle">
          Optional — add your Team ID for personalised squad advice. You can
          skip this and ask about any player or captaincy pick without it.
        </p>

        <div className="modal-how">
          <p className="modal-how-title">How to find your Team ID:</p>
          <ol>
            <li>
              Go to{" "}
              <a
                href="https://fantasy.premierleague.com/my-team"
                target="_blank"
                rel="noreferrer"
              >
                fantasy.premierleague.com/my-team
              </a>
            </li>
            <li>
              Click the <strong>Points</strong> tab — your ID is in the URL:{" "}
              <code>entry/&#123;YOUR_ID&#125;/event/...</code>
            </li>
          </ol>
        </div>

        <input
          className="modal-input"
          type="number"
          placeholder="e.g. 5402482"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setErr("");
          }}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          autoFocus
        />
        {err && <p className="modal-error">{err}</p>}
        <div className="modal-actions">
          <button className="modal-btn-secondary" onClick={onClose}>
            Skip for now
          </button>
          <button className="modal-btn" onClick={handleSubmit}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Bug report modal ──────────────────────────────────────────────────────────

function FeedbackModal({ onClose }: { onClose: () => void }) {
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");

  async function handleSubmit() {
    if (!message.trim()) {
      setErr("Please describe the issue.");
      return;
    }
    setSending(true);
    setErr("");
    try {
      await submitFeedback(message.trim(), email.trim());
      setSent(true);
    } catch {
      setErr("Failed to send — please try again.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        {sent ? (
          <>
            <h2>Thanks for the feedback!</h2>
            <p className="modal-subtitle">We'll look into it.</p>
            <button className="modal-btn" onClick={onClose}>
              Close
            </button>
          </>
        ) : (
          <>
            <h2>Report a bug</h2>
            <p className="modal-subtitle">
              Describe what went wrong and we'll fix it.
            </p>
            <textarea
              className="modal-textarea"
              placeholder="What happened? What did you expect?"
              value={message}
              onChange={(e) => {
                setMessage(e.target.value);
                setErr("");
              }}
              rows={4}
              autoFocus
            />
            <input
              className="modal-input"
              type="email"
              placeholder="Your email (optional)"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            {err && <p className="modal-error">{err}</p>}
            <div className="modal-actions">
              <button className="modal-btn-secondary" onClick={onClose}>
                Cancel
              </button>
              <button
                className="modal-btn"
                onClick={handleSubmit}
                disabled={sending}
              >
                {sending ? "Sending…" : "Send report"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Player-badge aware markdown renderer ─────────────────────────────────────

const PLAYER_TAG = /\[\[([^\]]+)\]\]/g;

function PlayerBadge({ name }: { name: string }) {
  const [label, setLabel] = useState(name);

  useEffect(() => {
    fetchPlayerCard(name).then((card) => {
      if (card) setLabel(`${card.name} · ${card.team} · £${card.price.toFixed(1)}m`);
    });
  }, [name]);

  return <span className="player-badge">{label}</span>;
}

function GafferMarkdown({ content }: { content: string }) {
  const segments: Array<{ type: "md" | "player"; value: string }> = [];
  let last = 0;
  let match;
  PLAYER_TAG.lastIndex = 0;
  while ((match = PLAYER_TAG.exec(content)) !== null) {
    if (match.index > last) {
      segments.push({ type: "md", value: content.slice(last, match.index) });
    }
    segments.push({ type: "player", value: match[1] });
    last = match.index + match[0].length;
  }
  if (last < content.length) {
    segments.push({ type: "md", value: content.slice(last) });
  }

  return (
    <>
      {segments.map((seg, i) =>
        seg.type === "player" ? (
          <PlayerBadge key={i} name={seg.value} />
        ) : (
          <ReactMarkdown key={i} remarkPlugins={[remarkGfm]}>
            {seg.value}
          </ReactMarkdown>
        )
      )}
    </>
  );
}

// ── Main app ──────────────────────────────────────────────────────────────────

export default function App() {
  const [sessions, setSessions] = useState<ChatSession[]>(() => loadSessions());
  const [activeId, setActiveId] = useState<string | null>(
    () => loadActiveSessionId()
  );
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [fplTeamId, setFplTeamId] = useState<number | null>(() =>
    loadFplTeamId()
  );
  const [showLanding, setShowLanding] = useState(() => loadSessions().length === 0);
  const [showFplModal, setShowFplModal] = useState(false);
  const [showFeedback, setShowFeedback] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const activeSession = sessions.find((s) => s.id === activeId) ?? null;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeSession?.messages.length, loading]);

  useEffect(() => {
    saveActiveSessionId(activeId);
  }, [activeId]);

  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = `${e.target.scrollHeight}px`;
  }

  function selectSession(id: string) {
    setActiveId(id);
    setError(null);
    setSidebarOpen(false);
    setTimeout(() => inputRef.current?.focus(), 50);
  }

  function startNewSession() {
    const session = newSession();
    setSessions((prev) => [session, ...prev]);
    saveSession(session);
    setActiveId(session.id);
    setShowLanding(false);
    setError(null);
    setTimeout(() => inputRef.current?.focus(), 50);
  }

  function handleDeleteSession(e: React.MouseEvent, sessionId: string) {
    e.stopPropagation();
    deleteSession(sessionId);
    setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    if (activeId === sessionId) {
      const remaining = sessions.filter((s) => s.id !== sessionId);
      setActiveId(remaining[0]?.id ?? null);
    }
  }

  async function handleSend() {
    const question = input.trim();
    if (!question || loading) return;

    let session = activeSession;
    if (!session) {
      session = newSession();
    }

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: question,
      timestamp: Date.now(),
      league: "fpl",
    };

    const updatedWithUser = appendMessage(session, userMsg);
    setSessions((prev) => {
      const exists = prev.find((s) => s.id === updatedWithUser.id);
      return exists
        ? prev.map((s) => (s.id === updatedWithUser.id ? updatedWithUser : s))
        : [updatedWithUser, ...prev];
    });
    saveSession(updatedWithUser);
    setActiveId(updatedWithUser.id);
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";
    setError(null);
    setLoading(true);
    setStatusText(null);

    try {
      // Create a placeholder assistant message to stream into
      const assistantMsgId = crypto.randomUUID();
      const assistantMsg: Message = {
        id: assistantMsgId,
        role: "assistant",
        content: "",
        timestamp: Date.now(),
        league: "fpl",
      };
      const updatedWithPlaceholder = appendMessage(updatedWithUser, assistantMsg);
      setSessions((prev) => {
        const exists = prev.find((s) => s.id === updatedWithPlaceholder.id);
        return exists
          ? prev.map((s) =>
              s.id === updatedWithPlaceholder.id ? updatedWithPlaceholder : s
            )
          : [updatedWithPlaceholder, ...prev];
      });

      let accumulated = "";
      await askGaffer(
        question,
        "fpl",
        fplTeamId,
        (chunk) => {
          accumulated += chunk;
          setStatusText(null);
          setSessions((prev) =>
            prev.map((s) => {
              if (s.id !== updatedWithPlaceholder.id) return s;
              return {
                ...s,
                messages: s.messages.map((m) =>
                  m.id === assistantMsgId ? { ...m, content: accumulated } : m
                ),
              };
            })
          );
        },
        (status) => {
          setStatusText(status);
        }
      );

      // Persist the final answer
      setSessions((prev) => {
        const session = prev.find((s) => s.id === updatedWithPlaceholder.id);
        if (session) saveSession(session);
        return prev;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
      setStatusText(null);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  if (showLanding) {
    return <Landing onStart={() => setShowLanding(false)} />;
  }

  return (
    <div className="app">
      {showFplModal && (
        <FplTeamModal
          onSave={(id) => {
            setFplTeamId(id);
            setShowFplModal(false);
          }}
          onClose={() => setShowFplModal(false)}
        />
      )}

      {showFeedback && (
        <FeedbackModal onClose={() => setShowFeedback(false)} />
      )}

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar */}
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="sidebar-header">
          <span className="logo">⚽ gaffer.io</span>
          <button className="new-chat-btn" onClick={startNewSession}>
            + New
          </button>
        </div>
        <nav className="session-list">
          {sessions.length === 0 && (
            <p className="empty-sessions">No chats yet</p>
          )}
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`session-item ${s.id === activeId ? "active" : ""}`}
              onClick={() => selectSession(s.id)}
            >
              <span className="session-title">{s.title}</span>
              <button
                className="delete-btn"
                onClick={(e) => handleDeleteSession(e, s.id)}
                title="Delete chat"
              >
                ×
              </button>
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <button
            className="sidebar-footer-btn"
            onClick={() => setShowFplModal(true)}
          >
            FPL ID: {fplTeamId ?? "not set"}
          </button>
          <button
            className="sidebar-footer-btn"
            onClick={() => setShowFeedback(true)}
          >
            Report a bug
          </button>
        </div>
      </aside>

      {/* Main chat area */}
      <main className="chat-area">
        <div className="mobile-header">
          <button className="menu-btn" onClick={() => setSidebarOpen(true)}>
            ☰
          </button>
          <span className="mobile-logo">⚽ gaffer.io</span>
        </div>

        {!activeSession || activeSession.messages.length === 0 ? (
          <div className="empty-state">
            <h1>The Gaffer</h1>
            <p>
              Your AI-powered FPL analyst. Ask anything about your squad,
              transfers, or captaincy.
            </p>
            <div className="suggestions">
              {[
                "Should I captain Salah this week?",
                "If I can make 2 transfers, who should I bring in?",
                "What's the best differential pick right now?",
                "Which premium midfielder is worth the price?",
              ].map((q) => (
                <button
                  key={q}
                  className="suggestion-btn"
                  onClick={() => {
                    setInput(q);
                    setTimeout(() => inputRef.current?.focus(), 50);
                  }}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="messages">
            {activeSession.messages.map((msg) => {
              const isLoadingPlaceholder =
                loading && msg.role === "assistant" && msg.content === "";
              return (
                <div key={msg.id} className={`message ${msg.role}`}>
                  {msg.role === "assistant" ? (
                    <div className={`assistant-bubble${isLoadingPlaceholder ? " thinking" : ""}`}>
                      {isLoadingPlaceholder ? (
                        statusText ? (
                          <span className="status-text">{statusText}</span>
                        ) : (
                          <>
                            <span className="dot" />
                            <span className="dot" />
                            <span className="dot" />
                          </>
                        )
                      ) : (
                        <>
                          <div className="bubble-label">The Gaffer · FPL</div>
                          <GafferMarkdown content={msg.content} />
                        </>
                      )}
                    </div>
                  ) : (
                    <div className="user-bubble">{msg.content}</div>
                  )}
                </div>
              );
            })}
            {error && <div className="error-banner">⚠ {error}</div>}
            <div ref={bottomRef} />
          </div>
        )}

        {/* Input */}
        <div className="input-row">
          <textarea
            ref={inputRef}
            className="chat-input"
            placeholder="Ask The Gaffer…"
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            rows={1}
            disabled={loading}
          />
          <button
            className="send-btn"
            onClick={handleSend}
            disabled={loading || !input.trim()}
          >
            {loading ? "…" : "Send"}
          </button>
        </div>
      </main>
    </div>
  );
}
