import { useState } from "react";
import ChangelogModal from "./ChangelogModal";
import "./Landing.css";

interface Props {
  onStart: (fplTeamId?: number) => void;
}

const FEATURES = [
  {
    icon: "⚡",
    title: "Live data",
    desc: "Real-time fixtures, standings, player stats, and bookmaker odds via API-Sports.",
  },
  {
    icon: "🧠",
    title: "AI-powered",
    desc: "Claude analyses your squad and gives a clear VERDICT with full reasoning.",
  },
  {
    icon: "👥",
    title: "Your squad",
    desc: "Personalised advice based on your actual FPL team — not generic tips.",
  },
  {
    icon: "📈",
    title: "Historical context",
    desc: "Head-to-head records, seasonal form, and fixture difficulty all factored in.",
  },
];

const EXAMPLES = [
  "Should I captain Salah or Haaland this week?",
  "If I can make 2 free transfers, who should I bring in?",
  "I have my Bench Boost left — is this the right DGW to play it?",
  "What's a good differential pick under £7m right now?",
  "Which players under 10% ownership have 100+ points this season?",
  "Which midfielder has the most goal involvements against the top 6?",
  "Who are the most cost-effective midfielders under £7m by points per game?",
  "Preview Arsenal vs Chelsea this weekend",
];

export default function Landing({ onStart }: Props) {
  const [showChangelog, setShowChangelog] = useState(false);
  const [showFplStep, setShowFplStep] = useState(false);
  const [fplValue, setFplValue] = useState("");
  const [err, setErr] = useState("");

  function handleCta() {
    setShowFplStep(true);
  }

  function handleSave() {
    const n = parseInt(fplValue.trim(), 10);
    if (isNaN(n) || n <= 0) {
      setErr("Please enter a valid numeric Team ID.");
      return;
    }
    onStart(n);
  }

  function handleSkip() {
    onStart(undefined);
  }

  if (showFplStep) {
    return (
      <div className="landing">
        <header className="landing-header">
          <span className="landing-logo">📋 the-gaffer.io</span>
        </header>
        <section className="landing-fpl-step">
          <h1 className="landing-fpl-title">Enter your FPL Team ID</h1>
          <p className="landing-fpl-sub">
            This lets The Gaffer give you personalised squad advice, transfer
            suggestions, and captain picks based on your actual team.
          </p>
          <div className="landing-fpl-how">
            <p className="landing-fpl-how-title">How to find your Team ID:</p>
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
            className="landing-fpl-input"
            type="number"
            placeholder="e.g. 5402482"
            value={fplValue}
            onChange={(e) => {
              setFplValue(e.target.value);
              setErr("");
            }}
            onKeyDown={(e) => e.key === "Enter" && handleSave()}
            autoFocus
          />
          {err && <p className="landing-fpl-error">{err}</p>}
          <div className="landing-fpl-actions">
            <button className="landing-fpl-skip" onClick={handleSkip}>
              Skip for now
            </button>
            <button className="landing-cta" onClick={handleSave}>
              Start asking →
            </button>
          </div>
          <p className="landing-fpl-note">
            You can add or update your Team ID anytime from the sidebar.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="landing">
      {showChangelog && <ChangelogModal onClose={() => setShowChangelog(false)} />}
      <header className="landing-header">
        <span className="landing-logo">📋 the-gaffer.io</span>
      </header>

      <section className="landing-hero">
        <h1 className="landing-title">
          Your AI-powered
          <br />
          FPL analyst
        </h1>
        <p className="landing-sub">
          Ask The Gaffer anything about your Fantasy Premier League squad.
          Get a clear verdict backed by live data, stats, and AI reasoning.
        </p>
        <button className="landing-cta" onClick={handleCta}>
          Start asking →
        </button>
      </section>

      <section className="landing-features">
        {FEATURES.map((f) => (
          <div key={f.title} className="feature-card">
            <span className="feature-icon">{f.icon}</span>
            <h3>{f.title}</h3>
            <p>{f.desc}</p>
          </div>
        ))}
      </section>

      <section className="landing-examples">
        <h2>What can you ask?</h2>
        <div className="example-list">
          {EXAMPLES.map((q) => (
            <div key={q} className="example-item">
              <span className="example-quote">"</span>
              {q}
              <span className="example-quote">"</span>
            </div>
          ))}
        </div>
      </section>

      <section className="landing-how">
        <h2>How it works</h2>
        <div className="steps">
          <div className="step">
            <div className="step-num">1</div>
            <div>
              <strong>Enter your FPL Team ID</strong>
              <p>Found in your team URL on the FPL website.</p>
            </div>
          </div>
          <div className="step">
            <div className="step-num">2</div>
            <div>
              <strong>Ask your question</strong>
              <p>Captain pick, transfers, differentials — anything FPL.</p>
            </div>
          </div>
          <div className="step">
            <div className="step-num">3</div>
            <div>
              <strong>Get a data-driven verdict</strong>
              <p>Live stats + AI reasoning in seconds.</p>
            </div>
          </div>
        </div>
      </section>

      <footer className="landing-footer">
        <p>Built for FPL managers who want an edge.</p>
        <button className="landing-cta landing-cta-sm" onClick={handleCta}>
          Start for free →
        </button>
        <button className="landing-changelog-btn" onClick={() => setShowChangelog(true)}>
          What's new in v0.8.0 →
        </button>
      </footer>
    </div>
  );
}
