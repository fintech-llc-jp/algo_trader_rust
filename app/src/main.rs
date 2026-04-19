//! Main binary: config, kill-switch, strategy bundle, tick loop.

use std::path::PathBuf;
use std::sync::Arc;

use engine_core::{
    kill_switch_active, AppConfig, Intent, RiskService, StrategyVote, TradingPipeline,
};
use figment::providers::{Env, Format, Toml};
use figment::Figment;
use strategies_arb::ArbitrageStrategy;
use strategies_mm::MarketMakerStrategy;
use strategies_momentum::MomentumStrategy;
use strategies_predict::{PredictStrategyConfig, PricePredictionStrategy};
use strategy_api::{MarketSnapshot, OrderBookTop, Strategy};
use tracing::{info, warn};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("engine=info".parse().unwrap())
                .add_directive("algo_trader=info".parse().unwrap()),
        )
        .init();

    let config_path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "config.toml".to_string());

    let figment = Figment::new()
        .merge(Toml::file(&config_path))
        .merge(Env::prefixed("ALGO_TRADER_").split("__"));

    let cfg: AppConfig = figment.extract()?;
    info!(policy_version = %cfg.policy_version, symbol = %cfg.symbol, "loaded config");

    let risk = RiskService::new(cfg.risk.clone());
    let pipeline = TradingPipeline::new(
        cfg.policy_version.clone(),
        cfg.symbol.clone(),
        cfg.vote.clone(),
        risk,
        cfg.runtime.default_order_quantity,
        cfg.runtime.execution_mode,
        cfg.runtime.dry_run,
    );

    let mm = Arc::new(MarketMakerStrategy::new(0.01, 0.4));
    let arb = Arc::new(ArbitrageStrategy::default());
    let mom = Arc::new(MomentumStrategy::new(2, 0.6));
    let workspace_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("algo-trader-app inside Cargo workspace")
        .to_path_buf();
    let predict_cfg = PredictStrategyConfig {
        model_path: workspace_root.join("ml_bridge/model.onnx"),
        schema_path: workspace_root.join("ml_bridge/feature_schema.json"),
        input_name: "input".into(),
        output_name: "output".into(),
        three_class: false,
    };
    let pred = Arc::new(PricePredictionStrategy::new(predict_cfg));

    let strategies: Vec<Arc<dyn Strategy>> = vec![mm, arb, mom, pred];

    let mut interval = tokio::time::interval(tokio::time::Duration::from_millis(
        cfg.runtime.tick_interval_ms,
    ));

    loop {
        interval.tick().await;

        if kill_switch_active(cfg.runtime.kill_switch_path.as_ref()) {
            warn!(
                path = ?cfg.runtime.kill_switch_path,
                "kill switch active — skipping tick"
            );
            continue;
        }

        let snapshot = sample_snapshot(&cfg.symbol).await;

        let mut votes: Vec<StrategyVote> = Vec::new();
        for s in &strategies {
            votes.push(s.evaluate(&snapshot).await);
        }

        let result = pipeline.decide(&votes);
        pipeline.log_tick(&result);

        if pipeline.is_live_execution() {
            if let Intent::PlaceOrder {
                side,
                quantity,
                symbol,
                ..
            } = &result.intent
            {
                info!(?side, quantity, %symbol, "live execution would send order (wire in adapter)");
            }
        }
    }
}

/// Stub snapshot until exchange wiring fills real books.
async fn sample_snapshot(symbol: &str) -> MarketSnapshot {
    MarketSnapshot {
        symbol: symbol.to_string(),
        book: OrderBookTop {
            best_bid: Some(100.0),
            best_ask: Some(100.5),
            bid_qty: Some(1.0),
            ask_qty: Some(1.0),
        },
        bars: vec![
            strategy_api::Bar {
                open: 99.0,
                high: 101.0,
                low: 98.0,
                close: 100.0,
                volume: 10.0,
            },
            strategy_api::Bar {
                open: 100.0,
                high: 102.0,
                low: 99.5,
                close: 101.0,
                volume: 12.0,
            },
        ],
        now_ms: chrono_now_ms(),
    }
}

fn chrono_now_ms() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}
