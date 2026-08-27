"""Unit tests for SectionTracker, which recovers a heading breadcrumb from Markdown.

Pure logic over strings: no loader, no chunker, no I/O. The chunker-side wiring
is covered separately in test_chunk_page_fields.py.
"""

from cognee.modules.chunking.section_markers import SectionTracker


class TestWithoutHeadings:
    def test_a_source_with_no_headings_never_gets_a_section(self):
        """Pasted text has no structure to cite; an invented one would be worse than none."""
        tracker = SectionTracker()

        assert tracker.stamp("Some prose with no heading at all.") is None
        assert tracker.stamp("More prose.") is None

    def test_a_document_preamble_before_the_first_heading_has_no_section(self):
        """Text above the first heading belongs to no section yet."""
        tracker = SectionTracker()

        assert tracker.stamp("Intro paragraph.") is None

    def test_a_hash_that_is_not_a_heading_is_ignored(self):
        """Only the ATX form counts: hashes mid-line, or without a space, are prose."""
        tracker = SectionTracker()

        assert tracker.stamp("Issue #42 is fixed.") is None
        assert tracker.stamp("#nospace is a tag, not a heading") is None

    def test_more_than_six_hashes_is_not_a_heading(self):
        """Markdown caps ATX headings at six levels."""
        tracker = SectionTracker()

        assert tracker.stamp("####### Seven hashes") is None


class TestSingleLevel:
    def test_a_chunk_introducing_a_heading_takes_it(self):
        tracker = SectionTracker()

        assert tracker.stamp("# Introduction\nSome text.") == "Introduction"

    def test_a_later_heading_at_the_same_level_replaces_the_earlier_one(self):
        """Sibling sections do not accumulate."""
        tracker = SectionTracker()
        tracker.stamp("# Introduction\n")

        assert tracker.stamp("# Methods\nText.") == "Methods"

    def test_the_last_heading_in_a_chunk_wins(self):
        """The breadcrumb describes where the chunk ends, matching PageTracker's page_end."""
        tracker = SectionTracker()

        assert tracker.stamp("# First\ntext\n# Second\nmore") == "Second"


class TestCarryForward:
    def test_a_chunk_without_a_heading_inherits_the_last_one(self):
        """The whole point: most chunks contain no heading of their own."""
        tracker = SectionTracker()
        tracker.stamp("## Setup\n")

        assert tracker.stamp("Continued prose.") == "Setup"
        assert tracker.stamp("Still more prose.") == "Setup"

    def test_each_document_starts_clean(self):
        """One tracker per document; a fresh tracker must not inherit anything."""
        first = SectionTracker()
        first.stamp("# Doc One")

        assert SectionTracker().stamp("Plain text.") is None


class TestNesting:
    def test_levels_nest_into_a_breadcrumb(self):
        tracker = SectionTracker()

        assert tracker.stamp("# Guide\n## Install\n### Linux\n") == "Guide > Install > Linux"

    def test_a_shallower_heading_closes_the_deeper_ones(self):
        """A new H2 ends the H3 that belonged to the previous subsection."""
        tracker = SectionTracker()
        tracker.stamp("# Guide\n## Install\n### Linux\n")

        assert tracker.stamp("## Usage\n") == "Guide > Usage"

    def test_a_skipped_level_is_kept_as_authored(self):
        """H1 straight to H3 is legal Markdown; the breadcrumb reports what is there."""
        tracker = SectionTracker()

        assert tracker.stamp("# Top\n### Deep\n") == "Top > Deep"

    def test_the_top_level_survives_a_deeper_replacement(self):
        tracker = SectionTracker()
        tracker.stamp("# Guide\n## Install\n")

        assert tracker.stamp("## Usage\n") == "Guide > Usage"


class TestHeadingText:
    def test_surrounding_whitespace_is_stripped(self):
        tracker = SectionTracker()

        assert tracker.stamp("#    Spaced   Heading   \n") == "Spaced Heading"

    def test_a_long_heading_is_clipped(self):
        """One runaway heading must not dominate the citation line."""
        tracker = SectionTracker()
        long_heading = "A" * 200

        result = tracker.stamp(f"# {long_heading}\n")

        assert len(result) == 80
        assert result.endswith("…")

    def test_a_tab_after_the_hashes_is_accepted(self):
        tracker = SectionTracker()

        assert tracker.stamp("#\tTabbed\n") == "Tabbed"
