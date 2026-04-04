# VideoCaptioner 문서

이것은 VideoCaptioner 프로젝트의 문서 원본 파일로, [VitePress](https://vitepress.dev/)를 사용하여 구축되었습니다.## 📚 온라인 보기

문서가 GitHub Pages에 자동으로 배포되었습니다:

**[https://weifeng2333.github.io/VideoCaptioner/](https://weifeng2333.github.io/VideoCaptioner/)**## 🚀 로컬 개발

### 의존성 설치

```bash
npm install
```

### 개발 서버 시작

```bash
npm run docs:dev
```

http://localhost:5173 에서 문서 확인

### 문서 빌드

```bash
npm run docs:build
```

빌드 산출물은 `docs/.vitepress/dist/` 에 위치합니다.

### 빌드 결과 미리보기

```bash
npm run docs:preview
```## 📁 디렉토리 구조

```
docs/
├── .vitepress/
│   ├── config.mts          # VitePress 설정 파일 (SEO 최적화 포함)
│   └── theme/              # 사용자 정의 테마 (선택 사항)
├── public/                 # 정적 자원 (이미지, 로고, robots.txt)
├── guide/                  # 한국어 사용 가이드
│   ├── getting-started.md
│   ├── configuration.md
│   └── ...
├── config/                 # 한국어 설정 문서
│   ├── llm.md
│   ├── asr.md
│   └── ...
├── dev/                    # 한국어 개발자 문서
│   ├── architecture.md
│   └── ...
├── en/                     # 영어 문서 (한국어 구조 미러)
│   ├── guide/
│   ├── config/
│   └── dev/
└── index.md                # 한국어 홈
```## ✍️ 기여 문서

### 새 페이지 추가하기

1. 해당 디렉토리에 Markdown 파일 생성
2. **Frontmatter SEO 최적화 추가** (중요!):

```markdown
---
title: 페이지 제목 - VideoCaptioner
description: 페이지 설명, 키워드 포함
head:
  - - meta
    - name: keywords
      content: 키워드1,키워드2,키워드3
---

# 페이지 제목

내용...
```

3. `.vitepress/config.mts`의 `sidebar`에 링크 추가
4. PR 제출

### 기존 페이지 편집하기

Markdown 파일을 직접 편집하면 됩니다, 지원 사항:

- **Markdown 확장 문법**: 표, 코드 블록, 팝업 등
- **Vue 컴포넌트**: Markdown 내에서 Vue 컴포넌트 사용 가능
- **사용자 정의 컨테이너**: `::: tip`, `::: warning`, `::: danger`

예시:

```md
::: tip 팁
이것은 팁 박스입니다
:::

::: warning 주의
이것은 경고 박스입니다
:::

::: danger 위험
이것은 위험 경고 박스입니다
:::
```

### 문서 규칙

- **파일 이름**: 소문자와 하이픈 사용 (예: `getting-started.md`)
- **제목**: 명확한 계층 구조 사용 (# → ## → ###)
- **코드 블록**: 언어 타입을 표시하여 문법 강조 활성화
- **이미지**: `public/` 디렉토리에 두고, `/image.png`로 참조
- **링크**: 내부 링크는 상대 경로 사용 (예: `/guide/getting-started`)
- **SEO**: 각 페이지에 title, description 및 keywords 추가## 🔍 SEO 최적화

이 문서 시스템은 포괄적인 SEO 최적화를 완료하였습니다. 자세한 내용은 [SEO_OPTIMIZATION.md](../SEO_OPTIMIZATION.md)를 확인하세요.

### 구현된 SEO 기능

✅ **기본 SEO**

- Title 태그 최적화
- Meta Description 및 Keywords
- Open Graph(소셜 미디어 카드)
- Twitter Card
- JSON-LD 구조화 데이터
- Sitemap 자동 생성
- robots.txt
- Canonical URL

✅ **기술 SEO**

- 반응형 디자인
- Clean URLs
- 빠른 로딩(Vite 최적화)
- HTTPS(GitHub Pages)

### 검색 엔진에 제출

배포 후 수동으로 검색 엔진에 제출해야 합니다:

1. **Google Search Console**
   - https://search.google.com/search-console 방문
   - 웹사이트 추가 및 검증
   - sitemap 제출: `https://weifeng2333.github.io/VideoCaptioner/sitemap.xml`

2. **Bing Webmaster Tools**
   - https://www.bing.com/webmasters 방문
   - 웹사이트 추가 및 검증
   - sitemap 제출

3. **바이두 웹마스터 플랫폼**
   - https://ziyuan.baidu.com/ 방문
   - 웹사이트 추가 및 검증
   - sitemap 제출

### SEO 검사 도구

- [Google PageSpeed Insights](https://pagespeed.web.dev/)
- [Google Rich Results Test](https://search.google.com/test/rich-results)
- [Open Graph Debugger](https://developers.facebook.com/tools/debug/)
- [Twitter Card Validator](https://cards-dev.twitter.com/validator)## 🌐 다국어 지원

문서 지원 중영 이중언어：

- **중국어**：`docs/` 루트 디렉토리
- **영어**：`docs/en/` 디렉토리

새 언어 추가:

1. `docs/` 아래에 언어 디렉토리 생성 (예: `ja/`)
2. `.vitepress/config.mts` 파일에 locale 설정 추가
3. 문서 구조 복사하고 내용 번역## 🔧 기술 스택

- **VitePress**: Vite 기반의 정적 사이트 생성기
- **Vue 3**: 컴포넌트 기반 개발
- **TypeScript**: 타입 안전한 구성## 📝 문서 업데이트

문서 업데이트는 GitHub Actions 배포를 자동으로 트리거합니다:

1. `docs/` 디렉토리에서 문서 수정 사항 제출
2. `master` 또는 `main` 브랜치에 푸시
3. GitHub Actions가 자동으로 빌드 및 배포
4. 약 2-3분 후 업데이트가 적용됩니다## ❓ 자주 묻는 질문

### 로컬 개발 시 스타일이 보이지 않나요?

의존성이 설치되어 있는지 확인하세요:

```bash
npm install
```

### 사용자 정의 스타일을 어떻게 추가하나요?

`docs/.vitepress/theme/` 디렉토리에 사용자 정의 테마를 생성하세요:

```ts
// docs/.vitepress/theme/index.ts
import DefaultTheme from "vitepress/theme";
import "./custom.css";

export default DefaultTheme;
```

### 검색 기능은 어떻게 설정하나요?

VitePress는 기본적으로 로컬 검색을 제공하며, `config.mts`에 이미 설정되어 있습니다.

### 이미지를 어떻게 최적화하나요?

1. 이미지 압축 도구 사용 (예: TinyPNG)
2. WebP 형식 사용 고려
3. `loading="lazy"` 속성 추가

### Google Analytics를 어떻게 추가하나요?

`config.mts`의 `head`에 다음을 추가하세요:

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

VitePress 사용 방법에 대한 자세한 내용은 [공식 문서](https://vitepress.dev/)를 참조하세요.

SEO 최적화에 대한 더 많은 세부정보는 [SEO_OPTIMIZATION.md](../SEO_OPTIMIZATION.md)를 확인하세요.