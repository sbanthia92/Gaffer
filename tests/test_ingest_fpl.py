import pytest

from pipeline.ingest_fpl import build_player_history_past_docs, _recency_score

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
