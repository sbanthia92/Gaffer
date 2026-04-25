import { useState } from "react";
import { logClientEvent, type PlayerCard as PlayerCardData } from "./api";
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

// Renders an inline player chip from pre-fetched card data.
// Used by GafferMarkdown — no fetch happens here, data is passed in.
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
          onError={() => {
            setImgFailed(true);
            logClientEvent("player.photo_missing", { player: card.name });
          }}
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

// Fallback for unresolved names — plain text, no fetch
export function PlayerFallback({ name }: { name: string }) {
  return <span>{name}</span>;
}
