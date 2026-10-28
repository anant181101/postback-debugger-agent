import { useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  type ClickContext,
  type DiagnoseResponse,
  type ExampleClick,
  type Health,
} from "./api";
import { DataTimeline } from "./components/DataTimeline";
import { DiagnosisCard, DiagnosisError, DiagnosisLoading } from "./components/DiagnosisCard";
import { EmptyState } from "./components/EmptyState";
import {
  IconAlert,
  IconCopy,
  IconPlay,
  IconRefresh,
  IconSearch,
  IconTerminal,
} from "./components/Icons";
import { JourneyFlow } from "./components/JourneyFlow";
import { PartnerAvatar } from "./components/PartnerAvatar";
import { RecentTable, type RecentRun } from "./components/RecentTable";
import { FAILURE_LABELS, FAILURE_TONES, formatTime } from "./format";

const OBJECT_ID = /^[0-9a-f]{24}$/; // click ids are MongoDB ObjectIds
const MODEL_KEY = "pbd.model"; // remembered model choice, "provider::model"

function readStoredModel(): string | null {
  try {
    return localStorage.getItem(MODEL_KEY);
  } catch {
    return null;
  }
}

function storeModel(value: string) {
  try {
    localStorage.setItem(MODEL_KEY, value);
  } catch {
    // storage unavailable (private mode); the choice just isn't remembered
  }
}

/** Plain-text report for pasting into a ticket or chat. */
function buildReport(result: DiagnoseResponse): string {
  const d = result.diagnosis;
  return [
    `Postback diagnosis for ${result.click_id}`,
    `Root cause: ${FAILURE_LABELS[d.failure_type]}`,
    "",
    d.summary,
    "",
    "Evidence:",
    ...d.evidence.map((e, i) => `${i + 1}. ${e}`),
    "",
    `Recommended action: ${d.recommended_fix}`,
    "",
    `Model: ${result.model} · ${(result.latency_ms / 1000).toFixed(1)} s`,
  ].join("\n");
}

