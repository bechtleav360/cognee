"""Unit tests asserting chunkers populate the reference scalar fields.

The References (Evidence) feature relies on every produced ``DocumentChunk``
carrying flat ``document_id`` / ``document_name`` scalars (basename only, never
an absolute path). These tests run the real chunkers over an in-memory text
generator (no LLM, no network) and assert the fields are set, and that the
format helper renders the 1-based number from ``chunk_index + 1``.
"""

from uuid import uuid4

import pytest

from cognee.modules.chunking.TextChunker import TextChunker
from cognee.modules.chunking.text_chunker_with_overlap import TextChunkerWithOverlap
from cognee.modules.data.processing.document_types import Document
from cognee.modules.retrieval.utils.references import format_chunk_references


@pytest.fixture(params=["TextChunker", "TextChunkerWithOverlap"])
def chunker_class(request):
    return TextChunker if request.param == "TextChunker" else TextChunkerWithOverlap


def _make_text_generator(*texts):
    async def gen():
        for text in texts:
            yield text

    return gen


async def _collect(chunker):
    chunks = []
    async for chunk in chunker.read():
        chunks.append(chunk)
    return chunks


@pytest.mark.asyncio
async def test_chunk_sets_document_id_and_name_from_document_name(chunker_class):
    """document_id is the document id; document_name uses document.name when present."""
    doc_id = uuid4()
    document = Document(
        id=doc_id,
        name="annual_report.pdf",
        raw_data_location="/abs/path/to/annual_report.pdf",
        external_metadata=None,
        mime_type="text/plain",
    )
    chunker = chunker_class(document, _make_text_generator("Hello world."), max_chunk_size=512)
    chunks = await _collect(chunker)

    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.document_id == str(doc_id)
        assert chunk.document_name == "annual_report.pdf"


@pytest.mark.asyncio
async def test_chunk_document_name_falls_back_to_basename(chunker_class):
    """When document.name is falsy, document_name uses basename(raw_data_location)."""
    document = Document(
        id=uuid4(),
        name="",  # empty -> fall back to basename
        raw_data_location="/abs/path/to/source_file.txt",
        external_metadata=None,
        mime_type="text/plain",
    )
    chunker = chunker_class(
        document, _make_text_generator("Some content here."), max_chunk_size=512
    )
    chunks = await _collect(chunker)

    assert len(chunks) >= 1
    for chunk in chunks:
        # basename only, never the absolute path
        assert chunk.document_name == "source_file.txt"
        assert "/" not in chunk.document_name


@pytest.mark.asyncio
async def test_format_helper_renders_one_based_number_from_real_chunk(chunker_class):
    """A real chunk's payload-shaped dict renders chunk_index + 1 in the Evidence block."""
    document = Document(
        id=uuid4(),
        name="report.pdf",
        raw_data_location="/p/report.pdf",
        external_metadata=None,
        mime_type="text/plain",
    )
    chunker = chunker_class(document, _make_text_generator("First chunk text."), max_chunk_size=512)
    chunks = await _collect(chunker)
    chunk = chunks[0]

    payload = {
        "document_name": chunk.document_name,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
    }
    result = format_chunk_references([payload])

    assert f"- chunk {chunk.chunk_index + 1} of document report.pdf:" in result


@pytest.mark.asyncio
async def test_chunk_page_start_end_derived_from_page_markers(chunker_class):
    """"Page N:" markers embedded in the source text (as emitted by
    PyPdfLoader/AdvancedPdfLoader/UnstructuredLoader) are recovered as
    structured page_start/page_end on each produced chunk, in order."""
    document = Document(
        id=uuid4(),
        name="handbook.pdf",
        raw_data_location="/p/handbook.pdf",
        external_metadata=None,
        mime_type="text/plain",
    )
    text = (
        "Page 1:\n"
        "This is the introduction paragraph explaining the purpose of the "
        "handbook in some detail, with enough content to fill a chunk.\n\n"
        "Page 2:\n"
        "This second page discusses the core methodology used throughout "
        "the rest of the document, again with plenty of content.\n\n"
        "Page 3:\n"
        "The third and final page wraps up with concluding remarks and a "
        "short summary of the findings presented earlier."
    )
    chunker = chunker_class(document, _make_text_generator(text), max_chunk_size=40)
    chunks = await _collect(chunker)

    assert len(chunks) >= 3
    # Markers are present throughout the source -- no chunk should be left
    # without a derived page number.
    assert all(chunk.page_start is not None and chunk.page_end is not None for chunk in chunks)
    page_starts = [chunk.page_start for chunk in chunks]
    assert page_starts == sorted(page_starts), "pages must be non-decreasing in document order"
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 3


