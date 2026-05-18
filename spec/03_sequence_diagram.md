# シーケンス図（ユースケース図ベース）

本書は [02_use-case-diagram.md](02_use-case-diagram.md) のアクター・ユースケースを、**時系列の相互作用**として表現したものである。  
**対象システム**は論理ブロックとして「アルゴトレード基盤」と総称する（内部モジュール名は含めない）。  
**静的な境界（C4 L1/L2）** とユースケースの対応は [04_c4-level1-system-context.md](04_c4-level1-system-context.md) / [05_c4-level2-containers.md](05_c4-level2-containers.md) を参照。

---

## 図の対応関係

| 節 | 対応 UC | 概要 |
|----|---------|------|
| [§1](#1-uc-1-期日に基づくモデル学習) | UC-1 | 学習ジョブの登録から成果物保存まで |
| [§2](#2-uc-1r-学習ジョブ成果物の参照) | UC-1r | 状態・メタデータの参照 |
| [§3](#3-uc-2-バックテスト) | UC-2 | モデル＋期間・条件での評価 |
| [§4](#4-uc-2r-バックテスト結果の参照比較) | UC-2r | 結果一覧・比較 |
| [§5](#5-uc-3-exchsim-でのリアルタイム取引) | UC-3 | ExchSim との継続的相互作用 |
| [§6](#6-uc3s-取引の停止キルスイッチ) | UC3s | 利用者／運用による停止 |
| [§7](#7-c4-静的図への参照) | UC 全体 | C4 レベル1・2の**静的**表現は別紙（トレーサビリティ表付き） |

---

## 1. UC-1 期日に基づくモデル学習

```mermaid
sequenceDiagram
  autonumber
  actor U as 利用者
  participant S as アルゴトレード基盤
  participant D as 学習用データ\n（内部／外部）

  U->>S: 学習ジョブ登録（実行予定／データ截至・条件）
  S->>D: 指定期間・条件のデータ取得
  D-->>S: 時系列・特徴量データ
  S->>S: 前処理・学習実行
  alt 成功
    S-->>U: 完了通知（成果物 ID・学習メタデータ）
  else 失敗
    S-->>U: 失敗通知（確認可能な理由）
  end
```

---

## 2. UC-1r 学習ジョブ・成果物の参照

```mermaid
sequenceDiagram
  autonumber
  actor U as 利用者
  participant S as アルゴトレード基盤

  U->>S: ジョブ／成果物の照会（ ID・期間フィルタ等）
  S-->>U: 状態・メタデータ（学習日時・データ範囲・バージョン等）
```

---

## 3. UC-2 バックテスト

```mermaid
sequenceDiagram
  autonumber
  actor U as 利用者
  participant S as アルゴトレード基盤
  participant H as 履歴市場データ\n（内部／外部）

  U->>S: バックテスト指定（モデル／戦略・評価期間・取引コスト条件）
  S->>S: 学習済モデル・設定の解決
  S->>H: 指定期間の履歴取得
  H-->>S: OHLCV・板相当データ等
  S->>S: シミュレーション実行（シグナル→約定ルール）
  S-->>U: 結果の保存とサマリ（損益・取引回数・リスク指標等）
```

> UC-2 はユースケース図上 UC-1 に依存（学習済モデルの利用）。上記では「モデル解決」に集約して表現している。

---

## 4. UC-2r バックテスト結果の参照・比較

[§3](#3-uc-2-バックテスト) の実行結果は基盤内に保存され、本節では **利用者とアルゴトレード基盤のみ** を対象とする（[04_c4-level1-system-context.md](04_c4-level1-system-context.md) の UC-2r 行とも対応）。

```mermaid
sequenceDiagram
  autonumber
  actor U as 利用者
  participant S as アルゴトレード基盤

  U->>S: 保存済み結果の一覧要求
  S-->>U: 一覧（実行 ID・期間・主要指標）
  U->>S: 複数結果の比較要求
  S-->>U: 比較ビュー／レポート（並列指標）
```

---

## 5. UC-3 ExchSim でのリアルタイム取引

```mermaid
sequenceDiagram
  autonumber
  actor U as 利用者
  actor O as 運用・リスク管理
  participant S as アルゴトレード基盤
  participant E as ExchSim

  U->>S: 取引セッション開始（モデル・シンボル・リスクパラメータ）
  opt 組織ポリシー（承認・上限）
    O->>S: 承認・上限・ガード条件の適用
  end
  S->>E: 接続・認証
  E-->>S: セッション確立

  loop 市場更新ティック（PoC では間欠でも可。更新頻度と UI の追随は NFR および [07_gui-spec.md](07_gui-spec.md) と整合させる）
    S->>E: 市場データ取得（板／約定 等）
    E-->>S: 最新状態
    S->>S: シグナル生成・リスク判定
    alt 注文が許可される
      S->>E: 注文
      E-->>S: 約定・注文状態
    else 注文なし／保留
      S->>S: スキップ
    end
    S-->>U: 状態更新（ポジション・未約定・損益の把握に必要な範囲）
  end
```

> UC-3 はユースケース図上 UC-2 への依存が「推奨」。上記では省略可能だが、運用ではバックテスト合格モデルのみ選択する想定を注記する。

---

## 6. UC3s 取引の停止・キルスイッチ

```mermaid
sequenceDiagram
  autonumber
  actor U as 利用者
  actor O as 運用・リスク管理
  participant S as アルゴトレード基盤
  participant E as ExchSim

  par 利用者による通常停止
    U->>S: 取引停止要求
  and 運用による緊急停止
    O->>S: キルスイッチ有効化（全セッション／指定のみ等）
  end

  S->>S: 新規注文抑止・戦略ループ停止
  opt ポリシーにより未約定取消
    S->>E: 注文キャンセル等
    E-->>S: 結果
  end
  S-->>U: 停止確定・最終状態
  opt 運用向け
    S-->>O: 監査用イベント（監査要件がある場合）
  end
```

---

## 7. C4 静的図への参照

[C4 モデル](https://c4model.com/) の **レベル1（システムコンテキスト）** と **レベル2（コンテナ）** は、**静的な境界図**で表すのが標準である。  
時系列の相互作用は **本書 §1〜§6** のシーケンス図を正とし、静的な「誰が・どのシステムと・どの境界でつながるか」は次の別紙に記載する（いずれも **ユースケースとのトレーサビリティ表** 付き）。

| レベル | ファイル | 内容 |
|--------|----------|------|
| L1 | [04_c4-level1-system-context.md](04_c4-level1-system-context.md) | 利用者・運用・アルゴトレード基盤・データ基盤・ExchSim |
| L2 | [05_c4-level2-containers.md](05_c4-level2-containers.md) | Web UI / BFF / 取引ランタイム / アダプタ / 学習・分析ワーカー と外部 |

---

## PlantUML（参考）

Mermaid が使えない場合の代替として、同内容を PlantUML で表す例を示す（§5 のみ抜粋）。

```plantuml
@startuml
actor 利用者 as U
actor "運用・リスク管理" as O
participant "アルゴトレード基盤" as S
participant ExchSim as E

U -> S: 取引セッション開始
opt 組織ポリシー
  O -> S: 承認・上限
end
S -> E: 接続・認証
... ループ省略 ...
@enduml
```

---

## 改訂

| 版 | 内容 |
|----|------|
| 0.1 | ユースケース図に基づく初版 |
| 0.2 | §7 C4 レベル1・2境界に相当するシーケンス図を追加 |
| 0.3 | §7 を静的 C4 図（L1/L2）の別紙参照に変更 |
