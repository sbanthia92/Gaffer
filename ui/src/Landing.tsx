import { useState } from "react";
import ChangelogModal from "./ChangelogModal";
import "./Landing.css";

interface Props {
  onStart: () => void;
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
    icon: "📋",
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
  "Is it worth taking a hit for a premium midfielder?",
  "What's a good differential pick under £7m right now?",
];

export default function Landing({ onStart }: Props) {
  const [showChangelog, setShowChangelog] = useState(false);

  return (
    <div className="landing">
      {showChangelog && <ChangelogModal onClose={() => setShowChangelog(false)} />}
      <header className="landing-header">
        <span className="landing-logo">⚽ gaffer.io</span>
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
        <button className="landing-cta" onClick={onStart}>
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
        <button className="landing-cta landing-cta-sm" onClick={onStart}>
          Start for free →
        </button>
        <button className="landing-changelog-btn" onClick={() => setShowChangelog(true)}>
          What's new in v0.4.0 →
        </button>
      </footer>
    </div>
  );
}
