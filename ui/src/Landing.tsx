import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import AuthStatus from "./AuthStatus";
import ChangelogModal from "./ChangelogModal";
import { Icon } from "./icons";
import { RELEASES } from "./releases";
import { loadFplTeamId, loadSessions, saveFplTeamId, syncFplTeamId } from "./storage";
import { submitContact } from "./api";
import "./Landing.css";

// Illustrative answers. Every figure comes from the live FPL API as of GW10 of the current
// season (checked 2026-11-13), so refresh them if players move or the numbers go stale.
const EXAMPLE_NOTE = "Example answer · figures from GW10";

const FEATURES = [
  {
    id: "live-data",
    icon: "zap",
    title: "Live data",
    desc: "Real-time fixtures, standings, player prices, ownership, and form pulled from the FPL API. Every answer is backed by data from the current gameweek — never stale.",
    chat: [
      { role: "user", text: "Preview Newcastle vs Arsenal this weekend" },
      { role: "assistant", text: `**VERDICT: Lean Arsenal, even away.**\n\n**DATA:**\n• Arsenal last 5: W5 D0 L0, 7 scored / 1 conceded, 4 clean sheets\n• Newcastle last 5: W1 D1 L3, 4 scored / 7 conceded\n• League position: Arsenal 1st, Newcastle 12th\n• Fixture FDR: NEW 4 vs ARS 3 (lower is easier)\n\n**REASONING:** Arsenal have won all five of their recent games and barely conceded, while Newcastle have lost three of five. Raya and Gabriel are the clean-sheet picks.`, truncated: true },
    ],
  },
  {
    id: "ai-powered",
    icon: "sparkles",
    title: "AI-powered verdicts",
    desc: "Claude analyses your question, pulls the relevant data, and delivers a clear VERDICT with full reasoning — not just a data dump. It thinks like an experienced FPL manager.",
    chat: [
      { role: "user", text: "Should I captain Haaland or Isak this GW?" },
      { role: "assistant", text: `**VERDICT: Captain Haaland.**\n\n**DATA:**\n• Haaland: 70 pts · 7.0 pts/game · xGI 7.93 · £15.8m · 78.9% owned\n• Isak: 61 pts · 6.8 pts/game · xGI 5.16 · £9.3m · 25.1% owned\n• Haaland GW11: MCI (H) vs FUL — FDR 2\n• Isak GW11: LIV (H) vs MUN — FDR 3\n• Form: Haaland 6.2, Isak 7.0\n\n**REASONING:** Haaland has the stronger underlying numbers and the easier home fixture, so he is the higher-floor armband. Isak is in slightly better form and owned by only a quarter of managers, which makes him the differential if you need to gain ground.`, truncated: true },
    ],
  },
  {
    id: "your-squad",
    icon: "users",
    title: "Your squad",
    desc: "Enter your FPL Team ID and get advice tailored to your actual 15 players — transfer targets, captain picks, and chip timing based on what you already own.",
    chat: [
      { role: "user", text: "Who should I bring in with my 2 free transfers?" },
      { role: "assistant", text: `**VERDICT: Konsa (DEF) + Evanilson (FWD).**\n\n**DATA:**\n• Konsa (ARS) £4.8m · 57 pts · form 10.2 · 24.6% owned\n• Evanilson (BOU) £6.5m · 61 pts · form 9.0 · xGI 5.50\n• Evanilson is the second most-bought player this gameweek\n• GW11: ARS (A) vs NEW — FDR 3 · BOU (H) vs NFO — FDR 3\n\n**REASONING:** Both are in strong form on modest prices with FDR 3 fixtures next week, and each is a like-for-like swap. Check your club count before committing: Konsa would be another Arsenal player, and you can only hold three.`, truncated: true },
    ],
  },
  {
    id: "historical",
    icon: "trending",
    title: "Season-by-season history",
    desc: "GW-by-GW stats for the current season, plus season totals for previous seasons — points, goals, assists, minutes, and clean sheets. Ask how a player's output compares with last year, or how they have done in recent gameweeks.",
    chat: [
      { role: "user", text: "How does Haaland's season compare with last year?" },
      { role: "assistant", text: `**Haaland: this season vs 2025/26**\n\n**DATA:**\n| Season | Pts | Goals | Assists | Minutes | Pts/90 |\n|---|---|---|---|---|---|\n| 2025/26 | 239 | 27 | 8 | 2,953 | 7.3 |\n| This season (10 GWs) | 70 | 9 | 0 | 889 | 7.1 |\n\n**REASONING:** He is scoring a little more per 90 (0.91 goals vs 0.82) but has no assists yet, so his points rate is slightly below last year's. Ten gameweeks is a small sample. Previous seasons are season totals, so per-gameweek detail is only available for this season.`, truncated: true },
    ],
  },
  {
    id: "player-news",
    icon: "activity",
    title: "Injuries & player news",
    desc: "FPL's own availability flags and chance-of-playing figures, plus a live web search for the players it's giving a verdict on — so The Gaffer flags injuries, doubts, and rotation hints before you commit a transfer.",
    chat: [
      { role: "user", text: "Any injury or rotation concerns for Saka this week?" },
      { role: "assistant", text: `**VERDICT: Yes, Saka is injured. Don't start him.**\n\n**DATA:**\n• FPL status: injured — "Thigh injury - Unknown return date"\n• Chance of playing next round: 0%\n• 30,669 managers sold him this gameweek, 161 bought\n• Season so far: 37 pts · £9.4m · 5.5% owned\n\n**REASONING:** With no return date, a transfer is better than carrying him on your bench. Replace him with another midfielder, such as Ødegaard (£6.7m, form 5.0), but check your Arsenal count first.`, truncated: true },
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
      <div className="mockup-note">{EXAMPLE_NOTE}</div>
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
  // A signed-in account's saved team ID counts as returning even on a fresh device.
  const [syncedTeamId, setSyncedTeamId] = useState<number | null>(null);
  useEffect(() => {
    syncFplTeamId().then(setSyncedTeamId);
  }, []);
  const isReturning =
    loadSessions().length > 0 || (syncedTeamId ?? loadFplTeamId()) !== null;

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

      {/* Top bar */}
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
        <div className="landing-topbar-right">
          <AuthStatus />
        </div>
      </div>

      {/* Hero */}
      <section id="home" ref={(el) => { sectionRefs.current["home"] = el; }} className="landing-hero">
        <div className="landing-hero-content">
          <h1 className="landing-title">The Gaffer<span className="landing-title-period">.</span></h1>
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
          <p className="hero-teamsheet-title">Sample starting XI</p>
          {[
            ["GKP", "Raya"],
            ["DEF", "De Cuyper"],
            ["DEF", "Vuskovic"],
            ["DEF", "Gabriel"],
            ["DEF", "Calafiori"],
            ["MID", "Groß"],
            ["MID", "Rogers"],
            ["MID", "Cherki"],
            ["FWD", "Haaland"],
            ["FWD", "Isak"],
            ["FWD", "Evanilson"],
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
          <div className="stat-value">Live</div>
          <div className="stat-label">FPL data on every answer</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">Hourly</div>
          <div className="stat-label">Player stats refresh</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">5</div>
          <div className="stat-label">Free questions a day</div>
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
                      <span className="nav-child-icon"><Icon name={child.icon} size={14} /></span>
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
                  <div className="feature-index">{String(idx + 1).padStart(2, "0")}</div>
                  <div className="feature-panel-text">
                    <div className="feature-panel-heading">
                      <span className="feature-panel-icon"><Icon name={f.icon} size={20} /></span>
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
        <h2 className="cta-band-headline">Ready to get the edge?</h2>
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
          <p className="landing-footer-heading">The Gaffer</p>
          <p>AI-powered FPL analyst.<br />Built for managers who want an edge.</p>
        </div>
        <div className="landing-footer-col">
          <p className="landing-footer-heading">Navigate</p>
          {NAV_SECTIONS.map((s) => (
            <button key={s.id} className="landing-changelog-btn" onClick={() => scrollTo(s.id === "features" ? FEATURES[0].id : s.id)}>
              {s.label}
            </button>
          ))}
        </div>
        <div className="landing-footer-col">
          <p className="landing-footer-heading">Updates</p>
          <button className="landing-changelog-btn" onClick={() => setShowChangelog(true)}>
            What's new in v{RELEASES[0].version} →
          </button>
        </div>
      </footer>
    </div>
  );
}
