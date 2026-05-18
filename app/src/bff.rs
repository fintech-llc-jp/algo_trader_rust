//! Minimal BFF for unified `/v1/*` APIs.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use axum::extract::Request;
use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, HeaderName, HeaderValue, Method, StatusCode};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, options, post, put};
use axum::{Json, Router};
use reqwest::Client;
use serde_json::Value;
use tokio::net::TcpListener;
use tokio::sync::Mutex;
use tracing::{info, warn};

#[derive(Clone)]
struct AppState {
    client: Client,
    control_base_url: String,
    training_base_url: String,
    backtest_base_url: String,
    ml_base_url: String,
    read_api_key: Option<String>,
    write_api_key: Option<String>,
    get_retry_count: usize,
    idempotency_ttl_ms: u64,
    idempotency_max_entries: usize,
    idempotency_store_path: Option<PathBuf>,
    request_seq: Arc<AtomicU64>,
    idempotency: Arc<Mutex<HashMap<String, CachedResponse>>>,
    metrics: Arc<BffMetrics>,
    ui_state: Arc<Mutex<UiState>>,
}

#[derive(Clone, serde::Serialize, serde::Deserialize)]
struct CachedResponse {
    status: u16,
    body: Value,
    created_at_ms: i64,
}

#[derive(Default)]
struct BffMetrics {
    requests_total: AtomicU64,
    auth_rejected_total: AtomicU64,
    upstream_failure_total: AtomicU64,
    idempotency_hit_total: AtomicU64,
}

#[derive(Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct UiRuntimeConfig {
    execution_mode: String,
    tick_interval_ms: u64,
    default_order_quantity: f64,
}

#[derive(Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct UiRiskLimits {
    max_position_units: f64,
    max_order_size: f64,
    max_daily_loss_abs: f64,
}

#[derive(Clone, serde::Serialize, serde::Deserialize)]
#[serde(tag = "mode", rename_all = "snake_case")]
enum UiVotePolicy {
    WeightedMajority {
        min_net_strength: f64,
        weights: HashMap<String, f64>,
    },
    Quorum {
        required_same_side: usize,
        min_strength_per_vote: f64,
    },
    SimplePlurality,
}

#[derive(Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct UiConfig {
    policy_version: String,
    symbol: String,
    vote: UiVotePolicy,
    risk: UiRiskLimits,
    runtime: UiRuntimeConfig,
}

#[derive(Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct UiRiskState {
    limits: UiRiskLimits,
    daily_pnl: f64,
    position_units: f64,
}

#[derive(Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct UiState {
    config: UiConfig,
    risk_state: UiRiskState,
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct UpdateDailyPnlRequest {
    daily_pnl: f64,
}

#[derive(Debug, serde::Deserialize)]
struct StartSessionRequest {
    config_path: Option<String>,
}

#[derive(Clone, Copy)]
enum AccessNeed {
    Read,
    Write,
}

mod error_code {
    pub const AUTH_MISSING_API_KEY: &str = "AUTH_001";
    pub const AUTH_FORBIDDEN: &str = "AUTH_002";
    pub const VALIDATION_FAILED: &str = "REQ_001";
    pub const UPSTREAM_TIMEOUT: &str = "UPSTREAM_001";
    pub const UPSTREAM_CONNECT_FAILED: &str = "UPSTREAM_002";
    pub const UPSTREAM_SEND_FAILED: &str = "UPSTREAM_003";
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    algo_trader_app::init_tracing();

    let listen_addr = std::env::args()
        .nth(1)
        .or_else(|| std::env::var("ALGO_TRADER_BFF_ADDR").ok())
        .unwrap_or_else(|| "127.0.0.1:8090".to_string());
    let control_base_url = std::env::var("ALGO_TRADER_CONTROL_BASE_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:8088".to_string())
        .trim_end_matches('/')
        .to_string();
    let training_base_url = std::env::var("ALGO_TRADER_PY_TRAINING_BASE_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:8001".to_string())
        .trim_end_matches('/')
        .to_string();
    let backtest_base_url = std::env::var("ALGO_TRADER_PY_BACKTEST_BASE_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:8002".to_string())
        .trim_end_matches('/')
        .to_string();
    let ml_base_url = std::env::var("ALGO_TRADER_PY_ML_BASE_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:8000".to_string())
        .trim_end_matches('/')
        .to_string();
    let timeout_ms = std::env::var("ALGO_TRADER_BFF_TIMEOUT_MS")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(5000);
    let get_retry_count = std::env::var("ALGO_TRADER_BFF_GET_RETRY")
        .ok()
        .and_then(|s| s.parse::<usize>().ok())
        .unwrap_or(1);
    let idempotency_ttl_ms = std::env::var("ALGO_TRADER_BFF_IDEMPOTENCY_TTL_MS")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(15 * 60 * 1000);
    let idempotency_max_entries = std::env::var("ALGO_TRADER_BFF_IDEMPOTENCY_MAX_ENTRIES")
        .ok()
        .and_then(|s| s.parse::<usize>().ok())
        .unwrap_or(1000);
    let idempotency_store_path = std::env::var("ALGO_TRADER_BFF_IDEMPOTENCY_STORE_PATH")
        .ok()
        .map(PathBuf::from);
    let read_api_key = std::env::var("ALGO_TRADER_BFF_READ_API_KEY").ok();
    let write_api_key = std::env::var("ALGO_TRADER_BFF_WRITE_API_KEY").ok();
    let client = Client::builder()
        .timeout(std::time::Duration::from_millis(timeout_ms))
        .build()?;

