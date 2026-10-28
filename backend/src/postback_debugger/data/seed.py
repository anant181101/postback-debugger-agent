"""Generate the synthetic MMP database.

Usage:
    uv run seed-db [--db PATH] [--seed N]
"""

import argparse
import json
import random
import re
import sqlite3
import uuid
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel

from postback_debugger.data.db import connect, default_db_path, init_db
from postback_debugger.data.models import (
    AttributionStatus,
    Click,
    Event,
    FailureType,
    Install,
    Partner,
    Platform,
    PostbackLog,
    PostbackStatus,
    PostbackType,
    is_2xx,
)
from postback_debugger.data.scenarios import SCENARIOS

DEFAULT_SEED = 42
BASE_TIME = datetime(2026, 10, 1, tzinfo=UTC)
APP_IDS = {Platform.ANDROID: "com.example.puzzlequest", Platform.IOS: "id6400000001"}

POSTBACK_DELAY = timedelta(seconds=5)  # time between a tracked install/event and its postback
RETRY_DELAYS = (timedelta(0), timedelta(minutes=1), timedelta(minutes=5))  # from first attempt

BACKGROUND_CLICKS = 50
BACKGROUND_PARTNERS = ("alpha_ads", "beta_media")
INSTALL_RATE = 0.4
PURCHASE_RATE = 0.5

PARTNERS: tuple[Partner, ...] = (
    Partner(
        partner_id="alpha_ads",
        name="AlphaAds",
        postback_url_template=(
            "https://alpha-ads.example/postback"
            "?click_id={click_id}&event={event_name}&revenue={revenue}"
        ),
        event_mapping={
            "install": "install",
            "registration": "complete_registration",
            "purchase": "purchase",
        },
        attribution_window_hours=168,
        timeout_ms=3000,
        max_attempts=3,
    ),
    Partner(
        partner_id="beta_media",
        name="BetaMedia",
        postback_url_template=(
            "https://track.beta-media.example/s2s?cid={click_id}&adid={advertising_id}&ev={event_name}"
        ),
        event_mapping={"install": "inst", "purchase": "buy"},
        attribution_window_hours=168,
        timeout_ms=3000,
        max_attempts=3,
    ),
    Partner(
        partner_id="gamma_network",
        name="GammaNetwork",
        postback_url_template="https://gamma-network.example/cb?clickid={click_id}&type={event_name}",
        event_mapping={"install": "install", "purchase": "purchase"},
        attribution_window_hours=72,
        timeout_ms=2000,
        max_attempts=3,
    ),
    Partner(
        partner_id="delta_reach",
        name="DeltaReach",
        postback_url_template=(
            "https://api.delta-reach.example/v1/conversions"
            "?click={click_id}&event={event_name}&key={api_key}"
        ),
        event_mapping={"install": "install"},
        attribution_window_hours=168,
        timeout_ms=3000,
        max_attempts=3,
        api_key="dk_test_7f3a9c51",
        api_key_expires_at=datetime(2026, 10, 5, tzinfo=UTC),
    ),
)

MACRO_PATTERN = re.compile(r"\{(\w+)\}")


def render_url(template: str, values: dict[str, str | None]) -> str:
    """Fill {macro} placeholders with URL-encoded values.

    Macros without a value are left in the URL unchanged, which is how the
    missing-macro scenario produces a broken postback.
    """

    def replace(match: re.Match[str]) -> str:
        value = values.get(match.group(1))
        return match.group(0) if value is None else quote(value, safe="")

    return MACRO_PATTERN.sub(replace, template)


@dataclass(frozen=True)
class Response:
    """What a partner endpoint returned for one postback attempt."""

    http_status: int | None
    body: str | None
    latency_ms: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return is_2xx(self.http_status)


OK = Response(200, '{"status":"ok"}', 140)


