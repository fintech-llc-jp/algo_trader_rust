# 仕様書インデックス

本ディレクトリは **実装に対応した設計・仕様** をまとめたものです。コードの単一の情報源はソースであり、ここは人間向けの説明と境界の固定に使います。

**ビジネス要求（設計の前段）:** [business-requirements.md](business-requirements.md)  
**ユースケース図（PRD ベース）:** [use-case-diagram.md](use-case-diagram.md)  
**シーケンス図（ユースケース対応）:** [sequence-diagrams.md](sequence-diagrams.md)  
**バックエンド充足度レビュー:** [backend-readiness.md](backend-readiness.md)  
**未充足機能 設計書（2026-04-12）:** [design-unmet-capabilities-2026-04-12.md](design-unmet-capabilities-2026-04-12.md)  
**Python `ml_pipeline` スナップショット方針:** [python-ml-snapshot-policy.md](python-ml-snapshot-policy.md)

| 文書 | 内容 |
|------|------|
| [architecture.md](architecture.md) | 全体アーキテクチャとデータフロー |
| [engine-core.md](engine-core.md) | `engine-core`（投票・パイプライン・リスク・設定・Exchange 抽象） |
| [strategy-api.md](strategy-api.md) | `strategy-api`（`Strategy` とスナップショット） |
| [strategies.md](strategies.md) | 各 `strategies-*` クレートの挙動とパラメータ |
| [adapter-exchsim.md](adapter-exchsim.md) | ExchSim アダプタの HTTP パスと認証 |
| [app.md](app.md) | `algo-trader` バイナリの起動・ループ・設定解決 |
| [ml-bridge.md](ml-bridge.md) | ONNX / `feature_schema.json` と Python 連携 |
| [python-ml-snapshot-policy.md](python-ml-snapshot-policy.md) | 上流 `ml_pipeline` のコピー配置・同期・Rust 契約 |
| [configuration.md](configuration.md) | TOML・環境変数の一覧と例 |
| [testing-and-operations.md](testing-and-operations.md) | テスト方針・CI・運用上の注意 |
