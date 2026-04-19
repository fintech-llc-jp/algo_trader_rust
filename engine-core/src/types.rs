use serde::{Deserialize, Serialize};

/// Order / position side.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Side {
    Buy,
    Sell,
}

/// Paper vs live execution.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum ExecutionMode {
    #[default]
    DryRun,
    Live,
}

/// Final trading intent after vote + risk.
#[derive(Debug, Clone, PartialEq)]
pub enum Intent {
    NoTrade {
        reason: String,
    },
    PlaceOrder {
        symbol: String,
        side: Side,
        quantity: f64,
        note: String,
    },
}
