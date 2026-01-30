"""VideoCaptioner CLI Module

A command-line interface for video captioning, completely decoupled from GUI.
Supports environment variables, config files, and command-line arguments.

Usage:
    videocaptioner process video.mp4 --translate en
    videocaptioner transcribe audio.mp3 --model whisper-api
    videocaptioner subtitle input.srt --optimize --translate zh
"""

from app.cli.main import main

__all__ = ["main"]
