"""media_info：ffmpeg -i stderr 解析器的单元测试（纯文本解析，无需真 ffmpeg）。"""

from videocaptioner.core.utils.media_info import _parse_ffmpeg_output, probe_media

_VIDEO_OUTPUT = """\
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'video.mp4':
  Metadata:
    title           : 测试视频【中文】
  Duration: 00:08:48.51, start: 0.000000, bitrate: 2886 kb/s
  Stream #0:0[0x1](und): Video: av1 (libdav1d) (Main) (av01 / 0x31307661), yuv420p(tv, bt709), 3840x2160 [SAR 1:1 DAR 16:9], 2752 kb/s, 23.98 fps, 23.98 tbr, 90k tbn (default)
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6D6134), 44100 Hz, stereo, fltp, 129 kb/s (default)
  Stream #0:2[0x3](eng): Audio: ac3 (ac-3 / 0x332D6361), 48000 Hz, 5.1(side), fltp, 448 kb/s
"""

_AUDIO_WITH_COVER_OUTPUT = """\
Input #0, mp3, from 'song.mp3':
  Duration: 00:03:21.60, start: 0.025057, bitrate: 320 kb/s
  Stream #0:0: Audio: mp3 (mp3float), 44100 Hz, stereo, fltp, 320 kb/s
  Stream #0:1: Video: mjpeg (Progressive), yuvj420p(pc, bt470bg/unknown/unknown), 500x500 [SAR 1:1 DAR 1:1], 90k tbr, 90k tbn (attached pic)
"""

_INVALID_OUTPUT = """\
[in#0 @ 000001] Error opening input: Invalid data found when processing input
Error opening input file not_media.txt.
"""


def test_parse_video_with_multiple_audio_tracks():
    info = _parse_ffmpeg_output(_VIDEO_OUTPUT)
    assert info.resolution == (3840, 2160)
    assert info.video_codec == "av1"
    assert info.fps == 23.98
    assert abs(info.duration_seconds - 528.51) < 0.01
    assert info.bitrate_kbps == 2886
    assert info.has_video and info.has_audio
    assert [s.index for s in info.audio_streams] == [1, 2]
    assert info.audio_streams[1].language == "eng"
    assert info.audio_codec == "aac" and info.audio_sampling_rate == 44100


def test_attached_cover_art_is_not_video():
    """mp3 内嵌封面是一条 mjpeg Video 流，不能把音频文件误判成视频。"""
    info = _parse_ffmpeg_output(_AUDIO_WITH_COVER_OUTPUT)
    assert not info.has_video
    assert info.has_audio
    assert info.width == 0 and info.height == 0
    assert abs(info.duration_seconds - 201.60) < 0.01


def test_fps_falls_back_to_tbr_not_tbn():
    """裸流只报 tbr 时取 tbr；tbn 是时基（90k）绝不能当帧率。"""
    out = (
        "Input #0, h264, from 'raw.264':\n"
        "  Duration: N/A, bitrate: N/A\n"
        "  Stream #0:0: Video: h264 (High), yuv420p(progressive), 1920x1080, 60 tbr, 1200k tbn\n"
    )
    info = _parse_ffmpeg_output(out)
    assert info.fps == 60.0
    assert info.resolution == (1920, 1080)


def test_no_streams_parses_empty():
    info = _parse_ffmpeg_output(_INVALID_OUTPUT)
    assert not info.has_video and not info.has_audio


def test_probe_media_rejects_non_media(tmp_path):
    bad = tmp_path / "not_media.txt"
    bad.write_text("hello", encoding="utf-8")
    assert probe_media(str(bad)) is None
