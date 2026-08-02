import { useEffect, useState } from "react";
import { getAuthStatus, logout, type AuthStatus as AuthStatusData } from "./api";
import "./AuthStatus.css";

export default function AuthStatus() {
  const [status, setStatus] = useState<AuthStatusData | null>(null);

  useEffect(() => {
    getAuthStatus().then(setStatus);
  }, []);

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
    <div className="auth-status">
      <span className="auth-status-name">{status.name || status.email}</span>
      <button
        className="auth-status-btn"
        onClick={async () => {
          await logout();
          setStatus({ authenticated: false });
        }}
      >
        Sign out
      </button>
    </div>
  );
}