    let mut initial_idempotency = if let Some(path) = idempotency_store_path.as_ref() {
        load_idempotency_cache(path).await
    } else {
        HashMap::new()
    };
    prune_expired_entries(&mut initial_idempotency, chrono_now_ms(), idempotency_ttl_ms);
    if initial_idempotency.len() > idempotency_max_entries {
        prune_oldest_entries(&mut initial_idempotency, idempotency_max_entries);
    }

    let state = AppState {
        client,
        control_base_url: control_base_url.clone(),
        training_base_url: training_base_url.clone(),
        backtest_base_url: backtest_base_url.clone(),
        ml_base_url: ml_base_url.clone(),
        read_api_key: read_api_key.clone(),
        write_api_key: write_api_key.clone(),
        get_retry_count,
        idempotency_ttl_ms,
        idempotency_max_entries,
        idempotency_store_path: idempotency_store_path.clone(),
        request_seq: Arc::new(AtomicU64::new(1)),
        idempotency: Arc::new(Mutex::new(initial_idempotency)),
        metrics: Arc::new(BffMetrics::default()),
        ui_state: Arc::new(Mutex::new(default_ui_state())),
    };

    let app = Router::new()
        .route("/v1/sessions", post(create_session))
        .route("/v1/sessions/{id}", delete(delete_session))
        .route("/v1/sessions/{id}/status", get(get_session_status))
        .route("/v1/ui/config", get(get_ui_config).put(put_ui_config))
        .route("/v1/ui/risk", get(get_ui_risk))
        .route("/v1/ui/risk/limits", put(put_ui_risk_limits))
        .route("/v1/ui/risk/daily-pnl", put(put_ui_daily_pnl))
        .route("/v1/training/jobs", post(create_training_job))
        .route(
            "/v1/training/jobs/{job_id}",
            get(get_training_job).delete(cancel_training_job),
        )
        .route("/v1/backtests", post(create_backtest))
        .route(
            "/v1/backtests/{job_id}",
            get(get_backtest).delete(cancel_backtest),
        )
        .route("/v1/backtests/{job_id}/result", get(get_backtest_result))
        .route("/v1/models", get(get_models))
        .route("/metrics", get(get_metrics))
        .route("/healthz", get(healthz))
        .route("/{*path}", options(cors_preflight))
        .with_state(state)
        .layer(middleware::from_fn(cors_middleware));

    let listener = TcpListener::bind(&listen_addr).await?;
    info!(
        %listen_addr,
        %control_base_url,
        %training_base_url,
        %backtest_base_url,
        %ml_base_url,
        timeout_ms,
        get_retry_count,
        idempotency_ttl_ms,
        idempotency_max_entries,
        idempotency_store_enabled = idempotency_store_path.is_some(),
        auth_read_enabled = read_api_key.is_some(),
        auth_write_enabled = write_api_key.is_some(),
        "algo-trader-bff listening"
    );
    axum::serve(listener, app).await?;
    Ok(())
}

async fn healthz() -> StatusCode {
    StatusCode::OK
}

async fn cors_preflight() -> Response {
    let mut headers = HeaderMap::new();
    inject_cors_headers(&mut headers);
    (StatusCode::NO_CONTENT, headers).into_response()
}

async fn cors_middleware(req: Request, next: Next) -> Response {
    if req.method() == Method::OPTIONS {
        return cors_preflight().await;
    }
    let mut resp = next.run(req).await;
    inject_cors_headers(resp.headers_mut());
    resp
}

