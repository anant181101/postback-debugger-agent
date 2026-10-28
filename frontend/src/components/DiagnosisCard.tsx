import { useEffect, useState } from "react";
import type { DiagnoseResponse } from "../api";
import { FAILURE_CATEGORY, FAILURE_LABELS, FAILURE_TONES, formatCost } from "../format";
import { IconAlert, IconCheck, IconCpu, IconInfo, IconRefresh, IconWrench, IconX } from "./Icons";

function pct(part: number, total: number): string {
  return `${((part / Math.max(total, 1)) * 100).toFixed(1)}%`;
}

function TokenBar({ result }: { result: DiagnoseResponse }) {
  const { input_tokens: input, output_tokens: output, thinking_tokens: thinking } = result.usage;
  const total = input + output;
  const answer = output - thinking;
  return (
    <div className="tokens">
      <div className="tokens-legend">
        <span className="label muted">Token distribution ({total.toLocaleString()})</span>
        <span>
          <i className="sq seg-input" /> Input {pct(input, total)}
        </span>
        <span>
          <i className="sq seg-thinking" /> Thinking {pct(thinking, total)}
        </span>
        <span>
          <i className="sq seg-output" /> Answer {pct(answer, total)}
        </span>
      </div>
      <div className="token-track">
        <span className="seg-input" style={{ width: pct(input, total) }} />
        <span className="seg-thinking" style={{ width: pct(thinking, total) }} />
        <span className="seg-output" style={{ width: pct(answer, total) }} />
      </div>
    </div>
  );
}

export function DiagnosisCard({ result }: { result: DiagnoseResponse }) {
  const { diagnosis, expected_failure_type: expected, usage } = result;
  const tone = FAILURE_TONES[diagnosis.failure_type];
  const matches = expected !== null && expected === diagnosis.failure_type;

  return (
    <section className={`panel diagnosis tone-${tone}`} aria-label="Diagnosis">
      <div className="diag-tags">
        <span className="tag-tone">
          Root cause · {FAILURE_CATEGORY[diagnosis.failure_type]}
        </span>
        {expected !== null && (
          <span className={`tag-truth ${matches ? "ok" : "bad"}`}>
            {matches ? <IconCheck size={12} /> : <IconX size={12} />}
            {matches ? "Matches ground truth" : `Expected: ${FAILURE_LABELS[expected]}`}
          </span>
        )}
      </div>

      <h2 className="diag-title">{FAILURE_LABELS[diagnosis.failure_type]}</h2>
      <p className="diag-summary">{diagnosis.summary}</p>

      {result.skipped_models.length > 0 && (
        <p className="note">
          <IconInfo size={14} />
          <span>
            {result.skipped_models.join(", ")} out of quota, answered by{" "}
            <span className="mono">{result.answered_by}</span>.
          </span>
        </p>
      )}

      <div className="section-head">
        <span className="label">Evidence</span>
        <span className="label muted">{diagnosis.evidence.length} facts</span>
      </div>
      <ol className="evidence">
        {diagnosis.evidence.map((item, i) => (
          <li key={i}>
            <span className="ev-num mono">{i + 1}</span>
            <span>{item}</span>
          </li>
        ))}
      </ol>

      <div className="action">
        <span className="label action-head">
          <IconWrench size={13} /> Recommended action
        </span>
        <p>{diagnosis.recommended_fix}</p>
      </div>

      <div className="kpis">
        <div className="kpi">
          <span className="label muted">Model</span>
          <span className="kpi-value mono accent" title={result.model}>
            {result.model}
          </span>
        </div>
        <div className="kpi">
          <span className="label muted">Latency</span>
          <span className="kpi-value mono">{(result.latency_ms / 1000).toFixed(1)} s</span>
        </div>
        <div className="kpi">
          <span className="label muted">Tokens</span>
          <span className="kpi-value mono">
            {(usage.input_tokens + usage.output_tokens).toLocaleString()}
          </span>
        </div>
        <div className="kpi">
          <span className="label muted">Cost</span>
          <span className="kpi-value mono">{formatCost(result.cost_usd)}</span>
        </div>
      </div>
      <TokenBar result={result} />
    </section>
  );
}

export function DiagnosisLoading({ model }: { model: string }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 250);
    return () => clearInterval(timer);
  }, []);

  return (
    <section className="panel diagnosis loading" aria-live="polite">
      <div className="diag-tags">
        <span className="tag-tone tag-accent">
          <span className="spinner" /> Diagnosing
        </span>
        <span className="label muted mono">{seconds}s elapsed</span>
      </div>
      <h2 className="diag-title">Reading the logs…</h2>
      <ol className="steps">
        <li className="done">
          <IconCheck size={13} /> Collected click, install, event and postback records
        </li>
        <li className="active">
          <span className="spinner" />
          <span>
            <span className="mono">{model || "model"}</span> is finding the root cause
          </span>
        </li>
        <li className="todo">
          <IconCpu size={13} /> Evidence and recommended action
        </li>
      </ol>
      <div className="skeleton">
        <span />
        <span />
        <span />
        <span />
      </div>
    </section>
  );
}

export function DiagnosisError({
  status,
  message,
  onRetry,
}: {
  status: number;
  message: string;
  onRetry: () => void;
}) {
  return (
    <section className="panel diagnosis tone-error" aria-label="Diagnosis failed">
      <div className="diag-tags">
        <span className="tag-tone">
          <IconAlert size={12} /> {status === 429 ? "Quota exhausted" : "Diagnosis failed"}
        </span>
        {status > 0 && <span className="label muted mono">HTTP {status}</span>}
      </div>
      <h2 className="diag-title">
        {status === 429 ? "Every model is out of quota" : "The model could not answer"}
      </h2>
      <p className="diag-summary">{message}</p>
      <p className="note">
        <IconInfo size={14} />
        <span>
          The lifecycle and evidence data on this page come straight from the database and are
          still accurate.
        </span>
      </p>
      <button type="button" className="btn" onClick={onRetry}>
        <IconRefresh size={14} /> Retry
      </button>
    </section>
  );
}
