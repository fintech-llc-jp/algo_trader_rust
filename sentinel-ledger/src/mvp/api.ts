type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';

type RequestOptions = {
  method?: HttpMethod;
  body?: unknown;
  idempotencyKey?: string;
};

type SessionCreateResponse = {
  session_id: string;
};

type SessionStatusResponse = {
  session_id: string;
  snapshot: {
    state: 'running' | 'stopped' | 'error';
    started_at_ms: number;
    ended_at_ms?: number;
    tick_count: number;
    last_intent?: string;
    last_error?: string;
  };
};

export type BffRuntimeConfigResponse = {
  config: unknown;
};

export type BffRiskStateResponse = {
  risk: {
    limits: unknown;
    dailyPnl: number;
    positionUnits: number;
  };
};

export type BffMetrics = {
  requests_total?: number;
  auth_rejected_total?: number;
  upstream_failure_total?: number;
  idempotency_hit_total?: number;
  idempotency_cache_entries?: number;
};

export type BffModelList = {
  models?: unknown[];
  [k: string]: unknown;
};

export type UiVotePolicy =
  | {
      mode: 'weighted_majority';
      min_net_strength: number;
      weights: Record<string, number>;
    }
  | {
      mode: 'quorum';
      required_same_side: number;
      min_strength_per_vote: number;
    }
  | {
      mode: 'simple_plurality';
    };

export type UiRuntimeConfig = {
  executionMode: 'dry_run' | 'live';
  tickIntervalMs: number;
  defaultOrderQuantity: number;
};

export type UiRiskLimits = {
  maxPositionUnits: number;
  maxOrderSize: number;
  maxDailyLossAbs: number;
};

export type UiAppConfig = {
  policyVersion: string;
  symbol: string;
  vote: UiVotePolicy;
  risk: UiRiskLimits;
  runtime: UiRuntimeConfig;
};

export type UiRiskState = {
  limits: UiRiskLimits;
  dailyPnl: number;
  positionUnits: number;
};

export type TrainingJobRequest = {
  model_name: string;
  symbol: string;
  training_window_days?: number;
  start_date?: string;
  end_date?: string;
  models?: string[];
  timeframes?: number[];
  prediction_horizon?: number;
};

export type TrainingJobStatus = {
  job_id: string;
  kind: string;
  status: string;
  progress?: number;
  message?: string;
  done: boolean;
  result?: unknown;
  upstream?: unknown;
};

export class BffClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;

  constructor(baseUrl: string, apiKey?: string) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.apiKey = apiKey;
  }

  async healthz(): Promise<void> {
    await this.request('/healthz');
  }

  async metrics(): Promise<BffMetrics> {
    return this.request<BffMetrics>('/metrics');
  }

  async listModels(): Promise<BffModelList> {
    return this.request<BffModelList>('/v1/models');
  }

  async createSession(configPath = 'config.toml'): Promise<SessionCreateResponse> {
    return this.request<SessionCreateResponse>('/v1/sessions', {
      method: 'POST',
      body: { config_path: configPath },
      idempotencyKey: `session-${Date.now()}`,
    });
  }

  async deleteSession(sessionId: string): Promise<void> {
    await this.request(`/v1/sessions/${sessionId}`, {
      method: 'DELETE',
    });
  }

  async getSessionStatus(sessionId: string): Promise<SessionStatusResponse> {
    return this.request<SessionStatusResponse>(`/v1/sessions/${sessionId}/status`);
  }

  async getUiConfig(): Promise<UiAppConfig> {
    const response = await this.request<BffRuntimeConfigResponse>('/v1/ui/config');
    return response.config as UiAppConfig;
  }

  async applyUiConfig(config: UiAppConfig): Promise<UiAppConfig> {
    const response = await this.request<BffRuntimeConfigResponse>('/v1/ui/config', {
      method: 'PUT',
      body: config,
    });
    return response.config as UiAppConfig;
  }

  async getUiRiskState(): Promise<UiRiskState> {
    const response = await this.request<BffRiskStateResponse>('/v1/ui/risk');
    return response.risk as UiRiskState;
  }

  async updateUiRiskLimits(limits: UiRiskLimits): Promise<UiRiskState> {
    const response = await this.request<BffRiskStateResponse>('/v1/ui/risk/limits', {
      method: 'PUT',
      body: limits,
    });
    return response.risk as UiRiskState;
  }

  async updateUiDailyPnl(dailyPnl: number): Promise<UiRiskState> {
    const response = await this.request<BffRiskStateResponse>('/v1/ui/risk/daily-pnl', {
      method: 'PUT',
      body: { dailyPnl },
    });
    return response.risk as UiRiskState;
  }

  async createTrainingJob(request: TrainingJobRequest): Promise<TrainingJobStatus> {
    return this.request<TrainingJobStatus>('/v1/training/jobs', {
      method: 'POST',
      body: request,
      idempotencyKey: `training-${Date.now()}`,
    });
  }

  async getTrainingJob(jobId: string): Promise<TrainingJobStatus> {
    return this.request<TrainingJobStatus>(`/v1/training/jobs/${jobId}`);
  }

  async cancelTrainingJob(jobId: string): Promise<TrainingJobStatus> {
    return this.request<TrainingJobStatus>(`/v1/training/jobs/${jobId}`, {
      method: 'DELETE',
    });
  }

  private async request<T = unknown>(
    path: string,
    options: RequestOptions = {},
  ): Promise<T> {
    const method = options.method ?? 'GET';
    const headers: Record<string, string> = {
      'content-type': 'application/json',
    };
    if (this.apiKey) {
      headers['x-api-key'] = this.apiKey;
    }
    if (options.idempotencyKey) {
      headers['idempotency-key'] = options.idempotencyKey;
    }
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers,
      body: options.body == null ? undefined : JSON.stringify(options.body),
    });
    const text = await response.text();
    const json = text ? JSON.parse(text) : {};
    if (!response.ok) {
      const message =
        json?.error?.message ??
        json?.detail ??
        `request failed: ${response.status} ${response.statusText}`;
      throw new Error(message);
    }
    return json as T;
  }
}

export function buildBffClient(): BffClient {
  const baseUrl =
    (import.meta.env.VITE_BFF_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8090';
  const apiKey = import.meta.env.VITE_BFF_API_KEY as string | undefined;
  return new BffClient(baseUrl, apiKey);
}
