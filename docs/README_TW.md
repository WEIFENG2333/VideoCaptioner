<div align="center">
  <img src="./images/logo.png"alt="VideoCaptioner Logo" width="100">
  <p>卡卡字幕助手</p>
  <h1>VideoCaptioner</h1>
  <p>一款基於大語言模型(LLM)的影片字幕處理助手，支援語音識別、字幕斷句、最佳化、翻譯全流程處理</p>

  [简体中文](./README.md) / 正體中文 / [English](./docs/README_EN.md)
  
</div>

## 📖 項目介紹

卡卡字幕助手（VideoCaptioner）操作簡單且無需高配置，支援網路呼叫和本機離線（支援呼叫GPU）兩種方式進行語音識別，利用可用透過大語言模型進行字幕智慧斷句、校正、翻譯，字幕影片全流程一鍵處理！為影片配上效果驚艷的字幕。

- 🎯 無需GPU即可使用強大的語音識別引擎，生成精準字幕
- ✂️ 基於 LLM 的智慧分割與斷句，字幕閱讀更自然流暢
- 🔄 AI字幕多執行緒最佳化與翻譯，調整字幕格式、表達更道地專業
- 🎬 支援批次影片字幕合成，提升處理效率
- 📝 直觀的字幕編輯查看介面，支援即時預覽和快捷編輯
- 🤖 消耗模型 Token 少，且內建基礎 LLM 模型，保證開箱即用

## 📸 介面預覽

<div align="center">
  <img src="https://h1.appinn.me/file/1731487405884_main.png" alt="軟體介面預覽" width="90%" style="border-radius: 5px;">
</div>

