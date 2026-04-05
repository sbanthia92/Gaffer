import pytest

from pipeline.ingest_fpl import (
    build_fixture_result_docs,
    build_player_gw_history_doc,
    build_player_season_doc,
    build_team_fdr_doc,
)

_PLAYER = {
    "id": 276,
    "first_name": "Erling",
    "second_name": "Haaland",
    "team": 43,
    "element_type": 4,
    "now_cost": 140,
    "goals_scored": 22,
    "assists": 5,
    "total_points": 198,
    "minutes": 2340,
    "form": "8.0",
    "selected_by_percent": "72.3",
    "clean_sheets": 0,
    "bonus": 30,
    "goals_conceded": 0,
    "yellow_cards": 1,
}

_TEAM = {
    "id": 43,
    "name": "Man City",
    "strength": 5,
    "strength_attack_home": 1310,
    "strength_attack_away": 1290,
    "strength_defence_home": 1300,
    "strength_defence_away": 1280,
}

_GW_HISTORY = [
    {"round": r, "total_points": pts, "goals_scored": g, "assists": a}
    for r, pts, g, a in [
        (1, 14, 2, 0),
        (2, 2, 0, 0),
        (3, 8, 1, 0),
        (4, 15, 2, 1),
        (5, 6, 1, 0),
        (6, 2, 0, 0),
        (7, 12, 2, 0),
        (8, 6, 1, 0),
        (9, 9, 1, 1),
        (10, 14, 2, 0),
    ]
]

_UPCOMING_FIXTURES = [
    {"event": 35, "team_h": 43, "team_a": 14, "team_h_difficulty": 2, "team_a_difficulty": 4},
    {"event": 36, "team_h": 10, "team_a": 43, "team_h_difficulty": 3, "team_a_difficulty": 2},
]

_FINISHED_FIXTURES = [
    {
        "id": 1001,
        "event": 30,
        "finished": True,
        "team_h": 43,
        "team_a": 14,
        "team_h_score": 3,
        "team_a_score": 1,
        "team_h_difficulty": 2,
        "team_a_difficulty": 4,
    }
]

_TEAMS_BY_ID = {43: {"name": "Man City"}, 14: {"name": "Liverpool"}}


# ---------------------------------------------------------------------------
# Player season stats
# ---------------------------------------------------------------------------


def test_player_season_doc_contains_key_fields():
    doc_id, text, meta = build_player_season_doc(_PLAYER, "Man City")
    assert "Erling Haaland" in text
    assert "Man City" in text
    assert "FWD" in text
    assert "£14.0m" in text
    assert "22g" in text
    assert "198pts" in text


def test_player_season_doc_metadata():
    doc_id, text, meta = build_player_season_doc(_PLAYER, "Man City")
    assert meta["type"] == "player_season_stats"
    assert meta["player_id"] == 276
    assert meta["recency_score"] == 0.9
    assert meta["text"] == text


def test_player_season_doc_id_is_stable():
    id1, _, _ = build_player_season_doc(_PLAYER, "Man City")
    id2, _, _ = build_player_season_doc(_PLAYER, "Man City")
    assert id1 == id2


# ---------------------------------------------------------------------------
# Player GW history
# ---------------------------------------------------------------------------


def test_gw_history_doc_hauls_and_blanks():
    _, text, meta = build_player_gw_history_doc("Erling Haaland", "Man City", 276, _GW_HISTORY)
    assert "Hauls" in text
    assert "Blanks" in text
    assert "GW1(14pts)" in text or "GW4(15pts)" in text or "GW10(14pts)" in text


def test_gw_history_doc_last_5():
    _, text, meta = build_player_gw_history_doc("Erling Haaland", "Man City", 276, _GW_HISTORY)
    assert "Last 5 GW points" in text


def test_gw_history_doc_metadata():
    _, text, meta = build_player_gw_history_doc("Erling Haaland", "Man City", 276, _GW_HISTORY)
    assert meta["type"] == "player_gw_history"
    assert meta["player_id"] == 276
    assert meta["recency_score"] == pytest.approx(10 / 38, rel=1e-3)


def test_gw_history_doc_empty_history_returns_none():
    result = build_player_gw_history_doc("Someone", "Some Team", 999, [])
    assert result is None


# ---------------------------------------------------------------------------
# Team FDR
# ---------------------------------------------------------------------------


def test_team_fdr_doc_contains_upcoming_fixtures():
    _, text, meta = build_team_fdr_doc(_TEAM, _UPCOMING_FIXTURES)
    assert "Man City" in text
    assert "GW35" in text
    assert "GW36" in text
    assert "FDR" in text


def test_team_fdr_doc_metadata():
    _, text, meta = build_team_fdr_doc(_TEAM, _UPCOMING_FIXTURES)
    assert meta["type"] == "team_fdr"
    assert meta["team_id"] == 43
    assert meta["recency_score"] == 1.0


def test_team_fdr_doc_no_upcoming_returns_none():
    result = build_team_fdr_doc(_TEAM, [])
    assert result is None


# ---------------------------------------------------------------------------
# Fixture results
# ---------------------------------------------------------------------------


def test_fixture_result_docs_score_and_teams():
    docs = build_fixture_result_docs(_FINISHED_FIXTURES, _TEAMS_BY_ID)
    assert len(docs) == 1
    doc_id, text, meta = docs[0]
    assert "Man City 3-1 Liverpool" in text
    assert meta["type"] == "fixture_result"
    assert meta["fixture_id"] == 1001
    assert meta["home_team"] == "Man City"
    assert meta["away_team"] == "Liverpool"


def test_fixture_result_docs_recency_score():
    docs = build_fixture_result_docs(_FINISHED_FIXTURES, _TEAMS_BY_ID)
    _, _, meta = docs[0]
    assert meta["recency_score"] == pytest.approx(30 / 38, rel=1e-3)


def test_fixture_result_docs_empty():
    assert build_fixture_result_docs([], _TEAMS_BY_ID) == []
