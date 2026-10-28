import re
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pydantic import BaseModel

from postback_debugger.data.db import connect
from postback_debugger.data.seed import seed_database
from postback_debugger.llm import StructuredResult, TextResult, Usage


@pytest.fixture
def db() -> Iterator[sqlite3.Connection]:
    """A freshly seeded in-memory database."""
    conn = connect(":memory:")
    seed_database(conn)
    yield conn
    conn.close()


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    """A seeded database file, for code that opens its own (read-only) connection."""
    path = tmp_path / "mmp.db"
    conn = connect(path)
    seed_database(conn)
    conn.close()
    return path


@dataclass
class FakeProvider:
    """Stands in for a real LLM. `answer` builds the structured reply from the prompt."""

    answer: Callable[[str], BaseModel] | None = None
    text: str = "fake explanation"
    calls: list[tuple[str, str]] = field(default_factory=list)
    name: str = "fake"
    model: str = "fake-model"

    def generate_text(self, system: str, prompt: str) -> TextResult:
        self.calls.append((system, prompt))
        return TextResult(self.text, self.model, Usage(10, 5), None, 1)

    def generate_structured[T: BaseModel](
        self, system: str, prompt: str, schema: type[T]
    ) -> StructuredResult[T]:
        self.calls.append((system, prompt))
        assert self.answer is not None, "FakeProvider.answer is not set"
        data = schema.model_validate(self.answer(prompt).model_dump())
        return StructuredResult(data, self.model, Usage(100, 50, 20), 0.001, 2)


def click_id_in(prompt: str) -> str:
    match = re.search(r"click (clk_[0-9a-f]{8})", prompt)
    assert match, "prompt does not name the click"
    return match.group(1)
