"""Turn the inline "Page N:" text marker (emitted by PyPdfLoader, AdvancedPdfLoader,
and the extended UnstructuredLoader) into structured page_start/page_end metadata.

The marker is plain text sitting inside a chunk's own content, not a structured
field, so a chunk's page range has to be recovered by scanning its text and
carrying the last-known page number forward across chunks that contain no
marker at all (e.g. a chunk that falls entirely within one page, after the
marker itself ended up in a previous chunk).
"""

import re
from typing import Optional, Tuple

# Matches the exact marker format emitted by the loaders: "Page {N}:" on its
# own line. Multiline mode so `^`/`$` anchor to line boundaries, not just the
# start/end of the whole chunk text.
_PAGE_MARKER_RE = re.compile(r"(?m)^Page (\d+):$")


def stamp_page_range(
    text: str, running_page: Optional[int]
) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """Compute (page_start, page_end, updated_running_page) for one chunk's text.

    Parameters
    ----------
    text:
        The chunk's own text, in original document order.
    running_page:
        The page number in effect at the end of the previous chunk (None if no
        marker has been seen yet in this document).

    Returns
    -------
    tuple
        ``(page_start, page_end, updated_running_page)``. All ``None`` when no
        marker has ever been seen for this document and none appears in this
        chunk (i.e. the source has no derivable page information).
    """
    matches = list(_PAGE_MARKER_RE.finditer(text))
    if not matches:
        # No marker in this chunk: it belongs to whatever page was last seen.
        return running_page, running_page, running_page

    first, last = matches[0], matches[-1]
    leading = text[: first.start()]
    # Only inherit the running page when this chunk actually has content
    # before its first marker (i.e. the tail end of the previous page). If the
    # chunk starts AT the marker, page_start is the marker's own number, not
    # the previous page.
    page_start = (
        running_page if (running_page is not None and leading.strip()) else int(first.group(1))
    )
    page_end = int(last.group(1))
    return page_start, page_end, page_end
