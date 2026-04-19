use serde::{Deserialize, Serialize};

use crate::types::{Intent, Side};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskLimits {
    pub max_position_units: f64,
    pub max_order_size: f64,
    pub max_daily_loss_abs: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub enum RiskDecision {
    Ok,
    Blocked { reason: String },
}

pub struct RiskService {
    limits: RiskLimits,
    /// Signed position (+ long, - short) for `symbol` (single-symbol MVP).
    position_units: f64,
    /// Cumulative realized + unrealized PnL for the day (simplified).
    daily_pnl: f64,
}

impl RiskService {
    pub fn new(limits: RiskLimits) -> Self {
        Self {
            limits,
            position_units: 0.0,
            daily_pnl: 0.0,
        }
    }

    pub fn set_position(&mut self, units: f64) {
        self.position_units = units;
    }

    pub fn set_daily_pnl(&mut self, pnl: f64) {
        self.daily_pnl = pnl;
    }

    /// Check whether an order of `quantity` on `side` is allowed.
    pub fn check_new_order(&self, symbol: &str, side: Side, quantity: f64) -> RiskDecision {
        if quantity <= 0.0 || !quantity.is_finite() {
            return RiskDecision::Blocked {
                reason: "invalid quantity".into(),
            };
        }
        if quantity > self.limits.max_order_size {
            return RiskDecision::Blocked {
                reason: format!("order size {quantity} > max {}", self.limits.max_order_size),
            };
        }
        let next_pos = match side {
            Side::Buy => self.position_units + quantity,
            Side::Sell => self.position_units - quantity,
        };
        if next_pos.abs() > self.limits.max_position_units {
            return RiskDecision::Blocked {
                reason: format!(
                    "position {next_pos} on {symbol} would exceed max {}",
                    self.limits.max_position_units
                ),
            };
        }
        if self.daily_pnl < -self.limits.max_daily_loss_abs {
            return RiskDecision::Blocked {
                reason: format!(
                    "daily loss {} exceeds limit {}",
                    self.daily_pnl, self.limits.max_daily_loss_abs
                ),
            };
        }
        RiskDecision::Ok
    }

    /// Turn a raw intent into a possibly blocked intent (MVP: only checks PlaceOrder).
    pub fn apply(&self, intent: Intent, symbol: &str) -> Intent {
        match &intent {
            Intent::PlaceOrder {
                side,
                quantity,
                note: _,
                ..
            } => match self.check_new_order(symbol, *side, *quantity) {
                RiskDecision::Ok => intent,
                RiskDecision::Blocked { reason } => Intent::NoTrade {
                    reason: format!("risk: {reason}"),
                },
            },
            Intent::NoTrade { .. } => intent,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blocks_oversized_order() {
        let limits = RiskLimits {
            max_position_units: 10.0,
            max_order_size: 1.0,
            max_daily_loss_abs: 1000.0,
        };
        let r = RiskService::new(limits);
        match r.check_new_order("BTCJPY", Side::Buy, 2.0) {
            RiskDecision::Blocked { .. } => {}
            _ => panic!("expected block"),
        }
    }
}
