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
    desc: "Real-time fixtures, standings, player stats, and bookmaker odds pulled directly from API-Sports. Every answer is backed by data from the current gameweek — never stale.",
    chat: [
      { role: "user", text: "Preview Arsenal vs Chelsea this weekend" },
      { role: "assistant", text: `**VERDICT: Lean Arsenal — but not a walkover.**\n\n**Odds:** Arsenal 1.72 · Draw 3.80 · Chelsea 4.50\n**BTTS:** 1.95 · **Over 2.5:** 1.80\n\n**Form:** Arsenal have won 4 of their last 5 at home, conceding just 2. Chelsea are unbeaten in 3 away but haven't faced a top-4 side in that run.\n\n**Key battle:** Saka vs. Cucurella. Saka has created 9 chances in his last 4 home games.`, truncated: true },
    ],
  },
  {
    id: "ai-powered",
    icon: "🧠",
    title: "AI-powered verdicts",
    desc: "Claude analyses your question, pulls the relevant data, and delivers a clear VERDICT with full reasoning — not just a data dump. It thinks like an experienced FPL manager.",
    chat: [
      { role: "user", text: "Should I captain Salah or Haaland this GW?" },
      { role: "assistant", text: `**VERDICT: Captain Salah ✅**\n\n**Salah (home vs Sheffield, 1.45 to score):**\n• 3 goals + 2 assists in last 5 GWs (avg 10.2 pts)\n• 8 attacking returns in 10 home games this season\n• Sheffield have conceded 2+ in 7 of last 9 away games\n\n**Haaland (away vs Man Utd, 1.90 to score):**\n• Blanked last 2 GWs · 1 goal in 5 vs top-6 this season\n• Man Utd have kept 3 clean sheets in last 5 at Old Trafford\n\nSalah's fixture, form, and floor are all superior this week.`, truncated: true },
    ],
  },
  {
    id: "your-squad",
    icon: "👥",
    title: "Your squad",
    desc: "Enter your FPL Team ID and get advice tailored to your actual 15 players — transfer targets, captain picks, and chip timing based on what you already own.",
    chat: [
      { role: "user", text: "Who should I bring in with my 2 free transfers?" },
      { role: "assistant", text: `**VERDICT: Palmer (MID) + Alexander-Arnold (DEF)**\n\n**Why Palmer (£5.6m):**\n• You have no Chelsea coverage and they have 3 of the next 4 at home\n• Palmer: 7 goals + 5 assists, 2nd highest xG among mids under £6m\n• Replaces your weakest midfielder by points-per-game\n\n**Why Alexander-Arnold (£7.2m):**\n• Liverpool's next 5 fixtures: avg difficulty 2.1/5\n• 8 assists this season · plays every minute\n\n**What to sell:** Trippier (injured, doubtful GW34+) and Andreas Pereira (3 blanks in a row).`, truncated: true },
    ],
  },
  {
    id: "historical",
    icon: "📈",
    title: "Historical context",
    desc: "3 seasons of match-by-match stats in a live database — goals, assists, xG, minutes, clean sheets per gameweek. Ask head-to-head comparisons or long-run form questions.",
    chat: [
      { role: "user", text: "How has Salah performed against Arsenal historically?" },
      { role: "assistant", text: `**8 appearances vs Arsenal (2022–2025)**\n\n| Season | Apps | Goals | Assists | Avg pts |\n|--------|------|-------|---------|--------|\n| 22/23 | 3 | 2 | 1 | 9.3 |\n| 23/24 | 3 | 1 | 2 | 7.7 |\n| 24/25 | 2 | 1 | 0 | 6.5 |\n\n**Overall:** 4 goals · 3 assists · 8.1 avg FPL pts · 1 blank\n\nSalah scores above his season average (7.4) against Arsenal. Home fixtures vs Arsenal have returned 10.5 avg pts.`, truncated: true },
    ],
  },
  {
    id: "press",
    icon: "📰",
    title: "Press conference context",
    desc: "BBC Sport and Sky Sports press conferences ingested twice daily — so The Gaffer knows about injury news, rotation risks, and manager comments before you do.",
    chat: [
      { role: "user", text: "Any injury or rotation concerns for Saka this week?" },
      { role: "assistant", text: `**VERDICT: No major concerns — but monitor.**\n\n**From Arteta's pre-match presser (Apr 11):**\n> "Bukayo trained fully today. We'll assess him tomorrow but I expect him to be available."\n\n**Context:**\n• Saka played 87 mins on Thursday in the Europa tie — slight fatigue risk\n• Arsenal have 3 games in 8 days after this weekend\n• Arteta has rotated Saka in the 3rd game of a triple-gameweek before\n\n**FPL take:** Still start him, but if you have a strong bench option, be ready to use it.`, truncated: true },
    ],
  },
];

const NAV_SECTIONS = [
  { id: "home", label: "Home" },
  {
    id: "features", label: "Features", children: FEATURES.map((f) => ({
      id: f.id, label: f.title, icon: f.icon,
    })),
  },
  { id: "how-it-works", label: "How it works" },
  { id: "contact", label: "Get in touch" },
];

function parseBold(line: string) {
  const parts = line.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, j) =>
    p.startsWith("**") && p.endsWith("**")
      ? <strong key={j}>{p.slice(2, -2)}</strong>
      : p
  );
}

