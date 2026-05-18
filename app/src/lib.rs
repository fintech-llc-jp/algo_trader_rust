use std::path::PathBuf;
use std::sync::Arc;

use adapter_exchsim::ExchSimAdapter;
use engine_core::{
    kill_switch_active, AppConfig, Exchange, ExchangeConfig, Intent, NewOrderRequest, OrderBook,
    RiskService, StrategyVote, TradingPipeline,
};
use figment::providers::{Env, Format, Toml};
use figment::Figment;
use strategies_arb::ArbitrageStrategy;
use strategies_mm::MarketMakerStrategy;
use strategies_momentum::MomentumStrategy;
use strategies_predict::{PredictStrategyConfig, PricePredictionStrategy};
use strategy_api::{Bar, MarketSnapshot, OrderBookTop, Strategy};
use tokio::sync::{watch, RwLock};
use tokio::task::JoinHandle;
use tracing::{info, warn};

#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionState {
    Running,
    Stopped,
    Error,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct SessionSnapshot {
    pub state: SessionState,
    pub started_at_ms: i64,
    pub ended_at_ms: Option<i64>,
    pub tick_count: u64,
    pub last_intent: Option<String>,
    pub last_error: Option<String>,
}

#[derive(Debug, Clone)]
struct SessionRuntime {
    state: SessionState,
    started_at_ms: i64,
    ended_at_ms: Option<i64>,
    tick_count: u64,
    last_intent: Option<String>,
    last_error: Option<String>,
}

impl SessionRuntime {
    fn new() -> Self {
        Self {
            state: SessionState::Running,
            started_at_ms: chrono_now_ms(),
            ended_at_ms: None,
            tick_count: 0,
            last_intent: None,
            last_error: None,
        }
    }

    fn snapshot(&self) -> SessionSnapshot {
        SessionSnapshot {
            state: self.state.clone(),
            started_at_ms: self.started_at_ms,
            ended_at_ms: self.ended_at_ms,
            tick_count: self.tick_count,
            last_intent: self.last_intent.clone(),
            last_error: self.last_error.clone(),
        }
    }
}

pub struct ManagedSession {
    runtime: Arc<RwLock<SessionRuntime>>,
    stop_tx: watch::Sender<bool>,
    task: JoinHandle<()>,
}

impl ManagedSession {
    pub fn snapshot(&self) -> SessionSnapshot {
        // blocking_read is acceptable for quick status endpoint reads.
        self.runtime.blocking_read().snapshot()
    }

    pub async fn stop(self) {
        let _ = self.stop_tx.send(true);
        let _ = self.task.await;
    }
}

pub fn init_tracing() {
    let _ = tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("engine=info".parse().unwrap())
                .add_directive("algo_trader=info".parse().unwrap()),
        )
        .try_init();
}

pub fn load_config(config_path: &str) -> anyhow::Result<AppConfig> {
    let figment = Figment::new()
        .merge(Toml::file(config_path))
        .merge(Env::prefixed("ALGO_TRADER_").split("__"));
    Ok(figment.extract()?)
}

pub async fn run_forever(cfg: AppConfig) -> anyhow::Result<()> {
    let mut runner = EngineRunner::new(cfg)?;
    loop {
        let intent = runner.tick().await;
        info!(%intent, "tick result");
    }
}

pub fn spawn_session(cfg: AppConfig) -> anyhow::Result<ManagedSession> {
    let mut runner = EngineRunner::new(cfg)?;
    let runtime = Arc::new(RwLock::new(SessionRuntime::new()));
    let (stop_tx, mut stop_rx) = watch::channel(false);
    let runtime_clone = Arc::clone(&runtime);

    let task = tokio::spawn(async move {
        loop {
            tokio::select! {
                _ = stop_rx.changed() => {
                    if *stop_rx.borrow() {
                        let mut rt = runtime_clone.write().await;
                        rt.state = SessionState::Stopped;
                        rt.ended_at_ms = Some(chrono_now_ms());
                        break;
                    }
                }
                _ = runner.interval.tick() => {
                    let result = runner.execute_tick().await;
                    let mut rt = runtime_clone.write().await;
                    rt.tick_count = rt.tick_count.saturating_add(1);
                    match result {
                        Ok(intent) => {
                            rt.last_intent = Some(intent);
                        }
                        Err(e) => {
                            rt.state = SessionState::Error;
                            rt.last_error = Some(e.to_string());
                            rt.ended_at_ms = Some(chrono_now_ms());
                            break;
                        }
                    }
                }
            }
        }
    });

    Ok(ManagedSession {
        runtime,
        stop_tx,
        task,
    })
}

struct EngineRunner {
    cfg: AppConfig,
    risk: RiskService,
    pipeline: TradingPipeline,
    exchange: Option<Arc<dyn Exchange>>,
    strategies: Vec<Arc<dyn Strategy>>,
    sync_every_ticks: u64,
    tick_count: u64,
    last_mid: Option<f64>,
    interval: tokio::time::Interval,
}

