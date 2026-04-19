# バックエンド充足度レビュー（PRD / シーケンス図対照）

**対象:** フロントがモックの前提で、「バックエンドとして機能が揃っているか」を整理する。  
**範囲:** [`algo_trader_rust`](../)（Rust）および参照用の [`algo_trader_v1/ml_pipeline`](file:///Users/sakamoto.yukio/workspace/algo_trader_v1/ml_pipeline)（Python）。

---

## 結論（要約）

| 判断 | 内容 |
|------|------|
| **統合バックエンドとしては未充足** | PRD の UC-1〜UC-3 を **単一の API 面**で満たすサーバは現状ない。モック UI が想定する「一覧・ジョブ・結果参照」を束ねる層が未整備。 |
| **Rust（`algo_trader_rust`）** | **リアルタイム意思決定コア**（投票・リスク・ONNX・ExchSim クライアント型）は PoC レベルで存在するが、**ExchSim との実配線・実注文・実板取得は未接続**。HTTP API なし。 |
| **Python（`algo_trader_v1/ml_pipeline`）** | **学習・バックテスト用 FastAPI**（`training_app` / `backtest_app` 等）があり、**UC-1 / UC-2 に近い能力**はこちらに寄っている。 |

→ **「バックエンドで機能が充足しているか」は No（全体）／部分 Yes（言語・コンポーネントごと）** が正確。

---

## ユースケース別マッピング

### UC-1 期日に基づくモデル学習

| 要求の観点 | `algo_trader_rust` | `algo_trader_v1/ml_pipeline` |
|------------|--------------------|------------------------------|
| 学習ジョブ登録・実行 | **なし**（CLI/スクリプトのみ `ml_bridge/export_dummy_onnx.py`） | **あり**: `api/training_app.py` 等、ジョブ状態 `training_jobs` 管理 |
| 失敗理由の参照 | 該当なし | API 設計次第（要コードレビューで確定） |
| ONNX 出力と Rust 連携 | `ml_bridge/` にダミー生成手順あり | 本番学習後のエクスポート運用は別途合意が必要 |

**充足度:** Rust 単体では **不足**。学習は **Python 側が主担当**。

---

### UC-1r 学習ジョブ・成果物の参照

| 観点 | `algo_trader_rust` | Python |
|------|--------------------|--------|
| メタデータ API | **なし** | `ModelManager` / DB 前提の経路あり（要確認） |

**充足度:** **フロント向けの参照 API は Rust にない**。Python 側に寄せるか、BFF を別途用意する必要がある。

---

### UC-2 バックテスト

| 観点 | `algo_trader_rust` | Python |
|------|--------------------|--------|
| バックテスト実行 | **なし** | **あり**: `api/backtest_app.py`、`backtest_service`、スクリプト `evaluation/run_simple_train_and_backtest.py` 等 |
| 条件の保存・再現 | なし | 実装・DB スキーマ次第 |

**充足度:** **Rust では不足**。**Python でカバー可能**（既存コードベース）。

---

### UC-2r 結果の参照・比較

| 観点 | `algo_trader_rust` | Python |
|------|--------------------|--------|
| 一覧・比較 API | **なし** | バックテスト API のレスポンス／ジョブ ID 設計次第 |

**充足度:** **要確認**（エンドポイントと永続化の有無）。

---

### UC-3 ExchSim でのリアルタイム取引

| 観点 | `algo_trader_rust` | 備考 |
|------|--------------------|------|
| ExchSim HTTP（認証・板・注文・キャンセル） | `adapter-exchsim::ExchSimAdapter` が **`Exchange` 実装** | 実装はある |
| メインループで板取得 | **`app` は `sample_snapshot` スタブ** | **未配線** |
| `Intent` → 実注文 | **`is_live_execution()` 時もログのみ**（「wire in adapter」コメント） | **未配線** |
| ポジション・損益の把握 | **未実装**（ExchSim の positions/summary を呼ぶ経路なし） | Java 版 `ExchSimClient` には相当メソッドあり |

**充足度:** **ドメインロジックは一部あるが、シーケンス図の「継続ループで ExchSim と相互作用」は未完成**。

---

### UC3s 停止・キルスイッチ

| 観点 | `algo_trader_rust` |
|------|--------------------|
| ファイルベース停止 | **`kill_switch_active` + `runtime.kill_switch_path`** でティックスキップ | **あり** |
| 未約定取消・全セッション停止 | **未実装**（`Exchange` 経由のキャンセルはクライアントに存在するが app から未使用） | **部分** |

---

## アーキテクチャ上のギャップ（モック UI 観点）

1. **単一バックエンドの不在**  
   学習・バックテスト（Python）と実時間エンジン（Rust）が **別プロセス・別設定**。フロントが「1 つの Base URL」で全部触る前提なら **API ゲートウェイ or BFF** が必要。

2. **Rust に HTTP サーバなし**  
   `Cargo.toml` ワークスペースに **axum/actix 等なし**。ジョブ登録・結果取得を Rust だけで提供する構成ではない。

3. **PRD のトレーサビリティ（G1）**  
   「学習 ID → バックテスト ID → 実時間セッション」の **一貫した ID と監査ログ**は、現状コードからは **全体設計として未完了**。

---

## Python `ml_pipeline` の本リポ内スナップショット

**方針（採用）:** 上流 [`algo_trader_v1/ml_pipeline`](file:///Users/sakamoto.yukio/workspace/algo_trader_v1/ml_pipeline) は今後も変更される一方、**互換性と再現性**のため、現時点の Python コードを **`algo_trader_rust` 配下にコピーして保持**する。二重管理のリスクは文書化したうえで受容する。

**詳細仕様:** [python-ml-snapshot-policy.md](python-ml-snapshot-policy.md)（配置名、上流との関係、同期方式、Rust 契約テスト、更新手順）

**充足度への影響:**

- **UC-1 / UC-2** を「本リポだけで」再現・検証しやすくなる（上流の最新破壊から隔離）。  
- **単一 URL の BFF**（未実装）とは独立に、**オフライン／CI** での一貫検証がしやすい。  
- 上流を **正**とする開発フローと併存するため、**どちらを本番デプロイに使うか**は運用で明示する必要がある。

---

## 推奨アクション（優先度の例）

1. **プロダクト境界の決定**  
   - 学習・バックテストは **Python API を正**とし、Rust は **推論＋注文実行**に専念するか、  
   - 将来的に **Rust 一本化**するか。

2. **最短の「充足」に向けた接続**  
   - モック UI のワイヤーフレームに合わせ、**OpenAPI 一覧**（training / backtest / session）を 1 ドキュメントにまとめる。  
   - Rust 側は **ExchSim 配線 + `place_order`** を `app` に実装し、UC-3 のシーケンスを通す。

3. **既存資産の棚卸し**  
   - `ml_pipeline` の `training_app` / `backtest_app` のエンドポイント一覧と、フロント要件の突合。

---

## 関連（設計）

- ギャップの **実装向け設計**:[design-unmet-capabilities-2026-04-12.md](design-unmet-capabilities-2026-04-12.md)

## 改訂

| 版 | 日付 | 内容 |
|----|------|------|
| 0.1 | （自動） | 初版：コードベース調査に基づく |
| 0.2 | 2026-04-12 | 未充足機能設計書へのリンク追加 |
| 0.3 | 2026-04-12 | Python ml_pipeline スナップショット方針を追記 |
