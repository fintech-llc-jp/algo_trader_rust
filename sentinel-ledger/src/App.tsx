import { useEffect, useMemo, useState } from 'react';
import MvpDashboard from './mvp/MvpDashboard';
import MvpStrategyMonitor from './mvp/MvpStrategyMonitor';
import MvpRiskControl from './mvp/MvpRiskControl';
import MvpRuntimeConfig from './mvp/MvpRuntimeConfig';
import MvpAuditLog from './mvp/MvpAuditLog';
import MvpTraining, { buildTrainingRequest, TrainingFormDraft } from './mvp/MvpTraining';
import { nextTick } from './mvp/engine';
import { buildBffClient, BffMetrics, TrainingJobStatus, UiRiskState } from './mvp/api';
import {
  AppConfig,
  AuditEvent,
  ConfigDraftState,
  EngineStatus,
  TickDecision,
  ViewId,
} from './mvp/types';

const INITIAL_CONFIG: AppConfig = {
  policyVersion: '1',
  symbol: 'BTCJPY',
  vote: {
    mode: 'weighted_majority',
    min_net_strength: 0.15,
    weights: {
      market_maker: 1,
      arbitrage: 0.5,
      price_prediction: 1.2,
      momentum: 1,
    },
  },
  risk: {
    maxPositionUnits: 10,
    maxOrderSize: 1,
    maxDailyLossAbs: 50000,
  },
  runtime: {
    executionMode: 'dry_run',
    tickIntervalMs: 2000,
    defaultOrderQuantity: 0.01,
  },
};

const INITIAL_TRAINING_DRAFT: TrainingFormDraft = {
  modelName: 'mvp_price_v1',
  symbol: 'G_FX_BTCJPY',
  trainingWindowDays: '30',
  predictionHorizon: '60',
  modelsCsv: 'price,momentum',
  timeframesCsv: '1,5,30',
};

