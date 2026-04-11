import "./ChangelogModal.css";

interface Release {
  version: string;
  date: string;
  added?: string[];
  changed?: string[];
}

const RELEASES: Release[] = [
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
