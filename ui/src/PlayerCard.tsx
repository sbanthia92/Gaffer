import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { PlayerCard as PlayerCardData } from "./api";
import "./PlayerCard.css";

function InjuryBadge({ status, chance }: { status: string; chance: number | null }) {
  if (status === "i")
    return <span className="player-card__badge player-card__badge--injured">Injured</span>;
  if (status === "d" && chance !== 100) {
    const pct = chance !== null ? `${chance}%` : "Doubt";
    return <span className="player-card__badge player-card__badge--doubt">{pct}</span>;
  }
  if (status === "s")
    return <span className="player-card__badge player-card__badge--suspended">Susp</span>;
  return null;
}

// Renders a player chip from pre-fetched card data.
// Reused inside PlayerLink's popover.
export function PlayerChip({ card }: { card: PlayerCardData }) {
  const [imgFailed, setImgFailed] = useState(false);
  return (
    <span className="player-card">
      {imgFailed ? (
        <span className="player-card__photo-fallback" aria-hidden>
          {card.name[0].toUpperCase()}
        </span>
      ) : (
        <img
          className="player-card__photo"
          src={card.photo_url}
          alt={card.name}
          onError={() => setImgFailed(true)}
        />
      )}
      <span className="player-card__info">
        <span className="player-card__name-row">
          <span className="player-card__name">{card.name}</span>
          <InjuryBadge status={card.status} chance={card.chance_of_playing_this_round} />
        </span>
        <span className="player-card__meta">
          <span className="player-card__team">{card.team}</span>
          <span className="player-card__dot">·</span>
          <span className="player-card__pos">{card.position}</span>
          <span className="player-card__dot">·</span>
          <span className="player-card__price">£{card.price.toFixed(1)}m</span>
          <span className="player-card__dot">·</span>
          <span className="player-card__form">
            Form {card.form}
          </span>
          <span className="player-card__dot">·</span>
          <span className="player-card__pts">
            {card.total_points} pts
          </span>
          <span className="player-card__dot">·</span>
          <span className="player-card__own">
            {card.selected_by_percent}% owned
          </span>
        </span>
        {card.news && <span className="player-card__news">{card.news}</span>}
      </span>
    </span>
  );
}

// Renders the player name as a styled link button.
// On click, toggles a popover that renders the full PlayerChip.
// Closes on outside click or Escape.
export function PlayerLink({ card }: { card: PlayerCardData }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement | null>(null);
  const popRef = useRef<HTMLSpanElement | null>(null);
  const [offsetX, setOffsetX] = useState(0);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useLayoutEffect(() => {
    if (!open || !popRef.current) return;
    const rect = popRef.current.getBoundingClientRect();
    const margin = 8;
    let dx = 0;
    if (rect.right > window.innerWidth - margin) {
      dx = window.innerWidth - margin - rect.right;
    }
    if (rect.left + dx < margin) {
      dx = margin - rect.left;
    }
    setOffsetX(dx);
  }, [open]);

  return (
    <span className="player-link-wrap" ref={wrapRef}>
      <button
        type="button"
        className="player-link"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
      >
        {card.name}
      </button>
      {open && (
        <span
          className="player-link__popover"
          ref={popRef}
          role="dialog"
          style={offsetX ? { transform: `translateX(${offsetX}px)` } : undefined}
        >
          <PlayerChip card={card} />
        </span>
      )}
    </span>
  );
}

// Fallback for unresolved names — plain text, no fetch
export function PlayerFallback({ name }: { name: string }) {
  return <span>{name}</span>;
}
