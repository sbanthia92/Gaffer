import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ChangelogModal from "./ChangelogModal";
import { loadSessions } from "./storage";
import { submitContact } from "./api";
import "./Landing.css";

const FPL_TEAM_ID_KEY = "gaffer_fpl_team_id";

function loadFplTeamId(): number | null {
  const raw = localStorage.getItem(FPL_TEAM_ID_KEY);
  const n = raw ? parseInt(raw, 10) : NaN;
  return isNaN(n) ? null : n;
}

function saveFplTeamId(id: number): void {
  localStorage.setItem(FPL_TEAM_ID_KEY, String(id));
}

const FEATURES = [
  {
    id: "live-data",
    icon: "⚡",
    title: "Live data",
    desc: "Real-time fixtures, standings, player stats, and bookmaker odds pulled directly from API-Sports. Every answer is backed by data from the current gameweek.",
    chat: [
      { role: "user", text: "What are the odds for Arsenal this weekend?" },
      { role: "assistant", text: "Arsenal vs Chelsea — Arsenal are 1.72 to win, Draw 3.80, Chelsea 4.50. BTTS is priced at 1.95 and Over 2.5 goals at 1.80. Arsenal have won their last 4 at home." },
    ],
  },
  {
    id: "ai-powered",
    icon: "🧠",
    title: "AI-powered",
    desc: "Claude analyses your squad and delivers a clear VERDICT with full reasoning — not just data dumps. It thinks like an FPL manager, not a search engine.",
    chat: [
      { role: "user", text: "Should I captain Salah or Haaland this GW?" },
      { role: "assistant", text: "VERDICT: Captain Salah.\n\nSalah has 3 goals + 2 assists in his last 5. Haaland is coming off a blank and faces a top-6 side. Salah's fixture is a home game vs 18th-placed Sheffield." },
    ],
  },
  {
    id: "your-squad",
    icon: "👥",
    title: "Your squad",
    desc: "Enter your FPL Team ID and get personalised advice — transfer suggestions, captain picks, and chip strategy tailored to your actual 15 players.",
    chat: [
      { role: "user", text: "Who should I transfer in with my 2 free transfers?" },
      { role: "assistant", text: "Based on your squad, I'd bring in Palmer (£5.6m, 3 double GWs) and Alexander-Arnold (£7.2m, easiest fixtures in GW32–35). This removes your weak midfield coverage." },
    ],
  },
  {
    id: "historical",
    icon: "📈",
    title: "Historical context",
    desc: "3 seasons of match-by-match stats in a live database — goals, assists, xG, minutes, clean sheets. Ask head-to-head comparisons or long-run form questions.",
    chat: [
      { role: "user", text: "How has Salah performed against Arsenal historically?" },
      { role: "assistant", text: "Across 8 appearances vs Arsenal (2022–2025): 4 goals, 3 assists, avg 8.1 FPL points. He blanked once in that run. Strong record — above his season average." },
    ],
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

function ChatMockup({ messages }: { messages: { role: string; text: string }[] }) {
  return (
    <div className="feature-chat-mockup">
      {messages.map((m, i) => (
        <div key={i} className={`mockup-msg mockup-msg--${m.role}`}>
          {m.role === "assistant" && <div className="mockup-label">The Gaffer</div>}
          <div className={`mockup-bubble mockup-bubble--${m.role}`}>{m.text}</div>
        </div>
      ))}
    </div>
  );
}

function ContactSection() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !email.trim() || !message.trim()) {
      setErr("Please fill in all fields.");
      return;
    }
    setSending(true);
    setErr("");
    try {
      await submitContact(name.trim(), email.trim(), message.trim());
      setSent(true);
    } catch {
      setErr("Failed to send — please try again.");
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="landing-contact" id="contact">
      <h2>Get in touch</h2>
      <p className="landing-contact-sub">Questions, feedback, or partnership enquiries — we'd love to hear from you.</p>
      {sent ? (
        <div className="contact-success">Message sent! We'll get back to you soon.</div>
      ) : (
        <form className="contact-form" onSubmit={handleSubmit}>
          <div className="contact-row">
            <input
              className="contact-input"
              type="text"
              placeholder="Your name"
              value={name}
              onChange={(e) => { setName(e.target.value); setErr(""); }}
            />
            <input
              className="contact-input"
              type="email"
              placeholder="Your email"
              value={email}
              onChange={(e) => { setEmail(e.target.value); setErr(""); }}
            />
          </div>
          <textarea
            className="contact-textarea"
            placeholder="Your message"
            rows={4}
            value={message}
            onChange={(e) => { setMessage(e.target.value); setErr(""); }}
          />
          {err && <p className="contact-error">{err}</p>}
          <button className="landing-cta contact-submit" type="submit" disabled={sending}>
            {sending ? "Sending…" : "Send message →"}
          </button>
        </form>
      )}
    </section>
  );
}

