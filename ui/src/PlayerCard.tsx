import { useEffect, useState } from "react";
import { fetchPlayerCard, type PlayerCard as PlayerCardData } from "./api";
import "./PlayerCard.css";

export default function PlayerCard({ name }: { name: string }) {
  const [card, setCard] = useState<PlayerCardData | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetchPlayerCard(name).then((data) => {
      if (data) setCard(data);
      else setFailed(true);
    });
  }, [name]);

  // Unresolved — just render plain text
  if (failed) return <span>{name}</span>;

  // Loading skeleton
  if (!card) {
    return (
      <span className="player-card player-card--loading">
        <span className="player-card__photo-placeholder" />
        <span className="player-card__info">
          <span className="player-card__name-skeleton" />
          <span className="player-card__meta-skeleton" />
        </span>
      </span>
    );
  }

  return (
    <span className="player-card">
      <img
        className="player-card__photo"
        src={card.photo_url}
        alt={card.name}
        onError={(e) => {
          (e.target as HTMLImageElement).style.display = "none";
        }}
      />
      <span className="player-card__info">
        <span className="player-card__name">{card.name}</span>
        <span className="player-card__meta">
          <span className="player-card__team">{card.team}</span>
          <span className="player-card__dot">·</span>
          <span className="player-card__pos">{card.position}</span>
          <span className="player-card__dot">·</span>
          <span className="player-card__price">£{card.price.toFixed(1)}m</span>
          <span className="player-card__dot">·</span>
          <span className="player-card__form" title="Form">
            {card.form} form
          </span>
          <span className="player-card__dot">·</span>
          <span className="player-card__pts" title="Total points">
            {card.total_points} pts
          </span>
        </span>
      </span>
    </span>
  );
}
