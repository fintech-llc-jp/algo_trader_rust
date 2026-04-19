use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use thiserror::Error;

use crate::types::Side;

/// Voting side (includes hold / abstain for aggregation).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VoteSide {
    Buy,
    Sell,
    Hold,
    Abstain,
}

/// One strategy's vote.
#[derive(Debug, Clone, PartialEq)]
pub struct StrategyVote {
    pub strategy_id: String,
    pub side: VoteSide,
    /// Confidence in \[0, 1\].
    pub strength: f64,
}

impl StrategyVote {
    pub fn abstain(strategy_id: impl Into<String>) -> Self {
        Self {
            strategy_id: strategy_id.into(),
            side: VoteSide::Abstain,
            strength: 0.0,
        }
    }
}

/// How to combine votes (deserialized from config).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "mode", rename_all = "snake_case")]
pub enum VotePolicy {
    /// Sum weighted strengths on buy vs sell; |net| must exceed threshold.
    WeightedMajority {
        #[serde(default)]
        weights: HashMap<String, f64>,
        min_net_strength: f64,
    },
    /// At least `required_same_side` strategies must agree on Buy or Sell (non-abstain).
    Quorum {
        required_same_side: usize,
        min_strength_per_vote: f64,
    },
    /// Choose side with largest total strength (Buy vs Sell); ties → Hold.
    SimplePlurality,
}

#[derive(Debug, Clone, PartialEq)]
pub struct VoteOutcome {
    pub side: VoteSide,
    pub net_strength: f64,
    pub detail: String,
}

#[derive(Debug, Error)]
pub enum VoteError {
    #[error("no actionable votes")]
    NoVotes,
}

pub struct VoteEngine;

impl VoteEngine {
    pub fn aggregate(
        votes: &[StrategyVote],
        policy: &VotePolicy,
    ) -> Result<VoteOutcome, VoteError> {
        if votes.is_empty() {
            return Err(VoteError::NoVotes);
        }

        match policy {
            VotePolicy::WeightedMajority {
                weights,
                min_net_strength,
            } => Self::weighted(votes, weights, *min_net_strength),
            VotePolicy::Quorum {
                required_same_side,
                min_strength_per_vote,
            } => Self::quorum(votes, *required_same_side, *min_strength_per_vote),
            VotePolicy::SimplePlurality => Self::plurality(votes),
        }
    }

    fn weight_for(weights: &HashMap<String, f64>, id: &str) -> f64 {
        weights.get(id).copied().unwrap_or(1.0)
    }

    fn weighted(
        votes: &[StrategyVote],
        weights: &HashMap<String, f64>,
        min_net: f64,
    ) -> Result<VoteOutcome, VoteError> {
        let mut buy = 0.0_f64;
        let mut sell = 0.0_f64;
        for v in votes {
            let w = Self::weight_for(weights, &v.strategy_id);
            match v.side {
                VoteSide::Buy => buy += v.strength * w,
                VoteSide::Sell => sell += v.strength * w,
                VoteSide::Hold | VoteSide::Abstain => {}
            }
        }
        let net = buy - sell;
        let abs = net.abs();
        let side = if abs < min_net {
            VoteSide::Hold
        } else if net > 0.0 {
            VoteSide::Buy
        } else {
            VoteSide::Sell
        };
        Ok(VoteOutcome {
            side,
            net_strength: net,
            detail: format!(
                "weighted net={net:.4} (buy={buy:.4}, sell={sell:.4}, min_net={min_net})"
            ),
        })
    }

