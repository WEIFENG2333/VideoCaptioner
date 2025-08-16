from typing import List, Optional, Callable, Any
import requests

from ..utils.logger import setup_logger
from .asr_data import ASRDataSeg
from .base import BaseASR

logger = setup_logger("kuaishou_asr")


class KuaiShouASR(BaseASR):
    def __init__(
        self, audio_path, use_cache: bool = False, need_word_time_stamp: bool = False
    ):
        super().__init__(audio_path, use_cache)
        self.need_word_time_stamp = need_word_time_stamp
        logger.info("KuaiShouASR initialized with audio_path: %s", audio_path)

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs: Any
    ) -> dict:
        logger.info("Running ASR process")
        return self._submit()

    def _make_segments(self, resp_data: dict) -> List[ASRDataSeg]:
        logger.debug("Making segments from response data")
        return [
            ASRDataSeg(
                u["text"],
                int(float(u["start_time"]) * 1000),
                int(float(u["end_time"]) * 1000),
            )
            for u in resp_data["data"]["text"]
        ]

    def _submit(self) -> dict:
        logger.info("Submitting audio file for ASR")
        payload = {"typeId": "1"}
        if self.file_binary is None:
            raise ValueError("No audio data available")
        files = [("file", ("test.mp3", self.file_binary, "audio/mpeg"))]
        try:
            result = requests.post(
                "https://ai.kuaishou.com/api/effects/subtitle_generate",
                data=payload,
                files=files,
            )
            result.raise_for_status()
            logger.info("Submission successful")
        except requests.exceptions.RequestException as e:
            logger.error("Submission failed: %s", e)
            raise
        return result.json()


if __name__ == "__main__":
    # Example usage
    audio_file = r"test.mp3"
    asr = KuaiShouASR(audio_file)
    asr_data = asr.run()
    print(asr_data)
