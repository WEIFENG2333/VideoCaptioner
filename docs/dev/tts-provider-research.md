# SiliconFlow and Gemini API Research

Date: 2026-05-24

This note records the current API surface and local connectivity tests for adding SiliconFlow and Gemini text/TTS providers to VideoCaptioner. API keys used during testing are intentionally omitted.

## Summary

| Provider | Text model tested | TTS model tested | Result |
| --- | --- | --- | --- |
| SiliconFlow | `deepseek-ai/DeepSeek-V4-Flash` | `FunAudioLLM/CosyVoice2-0.5B` | Text, TTS, and reference-audio voice cloning all succeeded |
| Gemini API | `gemini-3.5-flash` | `gemini-3.1-flash-tts-preview` | Text and single-speaker TTS succeeded |

Generated local test files:

| File | Format | Duration | Size |
| --- | --- | ---: | ---: |
| `work-dir/api-research/siliconflow_cosyvoice2_alex.mp3` | MP3, mono, 32 kHz | 4.932 s | 80,191 bytes |
| `work-dir/api-research/siliconflow_cosyvoice2_cloned_uri.mp3` | MP3, mono, 32 kHz | 4.320 s | 70,399 bytes |
| `work-dir/api-research/gemini_3_1_flash_tts_kore.wav` | WAV PCM, mono, 24 kHz | 5.760 s | 276,524 bytes |

## SiliconFlow

### Base API

Use the OpenAI-compatible API base:

```text
https://api.siliconflow.cn/v1
```

The public docs also show:

```text
https://api.siliconflow.com/v1
```

The `.cn` endpoint was used successfully in local tests.

### DeepSeek-V4-Flash

Model ID:

```text
deepseek-ai/DeepSeek-V4-Flash
```

Endpoint:

```http
POST /v1/chat/completions
```

Key documented capabilities:

| Capability | Status |
| --- | --- |
| Context window | 1049K tokens in the SiliconFlow model page |
| Max tokens | 393K in the SiliconFlow model page |
| JSON mode | Supported |
| Function/tool calling | Supported |
| Image input | Not supported |
| Embeddings/rerank/fine-tuning | Not supported for this model |
| Serverless | Supported |

Common request parameters supported by SiliconFlow chat completions:

| Parameter | Notes |
| --- | --- |
| `model` | Required |
| `messages` | Required, OpenAI-style chat messages |
| `stream` | SSE streaming |
| `max_tokens` | Output token cap |
| `temperature` | Sampling randomness |
| `top_p`, `top_k`, `min_p` | Sampling controls; `min_p` is model-limited |
| `frequency_penalty` | Repetition control |
| `stop` | Up to 4 stop sequences |
| `response_format` | JSON mode object |
| `tools` | Function calling |
| `enable_thinking`, `thinking_budget` | Documented for selected thinking models; the model page says V4-Flash has switchable reasoning modes, but the chat API reference list does not currently include V4-Flash under `enable_thinking`. Treat this as needing runtime validation before exposing in UI. |

Local connectivity test:

```json
{
  "model": "deepseek-ai/DeepSeek-V4-Flash",
  "ok": true,
  "usage": {
    "prompt_tokens": 17,
    "completion_tokens": 17,
    "total_tokens": 34
  }
}
```

### CosyVoice2 TTS

Model ID:

```text
FunAudioLLM/CosyVoice2-0.5B
```

Endpoint:

```http
POST /v1/audio/speech
```

Request parameters:

| Parameter | Type | Notes |
| --- | --- | --- |
| `model` | string | Required |
| `input` | string | Required, 1-128000 chars in API reference |
| `voice` | string | Required in API reference; can be system voice or `speech:...` cloned voice URI |
| `response_format` | enum | `mp3`, `opus`, `wav`, `pcm` |
| `sample_rate` | number | `mp3`: 32000/44100; `wav`/`pcm`: 8000/16000/24000/32000/44100; `opus`: 48000 |
| `stream` | boolean | Default true in docs |
| `speed` | float | 0.25-4.0 |
| `gain` | float | -10 to 10 dB |

System voices, using `FunAudioLLM/CosyVoice2-0.5B:<voice>`:

| Voice | Description |
| --- | --- |
| `alex` | Calm male |
| `benjamin` | Deep male |
| `charles` | Magnetic male |
| `david` | Cheerful male |
| `anna` | Calm female |
| `bella` | Passionate female |
| `claire` | Gentle female |
| `diana` | Cheerful female |

CosyVoice2-specific features from SiliconFlow docs:

| Feature | Notes |
| --- | --- |
| Cross-lingual synthesis | Chinese, English, Japanese, Korean, and Chinese dialects including Cantonese, Sichuanese, Shanghainese, Zhengzhou dialect, Changsha dialect, and Tianjin dialect |
| Emotion control | Happy, excited, sad, angry, etc. |
| Fine-grained prosody/emotion control | Via rich text or natural-language prompt |
| Prompt separator | Examples use instruction text plus `<|endofprompt|>` before spoken text |
| Reference audio | Must be under 30 seconds; recommended 8-10 seconds |
| Reference quality | Single speaker, clear articulation, stable volume/pitch/emotion, low noise/reverb |
| Reference formats | `mp3`, `wav`, `pcm`, `opus`; recommended MP3 >= 192 kbps |

