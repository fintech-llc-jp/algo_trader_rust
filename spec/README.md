# 仕様書インデックス

本ディレクトリは **実装に対応した設計・仕様** をまとめたものです。コードの単一の情報源はソースであり、ここは人間向けの説明と境界の固定に使います。

## 公式インデックス（推奨読順）

1. [01_business-requirements.md](01_business-requirements.md) — BRD（ビジネス要求）
2. [02_use-case-diagram.md](02_use-case-diagram.md) — ユースケース図
3. [03_sequence_diagram.md](03_sequence_diagram.md) — シーケンス（時系列）
4. [04_c4-level1-system-context.md](04_c4-level1-system-context.md) — C4 レベル1（システムコンテキスト）
5. [05_c4-level2-containers.md](05_c4-level2-containers.md) — C4 レベル2（コンテナ）
6. [06_external-design.md](06_external-design.md) — 外部設計（Rust ワークスペース境界）
7. [07_gui-spec.md](07_gui-spec.md) — GUI 仕様

**覚え方:** BRD → UC 図 → シーケンス → 静的 C4（L1 から L2）→ 外部設計 → GUI。

---

**クイック参照**

**ビジネス要求（設計の前段）:** [01_business-requirements.md](01_business-requirements.md)  
**ユースケース図（PRD ベース）:** [02_use-case-diagram.md](02_use-case-diagram.md)  
**シーケンス図（ユースケース対応）:** [03_sequence_diagram.md](03_sequence_diagram.md)  
**C4 静的図（L1 コンテキスト）:** [04_c4-level1-system-context.md](04_c4-level1-system-context.md)  
**C4 静的図（L2 コンテナ）:** [05_c4-level2-containers.md](05_c4-level2-containers.md)  
**外部設計:** [06_external-design.md](06_external-design.md)  
**GUI 設計:** [07_gui-spec.md](07_gui-spec.md)  
**バックエンド充足度レビュー:** `backend-readiness.md`（未同梱のリポジトリでは省略可）  
**未充足機能 設計書（2026-04-12）:** `design-unmet-capabilities-2026-04-12.md`（未同梱のリポジトリでは省略可）  
**Python `ml_pipeline` スナップショット方針:** [python-ml-snapshot-policy.md](python-ml-snapshot-policy.md)

| 文書 | 内容 |
|------|------|
| [architecture.md](architecture.md) | 全体アーキテクチャとデータフロー（`engine-core` 等の論理クレート配置を含む） |
| [03_sequence_diagram.md](03_sequence_diagram.md) | ユースケース別シーケンス（Mermaid） |
| [04_c4-level1-system-context.md](04_c4-level1-system-context.md) | C4 L1 システムコンテキスト（静的）と UC トレース |
| [05_c4-level2-containers.md](05_c4-level2-containers.md) | C4 L2 コンテナ図（静的）と UC トレース |
| [strategy-api.md](strategy-api.md) | `strategy-api`（`Strategy` とスナップショット） |
| [strategies.md](strategies.md) | 各 `strategies-*` クレートの挙動とパラメータ |
| [adapter-exchsim.md](adapter-exchsim.md) | ExchSim アダプタの HTTP パスと認証 |
| [app.md](app.md) | `algo-trader` バイナリの起動・ループ・設定解決 |
| [ml-bridge.md](ml-bridge.md) | ONNX / `feature_schema.json` と Python 連携 |
| [python-ml-snapshot-policy.md](python-ml-snapshot-policy.md) | 上流 `ml_pipeline` のコピー配置・同期・Rust 契約 |
| [configuration.md](configuration.md) | TOML・環境変数の一覧と例 |
| [testing-and-operations.md](testing-and-operations.md) | テスト方針・CI・運用上の注意 |
