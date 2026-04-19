# スナップショットメタデータ

| 項目 | 値 |
|------|-----|
| 作成日 | 2026-04-12 |
| 上流リポジトリ | `algo_trader_v1`（ローカルパス） |
| 上流コミット | `56c4d21978784fc6bff23efb36ad4557febb542e` |
| 上流ログ（1行） | `Merge pull request #17 from fintech-llc-jp/serene-napier` |

## コピーから除外したもの（容量・再現性のため）

以下は **ソーススナップショットに含めていない**。必要なら上流または学習パイプラインから再生成する。

| パス（上流 `ml_pipeline` 直下） | 理由 |
|----------------------------------|------|
| `models/` | 学習成果物（約 2GB 超）。バージョン管理対象外とする運用が望ましい。 |
| `venv_arm64/`, `.venv/` | 仮想環境。`requirements` 等から再作成。 |
| `logs/` | 実行ログ。 |
| `__pycache__/`, `*.pyc` | バイトコード。 |
| `.git/` | 上流の Git メタデータ（純コピーのため除外）。 |

## 復元手順（例）

```bash
cd vendor/ml_pipeline_snapshot_2026-04-12
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # または pyproject に従う
```

（依存ファイル名は当該スナップショットのルートを確認すること。）