class Dataset:
    """In-memory records plus helpers that keep them consistent with each other."""

    def __init__(self, partners: Sequence[Partner], rng: random.Random) -> None:
        self.partners = {p.partner_id: p for p in partners}
        self.rng = rng
        self.clicks: list[Click] = []
        self.installs: list[Install] = []
        self.events: list[Event] = []
        self.postback_logs: list[PostbackLog] = []

    def tables(self) -> dict[str, Sequence[BaseModel]]:
        """Records per table, in foreign-key order (parents first)."""
        return {
            "partners": list(self.partners.values()),
            "clicks": self.clicks,
            "installs": self.installs,
            "events": self.events,
            "postback_logs": self.postback_logs,
        }

    def new_id(self, prefix: str, hex_digits: int = 12) -> str:
        return f"{prefix}_{self.rng.getrandbits(hex_digits * 4):0{hex_digits}x}"

    def add_click(
        self,
        partner_id: str,
        clicked_at: datetime,
        *,
        click_id: str | None = None,
        device_id: str | None = None,
        platform: Platform = Platform.ANDROID,
        campaign_id: str = "cmp_autumn_launch",
    ) -> Click:
        if partner_id not in self.partners:
            raise ValueError(f"unknown partner: {partner_id}")
        click = Click(
            click_id=click_id or self.new_id("clk", 8),
            partner_id=partner_id,
            campaign_id=campaign_id,
            app_id=APP_IDS[platform],
            platform=platform,
            device_id=device_id or self.new_id("dev"),
            clicked_at=clicked_at,
        )
        self.clicks.append(click)
        return click

    def add_install(
        self,
        device_id: str,
        installed_at: datetime,
        *,
        status: AttributionStatus,
        click: Click | None = None,
        platform: Platform = Platform.ANDROID,
        ad_tracking: bool = True,
        rejection_reason: str | None = None,
    ) -> Install:
        advertising_id = str(uuid.UUID(int=self.rng.getrandbits(128), version=4))
        install = Install(
            install_id=self.new_id("ins"),
            app_id=APP_IDS[platform],
            platform=platform,
            device_id=device_id,
            advertising_id=advertising_id if ad_tracking else None,
            installed_at=installed_at,
            attribution_status=status,
            click_id=click.click_id if click else None,
            rejection_reason=rejection_reason,
        )
        self.installs.append(install)
        return install

    def add_event(
        self,
        install: Install,
        event_name: str,
        event_time: datetime,
        *,
        revenue: float | None = None,
    ) -> Event:
        event = Event(
            event_id=self.new_id("evt"),
            install_id=install.install_id,
            event_name=event_name,
            revenue=revenue,
            currency="USD" if revenue is not None else None,
            event_time=event_time,
        )
        self.events.append(event)
        return event

    def send_postback(
        self,
        click: Click,
        install: Install,
        sent_at: datetime,
        responses: Sequence[Response],
        *,
        event: Event | None = None,
    ) -> list[PostbackLog]:
        """Record one log row per delivery attempt; `responses` holds each attempt's outcome."""
        partner = self.partners[click.partner_id]
        if (
            install.attribution_status is not AttributionStatus.ATTRIBUTED
            or install.click_id != click.click_id
        ):
            raise ValueError("postbacks are sent only for the click an install is attributed to")
        if event is not None and event.install_id != install.install_id:
            raise ValueError("event does not belong to this install")
        max_attempts = min(partner.max_attempts, len(RETRY_DELAYS))
        if not 1 <= len(responses) <= max_attempts:
            raise ValueError(f"{partner.partner_id} allows 1..{max_attempts} attempts")
        if any(r.ok for r in responses[:-1]):
            raise ValueError("no retries are made after a successful delivery")

        mmp_event = event.event_name if event else "install"
        if mmp_event not in partner.event_mapping:
            raise ValueError(f"{partner.partner_id} has no mapping for event {mmp_event!r}")
        revenue = event.revenue if event else None
        url = render_url(
            partner.postback_url_template,
            {
                "click_id": click.click_id,
                "install_id": install.install_id,
                "event_name": partner.event_mapping[mmp_event],
                "revenue": f"{revenue:.2f}" if revenue is not None else "0",
                "advertising_id": install.advertising_id,
                "api_key": partner.api_key,
            },
        )

        logs = []
        for attempt, response in enumerate(responses, start=1):
            log = PostbackLog(
                postback_id=f"pb_{len(self.postback_logs) + 1:06d}",
                partner_id=partner.partner_id,
                click_id=click.click_id,
                install_id=install.install_id,
                event_id=event.event_id if event else None,
                postback_type=PostbackType.EVENT if event else PostbackType.INSTALL,
                url=url,
                attempt=attempt,
                status=PostbackStatus.SUCCESS if response.ok else PostbackStatus.FAILED,
                http_status=response.http_status,
                response_body=response.body,
                error=response.error,
                latency_ms=response.latency_ms,
                sent_at=sent_at + RETRY_DELAYS[attempt - 1],
            )
            self.postback_logs.append(log)
            logs.append(log)
        return logs


def _day(n: int, hour: int = 10) -> datetime:
    """Timestamp `n` days after BASE_TIME at the given hour."""
    return BASE_TIME + timedelta(days=n, hours=hour)


