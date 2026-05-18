import {
  AppConfig,
  RiskLimits,
  StrategyVote,
  TickDecision,
  TickIntent,
  VotePolicy,
  VoteSide,
} from './types';

const STRATEGIES = ['market_maker', 'arbitrage', 'price_prediction', 'momentum'] as const;

function rand(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

function pickVoteSide(): VoteSide {
  const r = Math.random();
  if (r < 0.35) return 'buy';
  if (r < 0.7) return 'sell';
  if (r < 0.9) return 'hold';
  return 'abstain';
}

export function buildVotes(policy: VotePolicy): StrategyVote[] {
  return STRATEGIES.map((id) => {
    const weight =
      policy.mode === 'weighted_majority' ? (policy.weights[id] ?? 1) : 1;
    return {
      strategyId: id,
      side: pickVoteSide(),
      strength: Number(rand(0.1, 0.99).toFixed(3)),
      weight,
    };
  });
}

export function aggregateVotes(votes: StrategyVote[], policy: VotePolicy): {
  side: VoteSide;
  netStrength: number;
  detail: string;
} {
  if (policy.mode === 'weighted_majority') {
    let buy = 0;
    let sell = 0;
    for (const v of votes) {
      if (v.side === 'buy') buy += v.strength * v.weight;
      if (v.side === 'sell') sell += v.strength * v.weight;
    }
    const net = Number((buy - sell).toFixed(3));
    if (Math.abs(net) < policy.min_net_strength) {
      return { side: 'hold', netStrength: net, detail: 'below min_net_strength' };
    }
    return {
      side: net >= 0 ? 'buy' : 'sell',
      netStrength: net,
      detail: `buy=${buy.toFixed(2)} sell=${sell.toFixed(2)}`,
    };
  }

  if (policy.mode === 'quorum') {
    const buyVotes = votes.filter(
      (v) => v.side === 'buy' && v.strength >= policy.min_strength_per_vote,
    ).length;
    const sellVotes = votes.filter(
      (v) => v.side === 'sell' && v.strength >= policy.min_strength_per_vote,
    ).length;
    if (buyVotes >= policy.required_same_side) {
      return {
        side: 'buy',
        netStrength: buyVotes,
        detail: `quorum buy=${buyVotes}`,
      };
    }
    if (sellVotes >= policy.required_same_side) {
      return {
        side: 'sell',
        netStrength: -sellVotes,
        detail: `quorum sell=${sellVotes}`,
      };
    }
    return {
      side: 'hold',
      netStrength: 0,
      detail: 'quorum unmet',
    };
  }

  const buy = votes
    .filter((v) => v.side === 'buy')
    .reduce((sum, v) => sum + v.strength, 0);
  const sell = votes
    .filter((v) => v.side === 'sell')
    .reduce((sum, v) => sum + v.strength, 0);
  if (Math.abs(buy - sell) < 0.001) {
    return { side: 'hold', netStrength: 0, detail: 'plurality tie' };
  }
  const side: VoteSide = buy > sell ? 'buy' : 'sell';
  return {
    side,
    netStrength: Number((buy - sell).toFixed(3)),
    detail: `plurality buy=${buy.toFixed(2)} sell=${sell.toFixed(2)}`,
  };
}

export function decideIntent(
  outcomeSide: VoteSide,
  defaultOrderQuantity: number,
  killSwitchActive: boolean,
): TickIntent {
  if (killSwitchActive) {
    return { type: 'no_trade', reason: 'kill_switch_active' };
  }
  if (outcomeSide !== 'buy' && outcomeSide !== 'sell') {
    return { type: 'no_trade', reason: 'consensus_hold' };
  }
  return {
    type: 'place_order',
    side: outcomeSide,
    quantity: defaultOrderQuantity,
  };
}

export function applyRisk(
  intent: TickIntent,
  symbol: string,
  limits: RiskLimits,
  currentPosition: number,
  dailyPnl: number,
): { blocked: boolean; reason?: string; nextPosition: number } {
  if (intent.type === 'no_trade') {
    return { blocked: false, nextPosition: currentPosition };
  }
  if (intent.quantity > limits.maxOrderSize) {
    return {
      blocked: true,
      reason: `ORDER_SIZE_EXCEEDED (${intent.quantity} > ${limits.maxOrderSize})`,
      nextPosition: currentPosition,
    };
  }
  const nextPosition =
    intent.side === 'buy'
      ? currentPosition + intent.quantity
      : currentPosition - intent.quantity;
  if (Math.abs(nextPosition) > limits.maxPositionUnits) {
    return {
      blocked: true,
      reason: `POSITION_LIMIT_EXCEEDED (${symbol})`,
      nextPosition: currentPosition,
    };
  }
  if (dailyPnl < -limits.maxDailyLossAbs) {
    return {
      blocked: true,
      reason: `DAILY_LOSS_LIMIT_EXCEEDED (${dailyPnl.toFixed(2)})`,
      nextPosition: currentPosition,
    };
  }
  return { blocked: false, nextPosition };
}

export function nextTick(
  id: number,
  cfg: AppConfig,
  killSwitchActive: boolean,
  currentPosition: number,
  dailyPnl: number,
): { tick: TickDecision; nextPosition: number; nextDailyPnl: number } {
  const votes = buildVotes(cfg.vote);
  const outcome = aggregateVotes(votes, cfg.vote);
  const rawIntent = decideIntent(
    outcome.side,
    cfg.runtime.defaultOrderQuantity,
    killSwitchActive,
  );
  const risk = applyRisk(
    rawIntent,
    cfg.symbol,
    cfg.risk,
    currentPosition,
    dailyPnl,
  );
  const intent: TickIntent =
    risk.blocked && rawIntent.type === 'place_order'
      ? { type: 'no_trade', reason: `risk: ${risk.reason}` }
      : rawIntent;

  const nextDailyPnl =
    !risk.blocked && rawIntent.type === 'place_order'
      ? Number((dailyPnl + rand(-80, 120)).toFixed(2))
      : dailyPnl;

  return {
    tick: {
      id,
      at: new Date().toISOString(),
      symbol: cfg.symbol,
      votes,
      outcome,
      intent,
      risk: {
        blocked: risk.blocked,
        reason: risk.reason,
      },
    },
    nextPosition: risk.nextPosition,
    nextDailyPnl,
  };
}
