//! Cross-symbol / mispricing stub (MVP: abstain until multi-book wiring exists).

use async_trait::async_trait;
use engine_core::{StrategyVote, VoteSide};
use strategy_api::{MarketSnapshot, Strategy};

pub struct ArbitrageStrategy {
    /// When two mids differ by more than this fraction, vote Buy on cheaper symbol path (stub uses single book).
    pub threshold_pct: f64,
}

impl Default for ArbitrageStrategy {
    fn default() -> Self {
        Self {
            threshold_pct: 0.001,
        }
    }
}

#[async_trait]
impl Strategy for ArbitrageStrategy {
    fn id(&self) -> &'static str {
        "arbitrage"
    }

    async fn evaluate(&self, snapshot: &MarketSnapshot) -> StrategyVote {
        // Stub: without a second venue/symbol book we abstain.
        let _ = (snapshot, self.threshold_pct);
        StrategyVote {
            strategy_id: self.id().to_string(),
            side: VoteSide::Abstain,
            strength: 0.0,
        }
    }
}
