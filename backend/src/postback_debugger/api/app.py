"""FastAPI application: diagnosis endpoints plus the built web UI.

Run with:  uv run --env-file ../.env serve      (from backend/)
"""

import os
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from postback_debugger import repository
from postback_debugger.data.db import connect, default_db_path
from postback_debugger.data.models import OBJECT_ID_PATTERN, FailureType, Platform
from postback_debugger.data.scenarios import SCENARIOS
from postback_debugger.diagnosis import ClickContext, Diagnosis, build_click_context, diagnose_click
from postback_debugger.llm import (
    AVAILABLE_MODELS,
    DEFAULT_PROVIDER,
    LLMError,
    LLMProvider,
    QuotaExceededError,
    Usage,
    configured_providers,
    get_provider,
)

# backend/src/postback_debugger/api/app.py -> repo root / frontend / dist
DEFAULT_FRONTEND_DIST = Path(__file__).resolve().parents[4] / "frontend" / "dist"
EXPECTED = {s.click_id: s.failure_type for s in SCENARIOS}

ProviderFactory = Callable[[str | None, str | None], LLMProvider]


class ProviderInfo(BaseModel):
    name: str
    default_model: str  # first model that still has quota
    models: list[str]
    exhausted_models: list[str]  # quota used up recently; skipped until it resets


class Health(BaseModel):
    status: str
    providers: list[ProviderInfo]  # only providers with credentials configured


class ExampleClick(BaseModel):
    """A seeded scenario click. Deliberately carries no expected answer."""

    click_id: str
    partner_id: str
    platform: Platform
    clicked_at: datetime


class DiagnoseRequest(BaseModel):
    click_id: str = Field(
        pattern=OBJECT_ID_PATTERN,
        description="24-character hex MongoDB ObjectId",
        examples=["6ac769a09e4c2a71d35b3c09"],
    )
    provider: str | None = None
    model: str | None = None


class DiagnoseResponse(BaseModel):
    click_id: str
    diagnosis: Diagnosis
    provider: str
    model: str  # model version that served the request
    usage: Usage
    cost_usd: float | None
    latency_ms: int
    expected_failure_type: FailureType | None  # ground truth, for seeded scenarios only
    requested_model: str
    answered_by: str  # allowed model id that produced the answer (model is its served version)
    skipped_models: list[str]  # tried first but out of quota, so the next model answered


def create_app(
    db_path: Path | None = None,
    provider_factory: ProviderFactory = get_provider,
    frontend_dist: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Postback Debugger", version="0.1.0")
    resolved_db = db_path or default_db_path()

    def get_db() -> Iterator[sqlite3.Connection]:
        if not resolved_db.exists():
            raise HTTPException(503, f"Database not found at {resolved_db}. Run: uv run seed-db")
        # FastAPI may run the dependency and the endpoint in different worker threads.
        with closing(connect(resolved_db, read_only=True, check_same_thread=False)) as conn:
            yield conn

    Db = Annotated[sqlite3.Connection, Depends(get_db)]

    @cache
    def provider_for(name: str | None, model: str | None) -> LLMProvider:
        return provider_factory(name, model)

    # model -> time.monotonic() when its quota should be back. Kept in memory: a restart
    # simply tries again, and a 429 answer costs no quota.
    exhausted_until: dict[str, float] = {}
    UNKNOWN_RESET_S = 3600.0

    def is_exhausted(model: str) -> bool:
        return exhausted_until.get(model, 0.0) > time.monotonic()

    def candidates(name: str, requested: str) -> list[str]:
        """Requested model first, then the provider's other models that still have quota."""
        others = [m for m in AVAILABLE_MODELS[name] if m != requested and not is_exhausted(m)]
        return [requested, *others]

    @app.get("/api/health")
    def health() -> Health:
        configured = configured_providers()
        providers = []
        for name, models in AVAILABLE_MODELS.items():
            if name not in configured:
                continue
            exhausted = [m for m in models if is_exhausted(m)]
            available = [m for m in models if m not in exhausted]
            providers.append(
                ProviderInfo(
                    name=name,
                    default_model=(available or list(models))[0],
                    models=list(models),
                    exhausted_models=exhausted,
                )
            )
        return Health(status="ok", providers=providers)

    @app.get("/api/examples")
    def examples(conn: Db) -> list[ExampleClick]:
        clicks = [repository.get_click(conn, s.click_id) for s in SCENARIOS]
        return [
            ExampleClick(
                click_id=c.click_id,
                partner_id=c.partner_id,
                platform=c.platform,
                clicked_at=c.clicked_at,
            )
            for c in clicks
            if c is not None
        ]

    @app.get("/api/clicks/{click_id}/context")
    def click_context(click_id: str, conn: Db) -> ClickContext:
        context = build_click_context(conn, click_id)
        if context is None:
            raise HTTPException(404, f"Unknown click_id: {click_id}")
        return context

    @app.post("/api/diagnoses")
    def diagnose(request: DiagnoseRequest, conn: Db) -> DiagnoseResponse:
        if repository.get_click(conn, request.click_id) is None:
            raise HTTPException(404, f"Unknown click_id: {request.click_id}")
        name = request.provider or os.environ.get("LLM_PROVIDER") or DEFAULT_PROVIDER
        if name not in AVAILABLE_MODELS:
            raise HTTPException(400, f"Unknown provider: {name}")
        if request.model is not None and request.model not in AVAILABLE_MODELS[name]:
            raise HTTPException(400, f"Model {request.model} is not enabled for {name}")

        requested = request.model or AVAILABLE_MODELS[name][0]
        skipped: list[str] = []
        result = None
        answered_by = requested
        for model in candidates(name, requested):
            if is_exhausted(model):  # only the requested model can still be marked here
                skipped.append(model)
                continue
            try:
                provider = provider_for(name, model)
                result = diagnose_click(provider, conn, request.click_id)
                answered_by = model
                break
            except QuotaExceededError as exc:
                wait = exc.retry_after_s or UNKNOWN_RESET_S
                exhausted_until[model] = time.monotonic() + wait
                skipped.append(model)
            except LLMError as exc:
                raise HTTPException(502, str(exc)) from exc
        if result is None:
            raise HTTPException(
                429,
                f"Every {name} model is out of quota right now ({', '.join(skipped)}). "
                "Free-tier quotas reset daily; try again later or add another provider key.",
            )

        return DiagnoseResponse(
            click_id=request.click_id,
            diagnosis=result.data,
            provider=provider.name,
            model=result.model,
            usage=result.usage,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
            expected_failure_type=EXPECTED.get(request.click_id),
            requested_model=requested,
            answered_by=answered_by,
            skipped_models=skipped,
        )

    dist = frontend_dist or Path(os.environ.get("FRONTEND_DIST") or DEFAULT_FRONTEND_DIST)
    if dist.is_dir():  # built UI (npm run build); in development Vite serves it instead
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app


app = create_app()


def main() -> None:
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("postback_debugger.api.app:app", host=host, port=port)
