# テストと運用

## 自動テスト

- **単体**: `engine-core` — 投票、設定パース、パイプライン、リスク、`kill_switch_active`
- **統合（HTTP）**: `adapter-exchsim` — wiremock
- **契約**: `strategies-predict/tests/onnx_smoke.rs` — ワークスペースの `ml_bridge/model.onnx` を読み推論
- **Python スナップショット**（`vendor/ml_pipeline_snapshot_*` 配置後）: スナップショット由来の ONNX／`feature_schema` と Rust 推論の一致を、必要に応じて同テスト系で拡張する（方針は [python-ml-snapshot-policy.md](python-ml-snapshot-policy.md)）

実行:

```bash
cargo test --workspace
```

## CI（GitHub Actions）

- `.github/workflows/ci.yml`: `cargo fmt --check`, `clippy -D warnings`, `cargo test`

## 運用上の注意

- **秘密情報**（API キー、JWT）はリポジトリに含めず、環境変数やローカル `.env`（gitignore）で渡す。
- **キルスイッチ**: `runtime.kill_switch_path` に触れるだけで新規ティックを止められる。パスは誤って書き込み可能な共有領域に置かないこと。
- **live 実行**: 現状バイナリは注文送信まで未配線だが、`execution_mode` と `dry_run` を誤ると将来の拡張で金銭リスクになる。本番前に必ずスタブ／小ロットで検証すること。
- **ONNX**: モデルと `feature_schema.json` のバージョンをデプロイ単位で固定し、ログに `policy_version` と合わせて記録すると追跡しやすい。
