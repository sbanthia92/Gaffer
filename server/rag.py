"""
RAG retrieval — Pinecone semantic search with recency weighting.

Always namespace-scoped (fpl | worldcup | laliga) and never hardcoded
to a specific sport. The caller provides the namespace and recency weight.

Pinecone's built-in inference handles embeddings — no separate embeddings API.
"""

from pinecone import Pinecone

from server.config import settings

_EMBEDDING_MODEL = "multilingual-e5-large"


def _client() -> Pinecone:
    return Pinecone(api_key=settings.pinecone_api_key)


async def retrieve(
    query: str,
    namespace: str,
    top_k: int = 5,
    recency_weight: float = 0.3,
    filters: dict | None = None,
) -> str:
    """
    Retrieve relevant historical documents from Pinecone and return them
    as a formatted string ready to inject into the Claude system prompt.

    Args:
        query: The natural language question to embed and search.
        namespace: Pinecone namespace — fpl | worldcup | laliga.
        top_k: Number of documents to retrieve.
        recency_weight: How much to boost recent documents (0.0–1.0).
                        Applied as a score multiplier using recency_score metadata.
        filters: Optional Pinecone metadata filters.

    Returns:
        Formatted string of retrieved documents for use as RAG context.
    """
    pc = _client()
    index = pc.Index(settings.pinecone_index_name)

    # Use Pinecone's built-in inference to embed the query
    try:
        embeddings = pc.inference.embed(
            model=_EMBEDDING_MODEL,
            inputs=[query],
            parameters={"input_type": "query"},
        )
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            return ""  # quota exhausted — degrade gracefully, no RAG context
        raise
    query_vector = embeddings[0].values

    results = index.query(
        vector=query_vector,
        top_k=top_k,
        namespace=namespace,
        include_metadata=True,
        filter=filters,
    )

    if not results.matches:
        return ""

    # Apply recency weighting: final_score = semantic_score * (1 + recency_weight * recency_score)
    weighted = []
    for match in results.matches:
        recency_score = match.metadata.get("recency_score", 0.5) if match.metadata else 0.5
        final_score = match.score * (1 + recency_weight * recency_score)
        weighted.append((final_score, match))

    weighted.sort(key=lambda x: x[0], reverse=True)

    return _format_results(weighted)


def _format_results(weighted: list[tuple[float, object]]) -> str:
    parts = []
    for rank, (score, match) in enumerate(weighted, start=1):
        meta = match.metadata or {}
        text = meta.get("text", "")
        doc_type = meta.get("type", "unknown")
        season = meta.get("season", "")
        date = meta.get("date", "")

        header = f"[{rank}] {doc_type}"
        if season:
            header += f" | {season}"
        if date:
            header += f" | {date}"
        header += f" | relevance: {score:.3f}"

        parts.append(f"{header}\n{text}")

    return "\n\n".join(parts)
