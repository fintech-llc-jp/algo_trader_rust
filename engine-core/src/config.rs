use serde::{Deserialize, Serialize};
use std::path::PathBuf;

use crate::risk::RiskLimits;
use crate::vote::VotePolicy;

/// Top-level application configuration (TOML + env overlay via figment in `app`).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    /// Logged on startup for audit trail.
    pub policy_version: String,
    pub symbol: String,
    pub vote: VotePolicy,
    pub risk: RiskLimits,
    #[serde(default)]
    pub runtime: RuntimeConfig,
    /// When set, `app` uses [`crate::exchange::Exchange`] (ExchSim) for board, orders, positions.
    #[serde(default)]
    pub exchange: Option<ExchangeConfig>,
}

/// ExchSim REST endpoint and credentials via environment variable names (values are not stored in TOML).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExchangeConfig {
    pub base_url: String,
    /// JWT: read from `std::env::var(token_env)` (e.g. `EXCHSIM_JWT_TOKEN`).
    #[serde(default)]
    pub token_env: Option<String>,
    /// Alternative: login with `std::env::var(username_env)` and `password_env`.
    #[serde(default)]
    pub username_env: Option<String>,
    #[serde(default)]
    pub password_env: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeConfig {
    #[serde(default = "default_dry_run")]
    pub dry_run: bool,
    #[serde(default)]
    pub execution_mode: crate::types::ExecutionMode,
    /// If this file exists, engine refuses new orders (kill switch).
    #[serde(default)]
    pub kill_switch_path: Option<PathBuf>,
    #[serde(default = "default_tick_ms")]
    pub tick_interval_ms: u64,
    #[serde(default = "default_order_qty")]
    pub default_order_quantity: f64,
    /// How often to refresh [`crate::risk::RiskService`] position from the exchange (ms). `0` = every tick.
    #[serde(default = "default_sync_position_interval_ms")]
    pub sync_position_interval_ms: u64,
}

fn default_dry_run() -> bool {
    true
}

fn default_tick_ms() -> u64 {
    1000
}

fn default_order_qty() -> f64 {
    0.01
}

fn default_sync_position_interval_ms() -> u64 {
    5000
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        Self {
            dry_run: true,
            execution_mode: crate::types::ExecutionMode::DryRun,
            kill_switch_path: None,
            tick_interval_ms: 1000,
            default_order_quantity: 0.01,
            sync_position_interval_ms: 5000,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::vote::VotePolicy;

    #[test]
    fn parse_sample_vote_policy_toml() {
        let toml_str = r#"
            policy_version = "1"
            symbol = "BTCJPY"
            [vote]
            mode = "weighted_majority"
            min_net_strength = 0.3
            [vote.weights]
            market_maker = 1.0
            momentum = 1.2
            [risk]
            max_position_units = 5.0
            max_order_size = 1.0
            max_daily_loss_abs = 10000.0
        "#;
        let cfg: AppConfig = toml::from_str(toml_str).expect("parse");
        assert_eq!(cfg.policy_version, "1");
        match &cfg.vote {
            VotePolicy::WeightedMajority {
                min_net_strength,
                weights,
            } => {
                assert!((*min_net_strength - 0.3).abs() < 1e-6);
                assert_eq!(weights.get("momentum"), Some(&1.2));
            }
            _ => panic!("expected weighted"),
        }
    }
}
