from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from postback_debugger.api.app import create_app
from postback_debugger.data.models import FailureType
from postback_debugger.data.scenarios import SCENARIOS, SCENARIOS_BY_TYPE
from postback_debugger.diagnosis import Diagnosis
from postback_debugger.llm import AVAILABLE_MODELS, LLMError, QuotaExceededError
from tests.conftest import FakeProvider, click_id_in

TIMEOUT_CLICK = SCENARIOS_BY_TYPE[FailureType.TIMEOUT].click_id


def _correct(prompt: str) -> Diagnosis:
    expected = {s.click_id: s.failure_type for s in SCENARIOS}[click_id_in(prompt)]
    return Diagnosis(failure_type=expected, summary="s", evidence=["e"], recommended_fix="f")


def _client(db_file: Path, provider: FakeProvider, tmp_path: Path) -> TestClient:
    app = create_app(
        db_path=db_file,
        provider_factory=lambda name, model: provider,
        frontend_dist=tmp_path / "no-ui",
    )
    return TestClient(app)


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider(answer=_correct)


@pytest.fixture
def client(db_file: Path, fake: FakeProvider, tmp_path: Path) -> TestClient:
    return _client(db_file, fake, tmp_path)


def test_health_lists_only_configured_providers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test")

    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert [p["name"] for p in body["providers"]] == ["gemini"]
    assert body["providers"][0]["default_model"] == body["providers"][0]["models"][0]


def test_examples_never_reveal_the_answer(client: TestClient) -> None:
    examples = client.get("/api/examples").json()
    assert [e["click_id"] for e in examples] == [s.click_id for s in SCENARIOS]
    assert all(set(e) == {"click_id", "partner_id", "platform", "clicked_at"} for e in examples)


def test_click_context(client: TestClient) -> None:
    body = client.get(f"/api/clicks/{TIMEOUT_CLICK}/context").json()
    assert body["click"]["click_id"] == TIMEOUT_CLICK
    assert len(body["postback_logs"]) == 3
    assert client.get("/api/clicks/clk_00000000/context").status_code == 404


def test_diagnose_returns_diagnosis_usage_and_ground_truth(
    client: TestClient, fake: FakeProvider
) -> None:
    response = client.post("/api/diagnoses", json={"click_id": TIMEOUT_CLICK})

    assert response.status_code == 200
    body = response.json()
    assert body["diagnosis"]["failure_type"] == "timeout"
    assert body["expected_failure_type"] == "timeout"
    assert body["usage"] == {"input_tokens": 100, "output_tokens": 50, "thinking_tokens": 20}
    assert body["provider"] == "fake" and body["cost_usd"] == 0.001
    assert len(fake.calls) == 1


def test_diagnose_unknown_click_makes_no_model_call(client: TestClient, fake: FakeProvider) -> None:
    response = client.post("/api/diagnoses", json={"click_id": "clk_00000000"})
    assert response.status_code == 404
    assert fake.calls == []


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"click_id": TIMEOUT_CLICK, "provider": "openai"}, 400),
        ({"click_id": TIMEOUT_CLICK, "provider": "gemini", "model": "not-a-model"}, 400),
        ({"click_id": ""}, 422),
    ],
)
def test_diagnose_rejects_bad_requests(
    client: TestClient, payload: dict[str, str], status: int
) -> None:
    assert client.post("/api/diagnoses", json=payload).status_code == status


def test_other_llm_errors_become_502(db_file: Path, tmp_path: Path) -> None:
    def fail(prompt: str) -> Diagnosis:
        raise LLMError("model broke")

    client = _client(db_file, FakeProvider(answer=fail), tmp_path)
    response = client.post("/api/diagnoses", json={"click_id": TIMEOUT_CLICK})
    assert response.status_code == 502
    assert response.json()["detail"] == "model broke"


class PerModelFake:
    """Provider factory whose models in `out_of_quota` raise QuotaExceededError."""

    def __init__(self, out_of_quota: set[str]) -> None:
        self.out_of_quota = out_of_quota
        self.calls: list[str] = []

    def __call__(self, name: str | None, model: str | None) -> FakeProvider:
        def answer(prompt: str) -> Diagnosis:
            self.calls.append(model or "")
            if model in self.out_of_quota:
                raise QuotaExceededError(f"{model} quota gone", retry_after_s=3600)
            return _correct(prompt)

        return FakeProvider(answer=answer, model=model or "")


def _gemini_models(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    models = ["m-flash", "m-lite", "m-other"]
    monkeypatch.setitem(AVAILABLE_MODELS, "gemini", tuple(models))
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    return models


def test_falls_back_to_next_model_and_remembers_exhaustion(
    db_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flash, lite, _ = _gemini_models(monkeypatch)
    factory = PerModelFake(out_of_quota={flash})
    client = TestClient(create_app(db_file, factory, tmp_path / "no-ui"))

    body = client.post(
        "/api/diagnoses", json={"click_id": TIMEOUT_CLICK, "provider": "gemini", "model": flash}
    ).json()
    assert body["requested_model"] == flash
    assert body["skipped_models"] == [flash]
    assert body["model"] == lite and body["answered_by"] == lite
    assert factory.calls == [flash, lite]

    gemini = client.get("/api/health").json()["providers"][0]
    assert gemini["exhausted_models"] == [flash]
    assert gemini["default_model"] == lite

    # The exhausted model is not called again while its quota is out.
    factory.calls.clear()
    body = client.post(
        "/api/diagnoses", json={"click_id": TIMEOUT_CLICK, "provider": "gemini", "model": flash}
    ).json()
    assert factory.calls == [lite] and body["skipped_models"] == [flash]


def test_all_models_out_of_quota_is_429(
    db_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models = _gemini_models(monkeypatch)
    factory = PerModelFake(out_of_quota=set(models))
    client = TestClient(create_app(db_file, factory, tmp_path / "no-ui"))

    response = client.post("/api/diagnoses", json={"click_id": TIMEOUT_CLICK, "provider": "gemini"})
    assert response.status_code == 429
    assert "out of quota" in response.json()["detail"]
    assert factory.calls == models


def test_missing_database_is_a_clear_503(tmp_path: Path, fake: FakeProvider) -> None:
    client = _client(tmp_path / "missing.db", fake, tmp_path)
    response = client.get("/api/examples")
    assert response.status_code == 503
    assert "seed-db" in response.json()["detail"]


def test_serves_built_frontend(db_file: Path, fake: FakeProvider, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<h1>ui</h1>")
    app = create_app(db_path=db_file, provider_factory=lambda n, m: fake, frontend_dist=dist)
    client = TestClient(app)

    assert client.get("/").text == "<h1>ui</h1>"
    assert client.get("/api/examples").status_code == 200  # API routes still win
