<div align="center">
  <img src="./docs/images/logo.png"alt="VideoCaptioner Logo" width="100">
  <p>卡卡字幕助手macOS</p>
  <h1>VideoCaptioner on Mac</h1>
  <p>一款基于大语言模型(LLM)的视频字幕处理助手，支持语音识别、字幕断句、优化、翻译全流程处理</p>
  
</div>

**本项目为卡卡字幕助手的macOS适配项目，支持通过 Whisper CPP 实现语音识别，并利用 Apple GPU 加速（MPS）。**

⚠️ 注意：本项目不支持 Faster Whisper且已删除Fast Whisper相关选项，因为Faster Whisper的加速方式CTranslate2已不再积极更新，且目前仍然不支持MPS，在Apple Silicon上只能依赖CPU运行，为运行效率考虑已经删掉相关选项。

# 画饼

1.小饼：未来可能会发布打包的macOS应用Release。  
2.大饼：很小可能会更新WhisperKit支持，极小可能会有swift UI重新开发的原生macOS本地应用。

# 如何运行
推荐使用 conda 创建独立环境进行部署。

1. 创建并激活虚拟环境  

`conda create -n whisper-env python=3.10
conda activate whisper-env`

2. 安装依赖（使用 Homebrew）  

`brew install ffmpeg aria2 whisper-cpp`

3. 克隆仓库

打开你想储存仓库文件的文件夹，这里打开的是macOS的【文稿】文件夹  

`cd Documents`

仓库文件会被复制到上一步打开的文件夹  

`git clone https://github.com/TensorP7/VideoCaptioneronMac.git`

打开仓库文件夹  

`cd VideoCaptioneronMac`

5. 运行主程序

`python main.py`
