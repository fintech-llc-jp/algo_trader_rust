//! Main trading loop binary.

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    algo_trader_app::init_tracing();

    let config_path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "config.toml".to_string());
    let cfg = algo_trader_app::load_config(&config_path)?;
    algo_trader_app::run_forever(cfg).await
}