async fn get_metrics(headers: HeaderMap, State(state): State<AppState>) -> Response {
    let entries = state.idempotency.lock().await.len();
    let requests_total = state.metrics.requests_total.load(Ordering::Relaxed);
    let auth_rejected_total = state.metrics.auth_rejected_total.load(Ordering::Relaxed);
    let upstream_failure_total = state.metrics.upstream_failure_total.load(Ordering::Relaxed);
    let idempotency_hit_total = state.metrics.idempotency_hit_total.load(Ordering::Relaxed);

    let wants_prom = headers
        .get("accept")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.contains("text/plain") || s.contains("application/openmetrics-text"))
        .unwrap_or(false);

    if wants_prom {
        let body = format!(
            "# TYPE bff_requests_total counter\nbff_requests_total {}\n# TYPE bff_auth_rejected_total counter\nbff_auth_rejected_total {}\n# TYPE bff_upstream_failure_total counter\nbff_upstream_failure_total {}\n# TYPE bff_idempotency_hit_total counter\nbff_idempotency_hit_total {}\n# TYPE bff_idempotency_cache_entries gauge\nbff_idempotency_cache_entries {}\n",
            requests_total, auth_rejected_total, upstream_failure_total, idempotency_hit_total, entries
        );
        return (
            StatusCode::OK,
            [("content-type", "text/plain; version=0.0.4")],
            body,
        )
            .into_response();
    }

    Json(serde_json::json!({
        "requests_total": requests_total,
        "auth_rejected_total": auth_rejected_total,
        "upstream_failure_total": upstream_failure_total,
        "idempotency_hit_total": idempotency_hit_total,
        "idempotency_cache_entries": entries,
        "idempotency_ttl_ms": state.idempotency_ttl_ms,
        "idempotency_max_entries": state.idempotency_max_entries,
    }))
    .into_response()
}

async fn create_session(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<StartSessionRequest>,
) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Write, &corr_id) {
        return resp;
    }
    if let Some(resp) = maybe_idempotent_hit(&state, &headers, "create_session", &corr_id).await {
        return resp;
    }
    let url = format!("{}/sessions", state.control_base_url);
    let body = serde_json::json!({
        "config_path": req.config_path.unwrap_or_else(|| "config.toml".to_string())
    });
    match forward_json(
        &state.client,
        reqwest::Method::POST,
        &url,
        &headers,
        &corr_id,
        Some(body),
        state.get_retry_count,
    )
    .await
    {
        Ok(resp) => {
            let (status, body) = response_to_json(resp).await;
            store_idempotent(&state, &headers, "create_session", status, &body).await;
            json_response(status, &body, &corr_id)
        }
        Err(e) => {
            state
                .metrics
                .upstream_failure_total
                .fetch_add(1, Ordering::Relaxed);
            gateway_error("control_api", &corr_id, e)
        }
    }
}

async fn delete_session(
    Path(id): Path<String>,
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Write, &corr_id) {
        return resp;
    }
    let url = format!("{}/sessions/{id}", state.control_base_url);
    match forward_json(
        &state.client,
        reqwest::Method::DELETE,
        &url,
        &headers,
        &corr_id,
        None,
        state.get_retry_count,
    )
    .await
    {
        Ok(resp) => to_axum_response(resp, &corr_id).await,
        Err(e) => {
            state
                .metrics
                .upstream_failure_total
                .fetch_add(1, Ordering::Relaxed);
            gateway_error("control_api", &corr_id, e)
        }
    }
}

async fn get_session_status(
    Path(id): Path<String>,
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Read, &corr_id) {
        return resp;
    }
    let url = format!("{}/sessions/{id}/status", state.control_base_url);
    match forward_json(
        &state.client,
        reqwest::Method::GET,
        &url,
        &headers,
        &corr_id,
        None,
        state.get_retry_count,
    )
    .await
    {
        Ok(resp) => to_axum_response(resp, &corr_id).await,
        Err(e) => {
            state
                .metrics
                .upstream_failure_total
                .fetch_add(1, Ordering::Relaxed);
            gateway_error("control_api", &corr_id, e)
        }
    }
}

async fn get_ui_config(State(state): State<AppState>, headers: HeaderMap) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Read, &corr_id) {
        return resp;
    }
    let snapshot = state.ui_state.lock().await.clone();
    json_response(
        StatusCode::OK,
        &serde_json::json!({
            "config": snapshot.config,
        }),
        &corr_id,
    )
}

async fn put_ui_config(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(config): Json<UiConfig>,
) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Write, &corr_id) {
        return resp;
    }
    let errors = validate_ui_config(&config);
    if !errors.is_empty() {
        return error_response(
            StatusCode::BAD_REQUEST,
            error_code::VALIDATION_FAILED,
            &errors.join(", "),
            &corr_id,
            "bff",
        );
    }
    let mut ui = state.ui_state.lock().await;
    ui.config = config.clone();
    ui.risk_state.limits = config.risk.clone();
    let snapshot = ui.clone();
    drop(ui);
    json_response(
        StatusCode::OK,
        &serde_json::json!({
            "config": snapshot.config,
            "risk": snapshot.risk_state,
        }),
        &corr_id,
    )
}

async fn get_ui_risk(State(state): State<AppState>, headers: HeaderMap) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Read, &corr_id) {
        return resp;
    }
    let snapshot = state.ui_state.lock().await.clone();
    json_response(
        StatusCode::OK,
        &serde_json::json!({
            "risk": snapshot.risk_state,
        }),
        &corr_id,
    )
}

