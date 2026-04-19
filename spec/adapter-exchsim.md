# adapter-exchsim

## 責務

`engine_core::Exchange` を **ExchSim 互換 REST API** に対して実装する。既存 Java `ExchSimClient` と同系のパス・JSON フィールド名（serde の rename）を踏襲する。

## 型: ExchSimAdapter

### 生成

- `from_token(base_url, jwt_token)` — ログイン省略
- `from_credentials(base_url, username, password)` — `login_or_refresh` で `POST /api/auth/login`

### 認証

- 認証付きリクエストは `Authorization: Bearer <token>`
- ログイン POST は JSON `{"username","password"}`、レスポンスの `token` を保持

## HTTP マッピング

| メソッド | パス | 用途 |
|----------|------|------|
| POST | `/api/auth/login` | JWT 取得 |
| GET | `/api/market/board/{symbol}?depth=2` | 板 |
| POST | `/api/orders/new` | 新規注文 |
| POST | `/api/orders/cancel` | キャンセル（DTO は `CancelOrderRequest`） |

注文の更新（Java にある `PUT /api/orders/{id}`）は **本トレイトには未追加**。必要なら `Exchange` 拡張と合わせて実装する。

## テスト

- `wiremock` でログイン → 板取得の結合テストあり（実ネットワークなし）。

## エラー方針

- 非 2xx は本文を読み `ExchangeError::BadResponse` に載せる。