def _attributed_install(
    ds: Dataset, click: Click, delay: timedelta, *, ad_tracking: bool = True
) -> Install:
    return ds.add_install(
        click.device_id,
        click.clicked_at + delay,
        status=AttributionStatus.ATTRIBUTED,
        click=click,
        platform=click.platform,
        ad_tracking=ad_tracking,
    )


# --- Scenarios: one builder per FailureType -------------------------------------------


def _delivered(ds: Dataset, click_id: str) -> None:
    click = ds.add_click("alpha_ads", _day(0), click_id=click_id)
    install = _attributed_install(ds, click, timedelta(hours=2))
    ds.send_postback(click, install, install.installed_at + POSTBACK_DELAY, [OK])
    purchase = ds.add_event(
        install, "purchase", install.installed_at + timedelta(days=1), revenue=4.99
    )
    ds.send_postback(click, install, purchase.event_time + POSTBACK_DELAY, [OK], event=purchase)


def _no_install(ds: Dataset, click_id: str) -> None:
    ds.add_click("alpha_ads", _day(1), click_id=click_id)


def _attributed_to_other_click(ds: Dataset, click_id: str) -> None:
    ours = ds.add_click("alpha_ads", _day(2, hour=9), click_id=click_id)
    competing = ds.add_click(
        "gamma_network", _day(2, hour=15), device_id=ours.device_id, campaign_id="cmp_retarget"
    )
    install = _attributed_install(ds, competing, timedelta(hours=1))
    ds.send_postback(competing, install, install.installed_at + POSTBACK_DELAY, [OK])


def _outside_attribution_window(ds: Dataset, click_id: str) -> None:
    click = ds.add_click("alpha_ads", _day(3), click_id=click_id)
    ds.add_install(
        click.device_id,
        click.clicked_at + timedelta(days=9),
        status=AttributionStatus.ORGANIC,
        platform=click.platform,
    )


def _fraud_rejected(ds: Dataset, click_id: str) -> None:
    click = ds.add_click("beta_media", _day(4, hour=12), click_id=click_id)
    ds.add_install(
        click.device_id,
        click.clicked_at + timedelta(seconds=4),
        status=AttributionStatus.REJECTED,
        click=click,
        platform=click.platform,
        rejection_reason="click_to_install_time_too_short",
    )


def _event_not_mapped(ds: Dataset, click_id: str) -> None:
    click = ds.add_click("alpha_ads", _day(5), click_id=click_id)
    install = _attributed_install(ds, click, timedelta(hours=1))
    ds.send_postback(click, install, install.installed_at + POSTBACK_DELAY, [OK])
    registration = ds.add_event(install, "registration", install.installed_at + timedelta(hours=1))
    ds.send_postback(
        click, install, registration.event_time + POSTBACK_DELAY, [OK], event=registration
    )
    # The app renamed its purchase event; the partner mapping only knows "purchase".
    ds.add_event(install, "purchase_v2", install.installed_at + timedelta(hours=3), revenue=9.99)


def _partner_5xx(ds: Dataset, click_id: str) -> None:
    click = ds.add_click("gamma_network", _day(6), click_id=click_id)
    install = _attributed_install(ds, click, timedelta(hours=1))
    unavailable = Response(503, '{"error":"service unavailable"}', 85)
    ds.send_postback(click, install, install.installed_at + POSTBACK_DELAY, [unavailable] * 3)


def _timeout(ds: Dataset, click_id: str) -> None:
    click = ds.add_click("gamma_network", _day(7), click_id=click_id)
    install = _attributed_install(ds, click, timedelta(hours=1))
    timeout_ms = ds.partners["gamma_network"].timeout_ms
    timed_out = Response(None, None, timeout_ms, error=f"timeout after {timeout_ms} ms")
    ds.send_postback(click, install, install.installed_at + POSTBACK_DELAY, [timed_out] * 3)


def _partner_4xx(ds: Dataset, click_id: str) -> None:
    # Sent after DeltaReach's api_key_expires_at; client errors are not retried.
    click = ds.add_click("delta_reach", _day(9), click_id=click_id)
    install = _attributed_install(ds, click, timedelta(minutes=30))
    unauthorized = Response(401, '{"error":"api key expired"}', 95)
    ds.send_postback(click, install, install.installed_at + POSTBACK_DELAY, [unauthorized])


def _missing_macro(ds: Dataset, click_id: str) -> None:
    click = ds.add_click("beta_media", _day(10), click_id=click_id, platform=Platform.IOS)
    install = _attributed_install(ds, click, timedelta(hours=1), ad_tracking=False)
    bad_request = Response(400, '{"error":"invalid parameter: adid"}', 70)
    ds.send_postback(click, install, install.installed_at + POSTBACK_DELAY, [bad_request])


