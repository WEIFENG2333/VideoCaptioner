<div align="center">
  <img src="./docs/images/logo.png" alt="VideoCaptioner Logo" width="100">
  <h1>VideoCaptioner</h1>
  <p>大規模言語モデルに基づく動画字幕処理ツール — 音声認識、字幕最適化、翻訳、動画合成のワンストップ処理</p>

  [オンラインドキュメント](https://weifeng2333.github.io/VideoCaptioner/) · [CLI 使用法](#cli-コマンドライン) · [GUI デスクトップ版](#gui-デスクトップ版) · [Claude Code Skill](#claude-code-skill)
</div>

## インストール

```bash
pip install videocaptioner          # CLI のみをインストール（軽量、GUI 依存なし）
pip install videocaptioner[gui]     # CLI + GUI デスクトップ版をインストール
```

無料機能（必剪音声認識、必応/グーグル翻訳）**は設定不要、インストールしてすぐに使えます**。

## CLI コマンドライン

```bash
# 音声転写（無料、APIキー不要）
videocaptioner transcribe video.mp4 --asr bijian

# 字幕翻訳（無料の必応翻訳）
videocaptioner subtitle input.srt --translator bing --target-language en

# 全プロセス：転写 → 最適化 → 翻訳 → 合成
videocaptioner process video.mp4 --target-language ja

# 字幕を動画に焼き付ける
videocaptioner synthesize video.mp4 -s subtitle.srt

# オンライン動画のダウンロード
videocaptioner download "https://youtube.com/watch?v=xxx"
```

LLM 機能（字幕最適化、大規模モデル翻訳）が必要な場合は、API キーを設定します：

```bash
videocaptioner config set llm.api_key <your-key>
videocaptioner config set llm.api_base https://api.openai.com/v1
videocaptioner config set llm.model gpt-4o-mini
```

設定の優先順位：`コマンドライン引数 > 環境変数 (VIDEOCAPTIONER_*) > 設定ファイル > デフォルト値`。現在の設定は `videocaptioner config show` で確認できます。

<details>
<summary>すべての CLI コマンド一覧</summary>

| コマンド | 説明 |
|------|------|
| `transcribe` | 音声を字幕に変換します。エンジン：`faster-whisper`、`whisper-api`、`bijian`（無料）、`jianying`（無料）、`whisper-cpp` |
| `subtitle` | 字幕の最適化/翻訳。翻訳サービス：`llm`、`bing`（無料）、`google`（無料） |
| `synthesize` | 字幕を動画に焼き付ける（ソフト字幕/ハード字幕） |
| `process` | 全プロセス処理 |
| `download` | YouTube、Bilibili などのプラットフォームから動画をダウンロード |
| `config` | 設定管理（`show`、`set`、`get`、`path`、`init`） |

`videocaptioner <コマンド> --help` を実行して完全なパラメータを確認できます。完全な CLI ドキュメントは [docs/cli.md](docs/cli.md) を参照してください。

</details>

## GUI デスクトップ版

```bash
pip install videocaptioner[gui]
videocaptioner                      # 引数なしでデスクトップ版を自動で開く
```

<details>
<summary>その他のインストール方法：Windows インストーラ / macOS ワンキースクリプト</summary>

**Windows**： [Release](https://github.com/WEIFENG2333/VideoCaptioner/releases) からインストーラをダウンロードしてインストール

**macOS**：
```bash
curl -fsSL https://raw.githubusercontent.com/WEIFENG2333/VideoCaptioner/master/scripts/run.sh | bash
```

</details>


<!-- <div align="center">
  <img src="https://h1.appinn.me/file/1731487405884_main.png" alt="インターフェースプレビュー" width="90%" style="border-radius: 5px;">
</div> -->

![ページプレビュー](https://h1.appinn.me/file/1731487410170_preview1.png)
![ページプレビュー](https://h1.appinn.me/file/1731487410832_preview2.png)

## LLM API 設定

LLM は字幕の最適化と大規模モデル翻訳のみに使用され、無料機能（必剪認識、必応翻訳）は設定不要です。

すべての OpenAI 互換インターフェースを持つサービスプロバイダーをサポート：

| サービスプロバイダー | 公式サイト |
|--------|------|
| **VideoCaptioner 中継所** | [api.videocaptioner.cn](https://api.videocaptioner.cn) — 高い同時接続性、コストパフォーマンスが高い、GPT/Claude/Gemini などをサポート |
| SiliconCloud | [cloud.siliconflow.cn](https://cloud.siliconflow.cn/i/HF95kaoz) |
| DeepSeek | [platform.deepseek.com](https://platform.deepseek.com) |

ソフトウェア設定または CLI で API Base URL と API Key を入力するだけです。[詳細な設定ガイド](https://weifeng2333.github.io/VideoCaptioner/config/llm)

## Claude Code Skill

本プロジェクトは、AI プログラミングアシスタントが VideoCaptioner を呼び出して動画を処理できる [Claude Code Skill](https://code.claude.com/docs/en/skills.md) を提供しています。

Claude Code にインストールするには：

```bash
mkdir -p ~/.claude/skills/videocaptioner
cp skills/SKILL.md ~/.claude/skills/videocaptioner/SKILL.md
```

その後、Claude Code で `/videocaptioner transcribe video.mp4 --asr bijian` と入力すれば、使用できます。

## 動作原理

```
音声・動画入力 → 音声認識 → 字幕分割 → LLM 最適化 → 翻訳 → 動画合成
```

- 単語レベルのタイムスタンプ + VAD 音声活動検出、高い認識精度
- LLM の意味理解に基づく文分割、字幕の読みやすい体験
- コンテキストを考慮した翻訳、反省最適化メカニズムをサポート
- バッチ並列処理、高効率

## 開発

```bash
git clone https://github.com/WEIFENG2333/VideoCaptioner.git
cd VideoCaptioner
uv sync && uv run videocaptioner     # GUI を実行
uv run videocaptioner --help          # CLI を実行
uv run pyright                        # 型チェック
uv run pytest tests/test_cli/ -q      # テストを実行
```

## ライセンス

[GPL-3.0](LICENSE)

[![スター履歴チャート](https://api.star-history.com/svg?repos=WEIFENG2333/VideoCaptioner&type=Date)](https://star-history.com/#WEIFENG2333/VideoCaptioner&Date)