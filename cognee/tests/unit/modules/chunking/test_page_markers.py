"""Unit tests for stamp_page_range(): turning the inline "Page N:" text
marker (emitted by PyPdfLoader/AdvancedPdfLoader/UnstructuredLoader) into
structured page_start/page_end, with a running page number carried across
chunks that contain no marker of their own.
"""

from cognee.modules.chunking.page_markers import stamp_page_range


def test_no_marker_and_no_running_page_yields_all_none():
    """Plain text with no page information anywhere -> nothing derivable."""
    assert stamp_page_range("Just some plain text.", None) == (None, None, None)


def test_no_marker_inherits_running_page():
    """A chunk entirely within one page (marker landed in a previous chunk)."""
    assert stamp_page_range("More text from the same page.", 5) == (5, 5, 5)


def test_chunk_starting_exactly_at_a_marker_does_not_inherit_previous_page():
    """Regression: a chunk beginning AT a page boundary must use the marker's
    own number for page_start, not the previous chunk's running page."""
    text = "Page 5:\nContent of page five."
    assert stamp_page_range(text, 4) == (5, 5, 5)


def test_chunk_with_leading_content_before_marker_inherits_running_page():
    """A marker appearing mid-chunk: page_start is the page in effect at the
    chunk's start (the running page), page_end is the new marker."""
    text = "Tail end of page four.\n\nPage 5:\nStart of page five."
    assert stamp_page_range(text, 4) == (4, 5, 5)


def test_chunk_spanning_multiple_markers():
    text = "Page 5:\nShort.\n\nPage 6:\nAlso short.\n\nPage 7:\nLast bit."
    assert stamp_page_range(text, None) == (5, 7, 7)


def test_first_marker_ever_seen_with_leading_content_and_no_running_page():
    """No running page yet (very first chunk of the document) but the chunk
    has content before its first marker: page_start falls back to that first
    marker's own number, since there is no earlier page to inherit."""
    text = "Some preamble with no page marker.\n\nPage 1:\nReal content."
    assert stamp_page_range(text, None) == (1, 1, 1)


def test_marker_without_a_digit_does_not_match():
    """AdvancedPdfLoader emits a bare 'Page:' header (glued directly to the
    segment text, no newline in between -- see advanced_pdf_loader.py) when
    it has no page number for an element. This must not be mistaken for a
    real marker, both because it has no digit and because it never lands on
    its own line."""
    text = "Page:Some content with an unknown page.\n"
    assert stamp_page_range(text, 3) == (3, 3, 3)


def test_marker_must_be_on_its_own_line():
    """'Page 5:' appearing mid-sentence (not its own line) is not a marker --
    guards against false positives from ordinary prose."""
    text = "As shown on Page 5: the results were positive."
    assert stamp_page_range(text, None) == (None, None, None)


def test_tiny_chunks_that_split_a_marker_degrade_gracefully():
    """If chunking ever splits a marker itself across two chunks (a marker's
    "Page N:" line broken mid-token), neither half matches the regex -- the
    page simply doesn't advance for that transition instead of crashing or
    misreporting. This exercises the degraded case directly, since real
    tokenization splitting requires a live tokenizer; here we assert the pure
    function's behavior on the resulting fragments."""
    first_half, second_half = "Page 5", ":\nRest of the page text."
    assert stamp_page_range(first_half, 4) == (4, 4, 4)
    assert stamp_page_range(second_half, 4) == (4, 4, 4)
