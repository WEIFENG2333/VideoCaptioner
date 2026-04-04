# VideoCaptioner Documentation

This is the documentation source file for the VideoCaptioner project, built with [VitePress](https://vitepress.dev/).## 📚 Online View

The documentation has been automatically deployed to GitHub Pages:

**[https://weifeng2333.github.io/VideoCaptioner/](https://weifeng2333.github.io/VideoCaptioner/)**## 🚀 Local Development

### Install Dependencies

```bash
npm install
```

### Start Development Server

```bash
npm run docs:dev
```

Visit http://localhost:5173 to view the documentation

### Build Documentation

```bash
npm run docs:build
```

The build artifacts are located in `docs/.vitepress/dist/`

### Preview Build Results

```bash
npm run docs:preview
```## 📁 Directory Structure

```
docs/
├── .vitepress/
│   ├── config.mts          # VitePress configuration file (including SEO optimization)
│   └── theme/              # Custom theme (optional)
├── public/                 # Static assets (images, logo, robots.txt)
├── guide/                  # English user guide
│   ├── getting-started.md
│   ├── configuration.md
│   └── ...
├── config/                 # English configuration documentation
│   ├── llm.md
│   ├── asr.md
│   └── ...
├── dev/                    # English developer documentation
│   ├── architecture.md
│   └── ...
├── en/                     # English documentation (mirroring Chinese structure)
│   ├── guide/
│   ├── config/
│   └── dev/
└── index.md                # English homepage
```## ✍️ Contribution Guidelines

### Adding a New Page

1. Create a Markdown file in the corresponding directory.
2. **Add Frontmatter for SEO Optimization** (Important!):

```markdown
---
title: Page Title - VideoCaptioner
description: Page description including keywords
head:
  - - meta
    - name: keywords
      content: keyword1,keyword2,keyword3
---

# Page Title

Content...
```

3. Add a link in the `sidebar` of `.vitepress/config.mts`.
4. Submit a PR.

### Editing an Existing Page

Simply edit the Markdown file; it supports:

- **Markdown Extended Syntax**: Tables, code blocks, tip boxes, etc.
- **Vue Components**: Vue components can be used within Markdown.
- **Custom Containers**: `::: tip`, `::: warning`, `::: danger`

Example:

```md
::: tip Tip
This is a tip box.
:::

::: warning Warning
This is a warning box.
:::

::: danger Danger
This is a danger warning box.
:::
```

### Documentation Standards

- **File Name**: Use lowercase letters and hyphens (e.g., `getting-started.md`).
- **Title**: Use a clear hierarchical structure (# → ## → ###).
- **Code Blocks**: Specify the language type to enable syntax highlighting.
- **Images**: Place in the `public/` directory, referenced as `/image.png`.
- **Links**: Internal links should use relative paths (e.g., `/guide/getting-started`).
- **SEO**: Each page should include a title, description, and keywords.## 🔍 SEO Optimization

This document system has been fully optimized for SEO. For details, please refer to [SEO_OPTIMIZATION.md](../SEO_OPTIMIZATION.md).

### Implemented SEO Features

✅ **Basic SEO**

- Title tag optimization
- Meta Description and Keywords
- Open Graph (social media cards)
- Twitter Card
- JSON-LD structured data
- Sitemap auto-generation
- robots.txt
- Canonical URL

✅ **Technical SEO**

- Responsive design
- Clean URLs
- Fast loading (Vite optimization)
- HTTPS (GitHub Pages)

### Submission to Search Engines

After deployment, it is necessary to manually submit to search engines:

1. **Google Search Console**
   - Visit https://search.google.com/search-console
   - Add and verify the website
   - Submit sitemap: `https://weifeng2333.github.io/VideoCaptioner/sitemap.xml`

2. **Bing Webmaster Tools**
   - Visit https://www.bing.com/webmasters
   - Add and verify the website
   - Submit sitemap

3. **Baidu Webmaster Platform**
   - Visit https://ziyuan.baidu.com/
   - Add and verify the website
   - Submit sitemap

### SEO Check Tools

- [Google PageSpeed Insights](https://pagespeed.web.dev/)
- [Google Rich Results Test](https://search.google.com/test/rich-results)
- [Open Graph Debugger](https://developers.facebook.com/tools/debug/)
- [Twitter Card Validator](https://cards-dev.twitter.com/validator)## 🌐 Multilingual Support

The documentation supports both Chinese and English:

- **Chinese**: `docs/` root directory
- **English**: `docs/en/` directory

To add a new language:

1. Create a language directory (e.g., `ja/`) under `docs/`
2. Add locale configuration in `.vitepress/config.mts`
3. Copy the document structure and translate the content## 🔧 Tech Stack

- **VitePress**: A static site generator based on Vite
- **Vue 3**: Component-based development
- **TypeScript**: Type-safe configuration## 📝 Update Documentation

Document updates trigger GitHub Actions deployments automatically:

1. Submit document changes to the `docs/` directory
2. Push to the `master` or `main` branch
3. GitHub Actions automatically builds and deploys
4. Updates take effect in about 2-3 minutes## ❓ Frequently Asked Questions

### Why can't I see styles during local development?

Make sure the dependencies are installed:

```bash
npm install
```

### How to add custom styles?

Create a custom theme in the `docs/.vitepress/theme/` directory:

```ts
// docs/.vitepress/theme/index.ts
import DefaultTheme from "vitepress/theme";
import "./custom.css";

export default DefaultTheme;
```

### How to configure the search function?

VitePress provides a local search by default, which is configured in `config.mts`.

### How to optimize images?

1. Use image compression tools (like TinyPNG)
2. Consider using WebP format
3. Add the `loading="lazy"` attribute

### How to add Google Analytics?

Add the following to the `head` in `config.mts`:

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

For more usage methods of VitePress, please refer to the [official documentation](https://vitepress.dev/) .

For more details on SEO optimization, please check [SEO_OPTIMIZATION.md](../SEO_OPTIMIZATION.md).