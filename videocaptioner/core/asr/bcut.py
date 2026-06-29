import json
import random
import time
from typing import Any, Callable, List, Optional, Union

import requests

from .asr_data import ASRDataSeg
from .base import BaseASR
from .status import ASRStatus

__version__ = "0.0.3"

API_BASE_URL = "https://member.bilibili.com/x/bcut/rubick-interface"
API_REQ_UPLOAD = API_BASE_URL + "/resource/create"
API_COMMIT_UPLOAD = API_BASE_URL + "/resource/create/complete"
API_CREATE_TASK = API_BASE_URL + "/task"
API_QUERY_RESULT = API_BASE_URL + "/task/result"

RETRYABLE_STATUS_CODES = {408, 409, 412, 425, 429, 500, 502, 503, 504}


class BcutASR(BaseASR):
    """Bilibili Bcut ASR API implementation.

    Uses Bilibili's cloud ASR service with multipart upload support.
    """

    headers = {
        "User-Agent": "Bilibili/1.0.0 (https://www.bilibili.com)",
        "Content-Type": "application/json",
    }

    def __init__(
        self,
        audio_input: Union[str, bytes],
        use_cache: bool = True,
        need_word_time_stamp: bool = False,
    ):
        super().__init__(audio_input, use_cache=use_cache)
        self.session = requests.Session()
        self.task_id: Optional[str] = None
        self.__etags: List[str] = []

        self.__in_boss_key: Optional[str] = None
        self.__resource_id: Optional[str] = None
        self.__upload_id: Optional[str] = None
        self.__upload_urls: List[str] = []
        self.__per_size: Optional[int] = None
        self.__clips: Optional[int] = None

        self.__etags_final: Optional[List[str]] = []
        self.__download_url: Optional[str] = None

        self.need_word_time_stamp = need_word_time_stamp

    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        max_attempts: int = 8,
        timeout: tuple[int, int] = (15, 300),
        **kwargs: Any,
    ) -> requests.Response:
        """Request Bcut/BOSS endpoints with retry for transient failures."""
        last_exc: Optional[BaseException] = None

        for attempt in range(1, max_attempts + 1):
            try:
                resp = self.session.request(method, url, timeout=timeout, **kwargs)
                if resp.status_code not in RETRYABLE_STATUS_CODES:
                    resp.raise_for_status()
                    return resp

                last_exc = requests.HTTPError(
                    f"{resp.status_code} retryable response", response=resp
                )
            except requests.RequestException as exc:
                last_exc = exc
                response = getattr(exc, "response", None)
                status_code = getattr(response, "status_code", None)
                if status_code is not None and status_code not in RETRYABLE_STATUS_CODES:
                    raise

            if attempt >= max_attempts:
                break

            response = getattr(last_exc, "response", None)
            retry_after = response.headers.get("Retry-After") if response else None
            try:
                wait_seconds = float(retry_after) if retry_after else None
            except ValueError:
                wait_seconds = None

            if wait_seconds is None:
                wait_seconds = min(60.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5)

            print(
                f"Bcut request failed ({last_exc}); "
                f"retry {attempt}/{max_attempts - 1} after {wait_seconds:.1f}s"
            )
            time.sleep(wait_seconds)

        assert last_exc is not None
        if isinstance(last_exc, requests.HTTPError) and last_exc.response is not None:
            last_exc.response.raise_for_status()
        raise last_exc

    def upload(self) -> None:
        """Request upload authorization and upload audio file."""
        if not self.file_binary:
            raise ValueError("No audio data to upload")
        payload = json.dumps(
            {
                "type": 2,
                "name": "audio.mp3",
                "size": len(self.file_binary),
                "ResourceFileType": "mp3",
                "model_id": "8",
            }
        )

        resp = self._request_with_retry(
            "POST", API_REQ_UPLOAD, data=payload, headers=self.headers
        )
        resp = resp.json()
        resp_data = resp["data"]

        self.__in_boss_key = resp_data["in_boss_key"]
        self.__resource_id = resp_data["resource_id"]
        self.__upload_id = resp_data["upload_id"]
        self.__upload_urls = resp_data["upload_urls"]
        self.__per_size = resp_data["per_size"]
        self.__clips = len(resp_data["upload_urls"])

        self.__upload_part()
        self.__commit_upload()

    def __upload_part(self) -> None:
        """Upload audio data in multiple parts."""
        if (
            self.__clips is None
            or self.__per_size is None
            or self.__upload_urls is None
            or self.file_binary is None
        ):
            raise ValueError("Upload parameters not initialized")

        for clip in range(self.__clips):
            start_range = clip * self.__per_size
            end_range = (clip + 1) * self.__per_size
            resp = self._request_with_retry(
                "PUT",
                self.__upload_urls[clip],
                data=self.file_binary[start_range:end_range],
                headers=self.headers,
            )
            etag = resp.headers.get("Etag")
            if etag is not None:
                self.__etags.append(etag)

    def __commit_upload(self) -> None:
        """Commit the upload and get download URL."""
        data = json.dumps(
            {
                "InBossKey": self.__in_boss_key,
                "ResourceId": self.__resource_id,
                "Etags": ",".join(self.__etags) if self.__etags else "",
                "UploadId": self.__upload_id,
                "model_id": "8",
            }
        )
        resp = self._request_with_retry(
            "POST", API_COMMIT_UPLOAD, data=data, headers=self.headers
        )
        resp = resp.json()
        self.__download_url = resp["data"]["download_url"]

    def create_task(self) -> str:
        """Create ASR task."""
        resp = self._request_with_retry(
            "POST",
            API_CREATE_TASK,
            json={"resource": self.__download_url, "model_id": "8"},
            headers=self.headers,
        )
        resp = resp.json()
        self.task_id = resp["data"]["task_id"]
        return self.task_id or ""

    def result(self, task_id: Optional[str] = None):
        """Query ASR result."""
        resp = self._request_with_retry(
            "GET",
            API_QUERY_RESULT,
            params={"model_id": 7, "task_id": task_id or self.task_id},
            headers=self.headers,
            timeout=(15, 120),
        )
        resp = resp.json()
        return resp["data"]

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs: Any
    ) -> dict:
        """Execute ASR workflow: upload -> create task -> poll result."""

        self._check_rate_limit()

        def _default_callback(x, y):
            pass

        if callback is None:
            callback = _default_callback

        callback(*ASRStatus.UPLOADING.callback_tuple())
        self.upload()

        callback(*ASRStatus.CREATING_TASK.callback_tuple())
        self.create_task()

        callback(*ASRStatus.TRANSCRIBING.callback_tuple())

        # Poll task status until complete
        task_resp = None
        for _ in range(500):
            task_resp = self.result()
            if task_resp["state"] == 4:
                break
            time.sleep(1)

        if task_resp is None or task_resp["state"] != 4:
            raise RuntimeError("ASR task failed or timeout")

        callback(*ASRStatus.COMPLETED.callback_tuple())
        return json.loads(task_resp["result"])

    def _make_segments(self, resp_data: dict) -> List[ASRDataSeg]:
        if self.need_word_time_stamp:
            return [
                ASRDataSeg(w["label"].strip(), w["start_time"], w["end_time"])
                for u in resp_data["utterances"]
                for w in u["words"]
            ]
        else:
            return [
                ASRDataSeg(u["transcript"], u["start_time"], u["end_time"])
                for u in resp_data["utterances"]
            ]


if __name__ == "__main__":
    # Example usage
    audio_file = r"test.mp3"
    asr = BcutASR(audio_file)
    asr_data = asr.run()
    print(asr_data)
