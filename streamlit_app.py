import logging
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from app.core.bk_asr.asr_data import ASRData
from app.core.bk_asr.bcut import BcutASR
from app.core.subtitle_processor.optimize import SubtitleOptimizer
from app.core.subtitle_processor.translate import TranslatorFactory, TranslatorType
from app.core.utils.video_utils import video2audio

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# 设置环境变量 - 安全处理可能为None的值
openai_base_url = os.getenv("OPENAI_BASE_URL")
openai_api_key = os.getenv("OPENAI_API_KEY")

if openai_base_url:
    os.environ["OPENAI_BASE_URL"] = openai_base_url
if openai_api_key:
    os.environ["OPENAI_API_KEY"] = openai_api_key

# 设置自定义样式
st.set_page_config(
    page_title="卡卡字幕助手",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)


def create_temp_dir():
    """创建临时目录用于存储处理文件"""
    temp_dir = Path("temp")
    temp_dir.mkdir(exist_ok=True)
    return temp_dir


def format_time(milliseconds):
    """将毫秒转换为时:分:秒.毫秒格式"""
    total_seconds = milliseconds / 1000
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    ms = int((total_seconds * 1000) % 1000)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"
    else:
        return f"{minutes:02d}:{seconds:02d}.{ms:03d}"


def format_duration(milliseconds):
    """将毫秒转换为时分秒的显示格式"""
    total_seconds = milliseconds / 1000
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)

    if hours > 0:
        return f"{hours:02d}时{minutes:02d}分{seconds:02d}秒"
    elif minutes > 0:
        return f"{minutes:02d}分{seconds:02d}秒"
    else:
        return f"{seconds:02d}秒"


