use tracing::{debug, info};

use crate::risk::RiskService;
use crate::types::{ExecutionMode, Intent};
use crate::vote::{vote_side_to_order_side, StrategyVote, VoteEngine, VotePolicy, VoteSide};

/// Result of one decision tick (before optional execution).
#[derive(Debug, Clone)]
pub struct PipelineResult {
    pub policy_version: String,
    pub vote_outcome: crate::vote::VoteOutcome,
    pub intent: Intent,
}

pub struct TradingPipeline {
    policy_version: String,
    vote_policy: VotePolicy,
    risk: RiskService,
    symbol: String,
    default_quantity: f64,
    execution_mode: ExecutionMode,
    dry_run: bool,
}

impl TradingPipeline {
    pub fn new(
        policy_version: String,
        symbol: String,
        vote_policy: VotePolicy,
        risk: RiskService,
        default_quantity: f64,
        execution_mode: ExecutionMode,
        dry_run: bool,
    ) -> Self {
        Self {
            policy_version,
            symbol,
            vote_policy,
            risk,
            default_quantity,
            execution_mode,
            dry_run,
        }
    }

    /// Evaluate votes → aggregate → risk → intent (no I/O).
    pub fn decide(&self, votes: &[StrategyVote]) -> PipelineResult {
        let vote_outcome = match VoteEngine::aggregate(votes, &self.vote_policy) {
            Ok(o) => o,
            Err(e) => {
                return PipelineResult {
                    policy_version: self.policy_version.clone(),
                    vote_outcome: crate::vote::VoteOutcome {
                        side: VoteSide::Hold,
                        net_strength: 0.0,
                        detail: format!("vote error: {e}"),
                    },
                    intent: Intent::NoTrade {
                        reason: format!("vote aggregation failed: {e}"),
                    },
                };
            }
        };

        let intent_raw = match vote_side_to_order_side(vote_outcome.side) {
            Some(side) => Intent::PlaceOrder {
                symbol: self.symbol.clone(),
                side,
                quantity: self.default_quantity,
                note: vote_outcome.detail.clone(),
            },
            None => Intent::NoTrade {
                reason: format!(
                    "consensus {:?} — {}",
                    vote_outcome.side, vote_outcome.detail
                ),
            },
        };

        let intent = self.risk.apply(intent_raw, &self.symbol);

        if self.dry_run || matches!(self.execution_mode, ExecutionMode::DryRun) {
            if let Intent::PlaceOrder { .. } = &intent {
                debug!(target: "engine", "dry_run: would place order {:?}", intent);
            }
        }

        PipelineResult {
            policy_version: self.policy_version.clone(),
            vote_outcome,
            intent,
        }
    }

    pub fn log_tick(&self, result: &PipelineResult) {
        info!(
            target: "engine",
            policy_version = %result.policy_version,
            symbol = %self.symbol,
            vote_side = ?result.vote_outcome.side,
            net = result.vote_outcome.net_strength,
            intent = ?result.intent,
            "tick"
        );
    }

    pub fn is_live_execution(&self) -> bool {
        !self.dry_run && matches!(self.execution_mode, ExecutionMode::Live)
    }

    pub fn symbol(&self) -> &str {
        &self.symbol
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::risk::RiskLimits;
    use crate::vote::VotePolicy;
    use std::collections::HashMap;

    fn mk_vote(id: &str, side: VoteSide, s: f64) -> StrategyVote {
        StrategyVote {
            strategy_id: id.to_string(),
            side,
            strength: s,
        }
    }

    #[test]
    fn pipeline_hold_when_vote_hold() {
        let risk = RiskService::new(RiskLimits {
            max_position_units: 10.0,
            max_order_size: 1.0,
            max_daily_loss_abs: 1000.0,
        });
        let vp = VotePolicy::WeightedMajority {
            weights: HashMap::new(),
            min_net_strength: 10.0,
        };
        let p = TradingPipeline::new(
            "1".into(),
            "BTCJPY".into(),
            vp,
            risk,
            0.1,
            ExecutionMode::DryRun,
            true,
        );
        let votes = vec![
            mk_vote("a", VoteSide::Buy, 0.5),
            mk_vote("b", VoteSide::Sell, 0.5),
        ];
        let r = p.decide(&votes);
        assert!(matches!(r.intent, Intent::NoTrade { .. }));
    }
}