async fn put_ui_risk_limits(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(limits): Json<UiRiskLimits>,
) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Write, &corr_id) {
        return resp;
    }
    if limits.max_position_units <= 0.0 || limits.max_order_size <= 0.0 || limits.max_daily_loss_abs <= 0.0 {
        return error_response(
            StatusCode::BAD_REQUEST,
            error_code::VALIDATION_FAILED,
            "risk limits must be positive numbers",
            &corr_id,
            "bff",
        );
    }
    let mut ui = state.ui_state.lock().await;
    ui.risk_state.limits = limits.clone();
    ui.config.risk = limits;
    let snapshot = ui.clone();
    drop(ui);
    json_response(
        StatusCode::OK,
        &serde_json::json!({
            "risk": snapshot.risk_state,
            "config": snapshot.config,
        }),
        &corr_id,
    )
}

async fn put_ui_daily_pnl(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<UpdateDailyPnlRequest>,
) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Write, &corr_id) {
        return resp;
    }
    if !req.daily_pnl.is_finite() {
        return error_response(
            StatusCode::BAD_REQUEST,
            error_code::VALIDATION_FAILED,
            "dailyPnl must be finite",
            &corr_id,
            "bff",
        );
    }
    let mut ui = state.ui_state.lock().await;
    ui.risk_state.daily_pnl = req.daily_pnl;
    let snapshot = ui.clone();
    drop(ui);
    json_response(
        StatusCode::OK,
        &serde_json::json!({
            "risk": snapshot.risk_state,
        }),
        &corr_id,
    )
}

async fn create_training_job(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Write, &corr_id) {
        return resp;
    }
    if let Some(resp) = maybe_idempotent_hit(&state, &headers, "create_training_job", &corr_id).await {
        return resp;
    }
    let url = format!("{}/retrain", state.training_base_url);
    match forward_json(
        &state.client,
        reqwest::Method::POST,
        &url,
        &headers,
        &corr_id,
        Some(body),
        state.get_retry_count,
    )
    .await
    {
        Ok(resp) => {
            let (status, upstream) = response_to_json(resp).await;
            let body = normalize_job_payload("training", None, &upstream);
            store_idempotent(&state, &headers, "create_training_job", status, &body).await;
            json_response(status, &body, &corr_id)
        }
        Err(e) => {
            state
                .metrics
                .upstream_failure_total
                .fetch_add(1, Ordering::Relaxed);
            gateway_error("training_api", &corr_id, e)
        }
    }
}

async fn get_training_job(
    Path(job_id): Path<String>,
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Read, &corr_id) {
        return resp;
    }
    let url = format!("{}/retrain/{job_id}/status", state.training_base_url);
    match forward_json(
        &state.client,
        reqwest::Method::GET,
        &url,
        &headers,
        &corr_id,
        None,
        state.get_retry_count,
    )
    .await
    {
        Ok(resp) => to_normalized_job_response(resp, "training", Some(&job_id), &corr_id).await,
        Err(e) => {
            state
                .metrics
                .upstream_failure_total
                .fetch_add(1, Ordering::Relaxed);
            gateway_error("training_api", &corr_id, e)
        }
    }
}

async fn cancel_training_job(
    Path(job_id): Path<String>,
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Write, &corr_id) {
        return resp;
    }
    let url = format!("{}/retrain/{job_id}", state.training_base_url);
    match forward_json(
        &state.client,
        reqwest::Method::DELETE,
        &url,
        &headers,
        &corr_id,
        None,
        state.get_retry_count,
    )
    .await
    {
        Ok(resp) => to_normalized_job_response(resp, "training", Some(&job_id), &corr_id).await,
        Err(e) => {
            state
                .metrics
                .upstream_failure_total
                .fetch_add(1, Ordering::Relaxed);
            gateway_error("training_api", &corr_id, e)
        }
    }
}

async fn create_backtest(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Write, &corr_id) {
        return resp;
    }
    if let Some(resp) = maybe_idempotent_hit(&state, &headers, "create_backtest", &corr_id).await {
        return resp;
    }
    let url = format!("{}/backtest/run", state.backtest_base_url);
    match forward_json(
        &state.client,
        reqwest::Method::POST,
        &url,
        &headers,
        &corr_id,
        Some(body),
        state.get_retry_count,
    )
    .await
    {
        Ok(resp) => {
            let (status, upstream) = response_to_json(resp).await;
            let body = normalize_job_payload("backtest", None, &upstream);
            store_idempotent(&state, &headers, "create_backtest", status, &body).await;
            json_response(status, &body, &corr_id)
        }
        Err(e) => {
            state
                .metrics
                .upstream_failure_total
                .fetch_add(1, Ordering::Relaxed);
            gateway_error("backtest_api", &corr_id, e)
        }
    }
}

async fn get_backtest(
    Path(job_id): Path<String>,
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Read, &corr_id) {
        return resp;
    }
    let url = format!("{}/backtest/{job_id}/status", state.backtest_base_url);
    match forward_json(
        &state.client,
        reqwest::Method::GET,
        &url,
        &headers,
        &corr_id,
        None,
        state.get_retry_count,
    )
    .await
    {
        Ok(resp) => to_normalized_job_response(resp, "backtest", Some(&job_id), &corr_id).await,
        Err(e) => {
            state
                .metrics
                .upstream_failure_total
                .fetch_add(1, Ordering::Relaxed);
            gateway_error("backtest_api", &corr_id, e)
        }
    }
}

