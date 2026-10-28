"""Command line interface.

Usage (from backend/, with keys in the repo-root .env):
    uv run --env-file ../.env pbd explain <postback_id>
    uv run --env-file ../.env pbd diagnose <click_id>
    uv run --env-file ../.env pbd diagnose --all
"""

import argparse
import sqlite3
import time
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

from postback_debugger import repository
from postback_debugger.data.db import connect, default_db_path
from postback_debugger.data.scenarios import SCENARIOS
from postback_debugger.diagnosis import diagnose_click, explain_postback
from postback_debugger.llm import LLMError, LLMProvider, QuotaExceededError, Usage, get_provider


def _format_usage(model: str, usage: Usage, cost: float | None, latency_ms: int) -> str:
    cost_text = f"${cost:.4f}" if cost is not None else "n/a (free tier or unknown price)"
    return (
        f"{model} | {usage.input_tokens:,} in / {usage.output_tokens:,} out "
        f"(thinking {usage.thinking_tokens:,}) | cost {cost_text} | {latency_ms / 1000:.1f} s"
    )


def _explain(provider: LLMProvider, conn: sqlite3.Connection, postback_id: str) -> int:
    log = repository.get_postback_log(conn, postback_id)
    if log is None:
        print(f"Unknown postback_id: {postback_id}")
        return 1
    result = explain_postback(provider, log)
    print(result.text.strip())
    print("\n" + _format_usage(result.model, result.usage, result.cost_usd, result.latency_ms))
    return 0


def _diagnose_one(provider: LLMProvider, conn: sqlite3.Connection, click_id: str) -> int:
    if repository.get_click(conn, click_id) is None:
        print(f"Unknown click_id: {click_id}")
        return 1
    result = diagnose_click(provider, conn, click_id)
    d = result.data
    print(f"Click {click_id}  ->  {d.failure_type}")
    print(f"\nSummary: {d.summary}")
    print("\nEvidence:")
    for item in d.evidence:
        print(f"  - {item}")
    print(f"\nFix: {d.recommended_fix}")
    print("\n" + _format_usage(result.model, result.usage, result.cost_usd, result.latency_ms))
    return 0


def _diagnose_all(provider: LLMProvider, conn: sqlite3.Connection, pause: float) -> int:
    """Diagnose every seeded scenario and compare with the expected failure type."""
    print(f"{'click_id':<14}{'expected':<28}{'diagnosed':<28}{'ok':<4}{'tokens':>8}{'time':>8}")
    correct = input_tokens = output_tokens = latency_ms = 0
    costs: list[float] = []
    for i, scenario in enumerate(SCENARIOS):
        if i and pause:
            time.sleep(pause)
        try:
            result = diagnose_click(provider, conn, scenario.click_id)
        except QuotaExceededError as exc:
            print(f"\nStopped after {i} of {len(SCENARIOS)} scenarios: {exc}")
            break  # every further call would fail the same way and waste attempts
        except LLMError as exc:
            print(f"{scenario.click_id:<14}{scenario.failure_type:<28}{'ERROR: ' + str(exc)[:60]}")
            continue
        ok = result.data.failure_type == scenario.failure_type
        correct += ok
        input_tokens += result.usage.input_tokens
        output_tokens += result.usage.output_tokens
        latency_ms += result.latency_ms
        if result.cost_usd is not None:
            costs.append(result.cost_usd)
        tokens = result.usage.input_tokens + result.usage.output_tokens
        print(
            f"{scenario.click_id:<14}{scenario.failure_type:<28}{result.data.failure_type:<28}"
            f"{'✓' if ok else '✗':<4}{tokens:>8,}{result.latency_ms / 1000:>7.1f}s"
        )
    cost_text = f"${sum(costs):.4f}" if costs else "n/a"
    print(
        f"\nScore {correct}/{len(SCENARIOS)} | {input_tokens:,} in / {output_tokens:,} out tokens"
        f" | cost {cost_text} | model time {latency_ms / 1000:.1f} s"
    )
    return 0 if correct == len(SCENARIOS) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pbd", description="Postback debugger.")
    parser.add_argument("--provider", help="gemini or claude (default: $LLM_PROVIDER or gemini)")
    parser.add_argument("--model", help="model id (default: provider's default)")
    parser.add_argument("--db", type=Path, default=None, help="SQLite file (default: seeded DB)")
    commands = parser.add_subparsers(dest="command", required=True)

    explain = commands.add_parser("explain", help="explain one postback log in plain English")
    explain.add_argument("postback_id")

    diagnose = commands.add_parser("diagnose", help="structured diagnosis for a click")
    target = diagnose.add_mutually_exclusive_group(required=True)
    target.add_argument("click_id", nargs="?")
    target.add_argument("--all", action="store_true", help="score every seeded scenario")
    diagnose.add_argument(
        "--pause", type=float, default=0.0, help="seconds between calls (free-tier rate limits)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = args.db or default_db_path()
    if not db_path.exists():
        print(f"Database not found at {db_path}. Create it with: uv run seed-db")
        return 1

    try:
        provider = get_provider(args.provider, args.model)
        with closing(connect(db_path, read_only=True)) as conn:
            if args.command == "explain":
                return _explain(provider, conn, args.postback_id)
            if args.all:
                return _diagnose_all(provider, conn, args.pause)
            return _diagnose_one(provider, conn, args.click_id)
    except (LLMError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1
    except sqlite3.Error as exc:
        print(f"Database error ({db_path}): {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
