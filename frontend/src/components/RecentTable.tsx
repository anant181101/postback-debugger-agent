import type { FailureType } from "../api";
import { FAILURE_LABELS, FAILURE_TONES } from "../format";
import { IconCheck, IconHistory, IconX } from "./Icons";

export interface RecentRun {
  clickId: string;
  partnerId: string;
  failureType: FailureType;
  model: string;
  latencyMs: number;
  matched: boolean | null; // null when the click has no ground truth
}

export function RecentTable({
  runs,
  activeId,
  onOpen,
}: {
  runs: RecentRun[];
  activeId: string | null;
  onOpen: (clickId: string) => void;
}) {
  const matched = runs.filter((r) => r.matched).length;
  const judged = runs.filter((r) => r.matched !== null).length;

  return (
    <section className="panel recent" aria-label="Recent diagnoses">
      <div className="panel-head">
        <span className="panel-title">
          <IconHistory size={16} /> Recent diagnoses
          <span className="chip">{runs.length} this session</span>
        </span>
        {judged > 0 && (
          <span className="label muted">
            Accuracy {matched}/{judged}
          </span>
        )}
      </div>
      {runs.length === 0 ? (
        <p className="empty-row">
          No diagnoses yet. Pick a scenario on the left; every run is listed here.
        </p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Click ID</th>
                <th>Partner</th>
                <th>Result</th>
                <th>Model</th>
                <th className="num">Latency</th>
                <th className="num">Ground truth</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run, i) => (
                <tr
                  key={`${run.clickId}-${i}`}
                  className={run.clickId === activeId && i === 0 ? "selected" : ""}
                  onClick={() => onOpen(run.clickId)}
                >
                  <td className="mono">{run.clickId}</td>
                  <td>{run.partnerId}</td>
                  <td>
                    <span className={`chip chip-dot tone-${FAILURE_TONES[run.failureType]}`}>
                      {FAILURE_LABELS[run.failureType]}
                    </span>
                  </td>
                  <td className="mono muted">{run.model}</td>
                  <td className="mono num">{(run.latencyMs / 1000).toFixed(1)}s</td>
                  <td className="num">
                    {run.matched === null ? (
                      <span className="muted">n/a</span>
                    ) : run.matched ? (
                      <span className="truth ok">
                        <IconCheck size={13} /> Matched
                      </span>
                    ) : (
                      <span className="truth bad">
                        <IconX size={13} /> Missed
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
