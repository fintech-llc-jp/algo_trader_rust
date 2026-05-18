//! Session control HTTP API.

use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use axum::extract::{Path, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::IntoResponse;
use axum::routing::{delete, get, post};
use axum::{Json, Router};
use tokio::net::TcpListener;
use tokio::sync::Mutex;
use tracing::info;

#[derive(Clone)]
struct AppState {
    sessions: Arc<Mutex<HashMap<String, algo_trader_app::ManagedSession>>>,
    next_id: Arc<AtomicU64>,
    metrics: Arc<ControlMetrics>,
}

#[derive(Default)]
struct ControlMetrics {
    sessions_started_total: AtomicU64,
    sessions_stopped_total: AtomicU64,
    session_start_errors_total: AtomicU64,
    session_stop_not_found_total: AtomicU64,
}

#[derive(Debug, serde::Deserialize)]
struct StartSessionRequest {
    config_path: Option<String>,
}

#[derive(Debug, serde::Serialize)]
struct StartSessionResponse {
    session_id: String,
}

#[derive(Debug, serde::Serialize)]
struct SessionStatusResponse {
    session_id: String,
    snapshot: algo_trader_app::SessionSnapshot,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    algo_trader_app::init_tracing();

    let listen_addr = std::env::args()
        .nth(1)
        .or_else(|| std::env::var("ALGO_TRADER_CONTROL_ADDR").ok())
        .unwrap_or_else(|| "127.0.0.1:8088".to_string());

    let state = AppState {
        sessions: Arc::new(Mutex::new(HashMap::new())),
        next_id: Arc::new(AtomicU64::new(1)),
        metrics: Arc::new(ControlMetrics::default()),
    };

    let app = Router::new()
        .route("/sessions", post(start_session))
        .route("/sessions/{id}", delete(stop_session))
        .route("/sessions/{id}/status", get(get_session_status))
        .route("/metrics", get(get_metrics))
        .with_state(state);

    let listener = TcpListener::bind(&listen_addr).await?;
    info!(%listen_addr, "algo-trader-control listening");
    axum::serve(listener, app).await?;
    Ok(())
}

async fn start_session(
    State(state): State<AppState>,
    Json(req): Json<StartSessionRequest>,
) -> Result<(StatusCode, Json<StartSessionResponse>), (StatusCode, String)> {
    let config_path = req.config_path.unwrap_or_else(|| "config.toml".to_string());
    let cfg = algo_trader_app::load_config(&config_path)
        .map_err(|e| {
            state
                .metrics
                .session_start_errors_total
                .fetch_add(1, Ordering::Relaxed);
            (StatusCode::BAD_REQUEST, format!("failed to load config: {e}"))
        })?;
    let session = algo_trader_app::spawn_session(cfg)
        .map_err(|e| {
            state
                .metrics
                .session_start_errors_total
                .fetch_add(1, Ordering::Relaxed);
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                format!("failed to spawn session: {e}"),
            )
        })?;

    let n = state.next_id.fetch_add(1, Ordering::Relaxed);
    let session_id = format!("sess_{n}");

    let mut sessions = state.sessions.lock().await;
    sessions.insert(session_id.clone(), session);
    drop(sessions);
    state
        .metrics
        .sessions_started_total
        .fetch_add(1, Ordering::Relaxed);

    Ok((StatusCode::CREATED, Json(StartSessionResponse { session_id })))
}

async fn stop_session(
    Path(id): Path<String>,
    State(state): State<AppState>,
) -> Result<StatusCode, (StatusCode, String)> {
    let session = {
        let mut sessions = state.sessions.lock().await;
        sessions.remove(&id)
    };

    let Some(session) = session else {
        state
            .metrics
            .session_stop_not_found_total
            .fetch_add(1, Ordering::Relaxed);
        return Err((StatusCode::NOT_FOUND, format!("session not found: {id}")));
    };
    session.stop().await;
    state
        .metrics
        .sessions_stopped_total
        .fetch_add(1, Ordering::Relaxed);
    Ok(StatusCode::NO_CONTENT)
}

async fn get_session_status(
    Path(id): Path<String>,
    State(state): State<AppState>,
) -> Result<Json<SessionStatusResponse>, (StatusCode, String)> {
    let sessions = state.sessions.lock().await;
    let Some(session) = sessions.get(&id) else {
        return Err((StatusCode::NOT_FOUND, format!("session not found: {id}")));
    };
    let snapshot = session.snapshot();
    Ok(Json(SessionStatusResponse {
        session_id: id,
        snapshot,
    }))
}

async fn get_metrics(headers: HeaderMap, State(state): State<AppState>) -> axum::response::Response {
    let active_sessions = state.sessions.lock().await.len();
    let started = state.metrics.sessions_started_total.load(Ordering::Relaxed);
    let stopped = state.metrics.sessions_stopped_total.load(Ordering::Relaxed);
    let start_errors = state.metrics.session_start_errors_total.load(Ordering::Relaxed);
    let stop_not_found = state
        .metrics
        .session_stop_not_found_total
        .load(Ordering::Relaxed);

    let wants_prom = headers
        .get("accept")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.contains("text/plain") || s.contains("application/openmetrics-text"))
        .unwrap_or(false);
    if wants_prom {
        let body = format!(
            "# TYPE control_sessions_started_total counter\ncontrol_sessions_started_total {}\n# TYPE control_sessions_stopped_total counter\ncontrol_sessions_stopped_total {}\n# TYPE control_session_start_errors_total counter\ncontrol_session_start_errors_total {}\n# TYPE control_session_stop_not_found_total counter\ncontrol_session_stop_not_found_total {}\n# TYPE control_active_sessions gauge\ncontrol_active_sessions {}\n",
            started, stopped, start_errors, stop_not_found, active_sessions
        );
        return (
            StatusCode::OK,
            [("content-type", "text/plain; version=0.0.4")],
            body,
        )
            .into_response();
    }

    Json(serde_json::json!({
        "sessions_started_total": started,
        "sessions_stopped_total": stopped,
        "session_start_errors_total": start_errors,
        "session_stop_not_found_total": stop_not_found,
        "active_sessions": active_sessions,
    }))
    .into_response()
}
