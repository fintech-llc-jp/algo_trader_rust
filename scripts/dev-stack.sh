#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${ROOT_DIR}/.run/local-stack"
LOG_DIR="${RUN_DIR}/logs"

ML_DIR="${ROOT_DIR}/vendor/ml_pipeline_snapshot_2026-04-12"
FRONTEND_DIR="${ROOT_DIR}/sentinel-ledger"

ML_API_PORT="${ML_API_PORT:-8000}"
TRAINING_API_PORT="${TRAINING_API_PORT:-8001}"
BACKTEST_API_PORT="${BACKTEST_API_PORT:-8002}"
CONTROL_PORT="${CONTROL_PORT:-8088}"
BFF_PORT="${BFF_PORT:-8090}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

BFF_API_KEY="${BFF_API_KEY:-}"

usage() {
  cat <<'EOF'
Usage:
  scripts/dev-stack.sh start
  scripts/dev-stack.sh stop
  scripts/dev-stack.sh restart
  scripts/dev-stack.sh status
  scripts/dev-stack.sh logs <service>

Services:
  ml_api | training_api | backtest_api | control | bff | frontend

Environment overrides:
  ML_API_PORT, TRAINING_API_PORT, BACKTEST_API_PORT, CONTROL_PORT, BFF_PORT, FRONTEND_PORT
  BFF_API_KEY  (if set, applied to both read/write keys on BFF and VITE_BFF_API_KEY on frontend)
EOF
}

