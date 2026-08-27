"""Turn Markdown ATX headings ("# Heading", "## Subheading", ...) into a
structured section breadcrumb, for chunks whose source has no real page
structure to fall back on (see page_markers.py for the page-number case).

Mirrors the same "scan this chunk's own text, carry state forward" approach:
a chunk's section is the heading breadcrumb in effect by the end of its text,
inheriting whatever was last seen if the chunk itself introduces no new
heading of its own.
"""

import re
from typing import Dict, Optional, Tuple

# Standard Markdown ATX heading: 1-6 '#' characters, a space, then the text.
_HEADING_RE = re.compile(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*$")

# Clip long headings the same way references.py clips text snippets.
_MAX_HEADING_CHARS = 80


def _clip(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _MAX_HEADING_CHARS:
        return collapsed
    return collapsed[: _MAX_HEADING_CHARS - 1].rstrip() + "…"


def stamp_section_heading(
    text: str, current_headings: Dict[int, str]
) -> Tuple[Optional[str], Dict[int, str]]:
    """Compute (section_breadcrumb, updated_headings) for one chunk's text.

    Parameters
    ----------
    text:
        The chunk's own text, in original document order.
    current_headings:
        Mapping of heading level (1-6) -> heading text in effect BEFORE this
        chunk, i.e. the running state carried from previous chunks. Pass {}
        for the first chunk of a document.

    Returns
    -------
    tuple
        ``(breadcrumb, updated_headings)``. ``breadcrumb`` is a " > "-joined
        string of the active heading levels from shallowest to deepest, or
        ``None`` if no heading has been seen yet at all -- e.g. a document
        preamble, or a source with no Markdown headings (most real PDFs,
        which get a page number from page_markers.py instead).
    """
    headings = dict(current_headings)

    for match in _HEADING_RE.finditer(text):
        level = len(match.group(1))
        heading_text = _clip(match.group(2))
        # A heading at this level replaces any deeper (higher-numbered)
        # headings currently in scope -- those belonged to the subsection
        # that just ended.
        headings = {lvl: txt for lvl, txt in headings.items() if lvl < level}
        headings[level] = heading_text

    if not headings:
        return None, headings

    breadcrumb = " > ".join(headings[level] for level in sorted(headings))
    return breadcrumb, headings
