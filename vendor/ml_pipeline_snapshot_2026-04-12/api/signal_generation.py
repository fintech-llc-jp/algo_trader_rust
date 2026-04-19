"""
共通シグナル生成ロジック

POST /signal と定期シグナル配信の両方で利用する、df/features/current_price から
シグナル（signal_type, confidence, predicted_price 等）を計算する関数。
"""
from __future__ import annotations

import logging
from typing import Optional, Any

import pandas as pd

from evaluation.run_price_prediction_backtest import (
    apply_error_correction,
    generate_signals_from_predictions,
)

logger = logging.getLogger(__name__)


def generate_signal_from_features(
    symbol: str,
    df: pd.DataFrame,
    features: pd.DataFrame,
    current_price: float,
    price_strategy: Any,
    momentum_strategy: Any,
    *,
    error_window_size: int = 100,
    min_samples: int = 10,
    price_change_threshold: float = 0.001,
    momentum_threshold: int = 2,
    max_prediction_error_pct: float = 10.0,
    log: Optional[logging.Logger] = None,
) -> Optional[dict]:
    """
    ﾃﾞｰﾀと特徴量から取引シグナルを生成する。

    Args:
        symbol: シンボル（ログ用）
        df: マーケットデータ（mid_price または exec_price_all 必須）
        features: 特徴量 DataFrame
        current_price: 現在価格（予測差分・シグナル判定に使用）
        price_strategy: 価格予測戦略（.predict(features) が使えること）
        momentum_strategy: モメンタム強度戦略（.predict_intensity(features) が使えること）
        error_window_size: 予測誤差補正のウィンドウサイズ
        min_samples: 誤差補正を適用する最小サンプル数
        price_change_threshold: 価格変動閾値（0.1%）
        momentum_threshold: モメンタム強度閾値
        max_prediction_error_pct: これを超える予測変動は HOLD に強制（%）
        log: ロガー（None の場合はモジュールロガー）

    Returns:
        signal_type, confidence, predicted_price, current_price, price_change_pct,
        momentum_intensity を含む辞書。失敗時は None。
    """
    _log = log or logger

    if df is None or len(df) == 0 or features is None or len(features) == 0:
        _log.warning("generate_signal_from_features: empty df or features")
        return None

    if price_strategy is None or (hasattr(price_strategy, "model") and price_strategy.model is None):
        _log.warning("generate_signal_from_features: price_strategy or model not available")
        return None

    try:
        predictions = price_strategy.predict(features)
    except Exception as e:
        _log.warning("generate_signal_from_features: price prediction failed: %s", e)
        return None

    if predictions is None or len(predictions) == 0:
        _log.warning("generate_signal_from_features: no predictions")
        return None

    if "exec_price_all" in df.columns:
        actual_prices = df["exec_price_all"]
    else:
        actual_prices = df["mid_price"]

    latest_idx = df.index[-1]
    raw_predicted_price: Optional[float] = None
    if latest_idx in predictions.index:
        raw_predicted_price = float(predictions.loc[latest_idx])

    if len(predictions) >= min_samples:
        try:
            predictions = apply_error_correction(
                predictions,
                actual_prices,
                error_window_size=error_window_size,
                min_samples=min_samples,
            )
        except Exception as e:
            _log.debug("Error correction skipped: %s", e)

    momentum_intensity_pred = None
    if momentum_strategy is not None and getattr(momentum_strategy, "model", None) is not None:
        try:
            momentum_intensity_pred = momentum_strategy.predict_intensity(features)
        except Exception as e:
            _log.debug("Momentum intensity failed: %s", e)

    if latest_idx not in predictions.index:
        _log.warning("generate_signal_from_features: prediction index mismatch")
        return None

    predicted_price = float(predictions.loc[latest_idx])
    # 補正がかかった場合にログ出力（バイアス＝補正で引いた値）
    if raw_predicted_price is not None and abs(predicted_price - raw_predicted_price) > 1e-6:
        bias_applied = raw_predicted_price - predicted_price
        _log.info(
            "[ERROR_CORRECTION] %s bias=%.2f raw_pred=%.2f corrected_pred=%.2f",
            symbol,
            bias_applied,
            raw_predicted_price,
            predicted_price,
        )
    price_change_pct = ((predicted_price - current_price) / current_price) * 100

    momentum_intensity_series = None
    momentum_intensity_value = None
    if momentum_intensity_pred is not None and latest_idx in momentum_intensity_pred.index:
        momentum_intensity_value = int(momentum_intensity_pred.loc[latest_idx])
        momentum_intensity_series = pd.Series(
            [momentum_intensity_pred.loc[latest_idx]],
            index=[latest_idx],
        )

    use_momentum = momentum_intensity_series is not None
    abs_price_change_pct = abs(price_change_pct)

    if abs_price_change_pct > max_prediction_error_pct:
        signal_value = 0
        confidence = 0.0
    else:
        signals, confidence_series = generate_signals_from_predictions(
            df.tail(1),
            predictions.tail(1),
            price_change_threshold=price_change_threshold,
            momentum_intensity=momentum_intensity_series,
            momentum_threshold=momentum_threshold,
            use_momentum=use_momentum,
            max_prediction_error_pct=max_prediction_error_pct,
        )
        signal_value = int(signals.iloc[-1]) if len(signals) > 0 else 0
        confidence = float(confidence_series.iloc[-1]) if len(confidence_series) > 0 else 0.0

        if abs_price_change_pct > 3.0:
            confidence_reduction = min(0.5, abs_price_change_pct / 10.0)
            confidence = max(0.1, confidence - confidence_reduction)

    if signal_value == 1:
        signal_type = "BUY"
    elif signal_value == -1:
        signal_type = "SELL"
    else:
        signal_type = "HOLD"

    return {
        "symbol": symbol,
        "signal_type": signal_type,
        "confidence": confidence,
        "predicted_price": predicted_price,
        "current_price": current_price,
        "price_change_pct": price_change_pct,
        "momentum_intensity": momentum_intensity_value,
    }
