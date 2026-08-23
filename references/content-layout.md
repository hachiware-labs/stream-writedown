# 内容単位 Markdown・校正・翻訳

この資料は、取得済みの原字幕キューを最終 Markdown へ変換し、監査データを作るときに読む。

## 処理順

順序を入れ替えない。

1. 原字幕キューを取得・固定する。
2. キューを表示順に連結した検証用原文を作る。
3. 原文の欠落・重複・先頭・末尾・時刻順を検証する。
4. 原表記のまま、内容単位の節と段落へ区切り直す。
5. 見出し・時間・Markdown 記号を除いた校正前本文と検証用原文の完全一致を確認する。
6. 校正前本文から保存用の原文本文を校正する。
7. 校正差分をすべて確認し、脱落と意味改変がないことを確認する。
8. 原字幕が英語なら、校正済み原文を日本語へ翻訳する。
9. 翻訳の段落対応、脱落・重複・意味改変を確認する。
10. 最終 Markdown と監査 JSON を保存し、検証スクリプトを実行する。

区切り直しでは文字を直さず、校正では節・段落の責任範囲を組み替えない。翻訳は原文校正の完了後にだけ行う。

## 原文の連結と完全性

原字幕キューは次の順序付き配列として保持する。

```json
[
  {"timestamp": "00:00", "text": "今日は"},
  {"timestamp": "00:02", "text": "テストです"}
]
```

検証用原文は `text` を配列順に連結したものとする。レイアウトによる改行と空白の差を除いて比較し、それ以外の文字は一致させる。キュー内部の表記は変更しない。

内容単位へ区切った校正前本文から、節見出し、見出し内の時間範囲、空行、Markdown のエスケープだけを除いた本文を取り出す。この本文と検証用原文を比較し、次を同時に満たすことを完全性合格とする。

- 全文が同じ順序で 1 回ずつ現れる。
- 欠落と重複がない。
- 先頭文字列と末尾文字列が一致する。
- 校正前の文字、句読点、`[音楽]` などが変わっていない。

## 内容単位への区切り直し

### 節

話題、質問、説明対象、議論の段階が実際に変わる位置で節を分ける。見出しは直後の発話内容から直接分かる短い話題名にする。見出しだけを読んで新しい結論や評価が生じる表現、要約文、外部知識は加えない。

時間範囲は、その開始・終了が文または話題の境界と一致するときだけ見出しへ添えられる。

```markdown
### 開発環境の説明（`00:00`–`02:14`）
```

境界がキュー途中または文中なら時間を省略する。本文途中にタイムスタンプ単独行を挟まない。

### 段落

文中で切れた連続キューは先につなぐ。文意、説明対象、話者の発話単位が続く範囲を同じ段落にし、文の途中で改段落しない。各段落は 1 行で保存し、表示折り返しに任せる。

本文は通常の段落とし、字幕キュー箇条書きにはしない。原文に Markdown と解釈される行頭記号がある場合はバックスラッシュでエスケープし、文字自体は保持する。

## 校正

完全性を確認した校正前本文を固定してから、複製した保存用本文を校正する。

修正できるもの:

- 明白な誤字脱字
- 明白な助詞抜け
- 文意を変えない句読点
- 同一語の明白な表記ゆれ
- 前後の発話だけから一意に判断できる自動字幕の誤認識

修正しないもの:

- 確信できない固有名詞、製品名、人名、専門用語
- 複数の解釈があり得る語
- 話者固有の口調、反復、ためらい、言い直し
- 事実関係を整えるための補足や外部知識による修正
- 要約、言い換え、説明追加、情報削減

校正後は校正前本文との全文差分を確認する。各差分が許可された修正であり、発言の意味、主張、否定、条件、留保、語調、数値、情報量を変えていないことを人が読める形で確認する。監査 JSON が校正前と校正後を両方保持するため、個別の変更履歴を別途手書きする必要はない。`scripts/verify_transcript.py --show-diff` で再現可能な差分を表示できる。

## 英語から日本語への翻訳

`transcript_language` が英語を示す場合、校正済み英語原文から日本語訳を作る。ユーザーが翻訳先を指定していなければ日本語 (`ja`) を使う。

