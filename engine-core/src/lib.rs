//! Core domain: voting, risk, configuration, exchange abstraction, pipeline orchestration.

pub mod config;
pub mod exchange;
pub mod pipeline;
pub mod risk;
pub mod runtime;
pub mod types;
pub mod vote;

pub use config::{AppConfig, ExchangeConfig};
pub use exchange::{
    CancelOrderRequest, CancelOrderResponse, Exchange, ExchangeError, LoginRequest, LoginResponse,
    NewOrderRequest, NewOrderResponse, OrderBook, OrderBookLevel, PositionEntry, PositionSummary,
};
pub use pipeline::{PipelineResult, TradingPipeline};
pub use risk::{RiskDecision, RiskLimits, RiskService};
pub use runtime::kill_switch_active;
pub use types::{ExecutionMode, Intent, Side};
pub use vote::{StrategyVote, VoteEngine, VoteError, VoteOutcome, VotePolicy, VoteSide};