impl EngineRunner {
    fn new(cfg: AppConfig) -> anyhow::Result<Self> {
        info!(policy_version = %cfg.policy_version, symbol = %cfg.symbol, "loaded config");
        let risk = RiskService::new(cfg.risk.clone());
        let pipeline = TradingPipeline::new(
            cfg.policy_version.clone(),
            cfg.symbol.clone(),
            cfg.vote.clone(),
            cfg.runtime.default_order_quantity,
            cfg.runtime.execution_mode,
            cfg.runtime.dry_run,
        );

        let exchange: Option<Arc<dyn Exchange>> = match &cfg.exchange {
            Some(ec) => Some(Arc::new(build_adapter(ec)?)),
            None => {
                info!("no [exchange] in config — using stub order book");
                None
            }
        };

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

        let sync_every_ticks = {
            let sync_ms = cfg.runtime.sync_position_interval_ms;
            if sync_ms == 0 {
                1_u64
            } else {
                (sync_ms / cfg.runtime.tick_interval_ms).max(1)
            }
        };

        let interval = tokio::time::interval(tokio::time::Duration::from_millis(
            cfg.runtime.tick_interval_ms,
        ));

        Ok(Self {
            cfg,
            risk,
            pipeline,
            exchange,
            strategies,
            sync_every_ticks,
            tick_count: 0,
            last_mid: None,
            interval,
        })
    }

    async fn tick(&mut self) -> String {
        self.interval.tick().await;
        self.execute_tick()
            .await
            .unwrap_or_else(|e| format!("error: {e}"))
    }

    async fn execute_tick(&mut self) -> anyhow::Result<String> {
        self.tick_count = self.tick_count.wrapping_add(1);

        if kill_switch_active(self.cfg.runtime.kill_switch_path.as_ref()) {
            warn!(
                path = ?self.cfg.runtime.kill_switch_path,
                "kill switch active — skipping tick"
            );
            return Ok("no_trade(kill_switch_active)".into());
        }

        let snapshot = if let Some(ex) = self.exchange.as_ref() {
            match ex.get_order_book(&self.cfg.symbol).await {
                Ok(book) => {
                    let snap = book_to_snapshot(&book, &self.cfg.symbol, self.last_mid);
                    self.last_mid = snap.book.mid();
                    snap
                }
                Err(e) => {
                    warn!(?e, "order book fetch failed — fallback snapshot");
                    sample_snapshot(&self.cfg.symbol).await
                }
            }
        } else {
            sample_snapshot(&self.cfg.symbol).await
        };

        if self.exchange.is_some() && self.tick_count.is_multiple_of(self.sync_every_ticks) {
            if let Some(ex) = self.exchange.as_ref() {
                match ex.get_position_summary().await {
                    Ok(ps) => {
                        let q = ps.quantity_for_symbol(&self.cfg.symbol);
                        self.risk.set_position(q);
                        info!(position = q, symbol = %self.cfg.symbol, "position sync");
                    }
                    Err(e) => warn!(?e, "position sync failed"),
                }
            }
        }

        let mut votes: Vec<StrategyVote> = Vec::new();
        for s in &self.strategies {
            votes.push(s.evaluate(&snapshot).await);
        }

        let result = self.pipeline.decide(&votes, &self.risk);
        self.pipeline.log_tick(&result);
        let intent_summary = format!("{:?}", result.intent);

        if self.pipeline.is_live_execution() {
            if let Intent::PlaceOrder {
                side,
                quantity,
                symbol,
                ..
            } = &result.intent
            {
                let Some(ex) = self.exchange.as_ref() else {
                    warn!("live execution requires [exchange] in config");
                    return Ok("no_trade(live_requires_exchange)".into());
                };
                let req = NewOrderRequest {
                    symbol: symbol.clone(),
                    side: side_to_exch_string(*side),
                    ord_type: "MARKET".into(),
                    price: None,
                    quantity: *quantity,
                    tif: Some("DAY".into()),
                    open: None,
                    close: None,
                };
                match ex.place_order(req).await {
                    Ok(resp) => info!(?resp, "order placed"),
                    Err(e) => warn!(?e, "place_order failed"),
                }
            }
        }

        Ok(intent_summary)
    }
}

fn build_adapter(cfg: &ExchangeConfig) -> anyhow::Result<ExchSimAdapter> {
    if let Some(key) = &cfg.token_env {
        let token = std::env::var(key).map_err(|e| anyhow::anyhow!("env {key}: {e}"))?;
        return Ok(ExchSimAdapter::from_token(&cfg.base_url, token));
    }
    match (&cfg.username_env, &cfg.password_env) {
        (Some(ue), Some(pe)) => {
            let u = std::env::var(ue).map_err(|e| anyhow::anyhow!("env {ue}: {e}"))?;
            let p = std::env::var(pe).map_err(|e| anyhow::anyhow!("env {pe}: {e}"))?;
            Ok(ExchSimAdapter::from_credentials(&cfg.base_url, u, p))
        }
        _ => anyhow::bail!(
            "exchange: set token_env (e.g. EXCHSIM_JWT_TOKEN) or username_env + password_env"
        ),
    }
}

fn side_to_exch_string(side: engine_core::Side) -> String {
    match side {
        engine_core::Side::Buy => "Buy".into(),
        engine_core::Side::Sell => "Sell".into(),
    }
}

fn book_to_snapshot(book: &OrderBook, symbol: &str, prev_mid: Option<f64>) -> MarketSnapshot {
    let top = OrderBookTop {
        best_bid: book.best_bid(),
        best_ask: book.best_ask(),
        bid_qty: book.best_bid_qty(),
        ask_qty: book.best_ask_qty(),
    };
    let mid = top.mid().unwrap_or_else(|| prev_mid.unwrap_or(100.0));
    let prev = prev_mid.unwrap_or(mid);
    let bars = vec![
        Bar {
            open: prev,
            high: prev.max(mid),
            low: prev.min(mid),
            close: prev,
            volume: 1.0,
        },
        Bar {
            open: mid,
            high: mid,
            low: mid,
            close: mid,
            volume: 1.0,
        },
    ];
    MarketSnapshot {
        symbol: symbol.to_string(),
        book: top,
        bars,
        now_ms: chrono_now_ms(),
    }
}

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
