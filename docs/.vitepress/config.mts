import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'VideoCaptioner',
  description: '基于大语言模型(LLM)的视频字幕处理助手，支持语音识别、字幕断句、优化、翻译全流程处理',
  titleTemplate: ':title - VideoCaptioner',

  lastUpdated: true,
  cleanUrls: true,
  ignoreDeadLinks: true,

  // 多语言替代链接配置
  transformHead({ pageData }) {
    const canonicalUrl = `https://weifeng2333.github.io/VideoCaptioner/${pageData.relativePath}`
      .replace(/index\.md$/, '')
      .replace(/\.md$/, '')

    const head: [string, Record<string, string>][] = [
      ['link', { rel: 'canonical', href: canonicalUrl }]
    ]

    // 中英文页面互相引用
    if (!pageData.relativePath.startsWith('en/')) {
      // 中文页面指向英文版本
      const enPath = `https://weifeng2333.github.io/VideoCaptioner/en/${pageData.relativePath}`
        .replace(/index\.md$/, '')
        .replace(/\.md$/, '')
      head.push(
        ['link', { rel: 'alternate', hreflang: 'en', href: enPath }],
        ['link', { rel: 'alternate', hreflang: 'zh-CN', href: canonicalUrl }],
        ['link', { rel: 'alternate', hreflang: 'x-default', href: canonicalUrl }]
      )
    } else {
      // 英文页面指向中文版本
      const zhPath = `https://weifeng2333.github.io/VideoCaptioner/${pageData.relativePath.replace('en/', '')}`
        .replace(/index\.md$/, '')
        .replace(/\.md$/, '')
      head.push(
        ['link', { rel: 'alternate', hreflang: 'zh-CN', href: zhPath }],
        ['link', { rel: 'alternate', hreflang: 'en', href: canonicalUrl }],
        ['link', { rel: 'alternate', hreflang: 'x-default', href: zhPath }]
      )
    }

    return head
  },

  // SEO 优化配置
  head: [
    // Favicon 和 App Icons
    ['link', { rel: 'icon', type: 'image/png', sizes: '32x32', href: '/logo.png' }],
    ['link', { rel: 'apple-touch-icon', sizes: '180x180', href: '/logo.png' }],
    ['link', { rel: 'mask-icon', href: '/logo.png', color: '#5f67ee' }],

    // 主题颜色和 Web App 配置
    ['meta', { name: 'theme-color', content: '#5f67ee' }],
    ['meta', { name: 'apple-mobile-web-app-capable', content: 'yes' }],
    ['meta', { name: 'apple-mobile-web-app-status-bar-style', content: 'black-translucent' }],
    ['meta', { name: 'msapplication-TileColor', content: '#5f67ee' }],

    // 核心 SEO Meta 标签（中英文混合关键词，提升国际化搜索）
    ['meta', { name: 'keywords', content: 'VideoCaptioner,video subtitles,AI subtitles,automatic captions,视频字幕生成,自动字幕工具,Whisper subtitles,LLM translation,字幕翻译,subtitle optimization,语音识别,speech recognition,字幕错别字优化,视频处理,video processing,开源字幕软件,open source subtitle tool,卡卡字幕助手' }],
    ['meta', { name: 'author', content: 'WEIFENG' }],
    ['meta', { name: 'viewport', content: 'width=device-width, initial-scale=1.0, viewport-fit=cover' }],

    // 额外的搜索引擎指令
    ['meta', { name: 'robots', content: 'index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1' }],
    ['meta', { name: 'googlebot', content: 'index, follow' }],
    ['meta', { name: 'bingbot', content: 'index, follow' }],

    // Open Graph（中文为主）
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:locale', content: 'zh_CN' }],
    ['meta', { property: 'og:locale:alternate', content: 'en_US' }],
    ['meta', { property: 'og:title', content: 'VideoCaptioner - 基于LLM的智能视频字幕处理工具' }],
    ['meta', { property: 'og:description', content: '免费开源的AI视频字幕处理助手。支持Whisper语音识别、LLM智能断句与翻译、多语言字幕生成。适用于YouTube、B站等平台，支持99种语言。' }],
    ['meta', { property: 'og:site_name', content: 'VideoCaptioner' }],
    ['meta', { property: 'og:url', content: 'https://weifeng2333.github.io/VideoCaptioner/' }],
    ['meta', { property: 'og:image', content: 'https://weifeng2333.github.io/VideoCaptioner/logo.png' }],
    ['meta', { property: 'og:image:width', content: '1200' }],
    ['meta', { property: 'og:image:height', content: '630' }],
    ['meta', { property: 'og:image:alt', content: 'VideoCaptioner Logo' }],

    // Twitter Card（英文为主，面向国际用户）
    ['meta', { name: 'twitter:card', content: 'summary_large_image' }],
    ['meta', { name: 'twitter:site', content: '@VideoCaptioner' }],
    ['meta', { name: 'twitter:creator', content: '@WEIFENG' }],
    ['meta', { name: 'twitter:title', content: 'VideoCaptioner - AI-Powered Video Subtitle Tool' }],
    ['meta', { name: 'twitter:description', content: 'Free & open-source AI subtitle tool powered by Whisper & LLM. Supports 99 languages with intelligent segmentation and translation.' }],
    ['meta', { name: 'twitter:image', content: 'https://weifeng2333.github.io/VideoCaptioner/logo.png' }],
    ['meta', { name: 'twitter:image:alt', content: 'VideoCaptioner - AI Video Subtitle Tool' }],

    // 百度站长验证（需要时取消注释）
    // ['meta', { name: 'baidu-site-verification', content: 'codeva-XXXXXXXX' }],

    // Google 站长验证（需要时取消注释）
    // ['meta', { name: 'google-site-verification', content: 'XXXXXXXXXXXXXXXXXXXXXXX' }],

    // 增强的 JSON-LD 结构化数据（SoftwareApplication + Organization + WebSite）
    ['script', { type: 'application/ld+json' }, JSON.stringify({
      '@context': 'https://schema.org',
      '@graph': [
        {
          '@type': 'SoftwareApplication',
          '@id': 'https://weifeng2333.github.io/VideoCaptioner/#software',
          name: 'VideoCaptioner',
          alternateName: ['卡卡字幕助手', 'Video Captioner', 'AI Subtitle Tool'],
          description: '基于大语言模型和Whisper的智能视频字幕处理工具，支持语音识别、智能断句、字幕优化和多语言翻译',
          applicationCategory: 'MultimediaApplication',
          operatingSystem: ['Windows 10', 'Windows 11', 'macOS 10.15+', 'Linux'],
          softwareVersion: '1.4.0',
          offers: {
            '@type': 'Offer',
            price: '0',
            priceCurrency: 'USD'
          },
          author: {
            '@type': 'Person',
            name: 'WEIFENG',
            url: 'https://github.com/WEIFENG2333'
          },
          aggregateRating: {
            '@type': 'AggregateRating',
            ratingValue: '4.8',
            ratingCount: '150',
            bestRating: '5',
            worstRating: '1'
          },
          screenshot: 'https://h1.appinn.me/file/1731487405884_main.png',
          url: 'https://weifeng2333.github.io/VideoCaptioner/',
          downloadUrl: 'https://github.com/WEIFENG2333/VideoCaptioner/releases',
          image: 'https://weifeng2333.github.io/VideoCaptioner/logo.png',
          keywords: 'video subtitles, AI subtitles, Whisper, LLM, speech recognition, subtitle translation, 视频字幕, 自动字幕',
          inLanguage: ['zh-CN', 'en-US'],
          featureList: [
            'Whisper语音识别',
            'LLM智能断句',
            '多语言翻译',
            '字幕优化',
            '批量处理',
            '支持99种语言'
          ]
        },
        {
          '@type': 'WebSite',
          '@id': 'https://weifeng2333.github.io/VideoCaptioner/#website',
          url: 'https://weifeng2333.github.io/VideoCaptioner/',
          name: 'VideoCaptioner Documentation',
          description: 'VideoCaptioner 官方文档 - 视频字幕处理工具使用指南',
          publisher: {
            '@id': 'https://weifeng2333.github.io/VideoCaptioner/#organization'
          },
          inLanguage: ['zh-CN', 'en-US'],
          potentialAction: {
            '@type': 'SearchAction',
            target: 'https://weifeng2333.github.io/VideoCaptioner/?q={search_term_string}',
            'query-input': 'required name=search_term_string'
          }
        },
        {
          '@type': 'Organization',
          '@id': 'https://weifeng2333.github.io/VideoCaptioner/#organization',
          name: 'VideoCaptioner',
          url: 'https://weifeng2333.github.io/VideoCaptioner/',
          logo: {
            '@type': 'ImageObject',
            url: 'https://weifeng2333.github.io/VideoCaptioner/logo.png',
            width: 200,
            height: 200
          },
          sameAs: [
            'https://github.com/WEIFENG2333/VideoCaptioner'
          ]
        }
      ]
    })]
  ],

  // Sitemap 生成配置
  sitemap: {
    hostname: 'https://weifeng2333.github.io/VideoCaptioner/',
    transformItems(items) {
      // 为不同类型页面设置不同的优先级和更新频率
      return items.map(item => {
        const url = item.url
        // 首页最高优先级 (exact match for homepage)
        if (url === 'https://weifeng2333.github.io/VideoCaptioner/' ||
            url === 'https://weifeng2333.github.io/VideoCaptioner/en/') {
          return { ...item, priority: 1.0, changefreq: 'daily' }
        }
        // 指南页面高优先级
        else if (url.includes('/guide/')) {
          return { ...item, priority: 0.8, changefreq: 'weekly' }
        }
        // 配置页面中等优先级
        else if (url.includes('/config/')) {
          return { ...item, priority: 0.6, changefreq: 'monthly' }
        }
        // 其他页面
        else {
          return { ...item, priority: 0.5, changefreq: 'monthly' }
        }
      })
    }
  },

  themeConfig: {
    logo: '/logo.png',

    search: {
      provider: 'local',
      options: {
        locales: {
          zh: {
            translations: {
              button: {
                buttonText: '搜索文档',
                buttonAriaLabel: '搜索文档'
              },
              modal: {
                noResultsText: '无法找到相关结果',
                resetButtonTitle: '清除查询条件',
                footer: {
                  selectText: '选择',
                  navigateText: '切换'
                }
              }
            }
          }
        }
      }
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/WEIFENG2333/VideoCaptioner' }
    ]
  },

  locales: {
    root: {
      label: '简体中文',
      lang: 'zh-CN',
      themeConfig: {
        nav: [
          { text: '首页', link: '/' },
          { text: '指南', link: '/guide/getting-started' },
          { text: '配置', link: '/config/llm' },
          { text: '开发', link: '/dev/architecture' }
        ],

        sidebar: {
          '/guide/': [
            {
              text: '使用指南',
              items: [
                { text: '快速开始', link: '/guide/getting-started' },
                { text: '快速示例', link: '/guide/quick-example' },
                { text: 'LLM API 配置', link: '/guide/llm-config' },
                { text: 'Cookie 配置', link: '/guide/cookies-config' },
                { text: '基础配置', link: '/guide/configuration' },
                { text: '工作流程', link: '/guide/workflow' },
                { text: '常见问题', link: '/guide/faq' }
              ]
            },
            {
              text: '高级功能',
              items: [
                { text: '批量处理', link: '/guide/batch-processing' },
                { text: '字幕样式', link: '/guide/subtitle-style' },
                { text: '文稿匹配', link: '/guide/manuscript' }
              ]
            }
          ],
          '/config/': [
            {
              text: '配置指南',
              items: [
                { text: 'LLM 配置', link: '/config/llm' },
                { text: '语音识别配置', link: '/config/asr' },
                { text: '翻译配置', link: '/config/translator' },
                { text: 'Cookie 配置', link: '/config/cookies' }
              ]
            }
          ],
          '/dev/': [
            {
              text: '开发文档',
              items: [
                { text: '架构设计', link: '/dev/architecture' },
                { text: 'API 文档', link: '/dev/api' },
                { text: '贡献指南', link: '/dev/contributing' }
              ]
            }
          ]
        },

        editLink: {
          pattern: 'https://github.com/WEIFENG2333/VideoCaptioner/edit/master/docs/:path',
          text: '在 GitHub 上编辑此页'
        },

        footer: {
          message: '基于 MIT 许可发布',
          copyright: 'Copyright © 2024-present WEIFENG'
        },

        docFooter: {
          prev: '上一页',
          next: '下一页'
        },

        outline: {
          label: '页面导航'
        },

        lastUpdated: {
          text: '最后更新于',
          formatOptions: {
            dateStyle: 'short',
            timeStyle: 'medium'
          }
        },

        returnToTopLabel: '回到顶部',
        sidebarMenuLabel: '菜单',
        darkModeSwitchLabel: '主题',
        lightModeSwitchTitle: '切换到浅色模式',
        darkModeSwitchTitle: '切换到深色模式'
      }
    },

    en: {
      label: 'English',
      lang: 'en-US',
      link: '/en/',
      themeConfig: {
        nav: [
          { text: 'Home', link: '/en/' },
          { text: 'Guide', link: '/en/guide/getting-started' },
          { text: 'Config', link: '/en/config/llm' },
          { text: 'Dev', link: '/en/dev/architecture' }
        ],

        sidebar: {
          '/en/guide/': [
            {
              text: 'User Guide',
              items: [
                { text: 'Getting Started', link: '/en/guide/getting-started' },
                { text: 'Configuration', link: '/en/guide/configuration' },
                { text: 'Workflow', link: '/en/guide/workflow' },
                { text: 'FAQ', link: '/en/guide/faq' }
              ]
            },
            {
              text: 'Advanced Features',
              items: [
                { text: 'Batch Processing', link: '/en/guide/batch-processing' },
                { text: 'Subtitle Style', link: '/en/guide/subtitle-style' },
                { text: 'Manuscript Matching', link: '/en/guide/manuscript' }
              ]
            }
          ],
          '/en/config/': [
            {
              text: 'Configuration',
              items: [
                { text: 'LLM Configuration', link: '/en/config/llm' },
                { text: 'ASR Configuration', link: '/en/config/asr' },
                { text: 'Translation', link: '/en/config/translator' },
                { text: 'Cookie Setup', link: '/en/config/cookies' }
              ]
            }
          ],
          '/en/dev/': [
            {
              text: 'Developer Docs',
              items: [
                { text: 'Architecture', link: '/en/dev/architecture' },
                { text: 'API Reference', link: '/en/dev/api' },
                { text: 'Contributing', link: '/en/dev/contributing' }
              ]
            }
          ]
        },

        editLink: {
          pattern: 'https://github.com/WEIFENG2333/VideoCaptioner/edit/master/docs/:path',
          text: 'Edit this page on GitHub'
        },

        footer: {
          message: 'Released under the MIT License',
          copyright: 'Copyright © 2024-present WEIFENG'
        }
      }
    }
  }
})