def _duplicate(ds: Dataset, click_id: str) -> None:
    click = ds.add_click("alpha_ads", _day(11), click_id=click_id)
    install = _attributed_install(ds, click, timedelta(hours=1))
    ds.send_postback(click, install, install.installed_at + POSTBACK_DELAY, [OK])
    first = ds.add_event(
        install, "purchase", install.installed_at + timedelta(hours=2), revenue=19.99
    )
    second = ds.add_event(
        install, "purchase", first.event_time + timedelta(seconds=2), revenue=19.99
    )
    ds.send_postback(click, install, first.event_time + POSTBACK_DELAY, [OK], event=first)
    conflict = Response(409, '{"error":"duplicate conversion"}', 110)
    ds.send_postback(click, install, second.event_time + POSTBACK_DELAY, [conflict], event=second)


SCENARIO_BUILDERS: dict[FailureType, Callable[[Dataset, str], None]] = {
    FailureType.NONE: _delivered,
    FailureType.NO_INSTALL: _no_install,
    FailureType.ATTRIBUTED_TO_OTHER_CLICK: _attributed_to_other_click,
    FailureType.OUTSIDE_ATTRIBUTION_WINDOW: _outside_attribution_window,
    FailureType.FRAUD_REJECTED: _fraud_rejected,
    FailureType.EVENT_NOT_MAPPED: _event_not_mapped,
    FailureType.PARTNER_4XX: _partner_4xx,
    FailureType.PARTNER_5XX: _partner_5xx,
    FailureType.TIMEOUT: _timeout,
    FailureType.MISSING_MACRO: _missing_macro,
    FailureType.DUPLICATE: _duplicate,
}


def _add_background_traffic(ds: Dataset, count: int) -> None:
    """Healthy traffic, so scenario rows are not the only rows in the database."""
    for _ in range(count):
        partner_id = ds.rng.choice(BACKGROUND_PARTNERS)
        clicked_at = BASE_TIME + timedelta(minutes=ds.rng.randrange(14 * 24 * 60))
        click = ds.add_click(partner_id, clicked_at)
        if ds.rng.random() >= INSTALL_RATE:
            continue
        install = _attributed_install(ds, click, timedelta(minutes=ds.rng.randint(5, 720)))
        delivered = Response(200, OK.body, ds.rng.randint(60, 400))
        ds.send_postback(click, install, install.installed_at + POSTBACK_DELAY, [delivered])
        if ds.rng.random() < PURCHASE_RATE:
            purchase = ds.add_event(
                install,
                "purchase",
                install.installed_at + timedelta(hours=ds.rng.randint(1, 48)),
                revenue=ds.rng.choice([0.99, 4.99, 9.99]),
            )
            ds.send_postback(
                click, install, purchase.event_time + POSTBACK_DELAY, [delivered], event=purchase
            )


def build_dataset(seed: int = DEFAULT_SEED) -> Dataset:
    """Build all records in memory. The same seed always produces the same dataset."""
    ds = Dataset(PARTNERS, random.Random(seed))
    for scenario in SCENARIOS:
        SCENARIO_BUILDERS[scenario.failure_type](ds, scenario.click_id)
    _add_background_traffic(ds, BACKGROUND_CLICKS)
    return ds


def _to_row(record: BaseModel) -> dict[str, object]:
    row = record.model_dump(mode="json")
    return {k: json.dumps(v) if isinstance(v, dict) else v for k, v in row.items()}


def write_dataset(conn: sqlite3.Connection, ds: Dataset) -> None:
    for table, records in ds.tables().items():
        if not records:
            continue
        rows = [_to_row(r) for r in records]
        columns = list(rows[0])
        # Table and column names come from our own models, never from user input.
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) "
            f"VALUES ({', '.join(':' + c for c in columns)})"
        )
        conn.executemany(sql, rows)


def seed_database(conn: sqlite3.Connection, seed: int = DEFAULT_SEED) -> Dataset:
    """Recreate the schema and fill it with a freshly built dataset."""
    ds = build_dataset(seed)
    with conn:  # schema reset and inserts commit together, or roll back together
        init_db(conn)
        write_dataset(conn, ds)
    return ds


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create the synthetic MMP database.")
    parser.add_argument("--db", type=Path, default=default_db_path(), help="SQLite file to write")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed")
    args = parser.parse_args(argv)

    args.db.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(args.db)) as conn:
        ds = seed_database(conn, args.seed)

    for table, records in ds.tables().items():
        print(f"{table:<14} {len(records):>4}")
    print(f"Wrote {args.db}")


if __name__ == "__main__":
    main()
