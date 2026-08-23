# Chrome による YouTube 取得

この資料は `chrome:control-chrome` 経路を使うときに読む。操作前に同スキル本体を読み、ブラウザー接続とドキュメント取得をその手順どおりに行う。

## 選択規則

- ユーザーが Chrome を指定した場合、Chrome はハード制約である。接続できなければ Computer Use へ無断で切り替えず、Chrome 拡張機能が必要なことを案内する。
- ユーザーがブラウザーを指定していない場合は、Chrome が利用できれば優先できる。接続不能や書き出し非対応なら Computer Use へ切り替えられる。
- Chrome の接続、タブ、要素は返却されたオブジェクトだけを使い、ID や URL を推測して構築しない。

## タブを一意に選ぶ

Chrome の完全な実行時ドキュメントを読んだ後、`chrome.tabs.list()` で開いているタブを取得する。返された URL を正規化し、次をすべて満たす候補だけを残す。

- HTTPS の `youtube.com` または `www.youtube.com`
- パスが `/watch`
- `v` パラメーターが対象動画 ID と一致

候補が 1 件だけなら `chrome.tabs.get(id)` でそのタブを得る。0 件なら Chrome のドキュメントに記載された方法で対象 URL を開き、再度一覧から選ぶ。2 件以上ならタイトルと URL を表示して一意に絞る。タブ選択後に `await tab.url()` を再確認し、対象動画 ID と一致しなければ操作しない。

`youtu.be`、`/shorts/`、`/live/` は、対象動画 ID を保った正規の `https://www.youtube.com/watch?v=<video-id>` ページへ UI ナビゲーションしてから書き出す。

## 組み込み文字起こし書き出し

単体 watch ページでは、画面スクロールによる収集より先に次を使う。

```js
const exportPath = await tab.content.exportYouTubeTranscript();
```

戻り値は UTF-8 `.txt` ファイルのパスである。通常のローカルファイル読み取り手段で読み、元ファイルは監査が終わるまで保持する。期待する内容は次の構造である。

```text
Video ID: RPD90NChDiM
Language: en
Captions:
[00:00] first caption
[00:04] next caption
```

`Video ID`、`Language`、`Captions` より後のすべての `[timestamp] text` 行を取得する。キューの `text` はこの段階で校正・翻訳しない。空行や非字幕ヘッダーを字幕本文へ混ぜない。

このメソッドは Chrome が公開する専用 API であり、本スキルが禁止するページソース、DOM、ネットワーク要求、非公式字幕 API には該当しない。字幕取得目的で別の DOM・Playwright・CDP・fetch 経路を作らない。

## メタデータ

- 書き出しの `Video ID` と、選択済みタブ URL の `v` を一致させる。
- `Language` を `transcript_language` に記録する。
- タイトルは `await tab.title()` とページ表示を照合する。
- チャンネル、公開日、字幕種別、再生リスト情報は Chrome の文書化された画面検査手段で表示内容から読む。字幕本文の抽出には使わない。
- URL は `https://www.youtube.com/watch?v=<video-id>` に正規化する。

## 完全性確認

内容単位への再構成前に次を確認する。

- `Video ID` と対象 ID が完全一致する。
- `Language` が空でない。
- `Captions` 後に 1 件以上のキューがある。
- すべての字幕行を解析でき、未解析の非空行が残っていない。
- タイムスタンプが逆行していない。
- 最初と最後のキューおよび総キュー数を記録する。
- `text` を表示順に連結した検証用原文を固定する。

全キュー、書き出し元パス、取得経路 `chrome_export`、検証結果を監査 JSON に残す。

## 失敗時

次を失敗として扱う。

- 選択したタブが一意でない、または URL を再確認できない
- watch ページ以外として拒否された
- 書き出しに `Video ID`、`Language`、`Captions` がない
- Video ID 不一致、字幕キュー 0 件、未解析行、時刻逆行
- Chrome 接続または拡張機能のエラー

ユーザーが Chrome を明示した場合は、Chrome スキルの復旧手順を一度適用し、解消しなければ停止して具体的なエラーを報告する。Chrome が任意選択だった場合は、同じ動画を Computer Use 経路で取得してよい。壊れた書き出しを部分的に採用しない。