function renderMockupText(text: string) {
  const lines = text.split("\n");
  const result: React.ReactNode[] = [];
  let tableLines: string[] = [];

  function flushTable() {
    if (tableLines.length === 0) return;
    const rows = tableLines.filter((l) => !l.replace(/[\s|:-]/g, "").length === false || l.includes("|"));
    const parsed = rows
      .filter((l) => !/^[\s|:-]+$/.test(l))
      .map((l) => l.split("|").filter((_, i, a) => i > 0 && i < a.length - 1).map((c) => c.trim()));
    if (parsed.length > 0) {
      result.push(
        <table key={result.length} className="mockup-table">
          <thead>
            <tr>{parsed[0].map((h, i) => <th key={i}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {parsed.slice(1).map((row, i) => (
              <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>
            ))}
          </tbody>
        </table>
      );
    }
    tableLines = [];
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith("|")) {
      tableLines.push(line);
    } else {
      flushTable();
      result.push(
        <div key={i} className="mockup-line">{parseBold(line)}</div>
      );
    }
  }
  flushTable();
  return result;
}

function ChatMockup({ messages }: { messages: { role: string; text: string; truncated?: boolean }[] }) {
  return (
    <div className="feature-chat-mockup">
      {messages.map((m, i) => (
        <div key={i} className={`mockup-msg mockup-msg--${m.role}`}>
          {m.role === "assistant" && <div className="mockup-label">The Gaffer · FPL</div>}
          <div className={`mockup-bubble mockup-bubble--${m.role}`}>
            {renderMockupText(m.text)}
            {m.truncated && <div className="mockup-truncated">↓ more detail below…</div>}
          </div>
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
  const [activeSection, setActiveSection] = useState("home");
  const [activeFeature, setActiveFeature] = useState(FEATURES[0].id);

  const sectionRefs = useRef<Record<string, HTMLElement | null>>({});
  const featureRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // Track top-level sections
  useEffect(() => {
    const ids = ["home", "features", "how-it-works", "contact"];
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActiveSection(entry.target.id);
        }
      },
      { rootMargin: "-30% 0px -60% 0px" }
    );
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  // Track feature sub-sections
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActiveFeature(entry.target.id);
        }
      },
      { rootMargin: "-35% 0px -55% 0px" }
    );
    for (const el of Object.values(featureRefs.current)) {
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  function scrollTo(id: string) {
    const el = featureRefs.current[id] ?? document.getElementById(id);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
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
                <a href="https://fantasy.premierleague.com/my-team" target="_blank" rel="noreferrer">
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
            onChange={(e) => { setFplValue(e.target.value); setErr(""); }}
            onKeyDown={(e) => e.key === "Enter" && handleSave()}
            autoFocus
          />
          {err && <p className="landing-fpl-error">{err}</p>}
          <div className="landing-fpl-actions">
            <button className="landing-fpl-skip" onClick={() => navigate("/chat")}>Skip for now</button>
            <button className="landing-cta" onClick={handleSave}>Start asking →</button>
          </div>
          <p className="landing-fpl-note">You can add or update your Team ID anytime from the sidebar.</p>
        </section>
      </div>
    );
  }

  return (
    <div className="landing">
      {showChangelog && <ChangelogModal onClose={() => setShowChangelog(false)} />}

      <header className="landing-header">
        <button className="landing-logo-btn" onClick={() => scrollTo("home")}>
          <img src="/logo.png" alt="The Gaffer" className="landing-logo-img" />
        </button>
        {isReturning && (
          <button className="landing-continue-btn" onClick={() => navigate("/chat")}>
            Continue →
          </button>
        )}
      </header>

      <div className="landing-body">
        {/* Global left nav */}
        <nav className="landing-nav">
          {NAV_SECTIONS.map((section) => (
            <div key={section.id} className="nav-section">
              <button
                className={`nav-item nav-item--top ${activeSection === section.id || (section.id === "features" && activeSection === "features") ? "active" : ""}`}
                onClick={() => scrollTo(section.id === "features" ? FEATURES[0].id : section.id)}
              >
                {section.label}
              </button>
              {section.children && (
                <div className="nav-children visible">
                  {section.children.map((child) => (
                    <button
                      key={child.id}
                      className={`nav-item nav-item--child ${activeFeature === child.id ? "active" : ""}`}
                      onClick={() => scrollTo(child.id)}
                    >
                      <span className="nav-child-icon">{child.icon}</span>
                      {child.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </nav>

        {/* Main scrollable content */}
        <main className="landing-main">
          <section id="home" ref={(el) => { sectionRefs.current["home"] = el; }} className="landing-hero">
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
                <button className="landing-cta" onClick={() => navigate("/chat")}>Continue →</button>
                <button className="landing-cta-secondary" onClick={() => setShowFplStep(true)}>Start fresh</button>
              </div>
            ) : (
              <button className="landing-cta" onClick={() => setShowFplStep(true)}>Start asking →</button>
            )}
          </section>

          <section id="features" ref={(el) => { sectionRefs.current["features"] = el; }} className="landing-features-v2">
            <div className="features-panels">
              {FEATURES.map((f) => (
                <div
                  key={f.id}
                  id={f.id}
                  ref={(el) => { featureRefs.current[f.id] = el; }}
                  className="feature-panel"
                >
                  <div className="feature-panel-text">
                    <div className="feature-panel-heading">
                      <span className="feature-panel-icon">{f.icon}</span>
                      <h3>{f.title}</h3>
                    </div>
                    <p>{f.desc}</p>
                  </div>
                  <ChatMockup messages={f.chat} />
                </div>
              ))}
            </div>
          </section>

          <section id="how-it-works" ref={(el) => { sectionRefs.current["how-it-works"] = el; }} className="landing-how">
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
              onClick={() => isReturning ? navigate("/chat") : setShowFplStep(true)}
            >
              {isReturning ? "Continue →" : "Start for free →"}
            </button>
            <button className="landing-changelog-btn" onClick={() => setShowChangelog(true)}>
              What's new in v0.9.0 →
            </button>
          </footer>
        </main>
      </div>
    </div>
  );
}