interface ErrorState {
  status: number;
  message: string;
}

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [examples, setExamples] = useState<ExampleClick[]>([]);
  const [model, setModel] = useState<string>("");
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [context, setContext] = useState<ClickContext | null>(null);
  const [result, setResult] = useState<DiagnoseResponse | null>(null);
  const [error, setError] = useState<ErrorState | null>(null);
  const [loading, setLoading] = useState(false);
  const [runs, setRuns] = useState<RecentRun[]>([]);
  const [copied, setCopied] = useState(false);
  const runId = useRef(0); // ignores responses from an older run if the user starts a new one

  useEffect(() => {
    api
      .health()
      .then((h) => {
        setHealth(h);
        const usable = h.providers.flatMap((p) =>
          p.models.filter((m) => !p.exhausted_models.includes(m)).map((m) => `${p.name}::${m}`),
        );
        const stored = readStoredModel();
        const first = h.providers[0];
        setModel(
          stored && usable.includes(stored)
            ? stored
            : first
              ? `${first.name}::${first.default_model}`
              : "",
        );
      })
      .catch((e) =>
        setError(
          e instanceof ApiError
            ? { status: e.status, message: e.message }
            : { status: 0, message: "Cannot reach the backend. Is it running?" },
        ),
      );
    api
      .examples()
      .then(setExamples)
      .catch((e) => {
        // e.g. 503 "Database not found ... Run: uv run seed-db"; other errors surface on use
        if (e instanceof ApiError && e.status === 503) {
          setError({ status: e.status, message: e.message });
        }
      });
  }, []);

  async function run(id: string) {
    const trimmed = id.trim().toLowerCase();
    if (!trimmed) return;
    if (!OBJECT_ID.test(trimmed)) {
      setActiveId(null);
      setError({
        status: 400,
        message: `"${trimmed}" is not a click ID. Click IDs are 24-character hex MongoDB ObjectIds.`,
      });
      return;
    }
    const current = ++runId.current;
    setActiveId(trimmed);
    setQuery(trimmed);
    setError(null);
    setResult(null);
    setContext(null);
    setLoading(true);
    try {
      // The data comes back instantly; show it while the model is thinking.
      const ctx = await api.context(trimmed);
      if (current !== runId.current) return;
      setContext(ctx);

      const [provider, modelId] = model.split("::");
      const diagnosis = await api.diagnose({
        click_id: trimmed,
        provider: provider || undefined,
        model: modelId || undefined,
      });
      if (current !== runId.current) return;
      setResult(diagnosis);
      setRuns((prev) => [
        {
          clickId: trimmed,
          partnerId: ctx.click.partner_id,
          failureType: diagnosis.diagnosis.failure_type,
          model: diagnosis.model,
          latencyMs: diagnosis.latency_ms,
          matched:
            diagnosis.expected_failure_type === null
              ? null
              : diagnosis.expected_failure_type === diagnosis.diagnosis.failure_type,
        },
        ...prev,
      ]);
      if (diagnosis.skipped_models.length > 0) {
        // The server switched models; follow it so the next run starts with a working one.
        const next = `${diagnosis.provider}::${diagnosis.answered_by}`;
        setModel(next);
        storeModel(next);
      }
      api.health().then(setHealth).catch(() => undefined);
    } catch (e) {
      if (current !== runId.current) return;
      if (e instanceof ApiError) setError({ status: e.status, message: e.message });
      else setError({ status: 0, message: String(e) });
      api.health().then(setHealth).catch(() => undefined);
    } finally {
      if (current === runId.current) setLoading(false);
    }
  }

  function copyReport() {
    if (!result) return;
    void navigator.clipboard?.writeText(buildReport(result)).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  const providers = health?.providers ?? [];
  const noProvider = health !== null && providers.length === 0;
  const [providerName, modelName = ""] = model.split("::");
  const activeProvider = providers.find((p) => p.name === providerName);
  const resultFor = (clickId: string) => runs.find((r) => r.clickId === clickId);
  // Errors that happen before any data is shown (unknown click, backend down) go on top.
  const topError = error && !context ? error : null;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <IconTerminal size={18} />
          </span>
          <div>
            <strong>Postback Debugger</strong>
            <span className="label muted">MMP failure analysis</span>
          </div>
        </div>

        <form
          className="search"
          onSubmit={(e) => {
            e.preventDefault();
            void run(query);
          }}
        >
          <label className="search-field">
            <IconSearch size={15} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Click ID (24-char ObjectId)"
              aria-label="Click ID"
              spellCheck={false}
            />
          </label>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading || noProvider || !query.trim()}
          >
            <IconPlay size={13} /> Run diagnosis
          </button>
        </form>

        <div className="side-section">
          <div className="side-heading">
            <span className="label">Scenarios ({examples.length})</span>
          </div>
          <ul className="scenario-list">
            {examples.map((ex) => {
              const done = resultFor(ex.click_id);
              return (
                <li key={ex.click_id}>
                  <button
                    type="button"
                    className={`scenario ${activeId === ex.click_id ? "active" : ""}`}
                    disabled={loading || noProvider}
                    onClick={() => void run(ex.click_id)}
                  >
                    <PartnerAvatar partnerId={ex.partner_id} size={26} />
                    <span className="scenario-text">
                      <span className="mono scenario-id" title={ex.click_id}>
                        {ex.click_id}
                      </span>
                      <span className="scenario-meta">
                        {ex.partner_id}
                        <span className="platform">{ex.platform}</span>
                      </span>
                    </span>
                    {done && (
                      <span
                        className={`led tone-${FAILURE_TONES[done.failureType]}`}
                        title={FAILURE_LABELS[done.failureType]}
                      />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="side-footer">
          {providers.length > 0 ? (
            <label className="model-card">
              <span className="model-head">
                <span className="led tone-ok" />
                <span className="label">Model</span>
                <span className="label muted">{providerName}</span>
              </span>
              <select
                value={model}
                onChange={(e) => {
                  setModel(e.target.value);
                  storeModel(e.target.value);
                }}
              >
                {providers.map((p) => (
                  <optgroup key={p.name} label={p.name}>
                    {p.models.map((m) => (
                      <option key={m} value={`${p.name}::${m}`}>
                        {m}
                        {p.exhausted_models.includes(m) ? " (quota used)" : ""}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              <span className="label muted">
                {activeProvider && activeProvider.exhausted_models.length > 0
                  ? `${activeProvider.exhausted_models.length} model(s) out of quota · auto-fallback on`
                  : "Auto-fallback to the next model on quota errors"}
              </span>
            </label>
          ) : (
            <span className="label muted">{health ? "No model configured" : "Connecting…"}</span>
          )}
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <nav className="crumbs">
            <button type="button" className="crumb" onClick={() => setActiveId(null)}>
              Diagnoses
            </button>
            {activeId && (
              <>
                <span className="muted">/</span>
                <span className="crumb-current mono">{activeId}</span>
              </>
            )}
          </nav>
          <div className="topbar-actions">
            {activeId && (
              <button
                type="button"
                className="btn"
                disabled={loading}
                onClick={() => void run(activeId)}
              >
                <IconRefresh size={14} /> Re-run
              </button>
            )}
            {result && (
              <button type="button" className="btn" onClick={copyReport}>
                <IconCopy size={14} /> {copied ? "Copied" : "Copy report"}
              </button>
            )}
          </div>
        </header>

        <main className="content">
          {noProvider && (
            <div className="alert" role="alert">
              <IconAlert size={16} />
              <div>
                <strong>No model API key configured</strong>
                <span>
                  Add GEMINI_API_KEY (or ANTHROPIC_API_KEY) to the repo-root .env and restart.
                </span>
              </div>
            </div>
          )}

          {topError && (
            <div className="alert" role="alert">
              <IconAlert size={16} />
              <div>
                <strong>{topError.status === 404
                    ? "Not found"
                    : topError.status === 400
                      ? "Invalid click ID"
                      : "Something went wrong"}</strong>
                <span>{topError.message}</span>
              </div>
            </div>
          )}

          {!activeId && <EmptyState />}

          {activeId && context && (
            <>
              <div className="tagbar">
                <PartnerAvatar partnerId={context.click.partner_id} size={28} />
                <span className="label muted">Click</span>
                <span className="chip chip-strong mono">{context.click.click_id}</span>
                <span className="chip">{context.click.partner_id}</span>
                <span className="chip">{context.click.campaign_id}</span>
                <span className="chip chip-accent">{context.click.platform}</span>
                <span className="chip mono">{context.click.device_id}</span>
                <span className="tagbar-time label muted">
                  {formatTime(context.click.clicked_at)}
                </span>
              </div>

              <JourneyFlow context={context} />

              <div className="grid">
                <div>
                  {result ? (
                    <DiagnosisCard result={result} />
                  ) : loading ? (
                    <DiagnosisLoading model={modelName} />
                  ) : error ? (
                    <DiagnosisError
                      status={error.status}
                      message={error.message}
                      onRetry={() => void run(activeId)}
                    />
                  ) : null}
                </div>
                <DataTimeline context={context} />
              </div>
            </>
          )}

          {activeId && !context && loading && <DiagnosisLoading model={modelName} />}

          <RecentTable runs={runs} activeId={activeId} onOpen={(id) => void run(id)} />
        </main>
      </div>
    </div>
  );
}