@pytest.mark.asyncio
async def test_chunk_page_fields_none_when_source_has_no_page_markers(chunker_class):
    """Plain pasted text (no file, no loader) has no page concept: page_start/
    page_end must stay None rather than fabricating a page."""
    document = Document(
        id=uuid4(),
        name="notes.txt",
        raw_data_location="/p/notes.txt",
        external_metadata=None,
        mime_type="text/plain",
    )
    chunker = chunker_class(
        document, _make_text_generator("Just plain pasted text with no pages at all."), max_chunk_size=512
    )
    chunks = await _collect(chunker)

    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.page_start is None
        assert chunk.page_end is None


@pytest.mark.asyncio
async def test_chunk_page_tracking_survives_tiny_max_chunk_size(chunker_class):
    """A very small max_chunk_size (but still >= the longest single word --
    chunk_by_sentence itself rejects anything smaller, unrelated to page
    tracking) can in principle split a "Page N:" marker across a chunk
    boundary; this must degrade gracefully (no crash / no exception), even if
    a page transition is occasionally missed."""
    document = Document(
        id=uuid4(),
        name="dense.pdf",
        raw_data_location="/p/dense.pdf",
        external_metadata=None,
        mime_type="text/plain",
    )
    text = "Page 1:\nAlpha bravo charlie.\n\nPage 2:\nDelta echo foxtrot.\n\nPage 3:\nGolf hotel india."
    chunker = chunker_class(document, _make_text_generator(text), max_chunk_size=10)

    chunks = await _collect(chunker)  # must not raise

    assert len(chunks) > 1  # small enough to actually force multiple chunks
    for chunk in chunks:
        assert chunk.page_start is None or isinstance(chunk.page_start, int)
        assert chunk.page_end is None or isinstance(chunk.page_end, int)


@pytest.mark.asyncio
async def test_chunk_section_derived_from_markdown_headings(chunker_class):
    """Sources with no page markers (e.g. plain Markdown, no PDF loader
    involved) get a section breadcrumb from their heading structure instead."""
    document = Document(
        id=uuid4(),
        name="PMflex-Projektmanagement-Leitfaden",
        raw_data_location="/p/PMflex-Projektmanagement-Leitfaden",
        external_metadata=None,
        mime_type="text/plain",
    )
    text = (
        "# PMflex Projektmanagement\n\n"
        "Some introductory text about the overall system, long enough to fill a chunk on its own.\n\n"
        "## 1 PMflex-Projektmanagement als Teil des PMflex-Systems\n\n"
        "This section explains how project management fits into the broader PMflex system in detail.\n\n"
        "## 2 Governance\n\n"
        "This section covers governance roles and responsibilities within the PMflex methodology."
    )
    chunker = chunker_class(document, _make_text_generator(text), max_chunk_size=40)
    chunks = await _collect(chunker)

    assert len(chunks) >= 3
    # No page markers anywhere in this source: page fields must stay None.
    assert all(chunk.page_start is None and chunk.page_end is None for chunk in chunks)
    # Every chunk after the first heading should have a non-None section.
    assert all(chunk.section is not None for chunk in chunks)
    assert chunks[0].section == "PMflex Projektmanagement"
    assert "2 Governance" in chunks[-1].section


@pytest.mark.asyncio
async def test_chunk_section_none_when_source_has_no_headings(chunker_class):
    """Plain prose with neither page markers nor Markdown headings: section
    stays None rather than fabricating one."""
    document = Document(
        id=uuid4(),
        name="notes.txt",
        raw_data_location="/p/notes.txt",
        external_metadata=None,
        mime_type="text/plain",
    )
    chunker = chunker_class(
        document, _make_text_generator("Just plain pasted text with no structure at all."), max_chunk_size=512
    )
    chunks = await _collect(chunker)

    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.section is None
