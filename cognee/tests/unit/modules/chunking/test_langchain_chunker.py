"""Regression tests for LangchainChunker.

LangchainChunker was left targeting the pre-unification chunker API
(``max_chunk_tokens``, a 4-arg base ``Chunker.__init__``, and
``word_count``/``token_count`` fields ``DocumentChunk`` does not define), so
it could not be instantiated at all — neither positionally nor through the
standard ``Document.read`` call path
(``chunker_cls(self, max_chunk_size=..., get_text=...)``). These tests pin
the class to the current API.

The langchain import is guarded so test collection stays safe in
environments without the ``langchain`` extra installed (the previous fix,
#2966, was reverted in #3167; its regression test imported langchain
unconditionally).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("langchain_text_splitters")

from cognee.modules.chunking.LangchainChunker import LangchainChunker
from cognee.modules.chunking.models.DocumentChunk import DocumentChunk
from cognee.modules.data.processing.document_types import Document


class _WordCountTokenizer:
    def count_tokens(self, text: str) -> int:
        return len(text.split())


def _make_document() -> Document:
    return Document(
        id=uuid.uuid4(),
        name="test-document",
        raw_data_location="/tmp/test-document.txt",
        external_metadata=None,
        mime_type="text/plain",
    )


def _mock_vector_engine():
    engine = MagicMock()
    engine.embedding_engine.tokenizer = _WordCountTokenizer()
    return engine


def test_constructs_positionally_like_base_chunker():
    document = _make_document()

    async def get_text():
        yield "hello world"

    chunker = LangchainChunker(document, get_text, 512)

    assert chunker.max_chunk_size == 512
    assert chunker.document is document


def test_constructs_via_document_read_call_shape():
    """Every Document.read() builds its chunker with
    chunker_cls(self, max_chunk_size=..., get_text=...)."""
    document = _make_document()

    async def get_text():
        yield "hello world"

    chunker = LangchainChunker(document, max_chunk_size=512, get_text=get_text)

    assert chunker.max_chunk_size == 512


@pytest.mark.asyncio
async def test_read_yields_valid_document_chunks():
    document = _make_document()
    text = "one two three four five. " * 40

    async def get_text():
        yield text

    chunker = LangchainChunker(document, max_chunk_size=512, get_text=get_text)

    with patch(
        "cognee.modules.chunking.LangchainChunker.get_vector_engine_async",
        new=AsyncMock(return_value=_mock_vector_engine()),
    ):
        chunks = [chunk async for chunk in chunker.read()]

    assert len(chunks) > 0
    for index, chunk in enumerate(chunks):
        assert isinstance(chunk, DocumentChunk)
        assert chunk.text
        assert chunk.chunk_size > 0
        assert chunk.chunk_index == index
        assert chunk.is_part_of == document
        assert chunk.document_id == str(document.id)


@pytest.mark.asyncio
async def test_read_raises_for_chunks_over_max_chunk_size():
    document = _make_document()

    async def get_text():
        yield "word " * 50

    # splitter chunk_size is large enough that the split chunk exceeds
    # max_chunk_size, which must raise instead of yielding oversized chunks
    chunker = LangchainChunker(document, max_chunk_size=3, get_text=get_text, chunk_size=1000)

    with (
        patch(
            "cognee.modules.chunking.LangchainChunker.get_vector_engine_async",
            new=AsyncMock(return_value=_mock_vector_engine()),
        ),
        pytest.raises(ValueError, match="larger than the maximum"),
    ):
        [chunk async for chunk in chunker.read()]


def _paged_text(pages: int, words_per_page: int = 40) -> str:
    """Mimic a paginating loader's output: a "Page N:" line, then that page's body."""
    return "\n".join(
        f"Page {number}:\n" + " ".join(f"word{index}" for index in range(words_per_page))
        for number in range(1, pages + 1)
    )


@pytest.mark.asyncio
async def test_read_stamps_the_page_every_chunk_belongs_to():
    """A chunk with no marker of its own still belongs to the last page seen."""
    document = _make_document()

    async def get_text():
        yield _paged_text(pages=3)

    # A chunk size well below one page, so most chunks contain no marker at all.
    chunker = LangchainChunker(
        document, max_chunk_size=512, get_text=get_text, chunk_size=15, chunk_overlap=0
    )

    with patch(
        "cognee.modules.chunking.LangchainChunker.get_vector_engine_async",
        new=AsyncMock(return_value=_mock_vector_engine()),
    ):
        chunks = [chunk async for chunk in chunker.read()]

    assert len(chunks) > 3, "expected the text to split into more chunks than it has pages"
    assert all(chunk.page_start is not None for chunk in chunks)
    assert all(chunk.page_end is not None for chunk in chunks)
    # Pages only ever advance, and every page of the source is represented.
    pages = [chunk.page_end for chunk in chunks]
    assert pages == sorted(pages)
    assert set(pages) == {1, 2, 3}


@pytest.mark.asyncio
async def test_read_stamps_the_heading_breadcrumb_when_there_are_no_pages():
    """Markdown has no pages, so the nearest heading path is the locator instead."""
    document = _make_document()
    body = " ".join(f"word{index}" for index in range(40))

    async def get_text():
        yield f"# Guide\n{body}\n## Install\n{body}\n### Linux\n{body}"

    chunker = LangchainChunker(
        document, max_chunk_size=512, get_text=get_text, chunk_size=15, chunk_overlap=0
    )

    with patch(
        "cognee.modules.chunking.LangchainChunker.get_vector_engine_async",
        new=AsyncMock(return_value=_mock_vector_engine()),
    ):
        chunks = [chunk async for chunk in chunker.read()]

    assert all(chunk.page_start is None for chunk in chunks)
    sections = [chunk.section for chunk in chunks if chunk.section]
    assert sections, "expected at least one chunk to carry a section"
    assert sections[0] == "Guide"
    assert sections[-1] == "Guide > Install > Linux"


@pytest.mark.asyncio
async def test_read_invents_neither_page_nor_section_for_plain_text():
    document = _make_document()

    async def get_text():
        yield " ".join(f"word{index}" for index in range(60))

    chunker = LangchainChunker(
        document, max_chunk_size=512, get_text=get_text, chunk_size=15, chunk_overlap=0
    )

    with patch(
        "cognee.modules.chunking.LangchainChunker.get_vector_engine_async",
        new=AsyncMock(return_value=_mock_vector_engine()),
    ):
        chunks = [chunk async for chunk in chunker.read()]

    assert chunks
    for chunk in chunks:
        assert chunk.page_start is None
        assert chunk.page_end is None
        assert chunk.section is None