async fn get_backtest_result(
    Path(job_id): Path<String>,
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Read, &corr_id) {
        return resp;
    }
    let url = format!("{}/backtest/{job_id}/result", state.backtest_base_url);
    match forward_json(
        &state.client,
        reqwest::Method::GET,
        &url,
        &headers,
        &corr_id,
        None,
        state.get_retry_count,
    )
    .await
    {
        Ok(resp) => {
            to_normalized_job_response(resp, "backtest_result", Some(&job_id), &corr_id).await
        }
        Err(e) => {
            state
                .metrics
                .upstream_failure_total
                .fetch_add(1, Ordering::Relaxed);
            gateway_error("backtest_api", &corr_id, e)
        }
    }
}

async fn cancel_backtest(
    Path(job_id): Path<String>,
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Write, &corr_id) {
        return resp;
    }
    let url = format!("{}/backtest/{job_id}", state.backtest_base_url);
    match forward_json(
        &state.client,
        reqwest::Method::DELETE,
        &url,
        &headers,
        &corr_id,
        None,
        state.get_retry_count,
    )
    .await
    {
        Ok(resp) => to_normalized_job_response(resp, "backtest", Some(&job_id), &corr_id).await,
        Err(e) => {
            state
                .metrics
                .upstream_failure_total
                .fetch_add(1, Ordering::Relaxed);
            gateway_error("backtest_api", &corr_id, e)
        }
    }
}

async fn get_models(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<HashMap<String, String>>,
) -> Response {
    state.metrics.requests_total.fetch_add(1, Ordering::Relaxed);
    let corr_id = new_correlation_id(&state);
    if let Some(resp) = authorize(&state, &headers, AccessNeed::Read, &corr_id) {
        return resp;
    }
    let url = format!("{}/models", state.ml_base_url);
    match forward_json_with_query(
        &state.client,
        reqwest::Method::GET,
        &url,
        &headers,
        &corr_id,
        &query,
        state.get_retry_count,
    )
    .await
    {
        Ok(resp) => to_axum_response(resp, &corr_id).await,
        Err(e) => {
            state
                .metrics
                .upstream_failure_total
                .fetch_add(1, Ordering::Relaxed);
            gateway_error("ml_api", &corr_id, e)
        }
    }
}

async fn forward_json(
    client: &Client,
    method: reqwest::Method,
    url: &str,
    headers: &HeaderMap,
    corr_id: &str,
    body: Option<Value>,
    get_retry_count: usize,
) -> Result<reqwest::Response, reqwest::Error> {
    let can_retry = method == reqwest::Method::GET && get_retry_count > 0;
    let mut attempt = 0;
    let started = std::time::Instant::now();
    loop {
        attempt += 1;
        let mut req = client.request(method.clone(), url);
        req = apply_forward_headers(req, headers, corr_id);
        if let Some(body) = body.clone() {
            req = req.json(&body);
        }
        match req.send().await {
            Ok(resp) => {
                let status = resp.status().as_u16();
                info!(
                    %corr_id,
                    method = %method,
                    %url,
                    attempt,
                    status,
                    elapsed_ms = started.elapsed().as_millis() as u64,
                    "upstream request completed"
                );
                return Ok(resp);
            }
            Err(e) => {
                if can_retry && attempt <= get_retry_count {
                    warn!(
                        %corr_id,
                        method = %method,
                        %url,
                        %attempt,
                        ?e,
                        "retrying upstream GET"
                    );
                    continue;
                }
                warn!(
                    %corr_id,
                    method = %method,
                    %url,
                    attempt,
                    elapsed_ms = started.elapsed().as_millis() as u64,
                    ?e,
                    "upstream request failed"
                );
                return Err(e);
            }
        }
    }
}

async fn forward_json_with_query(
    client: &Client,
    method: reqwest::Method,
    url: &str,
    headers: &HeaderMap,
    corr_id: &str,
    query: &HashMap<String, String>,
    get_retry_count: usize,
) -> Result<reqwest::Response, reqwest::Error> {
    let can_retry = method == reqwest::Method::GET && get_retry_count > 0;
    let mut attempt = 0;
    let started = std::time::Instant::now();
    loop {
        attempt += 1;
        let mut req = client.request(method.clone(), url);
        req = apply_forward_headers(req, headers, corr_id);
        req = req.query(query);
        match req.send().await {
            Ok(resp) => {
                let status = resp.status().as_u16();
                info!(
                    %corr_id,
                    method = %method,
                    %url,
                    attempt,
                    status,
                    elapsed_ms = started.elapsed().as_millis() as u64,
                    "upstream request completed"
                );
                return Ok(resp);
            }
            Err(e) => {
                if can_retry && attempt <= get_retry_count {
                    warn!(
                        %corr_id,
                        method = %method,
                        %url,
                        %attempt,
                        ?e,
                        "retrying upstream GET with query"
                    );
                    continue;
                }
                warn!(
                    %corr_id,
                    method = %method,
                    %url,
                    attempt,
                    elapsed_ms = started.elapsed().as_millis() as u64,
                    ?e,
                    "upstream request failed"
                );
                return Err(e);
            }
        }
    }
}

