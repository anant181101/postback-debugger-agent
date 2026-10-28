// Types mirror the Pydantic models in backend/src/postback_debugger (models.py, diagnosis.py,
// api/app.py). Timestamps arrive as ISO 8601 strings.

export type FailureType =
  | "none"
  | "no_install"
  | "attributed_to_other_click"
  | "outside_attribution_window"
  | "fraud_rejected"
  | "event_not_mapped"
  | "partner_4xx"
  | "partner_5xx"
  | "timeout"
  | "missing_macro"
  | "duplicate";

export type Platform = "android" | "ios";

export interface Partner {
  partner_id: string;
  name: string;
  postback_url_template: string;
  event_mapping: Record<string, string>;
  attribution_window_hours: number;
  timeout_ms: number;
  max_attempts: number;
  api_key: string | null;
  api_key_expires_at: string | null;
}

export interface Click {
  click_id: string;
  partner_id: string;
  campaign_id: string;
  app_id: string;
  platform: Platform;
  device_id: string;
  clicked_at: string;
}

export interface Install {
  install_id: string;
  app_id: string;
  platform: Platform;
  device_id: string;
  advertising_id: string | null;
  installed_at: string;
  attribution_status: "attributed" | "organic" | "rejected";
  click_id: string | null;
  rejection_reason: string | null;
}

export interface AppEvent {
  event_id: string;
  install_id: string;
  event_name: string;
  revenue: number | null;
  currency: string | null;
  event_time: string;
}

export interface PostbackLog {
  postback_id: string;
  partner_id: string;
  click_id: string;
  install_id: string;
  event_id: string | null;
  postback_type: "install" | "event";
  url: string;
  attempt: number;
  status: "success" | "failed";
  http_status: number | null;
  response_body: string | null;
  error: string | null;
  latency_ms: number;
  sent_at: string;
}

export interface ClickContext {
  click: Click;
  other_clicks_on_device: Click[];
  partners: Partner[];
  installs_on_device: Install[];
  events: AppEvent[];
  postback_logs: PostbackLog[];
}

export interface Diagnosis {
  failure_type: FailureType;
  summary: string;
  evidence: string[];
  recommended_fix: string;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  thinking_tokens: number;
}

export interface DiagnoseResponse {
  click_id: string;
  diagnosis: Diagnosis;
  provider: string;
  model: string;
  usage: Usage;
  cost_usd: number | null;
  latency_ms: number;
  expected_failure_type: FailureType | null;
  requested_model: string;
  answered_by: string;
  skipped_models: string[];
}

export interface ProviderInfo {
  name: string;
  default_model: string;
  models: string[];
  exhausted_models: string[];
}

export interface Health {
  status: string;
  providers: ProviderInfo[];
}

export interface ExampleClick {
  click_id: string;
  partner_id: string;
  platform: Platform;
  clicked_at: string;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      // not a JSON error body; keep the status text
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  examples: () => request<ExampleClick[]>("/api/examples"),
  context: (clickId: string) =>
    request<ClickContext>(`/api/clicks/${encodeURIComponent(clickId)}/context`),
  diagnose: (body: { click_id: string; provider?: string; model?: string }) =>
    request<DiagnoseResponse>("/api/diagnoses", { method: "POST", body: JSON.stringify(body) }),
};