Example input style:

```text
你能用高兴的情感说吗？<|endofprompt|>今天真是太开心了，马上要放假了！
```

Local TTS test:

```json
{
  "model": "FunAudioLLM/CosyVoice2-0.5B",
  "voice": "FunAudioLLM/CosyVoice2-0.5B:alex",
  "ok": true,
  "content_type": "audio/mpeg"
}
```

### SiliconFlow Voice Cloning

SiliconFlow supports two clone/reference flows.

1. Upload reference audio and reuse returned URI:

```http
POST /v1/uploads/audio/voice
```

Parameters:

| Parameter | Notes |
| --- | --- |
| `model` | `FunAudioLLM/CosyVoice2-0.5B` |
| `customName` | User-defined voice name |
| `text` | Exact transcript corresponding to the reference audio |
| `file` | Multipart file upload |
| `audio` | Alternative JSON/base64 field in `data:audio/mpeg;base64,...` form |

Response:

```json
{
  "uri": "speech:your-voice-name:xxx:xxx"
}
```

Then pass the returned `uri` as `voice` to `/audio/speech`.

2. Dynamic reference audio in one TTS call:

The SiliconFlow guide shows OpenAI SDK usage with `extra_body.references`, where each reference has `audio` and `text`. This is useful when the app should avoid storing a cloned voice URI.

Local clone-chain test:

```json
{
  "upload_reference": true,
  "tts_with_speech_uri": true
}
```

VideoCaptioner already has a partial implementation in `videocaptioner/core/tts/siliconflow.py`:

| Existing behavior | Status |
| --- | --- |
| `/audio/speech` binary output | Implemented |
| System voice selection | Implemented through `segment.voice` / `config.voice` |
| Upload reference audio | Implemented through `VoiceCloneManager.upload_voice` |
| Cache uploaded URI | Implemented |
| Dynamic `references` in a single TTS call | Not implemented |
| Exposing preset voices in UI/config | Needs integration work |

## Gemini API

### Latest text model

Official Google material says Gemini 3.5 Flash is available through the Gemini API. The DeepMind model page lists it as `Preview` and describes:

| Capability | Gemini 3.5 Flash |
| --- | --- |
| Input | Text, image, video, audio, PDF |
| Output | Text |
| Input tokens | 1M |
| Output tokens | 64K |
| Tool use | Function calling, structured output, Search as a tool, code execution |
| Best for | Everyday tasks, agentic coding, advanced reasoning, multimodal understanding, long-context understanding |

Model ID used successfully:

```text
gemini-3.5-flash
```

Endpoint:

```http
POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent
```

Local text test succeeded. The response included `thoughtsTokenCount`, so integrations should account for reasoning tokens in usage/cost reporting.

### Latest Gemini TTS model

The current Gemini TTS docs list `Gemini 3.1 Flash TTS Preview` as the newest TTS model, with this model ID:

```text
gemini-3.1-flash-tts-preview
```

Endpoint:

```http
POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-tts-preview:generateContent
```

Request structure:

```json
{
  "contents": [
    {
      "parts": [
        {
          "text": "Say cheerfully: Have a wonderful day!"
        }
      ]
    }
  ],
  "generationConfig": {
    "responseModalities": ["AUDIO"],
    "speechConfig": {
      "voiceConfig": {
        "prebuiltVoiceConfig": {
          "voiceName": "Kore"
        }
      }
    }
  }
}
```

The REST response returns base64 PCM audio at 24 kHz mono. The app needs to wrap it as WAV or convert it to the configured output format.

Supported Gemini TTS models:

| Model | Single speaker | Multi-speaker |
| --- | --- | --- |
| `gemini-3.1-flash-tts-preview` | Yes | Yes |
| `gemini-2.5-flash-preview-tts` | Yes | Yes |
| `gemini-2.5-pro-preview-tts` | Yes | Yes |

Gemini TTS voice options:

| Voice | Style |
| --- | --- |
| Zephyr | Bright |
| Puck | Upbeat |
| Charon | Informative |
| Kore | Firm |
| Fenrir | Excitable |
| Leda | Youthful |
| Orus | Firm |
| Aoede | Breezy |
| Callirrhoe | Easy-going |
| Autonoe | Bright |
| Enceladus | Breathy |
| Iapetus | Clear |
| Umbriel | Easy-going |
| Algieba | Smooth |
| Despina | Smooth |
| Erinome | Clear |
| Algenib | Gravelly |
| Rasalgethi | Informative |
| Laomedeia | Upbeat |
| Achernar | Soft |
| Alnilam | Firm |
| Schedar | Even |
| Gacrux | Mature |
| Pulcherrima | Forward |
| Achird | Friendly |
| Zubenelgenubi | Casual |
| Vindemiatrix | Gentle |
| Sadachbia | Lively |
| Sadaltager | Knowledgeable |
| Sulafat | Warm |