fn apply_forward_headers(
    req: reqwest::RequestBuilder,
    incoming: &HeaderMap,
    corr_id: &str,
) -> reqwest::RequestBuilder {
    let mut req = req.header("x-correlation-id", corr_id);
    if let Some(auth) = incoming.get("authorization") {
        req = req.header("authorization", auth.clone());
    }
    req
}

fn new_correlation_id(state: &AppState) -> String {
    let n = state.request_seq.fetch_add(1, Ordering::Relaxed);
    format!("corr_{}_{}", chrono_now_ms(), n)
}

async fn to_axum_response(resp: reqwest::Response, corr_id: &str) -> Response {
    let (status, json) = response_to_json(resp).await;
    json_response(status, &json, corr_id)
}

async fn to_normalized_job_response(
    resp: reqwest::Response,
    kind: &str,
    fallback_job_id: Option<&str>,
    corr_id: &str,
) -> Response {
    let (status, upstream) = response_to_json(resp).await;
    let normalized = normalize_job_payload(kind, fallback_job_id, &upstream);
    json_response(status, &normalized, corr_id)
}

fn normalize_job_payload(kind: &str, fallback_job_id: Option<&str>, upstream: &Value) -> Value {
    let upstream_obj = upstream.as_object();
    let job_id = upstream_obj
        .and_then(|o| o.get("job_id"))
        .and_then(Value::as_str)
        .or(fallback_job_id)
        .unwrap_or("unknown")
        .to_string();
    let status = upstream_obj
        .and_then(|o| o.get("status"))
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    let progress = upstream_obj.and_then(|o| o.get("progress")).cloned();
    let message = upstream_obj
        .and_then(|o| o.get("message"))
        .and_then(Value::as_str)
        .map(ToString::to_string);
    let result = upstream_obj.and_then(|o| o.get("result")).cloned();
    let done = matches!(status.as_str(), "completed" | "error" | "stopped" | "unsupported");

    serde_json::json!({
        "job_id": job_id,
        "kind": kind,
        "status": status,
        "progress": progress,
        "message": message,
        "done": done,
        "result": result,
        "upstream": upstream,
    })
}

fn authorize(
    state: &AppState,
    headers: &HeaderMap,
    need: AccessNeed,
    corr_id: &str,
) -> Option<Response> {
    let auth_enabled = state.read_api_key.is_some() || state.write_api_key.is_some();
    if !auth_enabled {
        return None;
    }
    let presented = extract_presented_api_key(headers);
    let read_ok = matches!(
        (&state.read_api_key, &presented),
        (Some(expected), Some(actual)) if expected == actual
    );
    let write_ok = matches!(
        (&state.write_api_key, &presented),
        (Some(expected), Some(actual)) if expected == actual
    );

    let allowed = match need {
        AccessNeed::Read => read_ok || write_ok,
        AccessNeed::Write => write_ok,
    };
    if allowed {
        return None;
    }
    let status = if presented.is_none() {
        StatusCode::UNAUTHORIZED
    } else {
        StatusCode::FORBIDDEN
    };
    let (code, message) = match status {
        StatusCode::UNAUTHORIZED => (error_code::AUTH_MISSING_API_KEY, "missing API key"),
        _ => (error_code::AUTH_FORBIDDEN, "insufficient permission"),
    };
    warn!(%corr_id, status = %status, code, "authorization rejected");
    state
        .metrics
        .auth_rejected_total
        .fetch_add(1, Ordering::Relaxed);
    Some(error_response(
        status,
        code,
        message,
        corr_id,
        "bff",
    ))
}

fn extract_presented_api_key(headers: &HeaderMap) -> Option<String> {
    if let Some(v) = headers.get("x-api-key").and_then(|v| v.to_str().ok()) {
        let s = v.trim();
        if !s.is_empty() {
            return Some(s.to_string());
        }
    }
    if let Some(v) = headers.get("authorization").and_then(|v| v.to_str().ok()) {
        let mut parts = v.split_whitespace();
        let scheme = parts.next().unwrap_or_default();
        let token = parts.next().unwrap_or_default();
        if scheme.eq_ignore_ascii_case("bearer") && !token.is_empty() {
            return Some(token.to_string());
        }
    }
    None
}

