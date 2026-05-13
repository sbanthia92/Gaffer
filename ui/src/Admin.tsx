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
  estimated_cost_usd: number;
  unique_users: number;
  avg_tool_turns: number;
  turn_limit_hits: number;
  thumbsdown_count: number;
  photo_missing_count: number;
  fetched_at: string;
}

interface JobRun {
  last_run_at: string | null;
  last_status: "success" | "failure" | null;
  last_gw: number | null;
  last_duration_s: number | null;
  last_details: Record<string, unknown>;
  runs_7d: { successes: number; failures: number };
}

interface JobsData {
  jobs: Record<string, JobRun>;
  postgres: {
    current_players: number;
    gameweeks_synced: number;
    gw_stats_rows: number;
    total_seasons: number;
  } | null;
  pinecone: {
    total_vectors: number;
    namespaces: Record<string, number>;
  } | null;
  fetched_at: string;
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function fmtCost(usd: number): string {
  if (usd === 0) return "$0.00";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function fmtMs(ms: number | null): string {
  if (ms === null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

function fmtRelative(iso: string | null): string {
  if (!iso) return "never";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
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

function StatusDot({ status }: { status: "success" | "failure" | null }) {
  const cls =
    status === "success"
      ? "admin-status-dot admin-status-dot--success"
      : status === "failure"
        ? "admin-status-dot admin-status-dot--failure"
        : "admin-status-dot admin-status-dot--unknown";
  return <span className={cls} />;
}

export default function Admin() {
  const [password, setPassword] = useState("");
  const [authed, setAuthed] = useState(false);
  const [data, setData] = useState<DashboardData | null>(null);
  const [jobs, setJobs] = useState<JobsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [hours, setHours] = useState(24);
  const [countdown, setCountdown] = useState(60);

  const fetchData = useCallback(async (pw: string, h: number) => {
    setLoading(true);
    setErr("");
    try {
      const [dashRes, jobsRes] = await Promise.all([
        fetch(`${BASE_URL}/api/admin/dashboard?hours=${h}`, {
          headers: { Authorization: `Basic ${btoa(`admin:${pw}`)}` },
        }),
        fetch(`${BASE_URL}/api/admin/jobs`, {
          headers: { Authorization: `Basic ${btoa(`admin:${pw}`)}` },
        }),
      ]);
      if (dashRes.status === 401) {
        sessionStorage.removeItem(SESSION_KEY);
        setAuthed(false);
        setErr("Incorrect password.");
        return;
      }
      if (!dashRes.ok) throw new Error(`Server error ${dashRes.status}`);
      setData(await dashRes.json());
      if (jobsRes.ok) setJobs(await jobsRes.json());
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

  const JOB_LABELS: Record<string, string> = {
    press_ingest: "Press Ingest",
    gw_check: "GW Check",
  };

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
          <MetricCard
            label="Estimated Cost"
            value={fmtCost(data.estimated_cost_usd)}
            sub="Claude Sonnet 4.6 API spend"
          />
          <MetricCard
            label="Unique Users"
            value={fmtNum(data.unique_users)}
            sub="distinct FPL team IDs"
          />
          <MetricCard
            label="Avg Tool Turns"
            value={String(data.avg_tool_turns)}
            sub="Claude tool-use rounds per request"
          />
          <MetricCard
            label="Turn Limit Hits"
            value={String(data.turn_limit_hits)}
            sub="requests capped at 5 turns"
          />
        </div>
      )}

      {/* ── Background Jobs ──────────────────────────────────────────────────── */}
      {jobs && (
        <>
          <h2 className="admin-section-title">Background Jobs</h2>
          <div className="admin-jobs-table">
            <div className="admin-jobs-header">
              <span>Job</span>
              <span>Last Run</span>
              <span>Status</span>
              <span>Duration</span>
              <span>7d Pass Rate</span>
            </div>
            {Object.entries(jobs.jobs).length === 0 && (
              <div className="admin-jobs-empty">No job runs recorded yet.</div>
            )}
            {Object.entries(jobs.jobs).map(([name, run]) => {
              const total = run.runs_7d.successes + run.runs_7d.failures;
              const pct = total > 0 ? Math.round((run.runs_7d.successes / total) * 100) : null;
              return (
                <div key={name} className="admin-jobs-row">
                  <span className="admin-jobs-name">{JOB_LABELS[name] ?? name}</span>
                  <span className="admin-jobs-time" title={run.last_run_at ?? ""}>
                    {fmtRelative(run.last_run_at)}
                  </span>
                  <span className="admin-jobs-status">
                    <StatusDot status={run.last_status} />
                    {run.last_status ?? "—"}
                  </span>
                  <span className="admin-jobs-dur">
                    {run.last_duration_s != null ? `${run.last_duration_s}s` : "—"}
                  </span>
                  <span
                    className={`admin-jobs-rate${pct !== null && pct < 90 ? " admin-jobs-rate--warn" : ""}`}
                  >
                    {pct !== null ? `${pct}% (${run.runs_7d.successes}/${total})` : "—"}
                  </span>
                </div>
              );
            })}
          </div>

          {/* ── Data Stores ─────────────────────────────────────────────────── */}
          <h2 className="admin-section-title">Data Stores</h2>
          <div className="admin-grid admin-grid--compact">
            {jobs.postgres && (
              <>
                <MetricCard
                  label="Players (current season)"
                  value={fmtNum(jobs.postgres.current_players)}
                  sub="rows in players table"
                />
                <MetricCard
                  label="Gameweeks Synced"
                  value={String(jobs.postgres.gameweeks_synced)}
                  sub="finished GWs with stats"
                />
                <MetricCard
                  label="GW Stat Rows"
                  value={fmtNum(jobs.postgres.gw_stats_rows)}
                  sub="rows in gw_player_stats"
                />
                <MetricCard
                  label="Seasons in DB"
                  value={String(jobs.postgres.total_seasons)}
                  sub="historical seasons loaded"
                />
              </>
            )}
            {jobs.pinecone ? (
              <>
                <MetricCard
                  label="Pinecone Vectors"
                  value={fmtNum(jobs.pinecone.total_vectors)}
                  sub="total across all namespaces"
                />
                {Object.entries(jobs.pinecone.namespaces).map(([ns, count]) => (
                  <MetricCard
                    key={ns}
                    label={`Pinecone · ${ns}`}
                    value={fmtNum(count)}
                    sub="vectors in namespace"
                  />
                ))}
              </>
            ) : (
              <MetricCard
                label="Pinecone"
                value="—"
                sub="stats unavailable (check API key)"
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