Gemini TTS style control:

| Control | Notes |
| --- | --- |
| Natural language prompt | Can guide style, accent, pace, and tone |
| Inline audio tags | Examples include `[excited]`, `[whispers]`, `[shouting]`, `[laughs]`, `[sighs]`, `[tired]`, `[sarcastic]` |
| Advanced prompt | Recommended sections: audio profile, scene, director's notes, transcript |
| Multi-speaker | Up to 2 speakers, each mapped to a prebuilt voice |
| Languages | Auto-detects input language; docs include Mandarin Chinese and many other languages |

Gemini TTS limitations:

| Limitation | Impact |
| --- | --- |
| Text input only, audio output only | No reference audio input for TTS |
| 32K-token TTS context window | Long transcripts must be chunked |
| No streaming | UI should show task progress, not stream playback |
| Longer output drift | Split transcripts into smaller chunks |
| Occasional audio failure / text tokens | Add retry logic |
| Prompt classifier false rejects | Use clear preamble and label the transcript |

Voice cloning status:

Gemini TTS does not expose a SiliconFlow-style upload/reference-audio voice cloning API in the current Gemini TTS docs. It supports expressive controllability and fixed prebuilt voices, but not custom voice cloning through this API.

Local TTS test:

```json
{
  "model": "gemini-3.1-flash-tts-preview",
  "voice": "Kore",
  "ok": true,
  "output": "24 kHz mono PCM wrapped as WAV"
}
```

## Integration Notes

### SiliconFlow in VideoCaptioner

SiliconFlow text models can already fit the existing OpenAI-compatible LLM client by setting:

```bash
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
OPENAI_API_KEY=<key>
```

For GUI/config integration, prefer adding a SiliconFlow preset:

| Field | Value |
| --- | --- |
| API base | `https://api.siliconflow.cn/v1` |
| Text model | `deepseek-ai/DeepSeek-V4-Flash` |
| TTS model | `FunAudioLLM/CosyVoice2-0.5B` |
| Default voice | `FunAudioLLM/CosyVoice2-0.5B:alex` or user-selected preset |

The existing `SiliconFlowTTS` implementation should be kept, with follow-up work to expose:

| UI/config item | Why |
| --- | --- |
| Preset voice dropdown | The model requires/benefits from explicit `voice` |
| Emotion/style prompt field | CosyVoice2 uses natural language + `<|endofprompt|>` |
| Reference audio file + transcript | Required for upload-based voice clone |
| Dynamic reference mode | Useful for one-off clone without saving URI |
| Speed/gain/sample rate controls | Already supported by API and `TTSConfig` |

### Gemini in VideoCaptioner

Gemini is not directly compatible with the current `OpenAI` client path used by `videocaptioner/core/llm/client.py`. It needs either:

1. a Gemini-native LLM client using `generateContent`, or
2. a provider adapter that maps VideoCaptioner messages/config into Gemini REST calls.

Gemini TTS needs a new TTS implementation because it returns base64 PCM inside JSON, not raw audio bytes from an OpenAI-compatible `/audio/speech` endpoint.

Recommended Gemini defaults:

| Use case | Model |
| --- | --- |
| Text / subtitle optimization / translation | `gemini-3.5-flash` |
| TTS | `gemini-3.1-flash-tts-preview` |
| Default TTS voice | `Kore` for firm/neutral, `Puck` for upbeat, `Achird` for friendly, `Sulafat` for warm |

Implementation considerations:

| Area | Requirement |
| --- | --- |
| Audio writing | Decode base64 PCM and wrap as WAV at 24 kHz, 16-bit, mono |
| Output conversion | Use ffmpeg/pydub if MP3/other formats are required |
| Retry | Retry transient 500s and occasional failed audio generations |
| Chunking | Split long TTS text to avoid drift after a few minutes |
| Multi-speaker | Add only if subtitle dubbing needs two-speaker dialogue; max 2 speakers |
| Voice clone | Not supported by Gemini TTS; use SiliconFlow CosyVoice2 for clone workflows |

## Sources

- SiliconFlow DeepSeek-V4-Flash model page: https://www.siliconflow.com/models/deepseek-v4-flash
- SiliconFlow chat completions API: https://docs.siliconflow.com/en/api-reference/chat-completions/chat-completions
- SiliconFlow create speech API: https://docs.siliconflow.com/en/api-reference/audio/create-speech
- SiliconFlow upload reference audio API: https://docs.siliconflow.com/en/api-reference/audio/upload-voice
- SiliconFlow TTS capability guide: https://docs.siliconflow.com/cn/userguide/capabilities/text-to-speech
- Google Gemini 3.5 announcement: https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-5/
- Google DeepMind Gemini 3.5 Flash model page: https://deepmind.google/models/gemini/flash/
- Gemini API TTS docs: https://ai.google.dev/gemini-api/docs/speech-generation