fn gateway_error(service: &str, corr_id: &str, err: reqwest::Error) -> Response {
    let (code, message) = if err.is_timeout() {
        (error_code::UPSTREAM_TIMEOUT, format!("upstream timeout: {err}"))
    } else if err.is_connect() {
        (
            error_code::UPSTREAM_CONNECT_FAILED,
            format!("upstream connect failed: {err}"),
        )
    } else {
        (error_code::UPSTREAM_SEND_FAILED, format!("upstream request failed: {err}"))
    };
    error_response(
        StatusCode::BAD_GATEWAY,
        code,
        &message,
        corr_id,
        service,
    )
}

fn error_response(
    status: StatusCode,
    code: &str,
    message: &str,
    corr_id: &str,
    upstream_service: &str,
) -> Response {
    let mut headers = HeaderMap::new();
    headers.insert(
        HeaderName::from_static("content-type"),
        HeaderValue::from_static("application/json"),
    );
    if let Ok(v) = HeaderValue::from_str(corr_id) {
        headers.insert(HeaderName::from_static("x-correlation-id"), v);
    }
    (
        status,
        headers,
        Json(serde_json::json!({
            "error": {
                "code": code,
                "message": message,
                "correlation_id": corr_id,
                "upstream_service": upstream_service,
            }
        })),
    )
        .into_response()
}

fn json_response(status: StatusCode, body: &Value, corr_id: &str) -> Response {
    let mut headers = HeaderMap::new();
    headers.insert(
        HeaderName::from_static("content-type"),
        HeaderValue::from_static("application/json"),
    );
    if let Ok(v) = HeaderValue::from_str(corr_id) {
        headers.insert(HeaderName::from_static("x-correlation-id"), v);
    }
    (status, headers, Json(body.clone())).into_response()
}

async fn response_to_json(resp: reqwest::Response) -> (StatusCode, Value) {
    let status = StatusCode::from_u16(resp.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);
    let text = resp.text().await.unwrap_or_else(|_| "{}".to_string());
    let json = serde_json::from_str::<Value>(&text).unwrap_or_else(|_| {
        serde_json::json!({
            "raw": text
        })
    });
    (status, json)
}

fn extract_idempotency_key(headers: &HeaderMap) -> Option<String> {
    headers
        .get("idempotency-key")
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(ToString::to_string)
}

async fn maybe_idempotent_hit(
    state: &AppState,
    headers: &HeaderMap,
    operation: &str,
    corr_id: &str,
) -> Option<Response> {
    let key = extract_idempotency_key(headers)?;
    let cache_key = format!("{operation}:{key}");
    let now_ms = chrono_now_ms();
    let mut cache = state.idempotency.lock().await;
    let expired = cache
        .get(&cache_key)
        .map(|v| is_cache_expired(v.created_at_ms, now_ms, state.idempotency_ttl_ms))
        .unwrap_or(false);
    if expired {
        cache.remove(&cache_key);
        let snapshot = cache.clone();
        drop(cache);
        persist_cache_snapshot(state, &snapshot).await;
        let cache = state.idempotency.lock().await;
        let hit = cache.get(&cache_key).cloned();
        drop(cache);
        if let Some(hit) = hit {
            state
                .metrics
                .idempotency_hit_total
                .fetch_add(1, Ordering::Relaxed);
            info!(%corr_id, operation, idempotency_key = %key, "idempotency cache hit");
            let status = StatusCode::from_u16(hit.status).unwrap_or(StatusCode::OK);
            return Some(json_response(status, &hit.body, corr_id));
        }
        return None;
    }
    let hit = cache.get(&cache_key).cloned();
    drop(cache);
    if let Some(hit) = hit {
        state
            .metrics
            .idempotency_hit_total
            .fetch_add(1, Ordering::Relaxed);
        info!(%corr_id, operation, idempotency_key = %key, "idempotency cache hit");
        let status = StatusCode::from_u16(hit.status).unwrap_or(StatusCode::OK);
        return Some(json_response(status, &hit.body, corr_id));
    }
    None
}

async fn store_idempotent(
    state: &AppState,
    headers: &HeaderMap,
    operation: &str,
    status: StatusCode,
    body: &Value,
) {
    let Some(key) = extract_idempotency_key(headers) else {
        return;
    };
    let cache_key = format!("{operation}:{key}");
    let now_ms = chrono_now_ms();
    let mut cache = state.idempotency.lock().await;
    prune_expired_entries(&mut cache, now_ms, state.idempotency_ttl_ms);
    if cache.len() >= state.idempotency_max_entries {
        prune_oldest_entries(&mut cache, state.idempotency_max_entries.saturating_sub(1));
    }
    cache.insert(
        cache_key,
        CachedResponse {
            status: status.as_u16(),
            body: body.clone(),
            created_at_ms: now_ms,
        },
    );
    let snapshot = cache.clone();
    drop(cache);
    persist_cache_snapshot(state, &snapshot).await;
}

fn is_cache_expired(created_at_ms: i64, now_ms: i64, ttl_ms: u64) -> bool {
    now_ms.saturating_sub(created_at_ms) > ttl_ms as i64
}

