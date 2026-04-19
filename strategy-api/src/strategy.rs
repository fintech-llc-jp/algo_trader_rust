use async_trait::async_trait;
use engine_core::StrategyVote;

use crate::snapshot::MarketSnapshot;

#[async_trait]
pub trait Strategy: Send + Sync {
    fn id(&self) -> &'static str;

    async fn evaluate(&self, snapshot: &MarketSnapshot) -> StrategyVote;
}
