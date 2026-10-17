# 自動更新型 アフィリエイト比較サイト

楽天市場の商品データを毎日取得し、カテゴリごとに「比較表・選び方・ランキング・FAQ」のページを自動で作って、GitHub Pages に公開します。

```
楽天API(商品取得) → ランキング(レビュー件数で補正) → Claude(解説文) → 静的HTML → GitHub Pages
          └──────────── GitHub Actions が毎日自動実行 ────────────┘
```

## 費用の目安

| 項目 | 費用 |
|---|---|
| 楽天API / GitHub / GitHub Pages | 無料 |
| Claude API（解説文の生成） | 1カテゴリ1回あたり約15〜25円。ラインナップが変わったときだけ、かつ最短7日おきに再生成するので、5カテゴリで月500円程度まで |
| 独自ドメイン（任意） | 年1,500円前後 |

`ANTHROPIC_API_KEY` を設定しない場合でも動きます。その場合、解説文は取得データから組み立てた簡易版になり、費用はかかりません。

## セットアップ（30分くらい）

### 1. 楽天のIDを取る
1. [楽天アフィリエイト](https://affiliate.rakuten.co.jp/) に登録して、**アフィリエイトID** を確認します。
2. [Rakuten Developers](https://webservice.rakuten.co.jp/) でアプリを新規登録して、**アプリID（applicationId）** と **アクセスキー（accessKey）** を取得します。
   - 2026年の仕様変更で accessKey が必須になりました。また、2026年5月より前に発行したIDは使えません。
   - 「許可されたWebサイト」には、公開するサイトのドメインを登録します（例: `yourname.github.io`）。

### 2. GitHubに置く
1. GitHubで新しいリポジトリを作り、このフォルダを push します。
2. `config.toml` の `site.url` を公開URLに書き換えます（例: `https://yourname.github.io/affiliate-site`）。
3. Settings → Pages → Source で **GitHub Actions** を選びます。
4. Settings → Secrets and variables → Actions に次を登録します。
   - `RAKUTEN_APP_ID` / `RAKUTEN_ACCESS_KEY` / `RAKUTEN_AFFILIATE_ID`
   - `ANTHROPIC_API_KEY`（任意。[Claude Console](https://platform.claude.com/) で発行）
5. Actions タブ → build-and-deploy → **Run workflow** を実行します。以後は毎朝自動で更新されます。

### 3. 検索エンジンに知らせる
[Google Search Console](https://search.google.com/search-console) にサイトを登録して、`sitemap.xml` を送信します。

## ローカルで確認

```bash
pip install -r requirements.txt
python -m autosite.build --demo          # 架空のサンプルデータで生成（noindex付き）
python -m http.server -d dist 8000       # http://localhost:8000 で表示
```

## カテゴリを増やす

`config.toml` に `[[categories]]` を追加するだけです。

## 稼ぐために大事なこと（正直な話）

- **自動生成ページだけで上位表示されるのは難しい**です。Googleは「独自の価値が少ない大量生成ページ」を評価を下げる対象にしています。このツールは土台と更新作業を自動化するものです。上位を狙うページには、実際に使った感想・写真・独自の比較軸などを手で書き足してください。それが一番効きます。
- **ジャンルは絞ったほうが勝ちやすい**です。「ワイヤレスイヤホン」のような大きなキーワードは強いサイトが占めています。「ワイヤレスイヤホン 寝ホン」「加湿器 一人暮らし 静音」のように用途を絞ったカテゴリを増やすのが現実的です。
- 楽天アフィリエイトの報酬率は多くの商品で数%です。慣れてきたら、A8.net などの高単価案件（サービス系）を同じ仕組みで扱うと伸ばしやすくなります。
- PR表記（ステマ規制対応）、楽天のクレジット表記、運営者情報ページは最初から入っています。消さないでください。