    fn quorum(
        votes: &[StrategyVote],
        required: usize,
        min_s: f64,
    ) -> Result<VoteOutcome, VoteError> {
        let mut buy_n = 0usize;
        let mut sell_n = 0usize;
        let mut buy_sum = 0.0_f64;
        let mut sell_sum = 0.0_f64;
        for v in votes {
            if v.strength < min_s {
                continue;
            }
            match v.side {
                VoteSide::Buy => {
                    buy_n += 1;
                    buy_sum += v.strength;
                }
                VoteSide::Sell => {
                    sell_n += 1;
                    sell_sum += v.strength;
                }
                VoteSide::Hold | VoteSide::Abstain => {}
            }
        }
        let side = if buy_n >= required && buy_n >= sell_n {
            VoteSide::Buy
        } else if sell_n >= required && sell_n > buy_n {
            VoteSide::Sell
        } else {
            VoteSide::Hold
        };
        let net = buy_sum - sell_sum;
        Ok(VoteOutcome {
            side,
            net_strength: net,
            detail: format!("quorum buy_n={buy_n} sell_n={sell_n} required={required}"),
        })
    }

    fn plurality(votes: &[StrategyVote]) -> Result<VoteOutcome, VoteError> {
        let mut buy = 0.0_f64;
        let mut sell = 0.0_f64;
        for v in votes {
            match v.side {
                VoteSide::Buy => buy += v.strength,
                VoteSide::Sell => sell += v.strength,
                VoteSide::Hold | VoteSide::Abstain => {}
            }
        }
        let net = buy - sell;
        let eps = 1e-9;
        let side = if (buy - sell).abs() < eps {
            VoteSide::Hold
        } else if buy > sell {
            VoteSide::Buy
        } else {
            VoteSide::Sell
        };
        Ok(VoteOutcome {
            side,
            net_strength: net,
            detail: format!("plurality buy={buy:.4} sell={sell:.4}"),
        })
    }
}

/// Map consensus vote to order side when not Hold/Abstain.
pub fn vote_side_to_order_side(v: VoteSide) -> Option<Side> {
    match v {
        VoteSide::Buy => Some(Side::Buy),
        VoteSide::Sell => Some(Side::Sell),
        VoteSide::Hold | VoteSide::Abstain => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(id: &str, side: VoteSide, s: f64) -> StrategyVote {
        StrategyVote {
            strategy_id: id.to_string(),
            side,
            strength: s,
        }
    }

    #[test]
    fn weighted_majority_net_below_min_is_hold() {
        let votes = vec![v("a", VoteSide::Buy, 0.2), v("b", VoteSide::Sell, 0.2)];
        let p = VotePolicy::WeightedMajority {
            weights: HashMap::new(),
            min_net_strength: 0.5,
        };
        let out = VoteEngine::aggregate(&votes, &p).unwrap();
        assert_eq!(out.side, VoteSide::Hold);
    }

    #[test]
    fn weighted_majority_clear_buy() {
        let votes = vec![v("a", VoteSide::Buy, 0.9), v("b", VoteSide::Sell, 0.1)];
        let p = VotePolicy::WeightedMajority {
            weights: HashMap::from([("a".to_string(), 1.0), ("b".to_string(), 1.0)]),
            min_net_strength: 0.2,
        };
        let out = VoteEngine::aggregate(&votes, &p).unwrap();
        assert_eq!(out.side, VoteSide::Buy);
    }

    #[test]
    fn quorum_needs_three_buy() {
        let votes = vec![
            v("a", VoteSide::Buy, 0.9),
            v("b", VoteSide::Buy, 0.9),
            v("c", VoteSide::Sell, 0.9),
        ];
        let p = VotePolicy::Quorum {
            required_same_side: 2,
            min_strength_per_vote: 0.5,
        };
        let out = VoteEngine::aggregate(&votes, &p).unwrap();
        assert_eq!(out.side, VoteSide::Buy);
    }

    #[test]
    fn all_abstain_quorum_holds() {
        let votes = vec![StrategyVote::abstain("a"), StrategyVote::abstain("b")];
        let p = VotePolicy::Quorum {
            required_same_side: 1,
            min_strength_per_vote: 0.1,
        };
        let out = VoteEngine::aggregate(&votes, &p).unwrap();
        assert_eq!(out.side, VoteSide::Hold);
    }
}
