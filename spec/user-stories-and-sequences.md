# ユーザーストーリーとシーケンス図（現状ベース）

このドキュメントは、現状の仕様（`engine-core` / `app` / `adapter-exchsim`）から導けるユーザーストーリーを整理したものです。  
実装済み機能と、仕様上の拡張ポイントの両方を含みます。

## 1. 運用者として、設定で投票ポリシーとリスク閾値を切り替えたい

**ユーザーストーリー**  
運用者として、`config.toml` と環境変数で投票ポリシー（weighted/quorum/simple）やリスク閾値を切り替え、再ビルドなしで戦略判断とリスク制約を調整したい。  
これにより、相場状況に合わせて運用ルールを迅速に変更できる。

```mermaid
sequenceDiagram
    autonumber
    actor Operator as 運用者
    participant App as algo-trader-app
    participant Config as AppConfig/RuntimeConfig
    participant Pipeline as TradingPipeline
    participant Vote as VoteEngine
    participant Risk as RiskService

    Operator->>App: 起動(config.toml, ALGO_TRADER_* env)
    App->>Config: 設定ロード(figment)
    loop 各ティック
        App->>Pipeline: decide(votes)
        Pipeline->>Vote: aggregate(votes, vote_policy)
        Vote-->>Pipeline: VoteOutcome
        Pipeline->>Risk: apply(intent, risk_limits)
        Risk-->>Pipeline: 許可/ブロック済みIntent
        Pipeline-->>App: 最終Intent
    end
```

## 2. 戦略開発者として、ドライランで意思決定ログを検証したい

**ユーザーストーリー**  
戦略開発者として、`dry_run` モードで戦略投票から最終 `Intent` までの流れを観測し、実注文なしでロジックの妥当性を確認したい。  
これにより、本番投入前に安全に閾値や重みをチューニングできる。

```mermaid
sequenceDiagram
    autonumber
    actor Dev as 戦略開発者
    participant App as algo-trader-app
    participant S1 as MarketMaker
    participant S2 as Arbitrage
    participant S3 as PricePrediction
    participant S4 as Momentum
    participant Pipeline as TradingPipeline

    Dev->>App: dry_run=true で起動
    loop 各ティック
        App->>S1: evaluate(snapshot)
        App->>S2: evaluate(snapshot)
        App->>S3: evaluate(snapshot)
        App->>S4: evaluate(snapshot)
        S1-->>App: StrategyVote
        S2-->>App: StrategyVote
        S3-->>App: StrategyVote
        S4-->>App: StrategyVote
        App->>Pipeline: decide(Vec<StrategyVote>)
        Pipeline-->>App: Intent(NoTrade or PlaceOrder)
        App-->>Dev: tracingログ(engine target)
    end
```

## 3. リスク管理者として、危険な注文を自動ブロックしたい

**ユーザーストーリー**  
リスク管理者として、注文サイズ上限・ポジション上限・日次損失上限を超える注文を自動でブロックしたい。  
これにより、戦略が強いシグナルを出しても損失拡大を抑制できる。

```mermaid
sequenceDiagram
    autonumber
    actor RiskMgr as リスク管理者
    participant Pipeline as TradingPipeline
    participant Risk as RiskService

    RiskMgr->>Risk: risk_limits設定 + daily_pnl注入
    Pipeline->>Risk: apply(Intent::PlaceOrder)
    alt max_order_size超過
        Risk-->>Pipeline: Intent::NoTrade(ブロック)
    else max_position_units超過見込み
        Risk-->>Pipeline: Intent::NoTrade(ブロック)
    else daily_pnl が -max_daily_loss_abs 未満
        Risk-->>Pipeline: Intent::NoTrade(ブロック)
    else すべて許容範囲
        Risk-->>Pipeline: Intent::PlaceOrder(許可)
    end
```

## 4. 運用者として、キルスイッチで新規ティック処理を即停止したい

**ユーザーストーリー**  
運用者として、障害時にキルスイッチ用ファイルを置くだけで新規ティック処理を停止したい。  
これにより、プロセス停止より安全かつ迅速に取引判断を止められる。

```mermaid
sequenceDiagram
    autonumber
    actor Operator as 運用者
    participant FS as ファイルシステム
    participant App as algo-trader-app

    Operator->>FS: kill_switch_path にファイル作成
    loop 各ティック
        App->>FS: kill_switch_active(path) を確認
        alt ファイル存在
            App-->>App: ティック処理をスキップ
        else ファイルなし
            App-->>App: snapshot生成 -> 戦略評価 -> decide
        end
    end
```

## 5. トレーダーとして、Live時に取引所アダプタ経由で注文を送信したい（拡張）

**ユーザーストーリー**  
トレーダーとして、`execution_mode=live` のとき `Intent::PlaceOrder` が ExchSim API に送信され、約定ライフサイクルを管理できるようにしたい。  
これにより、検証済み戦略を実運用に接続できる。  
※ 現状 `app` では live 時の実送信は未配線（ログのみ）。

```mermaid
sequenceDiagram
    autonumber
    actor Trader as トレーダー
    participant App as algo-trader-app
    participant Pipeline as TradingPipeline
    participant Adapter as ExchSimAdapter
    participant API as ExchSim REST

    Trader->>App: execution_mode=live で起動
    App->>Pipeline: decide(votes)
    Pipeline-->>App: Intent::PlaceOrder
    App->>Adapter: place_order(NewOrderRequest) [将来配線]
    Adapter->>Adapter: login_or_refresh(必要時)
    Adapter->>API: POST /api/orders/new (Bearer token)
    API-->>Adapter: order result
    Adapter-->>App: OrderResponse
    App-->>Trader: ログ/メトリクス反映
```

## 6. データ連携担当として、スタブsnapshotを実市場データに置き換えたい（拡張）

**ユーザーストーリー**  
データ連携担当として、`sample_snapshot` を `Exchange::get_order_book` と外部バー取得へ置き換え、実市場に近い `MarketSnapshot` で戦略を評価したい。  
これにより、バックテストと本番判断の乖離を小さくできる。

```mermaid
sequenceDiagram
    autonumber
    actor Integrator as データ連携担当
    participant App as algo-trader-app
    participant Adapter as ExchSimAdapter
    participant API as ExchSim REST
    participant Bars as Barストア(DB/Redis等)
    participant Strategy as Strategy群

    loop 各ティック
        App->>Adapter: get_order_book(symbol)
        Adapter->>API: GET /api/market/board/{symbol}
        API-->>Adapter: OrderBook
        App->>Bars: 直近バー取得
        Bars-->>App: Vec<Bar>
        App-->>App: MarketSnapshot構築
        App->>Strategy: evaluate(snapshot)
    end
```

## 補足（優先度の目安）

- まずは **1〜4** が現行実装に最も近い運用ストーリー。
- **5, 6** は仕様で明示されている拡張ポイントに基づく次フェーズ候補。
