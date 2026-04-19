use serde::{Deserialize, Serialize};

/// Best bid/ask snapshot.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct OrderBookTop {
    pub best_bid: Option<f64>,
    pub best_ask: Option<f64>,
    pub bid_qty: Option<f64>,
    pub ask_qty: Option<f64>,
}

impl OrderBookTop {
    pub fn mid(&self) -> Option<f64> {
        match (self.best_bid, self.best_ask) {
            (Some(b), Some(a)) => Some((b + a) / 2.0),
            _ => None,
        }
    }

    pub fn spread(&self) -> Option<f64> {
        match (self.best_bid, self.best_ask) {
            (Some(b), Some(a)) => Some(a - b),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Bar {
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
}

/// Inputs passed to strategies each tick.
#[derive(Debug, Clone, Default)]
pub struct MarketSnapshot {
    pub symbol: String,
    pub book: OrderBookTop,
    /// Recent bars, oldest first (caller-defined length).
    pub bars: Vec<Bar>,
    pub now_ms: i64,
}