def asr_page():
    st.title("🎯 ASR 视频字幕识别")
    st.markdown("---")

    # 初始化session state
    if "srt_content" not in st.session_state:
        st.session_state.srt_content = None
    if "subtitle_path" not in st.session_state:
        st.session_state.subtitle_path = None
    if "asr_data" not in st.session_state:
        st.session_state.asr_data = None
    if "translated_asr_data" not in st.session_state:
        st.session_state.translated_asr_data = None

    temp_dir = create_temp_dir()

    # 创建两列布局
    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### 📺 视频预览")
        video_file = st.file_uploader(
            label="上传视频文件",
            type=["mp4", "mov", "avi", "mkv", "flv"],
            key="asr_video",
            accept_multiple_files=False,
            label_visibility="collapsed",
            help="支持的视频格式: MP4, MOV, AVI, MKV, WMV, FLV, WebM, M4V",
        )
        video_placeholder = st.empty()

        if video_file:
            video_path = temp_dir / video_file.name
            # 检查文件是否已存在，避免重复写入
            if not video_path.exists():
                with open(video_path, "wb") as f:
                    f.write(video_file.getbuffer())
                logger.info(f"视频文件已保存到: {video_path}")

            video_placeholder.video(
                video_file,
                subtitles=(
                    st.session_state.subtitle_path
                    if st.session_state.subtitle_path
                    else None
                ),
            )

    with col2:
        st.markdown("### 🎯 操作面板")
        if video_file is not None:
            st.success("✅ 视频上传成功！")

            if st.button("🚀 开始识别", use_container_width=True):
                with st.spinner("⏳ 正在处理中..."):
                    try:
                        logger.info(f"开始处理视频文件: {video_file.name}")
                        # 转换为音频
                        audio_path = temp_dir / f"{video_path.stem}.wav"
                        logger.info(f"开始将视频转换为音频: {audio_path}")
                        is_success = video2audio(str(video_path), str(audio_path))

                        if not is_success:
                            logger.error("音频转换失败")
                            st.error("音频转换失败")
                            return

                        logger.info("开始ASR识别")
                        # 使用BcutASR进行识别
                        asr = BcutASR(str(audio_path))
                        asr_data = asr.run()
                        logger.info("ASR识别完成")

                        st.session_state.srt_content = asr_data.to_srt()
                        st.session_state.asr_data = asr_data

                        # 保存字幕文件
                        subtitle_path = temp_dir / f"{video_path.stem}.srt"
                        logger.info(f"保存字幕文件到: {subtitle_path}")
                        with open(subtitle_path, "w", encoding="utf-8") as f:
                            f.write(st.session_state.srt_content)

                        st.session_state.subtitle_path = str(subtitle_path)

                        # 使用之前创建的容器更新视频显示
                        video_placeholder.video(
                            video_file, subtitles=st.session_state.subtitle_path
                        )

                        logger.info("字幕识别全流程完成")
                        st.success("✨ 识别完成！")

                        # 显示字幕统计信息
                        if st.session_state.asr_data:
                            st.markdown("### 📊 字幕统计")
                            segments = st.session_state.asr_data.segments
                            total_segments = len(segments)
                            total_duration = sum(
                                seg.end_time - seg.start_time for seg in segments
                            )
                            total_chars = sum(len(seg.text.strip()) for seg in segments)
                            avg_segment_duration = (
                                total_duration / total_segments
                                if total_segments > 0
                                else 0
                            )

                            col_stats1, col_stats2, col_stats3 = st.columns(3)
                            with col_stats1:
                                st.metric("字幕段落数", f"{total_segments} 段")
                            with col_stats2:
                                st.metric("总时长", format_duration(total_duration))
                            with col_stats3:
                                st.metric("总字数", f"{total_chars} 字")

                    except Exception as e:
                        logger.exception(f"处理过程中出现错误: {str(e)}")
                        st.error(f"处理过程中出现错误: {str(e)}")
                    finally:
                        # 清理音频文件
                        if "audio_path" in locals() and audio_path.exists():
                            logger.info(f"清理临时音频文件: {audio_path}")
                            os.remove(audio_path)

            # 如果有字幕内容，显示预览和下载区域
            if st.session_state.srt_content and st.session_state.asr_data:
                st.markdown("---")
                # 创建字幕预览区域
                with st.expander("📝 字幕预览", expanded=True):
                    # 添加搜索框和过滤选项
                    search_term = st.text_input(
                        "🔍 搜索字幕内容",
                        key="subtitle_search",
                        placeholder="输入关键词进行搜索...",
                    )

                    # 将字幕内容转换为DataFrame格式显示
                    segments = st.session_state.asr_data.segments
                    df = pd.DataFrame(
                        [
                            {
                                "序号": i + 1,
                                "开始时间": format_time(seg.start_time),
                                "结束时间": format_time(seg.end_time),
                                "时长(秒)": round(
                                    (seg.end_time - seg.start_time) / 1000, 1
                                ),
                                "字幕文本": seg.text.strip(),
                            }
                            for i, seg in enumerate(segments)
                        ]
                    )

                    # 应用过滤条件
                    if search_term:
                        df = df[
                            df["字幕文本"].str.contains(
                                search_term, case=False, na=False
                            )
                        ]

                    # 使用自定义样式显示数据
                    st.dataframe(
                        df,
                        use_container_width=True,
                        height=400,
                        hide_index=True,
                        column_config={
                            "序号": st.column_config.NumberColumn(
                                "序号", help="字幕段落序号", format="%d", width="small"
                            ),
                            "开始时间": st.column_config.TextColumn(
                                "开始时间", help="字幕开始时间", width="small"
                            ),
                            "结束时间": st.column_config.TextColumn(
                                "结束时间", help="字幕结束时间", width="small"
                            ),
                            "时长(秒)": st.column_config.NumberColumn(
                                "时长(秒)",
                                help="字幕持续时间",
                                format="%.1f",
                                width="small",
                            ),
                            "字幕文本": st.column_config.TextColumn(
                                "字幕文本", help="识别出的字幕内容", width="medium"
                            ),
                        },
                    )

                # 下载按钮区域
                st.markdown("### 💾 导出字幕")
                st.download_button(
                    label="📥 下载 SRT 字幕文件",
                    data=st.session_state.srt_content,
                    file_name=f"{video_file.name.rsplit('.', 1)[0]}.srt",
                    mime="text/plain",
                    use_container_width=True,
                )


