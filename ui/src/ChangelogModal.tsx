import "./ChangelogModal.css";

interface Release {
  version: string;
  date: string;
  added?: string[];
  changed?: string[];
}

const RELEASES: Release[] = [
  {
    version: "0.66.0",
    date: "13 May 2026",
    added: [
      "Admin dashboard: Background Jobs section — shows last run time, pass/fail status, duration, and 7-day pass rate for the press ingestion and gameweek-check cron jobs. Jobs failing more than 10% of the time highlight in amber.",
      "Admin dashboard: Data Stores section — shows Postgres row counts (players, finished gameweeks, stat rows, seasons) and Pinecone vector counts by namespace so you can verify data is being ingested correctly.",
    ],
  },
  {
    version: "0.65.0",
    date: "13 May 2026",
    changed: [
      "Internal: removed the broken ingest.yml GitHub Actions workflow. Press ingestion now runs exclusively on the EC2 server via scheduled cron jobs (07:00 and 19:00 UTC daily).",
    ],
  },
  {
    version: "0.64.0",
    date: "11 May 2026",
    added: [
      "Dynamic post-gameweek ETL — the DB sync no longer runs on a fixed Tuesday schedule that breaks during double-gameweek weeks. An hourly poller (pipeline/check_gw_complete.py) checks the FPL API for newly-finished gameweeks and only triggers the full GW stats update when one is detected.",
    ],
  },
  {
    version: "0.63.0",
    date: "11 May 2026",
    changed: [
      "Landing page no longer references bookmaker odds or API-Sports — the 'Live data' feature description and example chat now reflect the FPL-API-only data path introduced in v0.52.0.",
    ],
  },
  {
    version: "0.62.0",
    date: "11 May 2026",
    changed: [
      "Player names are now click-to-reveal links — click any player name in an answer to open a popover showing their photo, team, position, price, form, points, and ownership. Closes on outside click or Escape. Fixes inline chips that were breaking table alignment and interrupting reading flow.",
    ],
  },
  {
    version: "0.61.0",
    date: "11 May 2026",
    changed: [
      "Removed leftover placeholder flavour text from the production UI — the 'The Dressing Room · Live' chip in the landing topbar and chat topbar, plus the 'Fanzine · Issue 27' hero sticker. These were holdovers from the terrace-zine redesign that meant nothing to real users.",
    ],
  },
  {
    version: "0.60.0",
    date: "11 May 2026",
    changed: [
      "CLAUDE.md cleanup — removed stale _CURRENT_SEASON note (constant deleted in v0.52.0; FPL tools derive the season from live bootstrap), corrected tool count from 17 to 15, and fixed search_player reference to search_players_by_criteria.",
    ],
  },
  {
    version: "0.59.0",
    date: "11 May 2026",
    changed: [
      "Landing page STARTING XI team sheet now fields all 11 players (was 7) in a realistic 4-3-3: Flekken; Alexander-Arnold, Saliba, Van Dijk, Pedro Porro; Salah, Palmer, Saka; Haaland, Isak, Watkins.",
    ],
  },
  {
    version: "0.58.0",
    date: "11 May 2026",
    changed: [
      "Player vs opponent history now shows which season each game was from — previously Claude only saw a GW number with no year attached. Results are also ordered correctly across seasons (newest first), so GW1 2025/26 ranks above GW38 2022/23.",
    ],
  },
  {
    version: "0.57.0",
    date: "11 May 2026",
    changed: [
      "Fixture difficulty (FDR) corruption fixed — the ETL was storing each fixture's home- and away-team difficulty ratings swapped, so xPts clean-sheet calculations used the opponent's FDR instead of the player's own team's FDR. Player projections (esp. defenders/keepers) will now reflect the correct fixture difficulty.",
    ],
  },
  {
    version: "0.56.0",
    date: "11 May 2026",
    changed: [
      "Feature mockup copy updated — all 5 landing page chat examples now match real Gaffer output style: bold VERDICT, DATA bullets with realistic numbers, then REASONING. Odds, API-Sports references, and fabricated injury quotes removed.",
    ],
  },
  {
    version: "0.55.0",
    date: "11 May 2026",
    changed: [
      "Latent ETL crash fixed — pipeline/etl_v2.py imported `datetime` as the class but the season-year fallback called `datetime.now(datetime.UTC)`. `UTC` is a module-level constant, not a class attribute, so the fallback path raised AttributeError. Import UTC directly and pass it to datetime.now().",
    ],
  },
  {
    version: "0.54.0",
    date: "11 May 2026",
    changed: [
      "Landing page press source attribution corrected — the press feature card credited BBC Sport and Sky Sports, but both have been retired in favour of The Guardian's Premier League coverage.",
    ],
  },
  {
    version: "0.53.0",
    date: "11 May 2026",
    changed: [
      "'team_id' KeyError fixed — tool dispatch in main.py still referenced team_id/team1_id/team2_id and the removed search_team/get_odds handlers after the v0.52.0 API-Sports removal. Updated to team_name/team1_name/team2_name to match the new FPL-based function signatures.",
    ],
  },
  {
    version: "0.52.0",
    date: "11 May 2026",
    changed: [
      "API-Sports dependency removed — fixtures, standings, recent results, and head-to-head now use the FPL API directly. Standings are computed from completed fixture results. search_team and get_odds removed; team-based tools now take team names instead of numeric IDs. API_SPORTS_KEY is no longer required.",
    ],
  },
  {
    version: "0.51.0",
    date: "11 May 2026",
    changed: [
      "CD pipeline now force-reinstalls sports-context-mcp on every deploy — pip was silently keeping the old version because git-sourced packages appear satisfied even when the upstream repo changes, causing 502s after MCP updates.",
    ],
  },
  {
    version: "0.50.0",
    date: "11 May 2026",
    changed: [
      "Terrace zine UI redesign — complete visual overhaul to a bold fanzine aesthetic: Anton headlines, cream halftone background, hard offset box-shadows, ink-black sidebar with gold accents, stat strip on landing, and rotated sticker chips throughout. Chat page gains a gold top bar, Anton empty-state headline, and a Send ⚽ composer.",
    ],
  },
  {
    version: "0.49.0",
    date: "11 May 2026",
    changed: [
      "Historical stats and injury news now served via MCP — The Gaffer connects to the sports-context-mcp server over stdio at startup. Claude calls query_historical_stats for SQL queries and query_press_conferences for injury news instead of an always-on Pinecone pre-fetch, reducing unnecessary token usage on every request.",
    ],
  },
  {
    version: "0.48.0",
    date: "11 May 2026",
    changed: [
      "Press ingestion upgraded — now pulls full article body from The Guardian content API (not just RSS summaries), giving richer injury and team news context when you ask about players.",
    ],
  },
  {
    version: "0.47.0",
    date: "11 May 2026",
    changed: [
      "MCP server extracted — press conference queries, historical stats queries, and ingestion jobs now live in the standalone sports-context-mcp package, keeping the Gaffer focused on the web app",
    ],
  },
  {
    version: "0.46.0",
    date: "2 May 2026",
    changed: [
      "Sky Sports RSS replaced with The Guardian PL feed — Sky Sports articles had empty descriptions (paywall), so 0 articles were being ingested. The Guardian provides full PL match reports, injury news, and press conference summaries.",
    ],
  },
  {
    version: "0.45.0",
    date: "1 May 2026",
    changed: [
      "Pinecone quota fix — player news vectors now use a stable per-player ID so each ingest run overwrites in place instead of accumulating a new vector per status update",
      "Stale press article cleanup — articles older than 14 days are deleted from Pinecone after each ingest run, preventing unbounded storage growth",
    ],
  },
  {
    version: "0.44.0",
    date: "29 Apr 2026",
    added: [
      "Expected Points (xPts) — transfer targets, captain picks, and start/bench decisions now show projected FPL points with a full breakdown: goals, assists, clean sheet probability, bonus, and saves. DGW players automatically score both fixtures.",
    ],
  },
  {
    version: "0.43.0",
    date: "28 Apr 2026",
    changed: [
      "Cache hit % fixed — was showing over 100% because the denominator excluded cached tokens; now correctly shows the proportion of total tokens served from cache",
    ],
  },
  {
    version: "0.42.0",
    date: "28 Apr 2026",
    changed: [
      "Fixture hallucinations fixed — Claude must now only cite opponents and home/away status from live tool data, never from memory",
      "Defender double-up guard — transfer suggestions no longer recommend a defender or keeper from the same mid/lower-table club you already have covered",
    ],
  },
  {
    version: "0.41.0",
    date: "28 Apr 2026",
    changed: [
      "Removed X-Ray tracing — it had no daemon running and was flooding logs with noise; CloudWatch structured logging covers everything it did",
      "Fewer tool calls on transfer and chip queries — Claude no longer looks up team names it already knows, and batches form checks for all candidates in one go",
    ],
  },
  {
    version: "0.40.0",
    date: "28 Apr 2026",
    changed: [
      "Cleaner server logs — removed X-Ray HTTP patching that was flooding logs with noise, making the admin dashboard metrics unreliable",
    ],
  },
  {
    version: "0.39.0",
    date: "27 Apr 2026",
    changed: [
      "Free Hit transfer advice — when Free Hit is active, The Gaffer now fetches your original squad (from the previous gameweek) so transfer suggestions are against the squad that comes back, not the temporary Free Hit one",
    ],
  },
  {
    version: "0.38.0",
    date: "23 Apr 2026",
    added: [
      "Admin dashboard at /admin — password-protected metrics page showing requests, errors, latency, token usage, cache hit rate, thumbs-down count, and missing photos over 1h/24h/7d windows",
    ],
  },
  {
    version: "0.37.0",
    date: "25 Apr 2026",
    changed: [
      "Player photo fallback — players without a photo now show their initial in a gold avatar instead of a broken/missing image",
    ],
  },
  {
    version: "0.36.0",
    date: "25 Apr 2026",
    added: [
      "Thumbs-down button on every answer — click 👎 to flag a wrong or unhelpful response, describe what went wrong, and submit directly from the chat",
    ],
  },
  {
    version: "0.35.0",
    date: "25 Apr 2026",
    changed: [
      "Token usage logging — every request now logs input/output tokens and cache hits to CloudWatch so API costs are visible per request",
      "Tool-loop turn limit — Claude is now capped at 5 tool-use rounds per request; prevents unbounded API calls if the model gets stuck",
    ],
  },
  {
    version: "0.34.0",
    date: "23 Apr 2026",
    added: [
      "Captain suggester — 'Who should I captain?' now fetches all candidates in one shot instead of querying each player separately",
    ],
  },
  {
    version: "0.33.0",
    date: "23 Apr 2026",
    added: [
      "Mini-league standings — ask 'show me my mini-league' and The Gaffer fetches your standings automatically",
    ],
  },
  {
    version: "0.32.0",
    date: "23 Apr 2026",
    changed: [
      "Faster SQL queries — database now uses a persistent connection pool instead of opening a new connection on every tool call",
    ],
  },
  {
    version: "0.31.0",
    date: "23 Apr 2026",
    changed: [
      "Press ingest fixed — RSS articles were silently filtered as 999 days old due to a Python datetime bug; injury news and manager quotes now flow correctly",
      "Pinecone token usage cut — ingest now skips re-embedding player news that hasn't changed since last run",
    ],
  },
  {
    version: "0.30.0",
    date: "23 Apr 2026",
    changed: [
      "Fixed false blank gameweek reports — Claude now must verify every team flagged as blank via get_team_all_fixtures before reporting it (FPL API holds rearranged fixtures at event=null)",
    ],
  },
  {
    version: "0.29.0",
    date: "23 Apr 2026",
    changed: [
      "Auto-merge now blocked when any CI check is failing — previously a failing UI build was silently ignored",
    ],
  },
  {
    version: "0.28.0",
    date: "22 Apr 2026",
    changed: [
      "Player chips now render inline — photo, team, position, price, form, points, ownership visible directly in the answer",
      "Injury badges on player chips — shows Injured / 75% / Doubt / Susp when relevant",
      "Player card stats now labelled — Form 5.0 · 199 pts · 45.8% owned instead of bare numbers",
    ],
  },
  {
    version: "0.27.0",
    date: "22 Apr 2026",
    changed: [
      "Gameweek schedule now includes fixture difficulty (1–5) for each match — Claude can assess fixture runs without an extra tool call",
      "Fixed false blank gameweek flags for unscheduled future GWs — only genuine blanks are reported now",
    ],
  },
  {
    version: "0.26.0",
    date: "21 Apr 2026",
    changed: [
      "Transfer suggestions now rank by form — in-form players surface first instead of season-long accumulators",
      "Defender/keeper search now includes clean sheets, bonus, and saves so Claude has full scoring context",
    ],
  },
  {
    version: "0.25.0",
    date: "21 Apr 2026",
    changed: [
      "Player stats now use PostgreSQL — accurate season aggregates (points, xG, ownership, form) instead of API-Sports raw data",
      "Bootstrap cache now reused across squad/chip tools — saves 2 redundant API calls per request",
      "Removed search_player tool — get_player_stats now takes a player name directly",
    ],
  },
  {
    version: "0.24.0",
    date: "21 Apr 2026",
    changed: [
      "Player vs opponent stats now use PostgreSQL — exact FPL points, CS, bonus, xG per fixture (was API-Sports raw stats, same hallucination risk as v0.23.0 fix)",
    ],
  },
  {
    version: "0.23.0",
    date: "21 Apr 2026",
    changed: [
      "Player form data now uses FPL API directly — exact GW points, CS, bonus, minutes, and opponents (was using API-Sports which has no FPL data, causing Claude to hallucinate the table values)",
    ],
  },
  {
    version: "0.22.0",
    date: "21 Apr 2026",
    changed: [
      "CD now fires after auto-merged PRs — GitHub suppresses ALL triggers from GITHUB_TOKEN merges; fixed by using a PAT (GH_PAT secret) for the auto-merge call so the push is attributed to a real user",
    ],
  },
  {
    version: "0.21.0",
    date: "21 Apr 2026",
    changed: [
      "CD trigger switched to pull_request:closed + workflow_dispatch (reverted in v0.22.0)",
    ],
  },
  {
    version: "0.20.0",
    date: "21 Apr 2026",
    changed: [
      "V1 removed — V2 (PostgreSQL + live tools + press RAG) is the only version",
      "Faster tool calls — shared HTTP connection pool reused across all concurrent tool calls",
      "Free-Hit and Wildcard squads now always return exactly 2 GKP, 5 DEF, 5 MID, 3 FWD",
      "ETL data freshness — GW stats now update hourly (was silently broken since launch)",
    ],
  },
  {
    version: "0.9.0",
    date: "12 Apr 2026",
    added: [
      "New gold shield logo and amber/gold accent colour throughout the UI",
      "Global left nav with scrollspy — jump to any section from the landing page",
      "Feature panels with live chat mockups showing real example responses",
      "Press conference feature — injury news and manager quotes before you ask",
      "Contact form — get in touch directly from the landing page",
    ],
    changed: [
      "Landing page redesigned with langchain-style feature navigation",
    ],
  },
  {
    version: "0.8.0",
    date: "11 Apr 2026",
    added: [
      "Landing page — new home at the-gaffer.io with features, examples, and onboarding",
      "Dedicated /chat route — landing always at /, chat always at /chat",
      "Press RAG — BBC Sport and Sky Sports articles plus FPL injury updates ingested twice daily",
      "Returning user detection — 'Continue →' skips onboarding if you've chatted before",
    ],
    changed: [
      "V2 (text-to-SQL) is now the default for all users — V1 still available via toggle",
    ],
  },
  {
    version: "0.7.0",
    date: "10 Apr 2026",
    added: [
      "V2 engine — natural language → SQL against a live PostgreSQL database",
      "3 seasons of historical stats (2022–2025) — goals, assists, xG, minutes, clean sheets per GW",
      "Head-to-head player comparisons backed by real match data",
      "Double gameweek detection using live fixture data",
      "Bookmaker odds integration — match winner, BTTS, over 2.5 goals",
    ],
    changed: [
      "Answers are faster and more precise — SQL returns exact numbers, not embeddings",
    ],
  },
  {
    version: "0.6.0",
    date: "9 Apr 2026",
    changed: [
      "Conversation memory — The Gaffer now remembers everything said earlier in the chat",
      "Longer responses — answers no longer cut off mid-sentence",
      "Streaming reliability — tool calls now timeout gracefully instead of hanging",
    ],
  },
  {
    version: "0.5.0",
    date: "9 Apr 2026",
    added: [
      "Chip Advisor — ask when to play your Bench Boost, Triple Captain, Free Hit, or Wildcard",
      "Double & blank gameweek detection — The Gaffer knows which GWs have DGWs and BGWs",
      "Player name tooltips — hover any player name to see team, position, and price",
    ],
    changed: ["Player search now covers all 825 FPL players (up from 400)"],
  },
  {
    version: "0.4.0",
    date: "7 Apr 2026",
    added: [
      "CloudWatch observability — every request and tool call is logged with latency",
      "EC2 User Data bootstrap — new instances configure themselves automatically",
      "Changelog — you're looking at it",
    ],
  },
  {
    version: "0.3.0",
    date: "6 Apr 2026",
    added: [
      "Live status during thinking — see what The Gaffer is doing while it works",
      "Bug report emails via Resend — reports now land reliably",
      "AWS Secrets Manager — secrets managed centrally, no manual server edits",
      "Daily RAG re-ingestion — player data refreshes every night at midnight UTC",
    ],
    changed: ["Removed SES; switched to Resend for email"],
  },
  {
    version: "0.2.0",
    date: "5 Apr 2026",
    added: [
      "SSE streaming — answers appear word by word in real time",
      "RAG pipeline — 1,129 FPL documents in Pinecone for historical context",
      "EC2 hosting at the-gaffer.io with HTTPS via Let's Encrypt",
      "Auto-deploy on merge to main via GitHub Actions",
      "FPL Team ID input with setup instructions",
      "Bug report form",
    ],
  },
  {
    version: "0.1.0",
    date: "5 Apr 2026",
    added: [
      "12 live FPL tools — squad, player stats, form, fixtures, standings, h2h, odds",
      "Claude tool-use loop with parallel execution",
      "React chat UI with session history",
      "Pinecone RAG for top 400 FPL players",
      "Verdict → Data → Reasoning answer structure",
    ],
  },
];

export default function ChangelogModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal changelog-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>What's new</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="changelog-body">
          {RELEASES.map((r) => (
            <div key={r.version} className="changelog-release">
              <div className="changelog-release-header">
                <span className="changelog-version">v{r.version}</span>
                <span className="changelog-date">{r.date}</span>
              </div>
              {r.added && (
                <ul className="changelog-list">
                  {r.added.map((item) => (
                    <li key={item}>
                      <span className="changelog-tag added">Added</span>
                      {item}
                    </li>
                  ))}
                </ul>
              )}
              {r.changed && (
                <ul className="changelog-list">
                  {r.changed.map((item) => (
                    <li key={item}>
                      <span className="changelog-tag changed">Changed</span>
                      {item}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