![頁面預覽](https://h1.appinn.me/file/1731487410170_preview1.png)
![頁面預覽](https://h1.appinn.me/file/1731487410832_preview2.png)


## 🧪 測試

全流程處理一個14分鐘1080P的 [B站英文 TED 影片](https://www.bilibili.com/video/BV1jT411X7Dz)，呼叫本機 Whisper 模型進行語音識別，使用 `gpt-4o-mini` 模型最佳化和翻譯為中文，總共消耗時間約 **4 分鐘**。

 近後臺計算，模型最佳化和翻譯消耗費用不足 NT$ 0.5（以官方價格為計算）

具體字幕和影片合成的效果的測試結果圖片，請參考 [TED影片測試](./docs/test.md)


## 🚀 快速開始

### Windows 使用者

軟體較為輕量，打包大小不足 60M,已整合所有必要環境，下載後可直接執行。

1. 從 [Release](https://github.com/WEIFENG2333/VideoCaptioner/releases) 頁面下載最新版本的可處理程序。

2. 打開安裝包進行安裝

3. （可選）LLM API 配置，選擇是否啟用字幕最佳化或者字幕翻譯

4. 拖曳影片檔案到軟體視窗，即可全自動處理

提示：每一個步驟均支援單獨處理，均支援文件拖曳。

<details>
<summary>MacOS 使用者</summary>

由於本人缺少 Mac，所以沒辦法測試和打包，暫無法提供 MacOS 的可處理程序。

Mac 使用者請自行使用下載原始碼和安裝 python 依賴執行。（本機 Whisper 功能暫不支援 MacOS）

1. 安裝 ffmpeg 和 Aria2 下載工具
```bash
brew install ffmpeg
brew install aria2
```

2. 複製項目
```bash
git clone https://github.com/WEIFENG2333/VideoCaptioner.git
```

3. 安裝依賴
```bash
pip install -r requirements.txt
```

4. 執行程式
```bash
python main.py
```
</details>

## ✨ 主要功能

軟體充分利用大語言模型(LLM)在理解上下文方面的優勢，對語音識別生成的字幕進一步處理。有效修正錯別字、統一專業術語，讓字幕內容更加準確連貫，為使用者帶來出色的觀看體驗！

#### 1. 多平臺影片下載與處理
- 支援主流影片平臺（Youtube、Bilibili等）
- 自動提取影片原有字幕處理

#### 2. 專業的語音識別引擎
- 提供多種介面線上識別，效果媲美剪映（免費、高速）
- 支援本機Whisper模型（保護隱私、可離線）

#### 3. 字幕智慧糾錯
- 自動最佳化專業術語、程式碼片段和數學公式格式
- 上下文進行斷句最佳化，提升閱讀體驗
- 支援文稿提示，使用原有文稿或者相關提示最佳化字幕斷句

#### 4. 高品質字幕翻譯
- 結合上下文的智慧翻譯，確保譯文兼顧全文
- 透過Prompt指導大模型反思翻譯，提升翻譯品質
- 使用序列模糊匹配演算法、保證時間軸完全一致

#### 5. 字幕樣式調整
- 豐富的字幕樣式模板（科普風、新聞風、番劇風等等）
- 多種格式字幕影片（SRT、ASS、VTT、TXT）


## ⚙️ 基本配置

### 1. LLM API 配置說明 （可選）

| 配置項 | 說明 |
|--------|------|
| 內建模型 | 軟體內建基礎大語言模型（`gpt-4o-mini`），無需配置即可使用 |
| API支援 | 支援標準 OpenAI API 格式。相容 [SiliconCloud](https://cloud.siliconflow.cn/i/HF95kaoz)、[DeepSeek](https://platform.deepseek.com/) 、 [Ollama](https://ollama.com/blog/openai-compatibility) 等。<br>配置方法請參考[配置檔案](./docs/llm_config.md) |

推薦模型: 追求更高品質可選用 `Claude-3.5-sonnet` 或 `gpt-4o`


### 2. 本機 Whisper 語音識別配置（需軟體內下載）

| 模型 | 磁碟空間 | 記憶體占用 | 說明 |
|------|----------|----------|------|
| Tiny | 75 MiB | ~273 MB | 轉錄很一般，僅用於測試 |
| Small | 466 MiB | ~852 MB | 英文識別效果已經不錯 |
| Medium | 1.5 GiB | ~2.1 GB | 中文識別建議至少使用此版本 |
| Large-v1/v2 | 2.9 GiB | ~3.9 GB | 效果好，配置允許情況推薦使用 |
| Large-v3 | 2.9 GiB | ~3.9 GB | 社群回饋可能會出現幻覺/字幕重複問題（實際不支援） |

註：以上模型支援GPU也支援核顯呼叫。


### 3. 文稿匹配

- 在"字幕最佳化與翻譯"頁面，包含"文稿匹配"選項，支援以下**一種或者多種**內容，輔助校正字幕和翻譯:

| 類型 | 說明 | 填寫範例 |
|------|------|------|
| 術語表 | 專業術語、人名、特定詞語的修正對照表 | 機器學習->Machine Learning<br>馬斯克->Elon Musk<br>打call -> 應援<br>圖靈斑圖<br>公車悖論 |
| 原字幕文稿 | 影片的原有文稿或相關內容 | 完整的演講稿、課程講義等 |
| 修正要求 | 內容相關的具體修正要求 | 統一人稱代詞、規範專業術語等<br>填寫**內容相關**的要求即可，[範例參考](https://github.com/WEIFENG2333/VideoCaptioner/issues/59#issuecomment-2495849752) |

- 如果需要文稿進行字幕最佳化輔助，全流程處理時，先填寫文稿資訊，再進行開始任務處理
- 注意: 使用上下文參數量不高的小型LLM模型時，建議控制文稿內容在1千字內，如果使用上下文較大的模型，則可以適當增加文稿內容。


### 4. 語音識別介面說明

| 介面名稱 | 支援語言 | 執行方式 | 說明 |
|---------|---------|---------|------|
| B介面 | 僅支援中文、英文 | 線上 | 免費、速度較快 |
| J介面 | 僅支援中文、英文 | 線上 | 免費、速度較快 |
| Whisper | 中文、日語、韓語、英文等 96 種語言，外語效果較好 | 本機 | 需要下載轉錄模型<br>中文建議medium以上模型<br>英文等使用較小模型即可達到不錯效果。 |

### 5. Cookie 配置說明

但你需要URL下載功能時，如果遇到以下情況:
1. 下載的影片需要登入資訊
2. 只能下載較低解析度的影片
3. 網路條件較差時需要驗證

- 請參考 [Cookie 配置說明](./docs/get_cookies.md) 獲取Cookie資訊，並將cookies.txt文件放置到軟體的 `AppData` 目錄下，即可正常下載高品質影片。

## 💡 軟體流程介紹

程式簡單的處理流程如下:
```
語音識別 -> 字幕斷句 -> 字幕最佳化翻譯(可選) -> 字幕影片合成
```

安裝軟體的主要目錄結構說明如下：
```
VideoCaptioner/
├── runtime/                    # 執行環境目錄（不用更改）
├── resources/               # 軟體資源文件目錄（介面、圖示等,不用更改）
├── work-dir/               # 工作目錄，處理完成的影片和字幕文件儲存在這裡
├── AppData/                    # 應用資料目錄
    ├── cache/              # 快取目錄，臨時資料
    ├── models/              # 存放 Whisper 模型文件
    ├── logs/               # 日誌目錄，記錄軟體執行狀態
    ├── settings.json          # 儲存使用者設定
    └──  cookies.txt           # 影片平臺的 cookie 資訊
└── VideoCaptioner.exe      # 主程式執行文件
```

## 📝 說明

1. 字幕斷句的品質對觀看體驗至關重要。為此我開發了 [SubtitleSpliter](https://github.com/WEIFENG2333/SubtitleSpliter)，它能將逐字字幕智慧重組為符合自然語言習慣的段落，並與影片畫面完美同步。

2. 在處理過程中，僅向大語言模型發送純文字內容，不包含時間軸資訊，這大大降低了處理開銷。

3. 在翻譯環節，我們採用吳恩達提出的"翻譯-反思-翻譯"方法論。這種疊代最佳化的方式不僅確保了翻譯的準確性。

## 🤝 貢獻指南

作者是一名大三學生，個人能力和項目都還有許多不足，項目也在不斷完善中，如果在使用過程遇到的Bug，歡迎提交 [Issue](https://github.com/WEIFENG2333/VideoCaptioner/issues) 和 Pull Request 幫助改進項目。