import { useCallback, useEffect, useState } from "react";
import "./Admin.css";

const BASE_URL = import.meta.env.VITE_API_URL ?? "";
const SESSION_KEY = "gaffer_admin_pw";

interface DashboardData {
  period_hours: number;
  total_requests: number;
  error_count: number;
  error_rate_pct: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  input_tokens: number;
  output_tokens: number;
  cache_hit_pct: number;
  thumbsdown_count: number;
  photo_missing_count: number;
  fetched_at: string;
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function fmtMs(ms: number | null): string {
  if (ms === null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

function MetricCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="admin-card">
      <div className="admin-card__label">{label}</div>
      <div className="admin-card__value">{value}</div>
      {sub && <div className="admin-card__sub">{sub}</div>}
    </div>
  );
}

export default function Admin() {
  const [password, setPassword] = useState("");
  const [authed, setAuthed] = useState(false);
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [hours, setHours] = useState(24);
  const [countdown, setCountdown] = useState(60);

  const fetchData = useCallback(async (pw: string, h: number) => {
    setLoading(true);
    setErr("");
    try {
      const res = await fetch(`${BASE_URL}/api/admin/dashboard?hours=${h}`, {
        headers: { Authorization: `Basic ${btoa(`admin:${pw}`)}` },
      });
      if (res.status === 401) {
        sessionStorage.removeItem(SESSION_KEY);
        setAuthed(false);
        setErr("Incorrect password.");
        return;
      }
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      setData(await res.json());
      setAuthed(true);
      setCountdown(60);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load.");
    } finally {
      setLoading(false);
    }
  }, []);

  // Restore session on mount
  useEffect(() => {
    const saved = sessionStorage.getItem(SESSION_KEY);
    if (saved) {
      setPassword(saved);
      fetchData(saved, 24);
    }
  }, [fetchData]);

  // Auto-refresh countdown
  useEffect(() => {
    if (!authed) return;
    const tick = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) {
          fetchData(sessionStorage.getItem(SESSION_KEY) ?? password, hours);
          return 60;
        }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(tick);
  }, [authed, password, hours, fetchData]);

  function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    sessionStorage.setItem(SESSION_KEY, password);
    fetchData(password, hours);
  }

  function changeHours(h: number) {
    setHours(h);
    fetchData(sessionStorage.getItem(SESSION_KEY) ?? password, h);
  }

  if (!authed) {
    return (
      <div className="admin-gate">
        <form className="admin-login" onSubmit={handleLogin}>
          <div className="admin-login__logo">🛡</div>
          <h1>Gaffer Admin</h1>
          <input
            type="password"
            className="admin-login__input"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
          />
          {err && <p className="admin-err">{err}</p>}
          <button className="admin-login__btn" type="submit" disabled={loading}>
            {loading ? "Checking…" : "Sign in"}
          </button>
        </form>
      </div>
    );
  }

  const periodLabel = hours === 1 ? "1h" : hours === 24 ? "24h" : "7d";

  return (
    <div className="admin">
      <header className="admin-header">
        <div className="admin-header__left">
          <span className="admin-header__title">🛡 Gaffer Admin</span>
          {data && (
            <span className="admin-header__updated">
              Updated {new Date(data.fetched_at).toLocaleTimeString()} · refresh in {countdown}s
            </span>
          )}
        </div>
        <div className="admin-header__right">
          <div className="admin-period-btns">
            {([1, 24, 168] as const).map((h) => (
              <button
                key={h}
                className={`admin-period-btn${hours === h ? " active" : ""}`}
                onClick={() => changeHours(h)}
                disabled={loading}
              >
                {h === 1 ? "1h" : h === 24 ? "24h" : "7d"}
              </button>
            ))}
          </div>
          <button
            className="admin-refresh-btn"
            onClick={() => fetchData(sessionStorage.getItem(SESSION_KEY) ?? password, hours)}
            disabled={loading}
            title="Refresh now"
          >
            {loading ? "…" : "↻"}
          </button>
        </div>
      </header>

      {err && <div className="admin-banner-err">{err}</div>}

      {data && (
        <div className="admin-grid">
          <MetricCard
            label="Requests"
            value={fmtNum(data.total_requests)}
            sub={`last ${periodLabel}`}
          />
          <MetricCard
            label="Errors"
            value={fmtNum(data.error_count)}
            sub={data.total_requests > 0 ? `${data.error_rate_pct}% error rate` : "no requests yet"}
          />
          <MetricCard
            label="Thumbs Down"
            value={String(data.thumbsdown_count)}
            sub={
              data.total_requests > 0
                ? `${((data.thumbsdown_count / data.total_requests) * 100).toFixed(1)}% of requests`
                : undefined
            }
          />
          <MetricCard
            label="Avg Latency"
            value={fmtMs(data.avg_latency_ms)}
            sub="end-to-end response time"
          />
          <MetricCard
            label="P95 Latency"
            value={fmtMs(data.p95_latency_ms)}
            sub="95th percentile"
          />
          <MetricCard
            label="Cache Hit"
            value={`${data.cache_hit_pct}%`}
            sub="input tokens from prompt cache"
          />
          <MetricCard
            label="Input Tokens"
            value={fmtNum(data.input_tokens)}
            sub="billed at input rate"
          />
          <MetricCard
            label="Output Tokens"
            value={fmtNum(data.output_tokens)}
            sub="billed at output rate"
          />
          <MetricCard
            label="Missing Photos"
            value={String(data.photo_missing_count)}
            sub="player.photo_missing events"
          />
        </div>
      )}
    </div>
  );
}
