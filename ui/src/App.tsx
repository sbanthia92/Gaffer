import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { askGaffer } from "./api";
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

export default function App() {
  const [sessions, setSessions] = useState<ChatSession[]>(() => loadSessions());
  const [activeId, setActiveId] = useState<string | null>(
    () => loadActiveSessionId()
  );
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const activeSession = sessions.find((s) => s.id === activeId) ?? null;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeSession?.messages.length, loading]);

  useEffect(() => {
    saveActiveSessionId(activeId);
  }, [activeId]);

  function selectSession(id: string) {
    setActiveId(id);
    setError(null);
    setTimeout(() => inputRef.current?.focus(), 50);
  }

  function startNewSession() {
    const session = newSession();
    setSessions((prev) => [session, ...prev]);
    saveSession(session);
    setActiveId(session.id);
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
    setError(null);
    setLoading(true);

    try {
      const answer = await askGaffer(question, "fpl");
      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: answer,
        timestamp: Date.now(),
        league: "fpl",
      };
      const updatedWithAnswer = appendMessage(updatedWithUser, assistantMsg);
      setSessions((prev) =>
        prev.map((s) =>
          s.id === updatedWithAnswer.id ? updatedWithAnswer : s
        )
      );
      saveSession(updatedWithAnswer);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="app">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <span className="logo">⚽ The Gaffer</span>
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
      </aside>

      {/* Main chat area */}
      <main className="chat-area">
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
            {activeSession.messages.map((msg) => (
              <div key={msg.id} className={`message ${msg.role}`}>
                {msg.role === "assistant" ? (
                  <div className="assistant-bubble">
                    <div className="bubble-label">The Gaffer · FPL</div>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <div className="user-bubble">{msg.content}</div>
                )}
              </div>
            ))}
            {loading && (
              <div className="message assistant">
                <div className="assistant-bubble thinking">
                  <span className="dot" />
                  <span className="dot" />
                  <span className="dot" />
                </div>
              </div>
            )}
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
            onChange={(e) => setInput(e.target.value)}
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
