//! Simple momentum from recent bar closes.

use async_trait::async_trait;
use engine_core::{StrategyVote, VoteSide};
use strategy_api::{MarketSnapshot, Strategy};

pub struct MomentumStrategy {
    min_bars: usize,
    strength: f64,
}

impl MomentumStrategy {
    pub fn new(min_bars: usize, strength: f64) -> Self {
        Self {
            min_bars,
            strength: strength.clamp(0.0, 1.0),
        }
    }
}

#[async_trait]
impl Strategy for MomentumStrategy {
    fn id(&self) -> &'static str {
        "momentum"
    }

    async fn evaluate(&self, snapshot: &MarketSnapshot) -> StrategyVote {
        if snapshot.bars.len() < self.min_bars {
            return StrategyVote::abstain(self.id());
        }
        let a = snapshot.bars[snapshot.bars.len() - 2].close;
        let b = snapshot.bars[snapshot.bars.len() - 1].close;
        let ret = (b - a) / a.max(1e-12);
        let side = if ret > 0.0 {
            VoteSide::Buy
        } else if ret < 0.0 {
            VoteSide::Sell
        } else {
            VoteSide::Hold
        };
        StrategyVote {
            strategy_id: self.id().to_string(),
            side,
            strength: self.strength * ret.abs().min(1.0),
        }
    }
}
