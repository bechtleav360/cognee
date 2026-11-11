"""Chunk page and section locators round-trip through a real LanceDB table.

The Evidence block reads them back from the ``DocumentChunk_text`` payload, so a
schema that dropped them would silently render citations without a location.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from cognee.modules.chunking.models.DocumentChunk import DocumentChunk
from cognee.modules.data.processing.document_types import Document
from cognee.modules.retrieval.utils.references import format_chunk_references

try:
    from cognee.infrastructure.databases.vector.lancedb.LanceDBAdapter import (
        IndexSchema,
        LanceDBAdapter,
    )

    HAS_LANCEDB = True
except ModuleNotFoundError:
    HAS_LANCEDB = False


class _FakeEmbeddingEngine:
    def get_vector_size(self):
        return 3

    def get_batch_size(self):
        return 100

    async def embed_text(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


def _chunk(text: str, **locators) -> DocumentChunk:
    document = Document(
        id=uuid4(),
        name="report.pdf",
        raw_data_location="/tmp/report.pdf",
        external_metadata=None,
        mime_type="application/pdf",
    )
    return DocumentChunk(
        id=uuid4(),
        text=text,
        chunk_size=2,
        chunk_index=0,
        cut_type="paragraph_end",
        is_part_of=document,
        contains=[],
        document_id=str(document.id),
        document_name=document.name,
        **locators,
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_LANCEDB, reason="lancedb not installed")
async def test_chunk_locators_round_trip_through_lancedb(tmp_path):
    adapter = LanceDBAdapter(
        url=str(tmp_path / "db"), api_key=None, embedding_engine=_FakeEmbeddingEngine()
    )
    paged = _chunk("paged chunk", page_start=3, page_end=4)
    sectioned = _chunk("sectioned chunk", section="Results > Revenue")
    plain = _chunk("plain chunk")

    await adapter.create_collection("DocumentChunk_text", IndexSchema)
    await adapter.index_data_points("DocumentChunk", "text", [paged, sectioned, plain])

    results = await adapter.search(
        "DocumentChunk_text", query_vector=[0.1, 0.2, 0.3], limit=5, include_payload=True
    )
    payloads = {str(result.id): result.payload for result in results}
    assert payloads[str(paged.id)]["page_start"] == 3
    assert payloads[str(paged.id)]["page_end"] == 4
    assert payloads[str(paged.id)]["section"] is None
    assert payloads[str(sectioned.id)]["section"] == "Results > Revenue"
    assert payloads[str(sectioned.id)]["page_start"] is None
    assert payloads[str(plain.id)]["page_start"] is None
    assert payloads[str(plain.id)]["page_end"] is None
    assert payloads[str(plain.id)]["section"] is None

    # And the stored payload is enough for the Evidence block to name the place.
    evidence = format_chunk_references(results)
    assert "of document report.pdf, page 3-4" in evidence
    assert "of document report.pdf, section: Results > Revenue" in evidence
