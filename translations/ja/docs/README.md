# VideoCaptioner ドキュメント

これは VideoCaptioner プロジェクトのドキュメントソースファイルで、[VitePress](https://vitepress.dev/) を使用して構築されています。## 📚 オンライン表示

ドキュメントは自動的に GitHub Pages にデプロイされました：

**[https://weifeng2333.github.io/VideoCaptioner/](https://weifeng2333.github.io/VideoCaptioner/)**## 🚀 ローカル開発

### 依存関係のインストール

```bash
npm install
```

### 開発サーバーの起動

```bash
npm run docs:dev
```

http://localhost:5173 にアクセスしてドキュメントを確認してください

### ドキュメントのビルド

```bash
npm run docs:build
```

ビルド成果物は `docs/.vitepress/dist/` にあります

### ビルド結果のプレビュー

```bash
npm run docs:preview
```## 📁 ディレクトリ構造

```
docs/
├── .vitepress/
│   ├── config.mts          # VitePress 設定ファイル（SEO 最適化を含む）
│   └── theme/              # カスタムテーマ（オプショナル）
├── public/                 # 静的リソース（画像、ロゴ、robots.txt）
├── guide/                  # 日本語使用ガイド
│   ├── getting-started.md
│   ├── configuration.md
│   └── ...
├── config/                 # 日本語設定文書
│   ├── llm.md
│   ├── asr.md
│   └── ...
├── dev/                    # 日本語開発者文書
│   ├── architecture.md
│   └── ...
├── en/                     # 英語文書（日本語構造のミラー）
│   ├── guide/
│   ├── config/
│   └── dev/
└── index.md                # 日本語ホームページ
```## ✍️ 貢献ドキュメント

### 新しいページの追加

1. 対応するディレクトリに Markdown ファイルを作成
2. **Frontmatter SEO 最適化を追加**（重要！）：

```markdown
---
title: ページタイトル - VideoCaptioner
description: ページの説明、キーワードを含む
head:
  - - meta
    - name: keywords
      content: キーワード1,キーワード2,キーワード3
---

# ページタイトル

内容...
```

3. `.vitepress/config.mts` の `sidebar` にリンクを追加
4. PR を提出

### 既存ページの編集

Markdown ファイルを直接編集するだけで大丈夫です。サポート内容：

- **Markdown 拡張構文**：表、コードブロック、ヒントボックスなど
- **Vue コンポーネント**：Markdown 内で Vue コンポーネントが使用可能
- **カスタムコンテナ**：`::: tip`, `::: warning`, `::: danger`

例：

```md
::: tip ヒント
これはヒントボックスです
:::

::: warning 注意
これは警告ボックスです
:::

::: danger 危険
これは危険警告ボックスです
:::
```

### ドキュメント規範

- **ファイル名**：小文字とハイフンを使用（例： `getting-started.md`）
- **タイトル**：明確な階層構造を使用（# → ## → ###）
- **コードブロック**：言語タイプを指定して構文ハイライトを有効化
- **画像**：`public/` ディレクトリに置き、 `/image.png` で参照
- **リンク**：内部リンクは相対パスを使用（例： `/guide/getting-started`）
- **SEO**：各ページには title、description、keywords を追加すること## 🔍 SEO最適化

本文書システムは全面的にSEO最適化されています。詳細は[SEO_OPTIMIZATION.md](../SEO_OPTIMIZATION.md)をご覧ください。

### 実施されたSEO機能

✅ **基本的なSEO**

- Titleタグの最適化
- Meta DescriptionとKeywords
- Open Graph（ソーシャルメディアカード）
- Twitter Card
- JSON-LD構造化データ
- Sitemapの自動生成
- robots.txt
- Canonical URL

✅ **技術的SEO**

- レスポンシブデザイン
- クリーンURL
- 高速ロード（Vite最適化）
- HTTPS（GitHub Pages）

### 検索エンジンへの提出

デプロイ後に手動で検索エンジンへ提出する必要があります：

1. **Google Search Console**
   - https://search.google.com/search-consoleにアクセス
   - ウェブサイトを追加して検証
   - Sitemapを提出します: `https://weifeng2333.github.io/VideoCaptioner/sitemap.xml`

2. **Bing Webmaster Tools**
   - https://www.bing.com/webmastersにアクセス
   - ウェブサイトを追加して検証
   - Sitemapを提出します

3. **百度站長プラットフォーム**
   - https://ziyuan.baidu.com/にアクセス
   - ウェブサイトを追加して検証
   - Sitemapを提出します

### SEOチェックツール

- [Google PageSpeed Insights](https://pagespeed.web.dev/)
- [Google Rich Results Test](https://search.google.com/test/rich-results)
- [Open Graph Debugger](https://developers.facebook.com/tools/debug/)
- [Twitter Card Validator](https://cards-dev.twitter.com/validator)## 🌐 多言語サポート

文書は中英二言語をサポートしています：

- **中国語**：`docs/` ルートディレクトリ
- **英語**：`docs/en/` ディレクトリ

新しい言語を追加するには：

1. `docs/` の下に言語ディレクトリ（例： `ja/`）を作成します
2. `.vitepress/config.mts` にロケール設定を追加します
3. 文書構造をコピーし、内容を翻訳します## 🔧 テクノロジースタック

- **VitePress**: Vite に基づく静的サイトジェネレーター
- **Vue 3**: コンポーネントベースの開発
- **TypeScript**: タイプセーフな設定## 📝 ドキュメントの更新

ドキュメントの更新は GitHub Actions のデプロイを自動でトリガーします：

1. `docs/` ディレクトリにドキュメントの変更をコミット
2. `master` または `main` ブランチにプッシュ
3. GitHub Actions が自動でビルドとデプロイを実行
4. 約 2-3 分後に更新が反映されます## ❓ よくある質問

### ローカル開発時にスタイルが見えない？

依存関係がインストールされていることを確認してください：

```bash
npm install
```

### カスタムスタイルを追加するには？

`docs/.vitepress/theme/` ディレクトリにカスタムテーマを作成します：

```ts
// docs/.vitepress/theme/index.ts
import DefaultTheme from "vitepress/theme";
import "./custom.css";

export default DefaultTheme;
```

### 検索機能を設定するには？

VitePressはデフォルトでローカル検索を提供しており、`config.mts`に設定されています。

### 画像を最適化するには？

1. 画像圧縮ツール（例：TinyPNG）を使用する
2. WebP形式の使用を検討する
3. `loading="lazy"`属性を追加する

### Google Analyticsを追加するには？

`config.mts`の`head`に追加します：

```typescript
([
  "script",
  {
    async: true,
    src: "https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX",
  },
],
  [
    "script",
    {},
    `
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-XXXXXXXXXX');
`,
  ]);
```

---

VitePressの使用方法の詳細については、[公式ドキュメント](https://vitepress.dev/)を参照してください。

SEO最適化の詳細は、[SEO_OPTIMIZATION.md](../SEO_OPTIMIZATION.md)をご覧ください。