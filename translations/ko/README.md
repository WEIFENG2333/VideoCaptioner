<div align="center">
  <img src="./docs/images/logo.png" alt="VideoCaptioner Logo" width="100">
  <h1>VideoCaptioner</h1>
  <p>대형 언어 모델 기반의 비디오 자막 처리 도구 — 음성 인식, 자막 최적화, 번역, 비디오 합성을 위한 원스톱 솔루션</p>

  [온라인 문서](https://weifeng2333.github.io/VideoCaptioner/) · [CLI 사용](#cli-명령행) · [GUI 데스크탑 버전](#gui-데스크탑버전) · [Claude 코드 스킬](#claude-code-skill)
</div>

## 설치

```bash
pip install videocaptioner          # CLI만 설치 (경량, GUI 의존성 없음)
pip install videocaptioner[gui]     # CLI + GUI 데스크탑 버전 설치
```

무료 기능(미剪 음성 인식, 빙/구글 번역) **설정 없이 설치 후 즉시 사용 가능**.

## CLI 명령행

```bash
# 음성 전사(무료, API Key 필요 없음)
videocaptioner transcribe video.mp4 --asr bijian

# 자막 번역(무료 빙 번역)
videocaptioner subtitle input.srt --translator bing --target-language en

# 전체 프로세스: 전사 → 최적화 → 번역 → 합성
videocaptioner process video.mp4 --target-language ja

# 자막을 비디오에 통합
videocaptioner synthesize video.mp4 -s subtitle.srt

# 온라인 비디오 다운로드
videocaptioner download "https://youtube.com/watch?v=xxx"
```

LLM 기능(자막 최적화, 대형 모델 번역)이 필요할 경우, API Key를 설정합니다:

```bash
videocaptioner config set llm.api_key <your-key>
videocaptioner config set llm.api_base https://api.openai.com/v1
videocaptioner config set llm.model gpt-4o-mini
```

설정 우선순위: `명령행 인자 > 환경 변수 (VIDEOCAPTIONER_*) > 설정 파일 > 기본값`입니다. 현재 설정을 보려면 `videocaptioner config show`를 실행하세요.

<details>
<summary>모든 CLI 명령 요약</summary>

| 명령 | 설명 |
|------|------|
| `transcribe` | 음성을 자막으로 전사. 엔진: `faster-whisper`, `whisper-api`, `bijian`(무료), `jianying`(무료), `whisper-cpp` |
| `subtitle` | 자막 최적화/번역. 번역 서비스: `llm`, `bing`(무료), `google`(무료) |
| `synthesize` | 자막을 비디오에 통합(소프트 자막/하드 자막) |
| `process` | 전체 프로세스 처리 |
| `download` | YouTube, Bilibili 등 플랫폼의 비디오 다운로드 |
| `config` | 설정 관리(`show`, `set`, `get`, `path`, `init`) |

`videocaptioner <명령> --help`를 실행하여 전체 매개변수를 확인하세요. 전체 CLI 문서는 [docs/cli.md](docs/cli.md)를 참조하세요.

</details>

## GUI 데스크탑 버전

```bash
pip install videocaptioner[gui]
videocaptioner                      # 매개변수 없이 실행 시 자동으로 데스크탑 버전 열기
```

<details>
<summary>기타 설치 방법: Windows 설치 패키지 / macOS 원클릭 스크립트</summary>

**Windows**: [Release](https://github.com/WEIFENG2333/VideoCaptioner/releases)에서 설치 패키지를 다운로드하여 설치

**macOS**:
```bash
curl -fsSL https://raw.githubusercontent.com/WEIFENG2333/VideoCaptioner/master/scripts/run.sh | bash
```

</details>

![페이지 미리보기](https://h1.appinn.me/file/1731487410170_preview1.png)
![페이지 미리보기](https://h1.appinn.me/file/1731487410832_preview2.png)

## LLM API 설정

LLM은 자막 최적화와 대형 모델 번역을 위해서만 사용되며, 무료 기능(미剪 인식, 빙 번역)은 설정이 필요하지 않습니다.

모든 OpenAI 호환 인터페이스를 지원하는 서비스 제공업체:

| 서비스 제공업체 | 웹사이트 |
|------------------|-----------|
| **VideoCaptioner 중계소** | [api.videocaptioner.cn](https://api.videocaptioner.cn) — 높은 동시 처리량, 가성비 우수, GPT/Claude/Gemini 등 지원 |
| SiliconCloud | [cloud.siliconflow.cn](https://cloud.siliconflow.cn/i/HF95kaoz) |
| DeepSeek | [platform.deepseek.com](https://platform.deepseek.com) |

소프트웨어 설정 또는 CLI에서 API Base URL 및 API Key를 입력하면 됩니다. [상세 설정 가이드](https://weifeng2333.github.io/VideoCaptioner/config/llm)

## Claude 코드 스킬

본 프로젝트는 [Claude 코드 스킬](https://code.claude.com/docs/en/skills.md)을 제공하여 AI 프로그래밍 도우미가 VideoCaptioner를 직접 호출하여 비디오를 처리할 수 있게 합니다.

Claude 코드에 설치하기:

```bash
mkdir -p ~/.claude/skills/videocaptioner
cp skills/SKILL.md ~/.claude/skills/videocaptioner/SKILL.md
```

그런 다음 Claude 코드에 입력하면 됩니다: `/videocaptioner transcribe video.mp4 --asr bijian`.

## 작업 원리

```
오디오 비디오 입력 → 음성 인식 → 자막 절단 → LLM 최적화 → 번역 → 비디오 합성
```

- 단어 수준 타임스탬프 + VAD 음성 활동 감지, 높은 인식 정확도
- LLM 의미 이해로 인한 자연스러운 자막 독서 경험
- 맥락 인식 번역, 반영 최적화 메커니즘 지원
- 배치 동시 처리, 높은 효율성

## 개발

```bash
git clone https://github.com/WEIFENG2333/VideoCaptioner.git
cd VideoCaptioner
uv sync && uv run videocaptioner     # GUI 실행
uv run videocaptioner --help          # CLI 실행
uv run pyright                        # 타입 검사
uv run pytest tests/test_cli/ -q      # 테스트 실행
```

## 라이선스

[GPL-3.0](LICENSE)

[![Star History Chart](https://api.star-history.com/svg?repos=WEIFENG2333/VideoCaptioner&type=Date)](https://star-history.com/#WEIFENG2333/VideoCaptioner&Date)