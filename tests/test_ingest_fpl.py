import pytest

from pipeline.ingest_fpl import (
    _current_season,
    _recency_score,
    build_player_history_past_docs,
    build_player_vs_opponent_docs,
)

_HISTORY_PAST = [
    {
        "season_name": "2024/25",
        "start_cost": 140,
        "end_cost": 145,
        "total_points": 259,
        "minutes": 2890,
        "goals_scored": 27,
        "assists": 9,
        "clean_sheets": 0,
        "bonus": 45,
        "yellow_cards": 3,
        "red_cards": 0,
        "starts": 33,
    },
    {
        "season_name": "2023/24",
        "start_cost": 135,
        "end_cost": 140,
        "total_points": 198,
        "minutes": 2340,
        "goals_scored": 22,
        "assists": 5,
        "clean_sheets": 0,
        "bonus": 30,
        "yellow_cards": 1,
        "red_cards": 0,
        "starts": 28,
    },
]


# ---------------------------------------------------------------------------
# Player historical season docs
# ---------------------------------------------------------------------------


def test_history_past_doc_count():
    docs = build_player_history_past_docs("Erling Haaland", "Man City", "FWD", 276, _HISTORY_PAST)
    assert len(docs) == 2


def test_history_past_doc_contains_key_fields():
    docs = build_player_history_past_docs("Erling Haaland", "Man City", "FWD", 276, _HISTORY_PAST)
    _, text, _ = docs[0]
    assert "Erling Haaland" in text
    assert "Man City" in text
    assert "FWD" in text
    assert "2024/25" in text
    assert "Goals: 27" in text
    assert "Points: 259" in text
    assert "£14.0m" in text


def test_history_past_doc_metadata():
    docs = build_player_history_past_docs("Erling Haaland", "Man City", "FWD", 276, _HISTORY_PAST)
    _, text, meta = docs[0]
    assert meta["type"] == "player_season_history"
    assert meta["player_id"] == 276
    assert meta["season"] == "2024/25"
    assert meta["text"] == text


def test_history_past_doc_id_stable():
    docs1 = build_player_history_past_docs("Erling Haaland", "Man City", "FWD", 276, _HISTORY_PAST)
    docs2 = build_player_history_past_docs("Erling Haaland", "Man City", "FWD", 276, _HISTORY_PAST)
    assert docs1[0][0] == docs2[0][0]
    assert docs1[1][0] == docs2[1][0]


def test_history_past_doc_unique_ids():
    docs = build_player_history_past_docs("Erling Haaland", "Man City", "FWD", 276, _HISTORY_PAST)
    ids = [d[0] for d in docs]
    assert len(ids) == len(set(ids))


def test_history_past_empty_returns_no_docs():
    docs = build_player_history_past_docs("Someone", "Some Team", "MID", 999, [])
    assert docs == []


# ---------------------------------------------------------------------------
# Recency score
# ---------------------------------------------------------------------------


def test_recency_score_most_recent():
    assert _recency_score("2024/25") == pytest.approx(1.0)


def test_recency_score_one_year_older():
    assert _recency_score("2023/24") == pytest.approx(0.8)


def test_recency_score_floor():
    assert _recency_score("2019/20") >= 0.2


def test_recency_score_invalid():
    assert _recency_score("unknown") == 0.5


# ---------------------------------------------------------------------------
# Player vs opponent docs
# ---------------------------------------------------------------------------

_TEAMS_BY_ID = {1: {"name": "Arsenal"}, 2: {"name": "Chelsea"}}

_GW_HISTORY = [
    {
        "round": 5,
        "opponent_team": 1,
        "was_home": True,
        "total_points": 12,
        "goals_scored": 2,
        "assists": 0,
        "minutes": 90,
    },
    {
        "round": 20,
        "opponent_team": 1,
        "was_home": False,
        "total_points": 6,
        "goals_scored": 1,
        "assists": 0,
        "minutes": 90,
    },
    {
        "round": 10,
        "opponent_team": 2,
        "was_home": True,
        "total_points": 2,
        "goals_scored": 0,
        "assists": 0,
        "minutes": 60,
    },
]

_SALAH_ARGS = ("M Salah", "MID", 308, "2025/26", _GW_HISTORY, _TEAMS_BY_ID)


def test_vs_opponent_doc_count():
    docs = build_player_vs_opponent_docs(*_SALAH_ARGS)
    assert len(docs) == 2  # one per opponent


def test_vs_opponent_doc_aggregates():
    docs = build_player_vs_opponent_docs(*_SALAH_ARGS)
    arsenal_doc = next(d for d in docs if "Arsenal" in d[1])
    _, text, meta = arsenal_doc
    assert "3g" in text  # 2 + 1 goals
    assert "18pts" in text  # 12 + 6
    assert "Appearances: 2" in text
    assert meta["opponent"] == "Arsenal"
    assert meta["season"] == "2025/26"
    assert meta["type"] == "player_vs_opponent"


def test_vs_opponent_doc_unique_ids():
    docs = build_player_vs_opponent_docs(*_SALAH_ARGS)
    ids = [d[0] for d in docs]
    assert len(ids) == len(set(ids))


def test_vs_opponent_empty_history():
    docs = build_player_vs_opponent_docs("M Salah", "MID", 308, "2025/26", [], _TEAMS_BY_ID)
    assert docs == []


# ---------------------------------------------------------------------------
# Current season detection
# ---------------------------------------------------------------------------


def test_current_season_from_bootstrap():
    bootstrap = {"events": [{"deadline_time": "2025-08-16T11:00:00Z"}]}
    assert _current_season(bootstrap) == "2025/26"


def test_current_season_fallback():
    assert _current_season({}) == "unknown"