function nowId(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

function makeCorrelationId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function validateConfig(cfg: AppConfig): string[] {
  const errors: string[] = [];
  if (cfg.runtime.tickIntervalMs <= 0) errors.push('tick_interval_ms must be > 0');
  if (cfg.runtime.defaultOrderQuantity <= 0)
    errors.push('default_order_quantity must be > 0');
  if (cfg.risk.maxPositionUnits <= 0) errors.push('max_position_units must be > 0');
  if (cfg.risk.maxOrderSize <= 0) errors.push('max_order_size must be > 0');
  if (cfg.risk.maxDailyLossAbs <= 0) errors.push('max_daily_loss_abs must be > 0');
  if (cfg.vote.mode === 'weighted_majority' && cfg.vote.min_net_strength < 0) {
    errors.push('min_net_strength must be >= 0');
  }
  if (cfg.vote.mode === 'quorum') {
    if (cfg.vote.required_same_side < 1) {
      errors.push('required_same_side must be >= 1');
    }
    if (cfg.vote.min_strength_per_vote < 0 || cfg.vote.min_strength_per_vote > 1) {
      errors.push('min_strength_per_vote must be in [0, 1]');
    }
  }
  return errors;
}

export default function App() {
  const bffClient = useMemo(() => buildBffClient(), []);
  const [view, setView] = useState<ViewId>('DASHBOARD');
  const [engineStatus, setEngineStatus] = useState<EngineStatus>('stopped');
  const [killSwitchActive, setKillSwitchActive] = useState(false);
  const [appliedConfig, setAppliedConfig] = useState<AppConfig>(INITIAL_CONFIG);
  const [draftConfig, setDraftConfig] = useState<AppConfig>(INITIAL_CONFIG);
  const [draftState, setDraftState] = useState<ConfigDraftState>('clean');
  const [validationErrors, setValidationErrors] = useState<string[]>([]);

  const [ticks, setTicks] = useState<TickDecision[]>([]);
  const [tickId, setTickId] = useState(0);
  const [selectedTickId, setSelectedTickId] = useState<number | null>(null);
  const [autoFollow, setAutoFollow] = useState(true);

  const [positionUnits, setPositionUnits] = useState(0);
  const [dailyPnl, setDailyPnl] = useState(0);

  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [backendSessionId, setBackendSessionId] = useState<string | null>(null);
  const [backendConnected, setBackendConnected] = useState(false);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [backendTickCount, setBackendTickCount] = useState<number | null>(null);
  const [backendLastIntent, setBackendLastIntent] = useState<string | null>(null);
  const [modelCount, setModelCount] = useState<number | null>(null);
  const [bffMetrics, setBffMetrics] = useState<BffMetrics>({});
  const [trainingDraft, setTrainingDraft] = useState<TrainingFormDraft>(INITIAL_TRAINING_DRAFT);
  const [trainingJob, setTrainingJob] = useState<TrainingJobStatus | null>(null);
  const [trainingError, setTrainingError] = useState<string | null>(null);
  const [trainingBusy, setTrainingBusy] = useState(false);

  const addAudit = (
    eventType: string,
    message: string,
    status: AuditEvent['status'],
    before?: unknown,
    after?: unknown,
  ) => {
    const ev: AuditEvent = {
      id: nowId(),
      at: new Date().toISOString(),
      actor: 'operator-ui',
      eventType,
      status,
      message,
      correlationId: makeCorrelationId('ui'),
      before,
      after,
    };
    setAuditEvents((prev) => [ev, ...prev].slice(0, 500));
  };

  useEffect(() => {
    setDraftConfig(appliedConfig);
    setDraftState('clean');
    setValidationErrors([]);
  }, [appliedConfig]);

  useEffect(() => {
    let cancelled = false;
    const loadUiState = async () => {
      try {
        const [config, risk] = await Promise.all([
          bffClient.getUiConfig(),
          bffClient.getUiRiskState(),
        ]);
        if (cancelled) return;
        setAppliedConfig(config);
        setDraftConfig(config);
        setDailyPnl(risk.dailyPnl);
        setPositionUnits(risk.positionUnits);
      } catch {
        // Keep local defaults when UI APIs are unavailable.
      }
    };
    void loadUiState();
    return () => {
      cancelled = true;
    };
  }, [bffClient]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        await bffClient.healthz();
        const [metrics, models] = await Promise.all([
          bffClient.metrics().catch(() => ({})),
          bffClient.listModels().catch(() => ({})),
        ]);
        if (cancelled) return;
        setBackendConnected(true);
        setBackendError(null);
        setBffMetrics(metrics);
        if (Array.isArray(models.models)) {
          setModelCount(models.models.length);
        }
      } catch (e) {
        if (cancelled) return;
        setBackendConnected(false);
        setBackendError(e instanceof Error ? e.message : String(e));
      }
    };
    void poll();
    const h = setInterval(() => {
      void poll();
    }, 10000);
    return () => {
      cancelled = true;
      clearInterval(h);
    };
  }, [bffClient]);

  useEffect(() => {
    if (!backendSessionId) return;
    let cancelled = false;
    const pollSession = async () => {
      try {
        const status = await bffClient.getSessionStatus(backendSessionId);
        if (cancelled) return;
        setBackendTickCount(status.snapshot.tick_count);
        setBackendLastIntent(status.snapshot.last_intent ?? null);
        if (status.snapshot.state === 'error') {
          setEngineStatus('degraded');
          setBackendError(status.snapshot.last_error ?? 'session error');
        } else if (status.snapshot.state === 'stopped') {
          setEngineStatus('stopped');
          setBackendSessionId(null);
        } else {
          setEngineStatus('running');
        }
      } catch (e) {
        if (cancelled) return;
        setEngineStatus('degraded');
        setBackendError(e instanceof Error ? e.message : String(e));
      }
    };
    void pollSession();
    const h = setInterval(() => {
      void pollSession();
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(h);
    };
  }, [backendSessionId, bffClient]);

  useEffect(() => {
    if (!trainingJob || trainingJob.done) return;
    let cancelled = false;
    const pollTraining = async () => {
      try {
        const next = await bffClient.getTrainingJob(trainingJob.job_id);
        if (cancelled) return;
        setTrainingJob(next);
        setTrainingError(null);
      } catch (e) {
        if (cancelled) return;
        setTrainingError(e instanceof Error ? e.message : String(e));
      }
    };
    void pollTraining();
    const h = setInterval(() => {
      void pollTraining();
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(h);
    };
  }, [bffClient, trainingJob]);

  useEffect(() => {
    if (engineStatus !== 'running') return;
    const interval = setInterval(() => {
      setTickId((prevId) => {
        const nextId = prevId + 1;
        const simulated = nextTick(
          nextId,
          appliedConfig,
          killSwitchActive,
          positionUnits,
          dailyPnl,
        );
        setPositionUnits(simulated.nextPosition);
        setDailyPnl(simulated.nextDailyPnl);
        setTicks((prev) => [simulated.tick, ...prev].slice(0, 500));
        if (autoFollow) {
          setSelectedTickId(simulated.tick.id);
        }
        if (simulated.tick.risk.blocked) {
          addAudit(
            'RISK_BLOCKED',
            simulated.tick.risk.reason ?? 'risk block',
            'warning',
          );
        }
        return nextId;
      });
    }, appliedConfig.runtime.tickIntervalMs);
    return () => clearInterval(interval);
  }, [
    engineStatus,
    appliedConfig,
    killSwitchActive,
    positionUnits,
    dailyPnl,
    autoFollow,
  ]);

  const alerts = useMemo(() => {
    const out: { level: 'info' | 'warn' | 'error'; message: string }[] = [];
    if (killSwitchActive) {
      out.push({ level: 'error', message: 'Kill switch active.' });
    }
    const blocked = ticks.slice(0, 20).filter((t) => t.risk.blocked).length;
    if (blocked > 0) {
      out.push({
        level: 'warn',
        message: `Recent risk blocks detected: ${blocked} / 20 ticks`,
      });
    }
    if (appliedConfig.runtime.executionMode === 'live') {
      out.push({
        level: 'info',
        message: 'Live mode enabled. Verify risk thresholds and kill switch.',
      });
    }
    if (!backendConnected) {
      out.push({ level: 'warn', message: 'BFF disconnected or unavailable.' });
    }
    if (backendError) {
      out.push({ level: 'error', message: `Backend error: ${backendError}` });
    }
    if (modelCount != null) {
      out.push({ level: 'info', message: `Available models: ${modelCount}` });
    }
    return out;
  }, [
    killSwitchActive,
    ticks,
    appliedConfig.runtime.executionMode,
    backendConnected,
    backendError,
    modelCount,
  ]);

  const onApplyConfig = async () => {
    setDraftState('validating');
    const errs = validateConfig(draftConfig);
    setValidationErrors(errs);
    if (errs.length > 0) {
      setDraftState('invalid');
      addAudit('CONFIG_APPLY_FAILED', errs.join('; '), 'error');
      return;
    }
    const before = appliedConfig;
    setDraftState('applying');
    try {
      const nextPolicyVersion = (() => {
        const parsed = Number(appliedConfig.policyVersion);
        if (Number.isFinite(parsed)) return String(parsed + 1);
        return `${appliedConfig.policyVersion}-next`;
      })();
      const requested = { ...draftConfig, policyVersion: nextPolicyVersion };
      const applied = await bffClient.applyUiConfig(requested);
      setAppliedConfig(applied);
      setDraftConfig(applied);
      setDraftState('applied');
      setValidationErrors([]);
      addAudit('CONFIG_APPLY', 'Configuration applied via BFF', 'success', before, applied);
    } catch (e) {
      setDraftState('invalid');
      const message = e instanceof Error ? e.message : String(e);
      setValidationErrors([message]);
      addAudit('CONFIG_APPLY_FAILED', message, 'error', before, draftConfig);
    }
  };

  const onRollback = () => {
    const before = draftConfig;
    setDraftConfig(appliedConfig);
    setDraftState('clean');
    setValidationErrors([]);
    addAudit('CONFIG_ROLLBACK', 'Draft rolled back to applied config', 'warning', before, appliedConfig);
  };

  const onUpdateLimits = async (next: AppConfig['risk']) => {
    if (
      next.maxPositionUnits <= 0 ||
      next.maxOrderSize <= 0 ||
      next.maxDailyLossAbs <= 0
    ) {
      return { ok: false, error: 'all limits must be > 0' };
    }
    const before = appliedConfig.risk;
    try {
      const risk = await bffClient.updateUiRiskLimits(next);
      applyRiskState(risk);
      addAudit('RISK_LIMIT_UPDATE', 'Risk limits updated via BFF', 'success', before, next);
      return { ok: true };
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      addAudit('RISK_LIMIT_UPDATE_FAILED', message, 'error', before, next);
      return { ok: false, error: message };
    }
  };

  const applyRiskState = (risk: UiRiskState) => {
    setAppliedConfig((prev) => ({ ...prev, risk: risk.limits }));
    setDraftConfig((prev) => ({ ...prev, risk: risk.limits }));
    setDailyPnl(risk.dailyPnl);
    setPositionUnits(risk.positionUnits);
  };

  const toggleKillSwitch = () => {
    const before = killSwitchActive;
    const next = !before;
    setKillSwitchActive(next);
    addAudit(
      'KILL_SWITCH_TOGGLED',
      next ? 'Kill switch enabled' : 'Kill switch disabled',
      next ? 'warning' : 'success',
      { active: before },
      { active: next },
    );
  };

  const navItems: { id: ViewId; label: string }[] = [
    { id: 'DASHBOARD', label: 'Dashboard' },
    { id: 'STRATEGY', label: 'Strategy & Vote' },
    { id: 'RISK', label: 'Risk Control' },
    { id: 'RUNTIME', label: 'Runtime & Config' },
    { id: 'TRAINING', label: 'ML Training' },
    { id: 'AUDIT', label: 'Audit Log' },
  ];

  const refreshTrainingStatus = async () => {
    if (!trainingJob) return;
    try {
      const next = await bffClient.getTrainingJob(trainingJob.job_id);
      setTrainingJob(next);
      setTrainingError(null);
    } catch (e) {
      setTrainingError(e instanceof Error ? e.message : String(e));
    }
  };

  const startTraining = async () => {
    setTrainingBusy(true);
    try {
      const req = buildTrainingRequest(trainingDraft);
      const job = await bffClient.createTrainingJob(req);
      setTrainingJob(job);
      setTrainingError(null);
      addAudit(
        'TRAINING_START',
        `Training job started: ${job.job_id}`,
        'success',
        undefined,
        req,
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setTrainingError(message);
      addAudit('TRAINING_START_FAILED', message, 'error');
    } finally {
      setTrainingBusy(false);
    }
  };

  const cancelTraining = async () => {
    if (!trainingJob) return;
    setTrainingBusy(true);
    try {
      const before = trainingJob;
      const next = await bffClient.cancelTrainingJob(trainingJob.job_id);
      setTrainingJob(next);
      setTrainingError(null);
      addAudit(
        'TRAINING_CANCEL',
        `Training job cancelled: ${trainingJob.job_id}`,
        'warning',
        before,
        next,
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setTrainingError(message);
      addAudit('TRAINING_CANCEL_FAILED', message, 'error', trainingJob);
    } finally {
      setTrainingBusy(false);
    }
  };

  const toggleEngine = async () => {
    if (engineStatus === 'running') {
      const before = backendSessionId;
      try {
        if (backendSessionId) {
          await bffClient.deleteSession(backendSessionId);
        }
        setEngineStatus('stopped');
        setBackendSessionId(null);
        setBackendTickCount(null);
        setBackendLastIntent(null);
        setBackendError(null);
        addAudit(
          'ENGINE_STOP',
          'Engine stopped via /v1/sessions delete',
          'success',
          { sessionId: before },
          { sessionId: null },
        );
      } catch (e) {
        setEngineStatus('degraded');
        setBackendError(e instanceof Error ? e.message : String(e));
        addAudit(
          'ENGINE_STOP_FAILED',
          e instanceof Error ? e.message : String(e),
          'error',
        );
      }
      return;
    }

    try {
      const created = await bffClient.createSession('config.toml');
      setBackendSessionId(created.session_id);
      setEngineStatus('running');
      setBackendError(null);
      addAudit(
        'ENGINE_START',
        `Engine started with session ${created.session_id}`,
        'success',
      );
    } catch (e) {
      setEngineStatus('degraded');
      setBackendError(e instanceof Error ? e.message : String(e));
      addAudit(
        'ENGINE_START_FAILED',
        e instanceof Error ? e.message : String(e),
        'error',
      );
    }
  };

  return (
    <div className="flex min-h-screen bg-background text-on-surface">
      <aside className="w-64 border-r p-4">
        <h1 className="mb-6 text-lg font-bold">Sentinel Ledger (MVP)</h1>
        <div className="space-y-1">
          {navItems.map((n) => (
            <button
              key={n.id}
              className={`w-full rounded px-3 py-2 text-left text-sm ${
                view === n.id ? 'bg-blue-100 text-blue-800' : 'hover:bg-surface-container'
              }`}
              onClick={() => setView(n.id)}
            >
              {n.label}
            </button>
          ))}
        </div>

        <div className="mt-8 rounded border p-3 text-sm">
          <div>Engine: {engineStatus}</div>
          <div>Mode: {appliedConfig.runtime.executionMode}</div>
          <div>KillSwitch: {killSwitchActive ? 'active' : 'inactive'}</div>
          <div>BFF: {backendConnected ? 'connected' : 'disconnected'}</div>
          <div>Session: {backendSessionId ?? '-'}</div>
          <div>Tick Count: {backendTickCount ?? '-'}</div>
          <div className="truncate">Last Intent: {backendLastIntent ?? '-'}</div>
          <div className="truncate">Metrics req_total: {bffMetrics.requests_total ?? '-'}</div>
          <button
            className="mt-3 w-full rounded border px-2 py-1 text-xs"
            onClick={() => {
              void toggleEngine();
            }}
          >
            {engineStatus === 'running' ? 'Stop Engine' : 'Start Engine'}
          </button>
        </div>
      </aside>

      <main className="flex-1 p-6">
        {view === 'DASHBOARD' && (
          <MvpDashboard
            engineStatus={engineStatus}
            executionMode={appliedConfig.runtime.executionMode}
            killSwitchActive={killSwitchActive}
            ticks={ticks}
            alerts={alerts}
          />
        )}
        {view === 'STRATEGY' && (
          <MvpStrategyMonitor
            ticks={ticks}
            selectedTickId={selectedTickId}
            onSelectTick={setSelectedTickId}
            autoFollow={autoFollow}
            onToggleAutoFollow={() => setAutoFollow((v) => !v)}
          />
        )}
        {view === 'RISK' && (
          <MvpRiskControl
            limits={appliedConfig.risk}
            dailyPnl={dailyPnl}
            ticks={ticks}
            onUpdateLimits={onUpdateLimits}
            onUpdateDailyPnl={async (n) => {
              const before = dailyPnl;
              try {
                const risk = await bffClient.updateUiDailyPnl(n);
                applyRiskState(risk);
                addAudit(
                  'DAILY_PNL_UPDATED',
                  `daily_pnl updated via BFF: ${n.toFixed(2)}`,
                  'success',
                  { dailyPnl: before },
                  { dailyPnl: n },
                );
              } catch (e) {
                addAudit(
                  'DAILY_PNL_UPDATE_FAILED',
                  e instanceof Error ? e.message : String(e),
                  'error',
                  { dailyPnl: before },
                  { dailyPnl: n },
                );
              }
            }}
          />
        )}
        {view === 'RUNTIME' && (
          <MvpRuntimeConfig
            draft={draftConfig}
            applied={appliedConfig}
            draftState={draftState}
            killSwitchActive={killSwitchActive}
            errors={validationErrors}
            onDraftChange={(next) => {
              setDraftConfig(next);
              setDraftState('dirty');
            }}
            onApply={() => {
              void onApplyConfig();
            }}
            onRollback={onRollback}
            onToggleKillSwitch={toggleKillSwitch}
          />
        )}
        {view === 'TRAINING' && (
          <MvpTraining
            draft={trainingDraft}
            running={trainingBusy}
            latestJob={trainingJob}
            error={trainingError}
            onDraftChange={setTrainingDraft}
            onStart={() => {
              void startTraining();
            }}
            onCancel={() => {
              void cancelTraining();
            }}
            onRefresh={() => {
              void refreshTrainingStatus();
            }}
          />
        )}
        {view === 'AUDIT' && <MvpAuditLog events={auditEvents} />}
      </main>
    </div>
  );
}
