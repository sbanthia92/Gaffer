import type { ChatSession, Message } from "./types";

const SESSIONS_KEY = "gaffer_sessions";
const ACTIVE_SESSION_KEY = "gaffer_active_session";

export function loadSessions(): ChatSession[] {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function saveSession(session: ChatSession): void {
  const sessions = loadSessions();
  const idx = sessions.findIndex((s) => s.id === session.id);
  if (idx >= 0) {
    sessions[idx] = session;
  } else {
    sessions.unshift(session);
  }
  localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
}

export function deleteSession(sessionId: string): void {
  const sessions = loadSessions().filter((s) => s.id !== sessionId);
  localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
}

export function loadActiveSessionId(): string | null {
  return localStorage.getItem(ACTIVE_SESSION_KEY);
}

export function saveActiveSessionId(id: string | null): void {
  if (id) {
    localStorage.setItem(ACTIVE_SESSION_KEY, id);
  } else {
    localStorage.removeItem(ACTIVE_SESSION_KEY);
  }
}

export function newSession(): ChatSession {
  const now = Date.now();
  return {
    id: crypto.randomUUID(),
    title: "New chat",
    messages: [],
    createdAt: now,
    updatedAt: now,
  };
}

export function deriveTitleFromMessage(content: string): string {
  return content.length > 50 ? content.slice(0, 50).trimEnd() + "…" : content;
}

export function appendMessage(
  session: ChatSession,
  message: Message
): ChatSession {
  const isFirst = session.messages.length === 0 && message.role === "user";
  return {
    ...session,
    title: isFirst ? deriveTitleFromMessage(message.content) : session.title,
    messages: [...session.messages, message],
    updatedAt: Date.now(),
  };
}
