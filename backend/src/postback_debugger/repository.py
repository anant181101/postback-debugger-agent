"""Read-only queries over the MMP database. Every function returns Pydantic models."""

import sqlite3

from pydantic import BaseModel

from postback_debugger.data.models import Click, Event, Install, Partner, PostbackLog


def _one[T: BaseModel](
    conn: sqlite3.Connection, model: type[T], sql: str, params: tuple[str, ...]
) -> T | None:
    row = conn.execute(sql, params).fetchone()
    return model.model_validate(dict(row)) if row else None


def _all[T: BaseModel](
    conn: sqlite3.Connection, model: type[T], sql: str, params: tuple[str, ...]
) -> list[T]:
    return [model.model_validate(dict(row)) for row in conn.execute(sql, params)]


def get_click(conn: sqlite3.Connection, click_id: str) -> Click | None:
    return _one(conn, Click, "SELECT * FROM clicks WHERE click_id = ?", (click_id,))


def get_clicks_for_device(conn: sqlite3.Connection, device_id: str) -> list[Click]:
    sql = "SELECT * FROM clicks WHERE device_id = ? ORDER BY clicked_at"
    return _all(conn, Click, sql, (device_id,))


def get_partner(conn: sqlite3.Connection, partner_id: str) -> Partner | None:
    return _one(conn, Partner, "SELECT * FROM partners WHERE partner_id = ?", (partner_id,))


def get_installs_for_device(conn: sqlite3.Connection, device_id: str) -> list[Install]:
    sql = "SELECT * FROM installs WHERE device_id = ? ORDER BY installed_at"
    return _all(conn, Install, sql, (device_id,))


def get_events_for_install(conn: sqlite3.Connection, install_id: str) -> list[Event]:
    sql = "SELECT * FROM events WHERE install_id = ? ORDER BY event_time"
    return _all(conn, Event, sql, (install_id,))


def get_postback_logs_for_click(conn: sqlite3.Connection, click_id: str) -> list[PostbackLog]:
    sql = "SELECT * FROM postback_logs WHERE click_id = ? ORDER BY sent_at, attempt"
    return _all(conn, PostbackLog, sql, (click_id,))


def get_postback_log(conn: sqlite3.Connection, postback_id: str) -> PostbackLog | None:
    sql = "SELECT * FROM postback_logs WHERE postback_id = ?"
    return _one(conn, PostbackLog, sql, (postback_id,))
