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

impl Default for RuntimeConfig {
    fn default() -> Self {
        Self {
            dry_run: true,
            execution_mode: crate::types::ExecutionMode::DryRun,
            kill_switch_path: None,
            tick_interval_ms: 1000,
            default_order_quantity: 0.01,
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
