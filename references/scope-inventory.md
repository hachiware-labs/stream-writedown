# Scope inventory と再開可能な一括処理

この資料は、再生リストまたはチャンネルを全件・選択取り込みするときに読む。単体動画には inventory を要求しない。

## 保存場所と責任

inventory は出力ルートへ保存する。

```text
<出力ルート>/.stream-writedown/<scope-id>.inventory.json
```

`scope-id` は再生リスト ID またはチャンネル ID・handle を安全なファイル名へ正規化したものとする。inventory は対象範囲、観測件数、選択状態、処理結果、実際に使ったファイルパスの唯一の台帳である。

`output_path` と `audit_path` は保存または再利用した時点の実パスを記録する。後から日付・タイトル・チャンネル名を使って再計算しない。相対パスは `output_root` 基準とし、`output_root` は実行時に確定した絶対パスを記録する。

## 状態語

状態は次の 6 種だけを使い、`status_summary` に 0 件の状態も含める。

- `pending`: 対象内に選択され、まだ一度も試行していない。`selected: true`、`attempt_count: 0`、理由は `not_attempted`。
- `complete`: 今回生成し、動画単位検証を通過した。実際の `output_path`、`audit_path`、`verified_at` を持つ。
- `existing_complete`: 既存 Markdown と audit を再利用し、今回もう一度動画単位検証を通過した。理由は `reused_existing_verified`。
- `unavailable`: UI 上で利用不能、非表示、削除などにより完全取得できない。確認できた具体的理由を持つ。
- `partial`: 試行したが途中で失敗した。再開に必要な具体的理由と、存在する場合だけ実パスを持つ。
- `out_of_scope`: inventory には観測されたが、選択取り込みの対象外。`selected: false`、`attempt_count: 0`、理由は `not_selected`。

「重要動画 20 本」のような選択取り込みでは、選んだ 20 本だけを `pending` にし、残りは `out_of_scope` にする。選外を未処理件数へ含めない。全件取り込みでは全て `selected: true` とし、`out_of_scope` を使わない。

## 件数

`scope` に次を別々に記録する。

- `displayed_total`: YouTube UI が示す総数。確認不能なら `null` とし、`displayed_total_reason` を必須にする。
- `observed_item_count`: inventory の `items` 数。非表示利用不能 placeholder も含む。
- `visible_video_count`: UI で表示された項目数。
- `hidden_unavailable_count`: UI が明示した非表示利用不能項目数。

通常は `observed_item_count = visible_video_count + hidden_unavailable_count` とする。`displayed_total` が既知なら `displayed_total = observed_item_count` も満たす。

実例のように UI が「80 本」、識別可能な可視項目 79 件、「利用できない動画 1 本が非表示」と示す場合、80 件目を次のような placeholder として追加する。

```json
{
  "inventory_index": 80,
  "kind": "unavailable_placeholder",
  "visibility": "hidden",
  "video_id": null,
  "title": null,
  "position": null,
  "selected": true,
  "status": "unavailable",
  "reason": "YouTube UI reported 1 unavailable video hidden",
  "reason_source": "youtube_ui",
  "attempt_count": 0,
  "transcript_language": null,
  "language_checked": false,
  "output_path": null,
  "audit_path": null,
  "verified_at": null
}
```

非表示項目の ID、タイトル、位置を一覧順や隣接動画から推測しない。非表示数が複数なら、その数だけ別 placeholder を作る。

## JSON スキーマ例

```json
{
  "schema_version": 1,
  "inventory_status": "in_progress",
  "output_root": "C:/transcripts",
  "scope": {
    "type": "playlist",
    "id": "PLexample",
    "url": "https://www.youtube.com/playlist?list=PLexample",
    "title": "Playlist title",
    "selection_mode": "all",
    "displayed_total": 80,
    "displayed_total_reason": null,
    "observed_item_count": 80,
    "visible_video_count": 79,
    "hidden_unavailable_count": 1
  },
  "status_summary": {
    "complete": 78,
    "existing_complete": 0,
    "unavailable": 1,
    "partial": 0,
    "pending": 1,
    "out_of_scope": 0
  },
  "items": []
}
```

各通常項目は `inventory_index`、`kind: "video"`、`visibility: "visible"`、`video_id`、`title`、`position`、`selected`、`status`、`reason`、`attempt_count`、`transcript_language`、`language_checked`、`output_path`、`audit_path`、`verified_at` を持つ。`items` の実数と `status_summary` の合計を常に一致させる。

## Item-level transaction

大きな処理は、動画長や実行環境に応じた有界の小バッチへ分ける。ただしチェックポイントの単位はバッチではなく 1 項目である。

1. inventory から `pending` の 1 項目を選ぶ。
2. `attempt_count` を増やして処理を開始する。途中状態を保持する場合は `partial` と具体的理由を使い、試行済み項目を `pending` に戻さない。
3. 字幕言語を本文処理前に確認する。英語なら日本語訳工程へ送る。
4. Markdown と audit を最終パスへ保存する。既存再利用の場合は既存の実パスを取得する。
5. `scripts/verify_transcript.py` でその組み合わせを検証する。
6. 成功後にだけ `complete` または `existing_complete`、実際の 2 パス、`verified_at` を item へ記録する。
7. `status_summary` を全 items から再集計し、一時ファイルへ完全な JSON を書いてから置き換える方法などで inventory を原子的に更新する。
8. 次の項目へ進む。

失敗時はその項目だけ `partial` または `unavailable` とし、具体的理由と存在する実パスを記録して直ちに inventory を更新する。同じバッチの既成功項目を巻き戻さない。再開時は inventory に記録された状態と実パスだけを使う。

全ての選択項目が終端状態になり `pending` が 0 になったら、`inventory_status: "complete"` にして `scripts/verify_inventory.py` を実行する。失敗した場合は完了報告せず、inventory または該当 item を修正する。

## 後方互換と移行

本仕様以前の inventory は自動推測で完成扱いにしない。元ファイルを保持したまま次を行う。

1. `schema_version: 1`、`inventory_status`、`output_root`、`scope` の件数フィールドを追加する。
2. 選択対象の未試行だけを `pending`、選外を `out_of_scope` に移す。
3. 既存結果は、記録済みまたは実在確認した実パスをそのまま `output_path` と `audit_path` に入れる。ファイル名を再計算しない。
4. 既存の Markdown と audit が動画単位検証を通れば `existing_complete` にする。audit がない、または検証不能なら理由付き `partial` とする。
5. UI の表示総数を再確認できなければ `displayed_total: null` とし、`displayed_total_reason` に確認不能理由を書く。`observed_item_count`、可視数、非表示数、items 数の内部整合性は必須とする。
6. `status_summary` を items から再集計し、inventory 検証を実行する。

検証 helper は旧フィールドを黙って補完しない。不足を具体的なエラーとして返し、この移行手順で明示的に直す。

## 検証

処理中のチェックポイントを検査する場合:

```bash
python -X utf8 scripts/verify_inventory.py <inventory.json> --allow-incomplete
```

最終完了を検査する場合:

```bash
python -X utf8 scripts/verify_inventory.py <inventory.json>
```

最終検証では `inventory_status: "complete"` と `pending: 0` を要求する。
