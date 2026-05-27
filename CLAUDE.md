# algo_trader_rust — Claude Code セッションメモ

このファイルはセッションをまたいで記憶を引き継ぐための永続メモです。
新しい改良・判断・注意点があれば随時追記してください。

---

## プロジェクト概要

- **Rust製アルゴ取引エンジン** + **Python ML パイプライン**
- 取引所: ExchSim (`http://77.42.74.155:8080`)
- MLパイプライン: `vendor/ml_pipeline_snapshot_2026-04-12/`
- シンボル: `G_FX_BTCJPY`

---

## ML パイプライン (`vendor/ml_pipeline_snapshot_2026-04-12/`)

### モデル仕様

| 項目 | 値 |
|------|----|
| アルゴリズム | XGBoost 多クラス分類 |
| クラス | SELL=0 / HOLD=1 / BUY=2 |
| LABEL_HORIZON | 5秒後の価格変動 |
| LABEL_THRESHOLD | 0.0001 (0.01%) |
| 特徴量数 | 58（mid_price・timestampを除く） |
| 最新モデルID | 15（accuracy=0.737、2026-05-26訓練） |

### 特徴量構成（model_id=15）

- **板特徴量** 35.2%: bid/ask/spread/深さなど
- **約定特徴量** 64.8%: exec_price_buy/sell/all、exec_price_weighted_buy/sell、volume_total

### 重要な設計判断

**LABEL_HORIZONは5秒が最適**
- 60秒に変更すると accuracy=0.44、BUY precision=13% で実用不可
- HOLDが支配的になりすぎて CONFIDENCE_THRESHOLD=0.70 をクリアできない
- 5秒に戻すと accuracy=0.737

**約定データの統合**
- `/api/executions/all?symbol=G_FX_BTCJPY&size=100` から取得
- `_last_exec_id` で重複排除（最新execIDを記憶して次回差分取得）
- 統合前の精度: 0.60 → 統合後: 0.737

---

## 既知のバグ修正履歴

### 1. ダブルポジションバグ（2026-05-26 修正済み）

**症状**: 指値チェイス中にキャンセル失敗→約定済みなのに新規発注してダブルポジション

**3層防御で修正** (`evaluation/live_trader.py`):
- Layer 1: `_cancel_pending_keep_state()` — キャンセル失敗時に `_sync_position()` 実行
- Layer 2: `_chase_side()` — キャンセル後にポジション変化を検出したら発注中止
- Layer 3: `_place_limit()` — ロング保有中のBUY、ショート保有中のSELLを絶対拒否

### 2. 特徴量数ミスマッチ（2026-05-26 修正済み）

**症状**: `ValueError: X has 59 features, but StandardScaler is expecting 58 features`

**原因**: `daily_trainer.py` の不整合
- `_generate_labels()`: mid_price を除外して58列でスケーラー学習
- `model.feature_columns = feature_engineer.get_feature_columns()`: mid_price を含む59列を保存

**修正箇所** (`evaluation/live_trader.py` の `_predict()`):
```python
EXCLUDE_FROM_SCALER = {"mid_price", "timestamp"}
use_cols = [c for c in self.feature_cols if c not in EXCLUDE_FROM_SCALER]
X = df_feat[use_cols].iloc[[-1]].values
```

### 3. Inf値によるoverflow警告（2026-05-26 修正済み）

**症状**: `overflow encountered in divide` (sklearn警告)

**原因**: 約定特徴量のゼロ除算で生成されたInfが `fillna(0)` で除去されない

**修正**:
```python
df_feat = df_feat.replace([np.inf, -np.inf], 0.0)
X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
```

---

## Maker Rebate 計算

```python
rebate = (entry_price + close_price) * qty * 0.0001
```
- エントリー・クローズ両レッグともにMaker rebate 0.01bps
- 例: qty=0.01 BTC、エントリー16,000,000円、クローズ16,010,000円
  → rebate = (16,000,000 + 16,010,000) * 0.01 * 0.0001 = 320.1円

---

## タイムアウト機能（シグナル適応型）

- **timeout_seconds** (デフォルト**30秒**): ポジション保有がこの時間を超えるとタイムアウト判定
- タイムアウト到達時の挙動がシグナルによって分岐する：
  - **同方向シグナル継続中**（ロング保有 + BUY↑ など）→ タイマーをリセットして延長（ログ: `⏱ タイムアウト延長`）
  - **逆シグナル or HOLD** → `_timeout_exit_mode = True` でクローズ方向指値チェイス開始（ログ: `⏰ タイムアウト`）
- タイムアウト時も market order ではなく limit order chase で決済（Maker rebate 維持）

**実績データ（2026-05-26 夜間、60秒タイムアウト時）**:
- 逆シグナル自然決済（22件）: raw **+58円** ✅
- タイムアウト強制決済（29件）: raw **-210円** ❌
- → タイムアウト短縮 + シグナル適応型延長で改善を期待

---

## テスト

```bash
cd vendor/ml_pipeline_snapshot_2026-04-12
python -m pytest evaluation/test_live_trader.py -v
# 43テスト全通過
```

---

## 自動再訓練パイプライン

### 構成
```
毎時0分 (cron)
  └─ infra/auto_retrain.sh
       ├─ [1] sync_from_vps.sh --incremental 1  （差分データ取得）
       └─ [2] daily_trainer.py --days 3          （再訓練 → model_id 自動採番）

LiveTrader（稼働中）
  └─ 30分ごと・ポジションなし時に DB を確認
       └─ 新モデルがあれば自動リロード（ログ: 🔄 新しいモデル検出）
```

### ログ確認
```bash
tail -f /tmp/auto_retrain.log    # 再訓練ログ
tail -f /tmp/live_trader_*.log | grep "🔄\|✅ モデル"  # 切替ログ
```

### 注意事項
- `--model-id` を明示指定して起動すると自動リロードはスキップされる
- ポジション保有中はリロードしない（安全のため）
- cron: `0 * * * *`（毎時0分）

## よく使うコマンド

```bash
# 訓練（直近3日）
cd vendor/ml_pipeline_snapshot_2026-04-12
python -m training.daily_trainer --symbol G_FX_BTCJPY

# ライブ実行
cd vendor/ml_pipeline_snapshot_2026-04-12/evaluation
python3 live_trader.py --symbol G_FX_BTCJPY --live

# ログ確認
tail -f /tmp/live_trader_*.log
```

---

## 今後の検討事項

- `daily_trainer.py` の `feature_columns` 保存ロジックを修正して `mid_price` を明示的に除外する（根本修正）
- モデルIDを明示指定する運用の整備（現在は最新モデルを自動選択）
- 約定特徴量の時系列集計（現在は最新100件の集計のみ）
