"""UnstructuredLoader emits "Page N:" markers the chunkers turn into page locators.

unstructured itself is replaced by a stand-in module: the loader imports
``unstructured.partition.auto.partition`` lazily inside ``load()``, and only
checks at import time that the package can be found. Faking it keeps these
tests independent of the optional ``docs`` extra and of libmagic.
"""

import importlib
import sys
from importlib.machinery import ModuleSpec
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

_LOADER_MODULE = "cognee.infrastructure.loaders.external.unstructured_loader"


class _Element:
    """Mimics unstructured's Element: ``metadata`` has attribute access, not dict access."""

    def __init__(self, text, page_number=None):
        self._text = text
        self.metadata = SimpleNamespace(page_number=page_number)

    def __str__(self):
        return self._text


def _fake_unstructured(elements):
    modules = {}
    for name in ("unstructured", "unstructured.partition", "unstructured.partition.auto"):
        module = ModuleType(name)
        module.__spec__ = ModuleSpec(name, loader=None)
        modules[name] = module
    modules["unstructured.partition.auto"].partition = lambda **kwargs: list(elements)
    return modules


async def _load_text(tmp_path, elements):
    source = tmp_path / "deck.pptx"
    source.write_bytes(b"not really a deck")
    with patch.dict(sys.modules, _fake_unstructured(elements)):
        sys.modules.pop(_LOADER_MODULE, None)
        loader_module = importlib.import_module(_LOADER_MODULE)
        return await loader_module.UnstructuredLoader().load(str(source), persist=False)


@pytest.mark.asyncio
async def test_one_marker_per_page_change_and_none_for_unpaged_elements(tmp_path):
    text = await _load_text(
        tmp_path,
        [
            _Element("Slide One Title", page_number=1),
            _Element("Slide One Body", page_number=1),
            _Element("Slide Two Title", page_number=2),
            _Element("Some undetectable element", page_number=None),
        ],
    )

    assert text.count("Page 1:") == 1
    assert text.count("Page 2:") == 1
    # The marker sits on its own line, which is what PageTracker matches.
    assert "Page 1:\n\nSlide One Title" in text
    # An element without a page number gets no marker, never a fabricated one.
    assert "Page None" not in text
    assert "Some undetectable element" in text


@pytest.mark.asyncio
async def test_a_source_without_page_numbers_gets_no_markers(tmp_path):
    text = await _load_text(
        tmp_path,
        [_Element("<h1>Title</h1>"), _Element("Paragraph")],
    )

    assert "Page" not in text
    assert text == "<h1>Title</h1>\n\nParagraph"
