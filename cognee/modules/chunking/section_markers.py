"""Recover a heading breadcrumb for sources that have no pagination to cite.

``page_markers.py`` covers documents whose loader knows about pages. Plain
Markdown and text have none, so a citation into them could previously name only
the document. The nearest equivalent of a page number there is the heading the
passage sits under, so this module reconstructs that from the ATX headings
("# Heading", "## Subheading", ...) present in the text itself.

The same two problems as with page markers apply, and are solved the same way:

- A chunk often contains no heading at all, because the heading landed in an
  earlier chunk. It still belongs under the last heading seen, so the state has
  to be carried forward across chunks.
- Headings nest, so the answer is a path rather than a single value. A heading
  at one level closes every deeper level currently open.

``SectionTracker`` holds that carried-forward state so callers cannot forget to
thread it through. Chunkers process a document's chunks in order, one tracker
per document.
"""

import re
from typing import Dict, Optional

# Standard Markdown ATX heading: 1-6 '#' characters, whitespace, then the text.
# Multiline mode so ^ and $ anchor to line boundaries inside the chunk.
_HEADING = re.compile(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*$")

# Clipped the way references.py clips snippets, so one runaway heading cannot
# dominate a citation line.
_MAX_HEADING_CHARS = 80

# Separator between levels of the breadcrumb.
_SEPARATOR = " > "


def _clip(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _MAX_HEADING_CHARS:
        return collapsed
    return collapsed[: _MAX_HEADING_CHARS - 1].rstrip() + "…"


class SectionTracker:
    """Assigns a heading breadcrumb to each chunk of one document, in order.

    Create one per document and call :meth:`stamp` with each chunk's text in the
    order the chunks appear. Returns ``None`` for every chunk until the first
    heading is seen — a document preamble, or a source with no Markdown
    headings, never gets a fabricated section.
    """

    def __init__(self) -> None:
        self._headings: Dict[int, str] = {}

    def stamp(self, text: str) -> Optional[str]:
        """Return the breadcrumb for one chunk and advance the tracker.

        The breadcrumb is the heading path in effect at the *end* of this
        chunk's text, joined shallowest to deepest.

        Parameters
        ----------
        text:
            The chunk's own text, in original document order.
        """
        for match in _HEADING.finditer(text):
            level = len(match.group(1))
            # A heading at this level closes every deeper one still open: those
            # belonged to the subsection that just ended.
            self._headings = {lvl: txt for lvl, txt in self._headings.items() if lvl < level}
            self._headings[level] = _clip(match.group(2))

        if not self._headings:
            return None

        return _SEPARATOR.join(self._headings[level] for level in sorted(self._headings))
