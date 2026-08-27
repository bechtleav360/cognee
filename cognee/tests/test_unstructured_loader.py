from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, mock_open

import pytest

from cognee.infrastructure.loaders.external.unstructured_loader import UnstructuredLoader


class MockElement:
    """Mimics unstructured's Element: .metadata is an object with attribute
    access (element.metadata.page_number), not a dict -- unlike the elements
    AdvancedPdfLoader deals with after calling .to_dict()."""

    def __init__(self, text, page_number=None):
        self._text = text
        self.metadata = SimpleNamespace(page_number=page_number)

    def __str__(self):
        return self._text


@pytest.fixture
def loader():
    return UnstructuredLoader()


@pytest.mark.asyncio
@patch("cognee.infrastructure.loaders.external.unstructured_loader.open", new_callable=mock_open)
@patch(
    "cognee.infrastructure.loaders.external.unstructured_loader.get_file_metadata",
    new_callable=AsyncMock,
)
@patch("cognee.infrastructure.loaders.external.unstructured_loader.get_storage_config")
@patch("cognee.infrastructure.loaders.external.unstructured_loader.get_file_storage")
@patch("cognee.infrastructure.loaders.external.unstructured_loader.partition")
async def test_load_emits_page_marker_only_when_page_number_changes(
    mock_partition,
    mock_get_file_storage,
    mock_get_storage_config,
    mock_get_file_metadata,
    mock_open,
    loader,
):
    """Consecutive elements on the same page/slide get one marker, not one
    per element; elements with no determinable page number get none."""
    mock_partition.return_value = [
        MockElement("Slide One Title", page_number=1),
        MockElement("Slide One Body", page_number=1),
        MockElement("Slide Two Title", page_number=2),
        MockElement("Some undetectable element", page_number=None),
    ]
    mock_get_file_metadata.return_value = {"content_hash": "abc123"}
    mock_get_storage_config.return_value = {"data_root_directory": "/data"}
    mock_storage = AsyncMock()
    mock_storage.store.return_value = "/data/text_abc123.txt"
    mock_get_file_storage.return_value = mock_storage

    await loader.load("/tmp/fake.pptx")

    stored_content = mock_storage.store.call_args.args[1]
    assert stored_content.count("Page 1:") == 1
    assert stored_content.count("Page 2:") == 1
    assert "Slide One Title" in stored_content
    assert "Slide One Body" in stored_content
    assert "Slide Two Title" in stored_content
    # The element with no page number gets no marker at all -- never a
    # fabricated one.
    assert "Page None" not in stored_content
    assert "Some undetectable element" in stored_content


@pytest.mark.asyncio
@patch("cognee.infrastructure.loaders.external.unstructured_loader.open", new_callable=mock_open)
@patch(
    "cognee.infrastructure.loaders.external.unstructured_loader.get_file_metadata",
    new_callable=AsyncMock,
)
@patch("cognee.infrastructure.loaders.external.unstructured_loader.partition")
async def test_load_with_no_page_numbers_anywhere_emits_no_markers(
    mock_partition, mock_get_file_metadata, mock_open, loader
):
    """A format unstructured can't paginate (e.g. plain HTML) emits plain
    text with zero "Page N:" markers -- never a fabricated page."""
    mock_partition.return_value = [
        MockElement("First paragraph.", page_number=None),
        MockElement("Second paragraph.", page_number=None),
    ]
    mock_get_file_metadata.return_value = {"content_hash": "def456"}

    content = await loader.load("/tmp/fake.html", persist=False)

    assert "Page" not in content
    assert "First paragraph." in content
    assert "Second paragraph." in content
