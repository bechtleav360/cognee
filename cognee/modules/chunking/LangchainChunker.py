from os.path import basename
from uuid import NAMESPACE_OID, uuid5

from langchain_text_splitters import RecursiveCharacterTextSplitter

from cognee.infrastructure.databases.vector import get_vector_engine_async
from cognee.modules.chunking.Chunker import Chunker
from cognee.modules.chunking.page_markers import PageTracker
from cognee.modules.chunking.section_markers import SectionTracker
from cognee.shared.logging_utils import get_logger

from .models.DocumentChunk import DocumentChunk

logger = get_logger()


class LangchainChunker(Chunker):
    """
    A Chunker that splits text into chunks using Langchain's RecursiveCharacterTextSplitter.

    The chunker will split the text into chunks of approximately the given size, but will not split
    a chunk if the split would result in a chunk with fewer than the given overlap tokens.
    """

    chunker_id = "langchain_chunker_v1"

    def __init__(
        self,
        document,
        get_text: callable,
        max_chunk_size: int,
        chunk_size: int = 1024,
        chunk_overlap=10,
    ):
        super().__init__(document, get_text, max_chunk_size)

        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=lambda text: len(text.split()),
        )

    async def read(self):
        document_id = str(self.document.id)
        document_name = self.document.name or basename(self.document.raw_data_location)
        # Resolve the embedding engine once — it's the same for every chunk, so
        # resolving it per chunk inside the loops just adds await/lookup overhead.
        embedding_engine = (await get_vector_engine_async()).embedding_engine
        # One tracker per document: it carries the current page across chunks that
        # contain no marker of their own.
        page_tracker = PageTracker()
        # Sibling of page_tracker: the fallback for sources with no pagination.
        section_tracker = SectionTracker()
        async for content_text in self.get_text():
            for chunk in self.splitter.split_text(content_text):
                token_count = embedding_engine.tokenizer.count_tokens(chunk)
                # Stamped before the size check: the trackers must see every chunk in
                # document order, and an oversized one still advances the page.
                page_start, page_end = page_tracker.stamp(chunk)
                section = section_tracker.stamp(chunk)
                if token_count <= self.max_chunk_size:
                    yield DocumentChunk(
                        chunker_id=self.chunker_id,
                        id=uuid5(NAMESPACE_OID, chunk),
                        text=chunk,
                        chunk_size=token_count,
                        is_part_of=self.document,
                        chunk_index=self.chunk_index,
                        cut_type="missing",
                        contains=[],
                        importance_weight=self.document.importance_weight,
                        document_id=document_id,
                        document_name=document_name,
                        page_start=page_start,
                        page_end=page_end,
                        section=section,
                        metadata={
                            "index_fields": ["text"],
                        },
                    )
                    self.chunk_index += 1
                else:
                    raise ValueError(
                        f"Chunk of {token_count} tokens is larger than the maximum of {self.max_chunk_size} tokens. Please reduce chunk_size in RecursiveCharacterTextSplitter."
                    )
