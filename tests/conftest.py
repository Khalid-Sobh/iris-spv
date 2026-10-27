"""Shared test helpers: an in-memory staging DB and the shipped fixtures."""
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from iris_spv.load import Db, Loader
from iris_spv.logging_setup import get_logger
from iris_spv.sources.file_source import FileSource

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)   # fixed "today": tests never depend on the clock


@pytest.fixture
def loader():
    """Fresh in-memory SQLite DB with the staging schema (iris_staging.*)."""
    db = Db("sqlite:///:memory:")
    ld = Loader(db)
    ld.init_schema()
    yield ld
    db.close()


@pytest.fixture
def log():
    return get_logger("test", "testrun")


@pytest.fixture
def fixture_source():
    return FileSource(str(FIXTURES / "handelsregister_sample.jsonl"), name="fixture")


@pytest.fixture
def reference_source():
    return FileSource(str(FIXTURES / "reference_sample.jsonl"), name="reference")
