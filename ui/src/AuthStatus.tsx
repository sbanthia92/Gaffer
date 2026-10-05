import { useEffect, useRef, useState } from "react";
import { getAuthStatus, logout, type AuthStatus as AuthStatusData } from "./api";
import "./AuthStatus.css";

export default function AuthStatus() {
  const [status, setStatus] = useState<AuthStatusData | null>(null);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getAuthStatus().then(setStatus);
  }, []);

  // Close the menu on an outside click or Escape
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!status) return null;

  if (!status.authenticated) {
    return (
      <div className="auth-status">
        <a className="auth-status-btn" href="/api/auth/google/login">
          Sign in with Google
        </a>
      </div>
    );
  }

  return (
    <div className="auth-status" ref={ref}>
      <button
        className="auth-status-btn auth-status-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="auth-status-name">{status.name || status.email}</span>
        <span className="auth-status-caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="auth-status-menu" role="menu">
          <button
            className="auth-status-menu-item"
            role="menuitem"
            onClick={async () => {
              await logout();
              setOpen(false);
              setStatus({ authenticated: false });
            }}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
