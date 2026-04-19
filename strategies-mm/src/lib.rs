//! Market-making strategy (MVP: quote skew from mid/spread).

use async_trait::async_trait;
use engine_core::{StrategyVote, VoteSide};
use strategy_api::{MarketSnapshot, Strategy};

pub struct MarketMakerStrategy {
    min_spread_abs: f64,
    quote_strength: f64,
}

impl MarketMakerStrategy {
    pub fn new(min_spread_abs: f64, quote_strength: f64) -> Self {
        Self {
            min_spread_abs,
            quote_strength: quote_strength.clamp(0.0, 1.0),
        }
    }
}

#[async_trait]
impl Strategy for MarketMakerStrategy {
    fn id(&self) -> &'static str {
        "market_maker"
    }

    async fn evaluate(&self, snapshot: &MarketSnapshot) -> StrategyVote {
        let Some(spread) = snapshot.book.spread() else {
            return StrategyVote::abstain(self.id());
        };
        if spread < self.min_spread_abs {
            return StrategyVote {
                strategy_id: self.id().to_string(),
                side: VoteSide::Hold,
                strength: 0.2,
            };
        }
        // Inventory-neutral MVP: lean buy when spread is wide (simulated inventory not tracked).
        StrategyVote {
            strategy_id: self.id().to_string(),
            side: VoteSide::Buy,
            strength: self.quote_strength,
        }
    }
}
