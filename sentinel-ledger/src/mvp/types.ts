export type ViewId = 'DASHBOARD' | 'STRATEGY' | 'RISK' | 'RUNTIME' | 'TRAINING' | 'AUDIT';

export type ExecutionMode = 'dry_run' | 'live';
export type EngineStatus = 'running' | 'stopped' | 'degraded';
export type VoteSide = 'buy' | 'sell' | 'hold' | 'abstain';
export type OrderSide = 'buy' | 'sell';

export type VotePolicy =
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

export type RuntimeConfig = {
  executionMode: ExecutionMode;
  tickIntervalMs: number;
  defaultOrderQuantity: number;
};

export type RiskLimits = {
  maxPositionUnits: number;
  maxOrderSize: number;
  maxDailyLossAbs: number;
};

export type AppConfig = {
  policyVersion: string;
  symbol: string;
  vote: VotePolicy;
  risk: RiskLimits;
  runtime: RuntimeConfig;
};

export type StrategyVote = {
  strategyId: string;
  side: VoteSide;
  strength: number;
  weight: number;
};

export type TickIntent =
  | { type: 'no_trade'; reason: string }
  | { type: 'place_order'; side: OrderSide; quantity: number };

export type TickRiskDecision = {
  blocked: boolean;
  reason?: string;
};

export type TickDecision = {
  id: number;
  at: string;
  symbol: string;
  votes: StrategyVote[];
  outcome: {
    side: VoteSide;
    netStrength: number;
    detail: string;
  };
  intent: TickIntent;
  risk: TickRiskDecision;
};

export type AuditEvent = {
  id: string;
  at: string;
  actor: string;
  eventType: string;
  status: 'success' | 'warning' | 'error';
  correlationId: string;
  message: string;
  before?: unknown;
  after?: unknown;
};

export type ConfigDraftState =
  | 'clean'
  | 'dirty'
  | 'validating'
  | 'invalid'
  | 'applying'
  | 'applied';
