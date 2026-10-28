import sqlite3
from collections.abc import Iterator

import pytest

from postback_debugger.data.db import connect
from postback_debugger.data.seed import seed_database


@pytest.fixture
def db() -> Iterator[sqlite3.Connection]:
    """A freshly seeded in-memory database."""
    conn = connect(":memory:")
    seed_database(conn)
    yield conn
    conn.close()