def translation_page():
    st.title("🌏 字幕翻译")
    st.markdown("---")

    # 初始化session state
    if "translated_content" not in st.session_state:
        st.session_state.translated_content = None
    if "current_subtitle_file" not in st.session_state:
        st.session_state.current_subtitle_file = None
    if "translation_done" not in st.session_state:
        st.session_state.translation_done = False

    temp_dir = create_temp_dir()

    # 使用容器布局
    with st.container():
        subtitle_file = st.file_uploader(
            label="上传字幕文件",
            type=["srt", "ass", "vtt"],
            key="trans_subtitle",
            label_visibility="visible",
            help="支持 SRT、ASS、VTT 格式的字幕文件",
        )

        target_language = st.selectbox(
            "选择要翻译成的目标语言",
            [
                "英语",
                "简体中文",
                "繁体中文",
                "日本語",
                "韩语",
                "粤语",
                "法语",
                "德语",
                "西班牙语",
                "俄语",
                "葡萄牙语",
                "土耳其语",
            ],
            index=0,
            help="选择要将字幕翻译成的目标语言",
        )

    # 如果上传了新文件，清理旧文件和状态
    if (
        subtitle_file is not None
        and subtitle_file != st.session_state.current_subtitle_file
    ):
        if st.session_state.current_subtitle_file:
            old_path = temp_dir / st.session_state.current_subtitle_file.name
            if os.path.exists(old_path):
                os.remove(old_path)
        st.session_state.current_subtitle_file = subtitle_file
        st.session_state.translation_done = False
        st.session_state.translated_content = None
        st.session_state.translated_asr_data = None

    if subtitle_file is not None:
        subtitle_path = temp_dir / subtitle_file.name
        with open(subtitle_path, "wb") as f:
            f.write(subtitle_file.getbuffer())

        # 显示原始字幕预览
        with st.expander("原始字幕预览"):
            asr_data = ASRData.from_subtitle_file(str(subtitle_path))
            st.session_state.asr_data = asr_data
            subtitle_json = st.session_state.asr_data.to_json()
            df = pd.DataFrame(
                [
                    {
                        "开始时间": format_time(v["start_time"]),
                        "结束时间": format_time(v["end_time"]),
                        "原文": v["original_subtitle"],
                        "译文": v["translated_subtitle"],
                    }
                    for k, v in subtitle_json.items()
                ]
            )

            st.dataframe(df, use_container_width=True)

        # 开始翻译按钮
        if st.button("开始翻译", use_container_width=True):
            with st.spinner("正在翻译中..."):
                try:
                    logger.info(f"开始翻译字幕文件: {subtitle_file.name}")
                    # 读取字幕文件
                    asr_data = ASRData.from_subtitle_file(str(subtitle_path))

                    logger.info(f"目标语言: {target_language}")
                    # 创建优化器实例（用于翻译）
                    translator = TranslatorFactory.create_translator(
                        translator_type=TranslatorType.BING,
                        target_language=target_language,
                    )

                    # 准备字幕数据
                    subtitle_json = {
                        str(k): v["original_subtitle"]
                        for k, v in asr_data.to_json().items()
                    }
                    logger.info(f"待翻译字幕段落数: {len(subtitle_json)}")

                    # 执行翻译
                    logger.info("开始多线程翻译")
                    asr_data = translator.translate_subtitle(asr_data)
                    logger.info("翻译完成")

                    # 保存翻译后的字幕
                    st.session_state.translated_content = asr_data.to_srt()
                    st.session_state.translated_asr_data = asr_data
                    st.session_state.translation_done = True

                    logger.info("字幕翻译全流程完成")
                    st.success("翻译完成！")

                except Exception as e:
                    logger.exception(f"翻译过程中出现错误: {str(e)}")
                    st.error(f"翻译过程中出现错误: {str(e)}")

        # 如果翻译完成，显示结果和下载按钮
        if (
            st.session_state.translation_done
            and st.session_state.translated_asr_data is not None
        ):
            # 显示翻译后的预览
            st.subheader("翻译结果预览")
            subtitle_json = st.session_state.translated_asr_data.to_json()
            df = pd.DataFrame(
                [
                    {
                        "开始时间": format_time(v["start_time"]),
                        "结束时间": format_time(v["end_time"]),
                        "原文": v["original_subtitle"],
                        "译文": v["translated_subtitle"],
                    }
                    for k, v in subtitle_json.items()
                ]
            )

            st.dataframe(df, use_container_width=True)

            # 提供下载按钮
            st.download_button(
                label="下载翻译后的字幕",
                data=st.session_state.translated_content,
                file_name=f"translated_{subtitle_file.name}",
                mime="text/plain",
                use_container_width=True,
            )


def main():
    logger.info("应用程序启动")
    # 侧边栏设计
    st.sidebar.markdown(
        """
    # 🎥 卡卡字幕助手
    ---
    ### 🛠️ 功能列表
    """
    )

    # 创建美化后的导航选项
    page = st.sidebar.radio("", options=["🎯 ASR 字幕识别", "🌏 字幕翻译"], index=0)

    logger.info(f"用户选择页面: {page}")
    # 根据选择显示不同的页面
    if "ASR" in page:
        asr_page()
    else:
        translation_page()


if __name__ == "__main__":
    main()