- 原文の節と段落を 1 対 1 で対応させる。日本語として不自然な場合も、複数段落の統合や分割は監査上の対応を失わない範囲に限る。
- 固有名詞、数値、単位、コード、否定、条件、留保、因果関係を保持する。
- 情報を要約・補足・解説しない。曖昧さを推測で解消しない。
- 見出しも翻訳するが、原文にない主張を加えない。
- 校正済み原文の各段落に対応する訳が 1 回ずつあり、脱落と重複がないことを確認する。

最終 Markdown には日本語訳を保存し、英語原文は監査 JSON の `proofread_body_markdown` に保持する。

## 最終 Markdown

完全取得した日本語字幕の例:

```markdown
---
title: "動画タイトル"
channel: "チャンネル名"
video_id: "abcdefghijk"
url: "https://www.youtube.com/watch?v=abcdefghijk"
published_date: "2026-08-23"
source_scope: "video"
playlist_name: null
playlist_position: null
transcript_language: "ja"
transcript_kind: "auto"
transcript_status: "complete"
transcript_layout: "content_sections"
proofread: true
proofread_audit: ".stream-writedown/abcdefghijk.audit.json"
translated: false
translation_target_language: null
retrieved_at: "2026-08-23T12:34:56+09:00"
---

# 動画タイトル

## 動画情報

- チャンネル: チャンネル名
- 公開日: 2026-08-23
- URL: https://www.youtube.com/watch?v=abcdefghijk
- 文字起こし: ja / 自動生成
- 校正: 済み

## 文字起こし

### 最初の話題（`00:00`–`02:14`）

内容のつながった最初の段落です。文の途中では改段落しません。

同じ話題の次の段落です。

### 次の話題

次の話題に対応する段落です。
```

英語字幕を日本語へ翻訳した場合は `translated: true`、`translation_target_language: "ja"` とし、見出しを `## 文字起こし（日本語訳）` にする。動画情報にも `翻訳: 英語 → 日本語` を記載する。

`source_scope` は `video`、`playlist`、`channel` のいずれか。`transcript_kind` は UI で確認できた場合だけ `manual` または `auto`、不明なら `unknown` とする。

取得不能時は `transcript_status: "unavailable"`、部分取得時は `partial` とし、状態、理由、最終取得時刻を本文へ記す。完全取得でない場合は `proofread: false` とし、`transcript_layout` を偽って `content_sections` にしない。

## 監査 JSON

`.stream-writedown/<video-id>.audit.json` は UTF-8 の次の構造にする。

```json
{
  "schema_version": 1,
  "video_id": "abcdefghijk",
  "source_route": "chrome_export",
  "source_export_path": "C:/path/to/export.txt",
  "source_language": "en",
  "cues": [
    {"timestamp": "00:00", "text": "original caption"}
  ],
  "preproofread_body_markdown": "### Topic\\n\\noriginal caption",
  "proofread_body_markdown": "### Topic\\n\\nOriginal caption.",
  "translation": {
    "enabled": true,
    "target_language": "ja",
    "body_markdown": "### 話題\\n\\n元の字幕です。",
    "review": {
      "paragraphs_aligned": true,
      "no_omissions_or_duplicates": true,
      "meaning_preserved": true
    }
  },
  "checks": {
    "source_complete": true,
    "source_matches_preproofread": true,
    "proofread_no_omissions": true,
    "proofread_meaning_preserved": true
  }
}
```

Computer Use の場合は `source_route: "computer_use"`、Chrome 組み込み書き出しは `chrome_export` とする。`source_export_path` は該当しない場合 `null`。

## 検証コマンド

完全取得した各動画で実行する。

```bash
python -X utf8 scripts/verify_transcript.py <audit.json> <transcript.md>
```

校正前後と翻訳前後の差分を確認する場合:

```bash
python -X utf8 scripts/verify_transcript.py <audit.json> <transcript.md> --show-diff
```

スクリプトは、原キュー対校正前本文の無損失一致、時刻順、監査 JSON と最終本文の一致、必須 frontmatter、各レビュー結果を検証する。校正や翻訳の意味保持自体は機械的に断定できないため、差分を人間が読める形で確認したうえでレビュー値を `true` にする。

スクリプト自身の再現テスト:

```bash
python -X utf8 -m unittest discover -s tests -v
```

## 実測ベンチマーク

動画 `RPD90NChDiM` では、自動字幕 307 キュー、連結本文 5,689 文字を 6 節・24 段落へ再構成し、校正前本文について欠落 0、重複 0、先頭・末尾一致、文中で終わる段落 0 を確認できた。この数値は再現性の参考であり、別動画へ 6 節・24 段落を強制しない。