require_commands() {
  local missing=()
  for cmd in bash cargo python npm; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
      missing+=("${cmd}")
    fi
  done
  if ((${#missing[@]} > 0)); then
    echo "Missing required commands: ${missing[*]}" >&2
    exit 1
  fi
}

python_bin() {
  if [[ -x "${ML_DIR}/.venv/bin/python" ]]; then
    echo "${ML_DIR}/.venv/bin/python"
  else
    echo "python"
  fi
}

pid_file() {
  local service="$1"
  echo "${RUN_DIR}/${service}.pid"
}

is_running() {
  local service="$1"
  local pidf
  pidf="$(pid_file "${service}")"
  [[ -f "${pidf}" ]] || return 1
  local pid
  pid="$(<"${pidf}")"
  [[ -n "${pid}" ]] || return 1
  kill -0 "${pid}" >/dev/null 2>&1
}

start_service() {
  local service="$1"
  local workdir="$2"
  local cmd="$3"

  mkdir -p "${RUN_DIR}" "${LOG_DIR}"
  local logf="${LOG_DIR}/${service}.log"
  local pidf
  pidf="$(pid_file "${service}")"

  if is_running "${service}"; then
    echo "[skip] ${service} already running (pid $(<"${pidf}"))"
    return 0
  fi

  echo "[start] ${service}"
  (
    cd "${workdir}"
    nohup bash -lc "${cmd}" >"${logf}" 2>&1 &
    echo $! >"${pidf}"
  )

  sleep 1
  if is_running "${service}"; then
    echo "[ok] ${service} pid=$(<"${pidf}") log=${logf}"
  else
    echo "[fail] ${service} did not start. Check ${logf}" >&2
    rm -f "${pidf}"
    return 1
  fi
}

stop_service() {
  local service="$1"
  local pidf
  pidf="$(pid_file "${service}")"
  if [[ ! -f "${pidf}" ]]; then
    echo "[skip] ${service} not running (no pid file)"
    return 0
  fi

  local pid
  pid="$(<"${pidf}")"
  if [[ -z "${pid}" ]] || ! kill -0 "${pid}" >/dev/null 2>&1; then
    echo "[skip] ${service} stale pid file removed"
    rm -f "${pidf}"
    return 0
  fi

  echo "[stop] ${service} pid=${pid}"
  kill "${pid}" >/dev/null 2>&1 || true

  for _ in {1..20}; do
    if ! kill -0 "${pid}" >/dev/null 2>&1; then
      rm -f "${pidf}"
      echo "[ok] ${service} stopped"
      return 0
    fi
    sleep 0.2
  done

  echo "[warn] ${service} still running; sending SIGKILL"
  kill -9 "${pid}" >/dev/null 2>&1 || true
  rm -f "${pidf}"
}

show_status() {
  local services=(ml_api training_api backtest_api control bff frontend)
  for s in "${services[@]}"; do
    local pidf
    pidf="$(pid_file "${s}")"
    if is_running "${s}"; then
      echo "[running] ${s} pid=$(<"${pidf}") log=${LOG_DIR}/${s}.log"
    else
      echo "[stopped] ${s}"
    fi
  done
}

tail_logs() {
  local service="${1:-}"
  if [[ -z "${service}" ]]; then
    echo "Specify a service name. See usage." >&2
    exit 1
  fi
  local logf="${LOG_DIR}/${service}.log"
  if [[ ! -f "${logf}" ]]; then
    echo "No log file: ${logf}" >&2
    exit 1
  fi
  tail -f "${logf}"
}

start_all() {
  require_commands
  local py
  py="$(python_bin)"

  local bff_auth_env=""
  local frontend_auth_env=""
  if [[ -n "${BFF_API_KEY}" ]]; then
    bff_auth_env="ALGO_TRADER_BFF_READ_API_KEY='${BFF_API_KEY}' ALGO_TRADER_BFF_WRITE_API_KEY='${BFF_API_KEY}'"
    frontend_auth_env="VITE_BFF_API_KEY='${BFF_API_KEY}'"
  fi

  start_service "ml_api" "${ML_DIR}" \
    "API_PORT='${ML_API_PORT}' '${py}' -m api.app"

  start_service "training_api" "${ML_DIR}" \
    "'${py}' -m uvicorn api.training_app:app --host 127.0.0.1 --port '${TRAINING_API_PORT}'"

  start_service "backtest_api" "${ML_DIR}" \
    "'${py}' -m uvicorn api.backtest_app:app --host 127.0.0.1 --port '${BACKTEST_API_PORT}'"

  start_service "control" "${ROOT_DIR}" \
    "ALGO_TRADER_CONTROL_ADDR='127.0.0.1:${CONTROL_PORT}' cargo run -p algo-trader-app --bin algo-trader-control"

  start_service "bff" "${ROOT_DIR}" \
    "${bff_auth_env} ALGO_TRADER_BFF_ADDR='127.0.0.1:${BFF_PORT}' ALGO_TRADER_CONTROL_BASE_URL='http://127.0.0.1:${CONTROL_PORT}' ALGO_TRADER_PY_ML_BASE_URL='http://127.0.0.1:${ML_API_PORT}' ALGO_TRADER_PY_TRAINING_BASE_URL='http://127.0.0.1:${TRAINING_API_PORT}' ALGO_TRADER_PY_BACKTEST_BASE_URL='http://127.0.0.1:${BACKTEST_API_PORT}' cargo run -p algo-trader-app --bin algo-trader-bff"

  start_service "frontend" "${FRONTEND_DIR}" \
    "${frontend_auth_env} VITE_BFF_BASE_URL='http://127.0.0.1:${BFF_PORT}' npm run dev -- --host 127.0.0.1 --port '${FRONTEND_PORT}'"

  echo ""
  echo "All services started."
  echo "Frontend: http://127.0.0.1:${FRONTEND_PORT}"
  echo "BFF:      http://127.0.0.1:${BFF_PORT}"
}

stop_all() {
  local services=(frontend bff control backtest_api training_api ml_api)
  for s in "${services[@]}"; do
    stop_service "${s}"
  done
}

main() {
  local cmd="${1:-}"
  case "${cmd}" in
    start)
      start_all
      ;;
    stop)
      stop_all
      ;;
    restart)
      stop_all
      start_all
      ;;
    status)
      show_status
      ;;
    logs)
      tail_logs "${2:-}"
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"
