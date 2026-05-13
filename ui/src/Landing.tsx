import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ChangelogModal, { RELEASES } from "./ChangelogModal";
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
    desc: "Real-time fixtures, standings, player prices, ownership, and form pulled from the FPL API. Every answer is backed by data from the current gameweek — never stale.",
    chat: [
      { role: "user", text: "Preview Arsenal vs Chelsea this weekend" },
      { role: "assistant", text: `**VERDICT: Lean Arsenal at home.**\n\n**DATA:**\n• Arsenal home form (last 5): W4 D1 L0, 12 GF / 3 GA\n• Chelsea away form (last 5): W2 D2 L1, conceding 1.4/game\n• Fixture FDR: ARS 2 vs CHE 4\n• xG over last 5: Arsenal 10.2 for / 4.1 against\n\n**REASONING:** Arsenal's home record and underlying numbers outweigh Chelsea's softer away xG profile. Saka and Saliba both nailed for 90.`, truncated: true },
    ],
  },
  {
    id: "ai-powered",
    icon: "🧠",
    title: "AI-powered verdicts",
    desc: "Claude analyses your question, pulls the relevant data, and delivers a clear VERDICT with full reasoning — not just a data dump. It thinks like an experienced FPL manager.",
    chat: [
      { role: "user", text: "Should I captain Salah or Haaland this GW?" },
      { role: "assistant", text: `**VERDICT: Captain Salah.**\n\n**DATA:**\n• Salah: 87 season pts · last 5 GWs avg 7.4 · xGI 1.3/game\n• Haaland: 79 season pts · last 5 GWs avg 5.8 · xGI 1.0/game\n• Salah fixture: LIV (H) vs Sheffield Utd — FDR 2\n• Haaland fixture: MCI (A) vs Man Utd — FDR 4\n\n**REASONING:** Salah's form, xGI, and a soft home fixture outweigh Haaland's tougher derby trip. Higher floor and ceiling this week.`, truncated: true },
    ],
  },
  {
    id: "your-squad",
    icon: "👥",
    title: "Your squad",
    desc: "Enter your FPL Team ID and get advice tailored to your actual 15 players — transfer targets, captain picks, and chip timing based on what you already own.",
    chat: [
      { role: "user", text: "Who should I bring in with my 2 free transfers?" },
      { role: "assistant", text: `**VERDICT: Palmer (MID) + Gabriel (DEF).**\n\n**DATA:**\n• Palmer £6.0m · 142 pts · last 5 avg 7.8 · xGI 1.4/game\n• Gabriel £6.2m · 118 pts · 11 CS · 4 attacking returns\n• Your weakest MID by PPG: 3.2 — like-for-like swap\n• Next 5 FDR: Chelsea 2.4, Arsenal 2.0\n\n**REASONING:** Both upgrades hold price value and improve your fixture run through GW38. Captaincy options expand too.`, truncated: true },
    ],
  },
  {
    id: "historical",
    icon: "📈",
    title: "Historical context",
    desc: "3 seasons of match-by-match stats in a live database — goals, assists, xG, minutes, clean sheets per gameweek. Ask head-to-head comparisons or long-run form questions.",
    chat: [
      { role: "user", text: "How has Salah performed against Arsenal historically?" },
      { role: "assistant", text: `**Salah vs Arsenal — last 3 seasons (8 apps):**\n\n**DATA:**\n• 22/23: 3 apps · 2G 1A · 9.3 avg pts\n• 23/24: 3 apps · 1G 2A · 7.7 avg pts\n• 24/25: 2 apps · 1G 0A · 6.5 avg pts\n• Overall: 4G · 3A · 8.1 avg FPL pts\n• Home vs Arsenal: 10.5 avg · Away: 5.7 avg\n\n**REASONING:** Above his career average (7.4) against Arsenal, with home fixtures the standout split.`, truncated: true },
    ],
  },
  {
    id: "press",
    icon: "📰",
    title: "Press conference context",
    desc: "The Guardian's Premier League coverage and FPL bootstrap player news ingested twice daily — so The Gaffer flags injury status, doubts, and rotation hints from official sources.",
    chat: [
      { role: "user", text: "Any injury or rotation concerns for Saka this week?" },
      { role: "assistant", text: `**VERDICT: No flagged injury — monitor minutes.**\n\n**DATA:**\n• FPL bootstrap status: 100% (no news)\n• Saka minutes last 4 GWs: 90, 87, 90, 90\n• Arsenal fixture density: 3 games in 8 days post-weekend\n• No injury mention in latest BBC / Guardian coverage\n\n**REASONING:** Clean status but heavy recent minutes. Start him, keep a bench fallback ready in case of a late rotation call.`, truncated: true },
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
    navigate("/chat?new=1");
  }

  if (showFplStep) {
    return (
      <div className="landing">
        <div className="landing-topbar">
          <div className="landing-topbar-left"></div>
          <button className="landing-continue-btn" onClick={() => setShowFplStep(false)}>← Back</button>
        </div>
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
            <button className="landing-fpl-skip" onClick={() => navigate("/chat?new=1")}>Skip for now</button>
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

      {/* Gold top bar */}
      <div className="landing-topbar">
        <div className="landing-topbar-left">
          <nav className="landing-topbar-nav">
            {NAV_SECTIONS.map((s) => (
              <button
                key={s.id}
                className={`topbar-nav-btn ${activeSection === s.id ? "active" : ""}`}
                onClick={() => scrollTo(s.id === "features" ? FEATURES[0].id : s.id)}
              >
                {s.label}
              </button>
            ))}
          </nav>
        </div>
        {isReturning && (
          <button className="landing-continue-btn" onClick={() => navigate("/chat")}>
            Continue →
          </button>
        )}
      </div>

      {/* Hero */}
      <section id="home" ref={(el) => { sectionRefs.current["home"] = el; }} className="landing-hero">
        <div className="landing-hero-content">
          <h1 className="landing-title">THE GAFFER<span className="landing-title-period">.</span></h1>
          <p className="landing-sub">
            Ask anything about your Fantasy Premier League squad. Get a clear
            verdict backed by live data, stats, and AI reasoning.
          </p>
          <div className="landing-hero-actions">
            {isReturning ? (
              <>
                <button className="landing-cta" onClick={() => navigate("/chat")}>Continue →</button>
                <button className="landing-cta-secondary" onClick={() => setShowFplStep(true)}>Start fresh</button>
              </>
            ) : (
              <button className="landing-cta" onClick={() => setShowFplStep(true)}>Start asking →</button>
            )}
          </div>
        </div>
        <div className="hero-teamsheet" aria-hidden="true">
          <p className="hero-teamsheet-title">STARTING XI</p>
          {[
            ["GKP", "Flekken"],
            ["DEF", "Alexander-Arnold"],
            ["DEF", "Saliba"],
            ["DEF", "Van Dijk"],
            ["DEF", "Pedro Porro"],
            ["MID", "Salah"],
            ["MID", "Palmer"],
            ["MID", "Saka"],
            ["FWD", "Haaland"],
            ["FWD", "Isak"],
            ["FWD", "Watkins"],
          ].map(([pos, name]) => (
            <div key={name} className="hero-teamsheet-row">
              <span className="hero-teamsheet-pos">{pos}</span>
              <span>{name}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Stat strip */}
      <div className="stat-strip">
        <div className="stat-card">
          <div className="stat-value">12,400+</div>
          <div className="stat-label">Managers helped</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">81%</div>
          <div className="stat-label">Captain hit rate</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">&lt;2s</div>
          <div className="stat-label">Response time</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">24/7</div>
          <div className="stat-label">Press coverage</div>
        </div>
      </div>

      <div className="landing-body">
        {/* Global left nav */}
        <nav className="landing-nav">
          {NAV_SECTIONS.map((section) => (
            <div key={section.id} className="nav-section">
              <button
                className={`nav-item nav-item--top ${activeSection === section.id ? "active" : ""}`}
                onClick={() => scrollTo(section.id === "features" ? FEATURES[0].id : section.id)}
              >
                {section.label}
              </button>
              {section.children && (
                <div className="nav-children visible">
                  {section.children.map((child) => (
                    <button
                      key={child.id}
                      className={`nav-item nav-item--child ${activeSection === "features" && activeFeature === child.id ? "active" : ""}`}
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
          <section id="features" ref={(el) => { sectionRefs.current["features"] = el; }} className="landing-features-v2">
            <div className="features-panels">
              {FEATURES.map((f, idx) => (
                <div
                  key={f.id}
                  id={f.id}
                  ref={(el) => { featureRefs.current[f.id] = el; }}
                  className="feature-panel"
                >
                  <div className="feature-index">№{String(idx + 1).padStart(2, "0")}</div>
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
            <h2>HOW IT WORKS</h2>
            <div className="steps">
              <div className="step">
                <div className="step-num">01</div>
                <strong>Enter your FPL Team ID</strong>
                <p>Found in your team URL on the FPL website.</p>
              </div>
              <div className="step">
                <div className="step-num">02</div>
                <strong>Ask your question</strong>
                <p>Captain pick, transfers, differentials — anything FPL.</p>
              </div>
              <div className="step">
                <div className="step-num">03</div>
                <strong>Get a data-driven verdict</strong>
                <p>Live stats + AI reasoning in seconds.</p>
              </div>
            </div>
          </section>

          <ContactSection />
        </main>
      </div>

      {/* Full-width CTA band */}
      <div className="landing-cta-band">
        <h2 className="cta-band-headline">READY TO GET<br />THE EDGE?</h2>
        <button
          className="landing-cta"
          onClick={() => isReturning ? navigate("/chat") : setShowFplStep(true)}
        >
          {isReturning ? "Continue →" : "Start for free →"}
        </button>
      </div>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="landing-footer-col">
          <p className="landing-footer-heading">THE GAFFER</p>
          <p>AI-powered FPL analyst.<br />Built for managers who want an edge.</p>
        </div>
        <div className="landing-footer-col">
          <p className="landing-footer-heading">NAVIGATE</p>
          {NAV_SECTIONS.map((s) => (
            <button key={s.id} className="landing-changelog-btn" onClick={() => scrollTo(s.id === "features" ? FEATURES[0].id : s.id)}>
              {s.label}
            </button>
          ))}
        </div>
        <div className="landing-footer-col">
          <p className="landing-footer-heading">UPDATES</p>
          <button className="landing-changelog-btn" onClick={() => setShowChangelog(true)}>
            What's new in v{RELEASES[0].version} →
          </button>
        </div>
      </footer>
    </div>
  );
}
