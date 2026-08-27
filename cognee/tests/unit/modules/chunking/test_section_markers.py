"""Unit tests for stamp_section_heading(): turning Markdown ATX headings into
a structured section breadcrumb, with heading state carried across chunks
that introduce no heading of their own (mirrors test_page_markers.py).
"""

from cognee.modules.chunking.section_markers import stamp_section_heading


def test_no_heading_and_no_running_state_yields_none():
    """Plain prose with no Markdown headings anywhere -- e.g. most real PDFs."""
    breadcrumb, headings = stamp_section_heading("Just some plain prose text.", {})
    assert breadcrumb is None
    assert headings == {}


def test_single_top_level_heading():
    text = "# PMflex Projektmanagement\n\nSome introductory text."
    breadcrumb, headings = stamp_section_heading(text, {})
    assert breadcrumb == "PMflex Projektmanagement"
    assert headings == {1: "PMflex Projektmanagement"}


def test_nested_heading_builds_breadcrumb():
    text = "## 1 PMflex-Projektmanagement als Teil des PMflex-Systems\n\nBody text."
    breadcrumb, headings = stamp_section_heading(text, {1: "PMflex Projektmanagement"})
    assert breadcrumb == "PMflex Projektmanagement > 1 PMflex-Projektmanagement als Teil des PMflex-Systems"


def test_no_heading_in_chunk_inherits_running_state():
    """A chunk entirely within one section (heading landed in a previous chunk)."""
    breadcrumb, headings = stamp_section_heading(
        "More body text with no heading at all.",
        {1: "PMflex Projektmanagement", 2: "1 Einleitung"},
    )
    assert breadcrumb == "PMflex Projektmanagement > 1 Einleitung"
    assert headings == {1: "PMflex Projektmanagement", 2: "1 Einleitung"}


def test_new_heading_at_shallower_level_clears_deeper_ones():
    """A new H1 ends whatever H2/H3 subsection was previously active."""
    text = "# Chapter Two\n\nStarts fresh."
    breadcrumb, headings = stamp_section_heading(
        text, {1: "Chapter One", 2: "1.1 Details", 3: "1.1.1 Fine print"}
    )
    assert breadcrumb == "Chapter Two"
    assert headings == {1: "Chapter Two"}


def test_new_heading_at_same_level_replaces_sibling():
    text = "## 2 Second Section\n\nBody."
    breadcrumb, headings = stamp_section_heading(text, {1: "Part One", 2: "1 First Section"})
    assert breadcrumb == "Part One > 2 Second Section"
    assert headings == {1: "Part One", 2: "2 Second Section"}


def test_multiple_headings_in_one_chunk_ends_on_the_last():
    text = "# Title\n\n## Sub A\n\nShort.\n\n## Sub B\n\nAlso short."
    breadcrumb, headings = stamp_section_heading(text, {})
    assert breadcrumb == "Title > Sub B"


def test_heading_not_on_its_own_line_does_not_match():
    """A '#' inside a sentence (e.g. a hashtag or issue reference) is not a heading."""
    text = "See issue #42 for details, not a real heading."
    breadcrumb, headings = stamp_section_heading(text, {})
    assert breadcrumb is None
    assert headings == {}


def test_long_heading_text_is_clipped():
    long_heading = "# " + ("Very long heading text " * 10)
    breadcrumb, _ = stamp_section_heading(long_heading, {})
    assert breadcrumb is not None
    assert len(breadcrumb) <= 81  # _MAX_HEADING_CHARS + ellipsis
    assert breadcrumb.endswith("…")
