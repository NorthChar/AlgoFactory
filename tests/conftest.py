import json
from pathlib import Path

import pytest

from algofactory.knowledge.extraction import extract_document
from algofactory.llm.providers import MockProvider
from algofactory.schemas.knowledge import SourceDocument

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def source():
    path = ROOT / "data/customer_churn.txt"
    return SourceDocument.from_text(path.name, path.read_bytes().decode("utf-8"))


@pytest.fixture
def fixtures():
    return json.loads((ROOT / "src/algofactory/llm/fixtures/churn.json").read_text())


@pytest.fixture
def batch(source, fixtures):
    return extract_document(source, MockProvider(fixtures))