fn prune_expired_entries(
    cache: &mut HashMap<String, CachedResponse>,
    now_ms: i64,
    ttl_ms: u64,
) {
    cache.retain(|_, v| !is_cache_expired(v.created_at_ms, now_ms, ttl_ms));
}

fn prune_oldest_entries(cache: &mut HashMap<String, CachedResponse>, keep_len: usize) {
    if cache.len() <= keep_len {
        return;
    }
    let mut pairs: Vec<(String, i64)> = cache
        .iter()
        .map(|(k, v)| (k.clone(), v.created_at_ms))
        .collect();
    pairs.sort_by_key(|(_, created)| *created);
    let to_remove = cache.len().saturating_sub(keep_len);
    for (k, _) in pairs.into_iter().take(to_remove) {
        cache.remove(&k);
    }
}

async fn load_idempotency_cache(path: &PathBuf) -> HashMap<String, CachedResponse> {
    let Ok(raw) = tokio::fs::read_to_string(path).await else {
        return HashMap::new();
    };
    serde_json::from_str::<HashMap<String, CachedResponse>>(&raw).unwrap_or_default()
}

async fn persist_cache_snapshot(state: &AppState, cache: &HashMap<String, CachedResponse>) {
    let Some(path) = state.idempotency_store_path.as_ref() else {
        return;
    };
    let Some(parent) = path.parent() else {
        return;
    };
    if tokio::fs::create_dir_all(parent).await.is_err() {
        return;
    }
    let Ok(body) = serde_json::to_vec(cache) else {
        return;
    };
    let tmp = path.with_extension("tmp");
    if tokio::fs::write(&tmp, body).await.is_err() {
        return;
    }
    let _ = tokio::fs::rename(&tmp, path).await;
}

fn chrono_now_ms() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

fn inject_cors_headers(headers: &mut HeaderMap) {
    headers.insert(
        HeaderName::from_static("access-control-allow-origin"),
        HeaderValue::from_static("*"),
    );
    headers.insert(
        HeaderName::from_static("access-control-allow-methods"),
        HeaderValue::from_static("GET,POST,PUT,DELETE,OPTIONS"),
    );
    headers.insert(
        HeaderName::from_static("access-control-allow-headers"),
        HeaderValue::from_static("content-type,authorization,x-api-key,idempotency-key"),
    );
}

fn default_ui_state() -> UiState {
    let risk = UiRiskLimits {
        max_position_units: 25.0,
        max_order_size: 5.0,
        max_daily_loss_abs: 2000.0,
    };
    UiState {
        config: UiConfig {
            policy_version: "v1".to_string(),
            symbol: "BTCUSDT".to_string(),
            vote: UiVotePolicy::WeightedMajority {
                min_net_strength: 0.15,
                weights: HashMap::from([
                    ("market_maker".to_string(), 1.0),
                    ("arbitrage".to_string(), 0.5),
                    ("price_prediction".to_string(), 1.2),
                    ("momentum".to_string(), 1.0),
                ]),
            },
            risk: risk.clone(),
            runtime: UiRuntimeConfig {
                execution_mode: "dry_run".to_string(),
                tick_interval_ms: 1000,
                default_order_quantity: 1.0,
            },
        },
        risk_state: UiRiskState {
            limits: risk,
            daily_pnl: 0.0,
            position_units: 0.0,
        },
    }
}

fn validate_ui_config(config: &UiConfig) -> Vec<String> {
    let mut errors = Vec::new();
    if config.symbol.trim().is_empty() {
        errors.push("symbol must not be empty");
    }
    if config.runtime.execution_mode != "dry_run" && config.runtime.execution_mode != "live" {
        errors.push("runtime.executionMode must be dry_run or live");
    }
    if config.runtime.tick_interval_ms == 0 {
        errors.push("runtime.tickIntervalMs must be > 0");
    }
    if config.runtime.default_order_quantity <= 0.0 {
        errors.push("runtime.defaultOrderQuantity must be > 0");
    }
    if config.risk.max_position_units <= 0.0
        || config.risk.max_order_size <= 0.0
        || config.risk.max_daily_loss_abs <= 0.0
    {
        errors.push("risk limits must be positive");
    }
    match &config.vote {
        UiVotePolicy::WeightedMajority {
            min_net_strength,
            weights,
        } => {
            if *min_net_strength < 0.0 {
                errors.push("vote.min_net_strength must be >= 0");
            }
            if weights.is_empty() {
                errors.push("vote.weights must not be empty");
            }
        }
        UiVotePolicy::Quorum {
            required_same_side,
            min_strength_per_vote,
        } => {
            if *required_same_side == 0 {
                errors.push("vote.required_same_side must be > 0");
            }
            if *min_strength_per_vote < 0.0 {
                errors.push("vote.min_strength_per_vote must be >= 0");
            }
        }
        UiVotePolicy::SimplePlurality => {}
    }
    errors.into_iter().map(ToString::to_string).collect()
}