export default function Landing() {
  const navigate = useNavigate();
  const isReturning = loadSessions().length > 0 || loadFplTeamId() !== null;

  const [showChangelog, setShowChangelog] = useState(false);
  const [showFplStep, setShowFplStep] = useState(false);
  const [fplValue, setFplValue] = useState("");
  const [err, setErr] = useState("");
  const [activeFeature, setActiveFeature] = useState(FEATURES[0].id);

  const featureRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveFeature(entry.target.id);
          }
        }
      },
      { rootMargin: "-40% 0px -50% 0px" }
    );
    for (const el of Object.values(featureRefs.current)) {
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  function scrollToFeature(id: string) {
    featureRefs.current[id]?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function handleSave() {
    const n = parseInt(fplValue.trim(), 10);
    if (isNaN(n) || n <= 0) {
      setErr("Please enter a valid numeric Team ID.");
      return;
    }
    saveFplTeamId(n);
    navigate("/chat");
  }

  if (showFplStep) {
    return (
      <div className="landing">
        <header className="landing-header">
          <button className="landing-logo-btn" onClick={() => setShowFplStep(false)}>
            <img src="/logo.png" alt="The Gaffer" className="landing-logo-img" />
          </button>
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
            <button
              className="landing-fpl-skip"
              onClick={() => navigate("/chat")}
            >
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
      {showChangelog && (
        <ChangelogModal onClose={() => setShowChangelog(false)} />
      )}
      <header className="landing-header">
        <button className="landing-logo-btn" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>
          <img src="/logo.png" alt="The Gaffer" className="landing-logo-img" />
        </button>
        {isReturning && (
          <button
            className="landing-continue-btn"
            onClick={() => navigate("/chat")}
          >
            Continue →
          </button>
        )}
      </header>

      <section className="landing-hero">
        <div className="landing-hero-glow">
          <img src="/logo.png" alt="The Gaffer" className="landing-hero-logo" />
        </div>
        <h1 className="landing-title">
          Your AI-powered
          <br />
          <span className="landing-title-accent">FPL analyst</span>
        </h1>
        <p className="landing-sub">
          Ask The Gaffer anything about your Fantasy Premier League squad. Get a
          clear verdict backed by live data, stats, and AI reasoning.
        </p>
        {isReturning ? (
          <div className="landing-hero-actions">
            <button className="landing-cta" onClick={() => navigate("/chat")}>
              Continue →
            </button>
            <button
              className="landing-cta-secondary"
              onClick={() => setShowFplStep(true)}
            >
              Start fresh
            </button>
          </div>
        ) : (
          <button
            className="landing-cta"
            onClick={() => setShowFplStep(true)}
          >
            Start asking →
          </button>
        )}
      </section>

      {/* Langchain-style features section */}
      <section className="landing-features-v2">
        <div className="features-sidebar">
          <p className="features-sidebar-label">Features</p>
          {FEATURES.map((f) => (
            <button
              key={f.id}
              className={`features-nav-item ${activeFeature === f.id ? "active" : ""}`}
              onClick={() => scrollToFeature(f.id)}
            >
              <span className="features-nav-icon">{f.icon}</span>
              {f.title}
            </button>
          ))}
        </div>
        <div className="features-panels">
          {FEATURES.map((f) => (
            <div
              key={f.id}
              id={f.id}
              ref={(el) => { featureRefs.current[f.id] = el; }}
              className="feature-panel"
            >
              <div className="feature-panel-text">
                <span className="feature-panel-icon">{f.icon}</span>
                <h3>{f.title}</h3>
                <p>{f.desc}</p>
              </div>
              <ChatMockup messages={f.chat} />
            </div>
          ))}
        </div>
      </section>

      <section className="landing-examples">
        <h2>What can you ask?</h2>
        <div className="example-list">
          {EXAMPLES.map((q) => (
            <button
              key={q}
              className="example-item"
              onClick={() => navigate(`/chat?q=${encodeURIComponent(q)}`)}
            >
              <span className="example-quote">&ldquo;</span>
              <span className="example-text">{q}</span>
              <span className="example-quote">&rdquo;</span>
              <span className="example-arrow">→</span>
            </button>
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

      <ContactSection />

      <footer className="landing-footer">
        <p>Built for FPL managers who want an edge.</p>
        <button
          className="landing-cta landing-cta-sm"
          onClick={() =>
            isReturning ? navigate("/chat") : setShowFplStep(true)
          }
        >
          {isReturning ? "Continue →" : "Start for free →"}
        </button>
        <button
          className="landing-changelog-btn"
          onClick={() => setShowChangelog(true)}
        >
          What's new in v0.8.0 →
        </button>
      </footer>
    </div>
  );
}
