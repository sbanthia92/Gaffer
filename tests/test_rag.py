from unittest.mock import MagicMock, patch

import pytest

from server.rag import retrieve


def _make_match(score: float, text: str, doc_type: str, recency_score: float = 0.9) -> MagicMock:
    match = MagicMock()
    match.score = score
    match.metadata = {
        "text": text,
        "type": doc_type,
        "season": "2024-25",
        "date": "2025-03-01",
        "recency_score": recency_score,
    }
    return match


@pytest.mark.asyncio
async def test_retrieve_returns_formatted_context():
    mock_match = _make_match(0.9, "Salah scored vs Man City in GW28.", "player_performance")

    with (
        patch("server.rag.Pinecone") as mock_pinecone_cls,
    ):
        mock_pc = MagicMock()
        mock_pinecone_cls.return_value = mock_pc

        mock_pc.inference.embed.return_value = [MagicMock(values=[0.1, 0.2, 0.3])]

        mock_index = MagicMock()
        mock_pc.Index.return_value = mock_index
        mock_index.query.return_value = MagicMock(matches=[mock_match])

        result = await retrieve(
            query="How has Salah performed vs Man City?",
            namespace="fpl",
        )

    assert "Salah scored vs Man City" in result
    assert "player_performance" in result


@pytest.mark.asyncio
async def test_retrieve_returns_empty_string_when_no_matches():
    with patch("server.rag.Pinecone") as mock_pinecone_cls:
        mock_pc = MagicMock()
        mock_pinecone_cls.return_value = mock_pc
        mock_pc.inference.embed.return_value = [MagicMock(values=[0.1, 0.2, 0.3])]
        mock_index = MagicMock()
        mock_pc.Index.return_value = mock_index
        mock_index.query.return_value = MagicMock(matches=[])

        result = await retrieve(query="obscure question", namespace="fpl")

    assert result == ""


@pytest.mark.asyncio
async def test_retrieve_applies_recency_weighting():
    old_match = _make_match(0.95, "Old data.", "team_performance", recency_score=0.1)
    new_match = _make_match(0.80, "Recent data.", "team_performance", recency_score=1.0)

    with patch("server.rag.Pinecone") as mock_pinecone_cls:
        mock_pc = MagicMock()
        mock_pinecone_cls.return_value = mock_pc
        mock_pc.inference.embed.return_value = [MagicMock(values=[0.1, 0.2, 0.3])]
        mock_index = MagicMock()
        mock_pc.Index.return_value = mock_index
        mock_index.query.return_value = MagicMock(matches=[old_match, new_match])

        result = await retrieve(query="recent form", namespace="fpl", recency_weight=0.5)

    # Recent match should appear first despite lower semantic score
    assert result.index("Recent data.") < result.index("Old data.")


@pytest.mark.asyncio
async def test_retrieve_uses_correct_namespace():
    with patch("server.rag.Pinecone") as mock_pinecone_cls:
        mock_pc = MagicMock()
        mock_pinecone_cls.return_value = mock_pc
        mock_pc.inference.embed.return_value = [MagicMock(values=[0.1, 0.2, 0.3])]
        mock_index = MagicMock()
        mock_pc.Index.return_value = mock_index
        mock_index.query.return_value = MagicMock(matches=[])

        await retrieve(query="test", namespace="worldcup")

    call_kwargs = mock_index.query.call_args.kwargs
    assert call_kwargs["namespace"] == "worldcup"
