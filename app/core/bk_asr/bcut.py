import json
import time
from typing import Optional, Union, List, Callable, Any

import requests

from ..utils.logger import setup_logger
from .asr_data import ASRDataSeg
from .base import BaseASR

logger = setup_logger("bcut_asr")

__version__ = "0.0.3"
API_BASE_URL = "https://member.bilibili.com/x/bcut/rubick-interface"
# 申请上传
API_REQ_UPLOAD = API_BASE_URL + "/resource/create"
# 提交上传
API_COMMIT_UPLOAD = API_BASE_URL + "/resource/create/complete"
# 创建任务
API_CREATE_TASK = API_BASE_URL + "/task"
# 查询结果
API_QUERY_RESULT = API_BASE_URL + "/task/result"


class BcutASR(BaseASR):
    """必剪 语音识别接口"""

    headers = {
        "User-Agent": "Bilibili/1.0.0 (https://www.bilibili.com)",
        "Content-Type": "application/json",
    }

    def __init__(
        self,
        audio_path: Union[str, bytes],
        use_cache: bool = True,
        need_word_time_stamp: bool = False,
    ):
        super().__init__(audio_path, use_cache=use_cache)
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

    def upload(self) -> None:
        """申请上传"""
        if not self.file_binary:
            raise ValueError("none set data")
        payload = json.dumps(
            {
                "type": 2,
                "name": "audio.mp3",
                "size": len(self.file_binary),
                "ResourceFileType": "mp3",
                "model_id": "8",
            }
        )

        resp = requests.post(API_REQ_UPLOAD, data=payload, headers=self.headers)
        resp.raise_for_status()
        resp = resp.json()
        resp_data = resp["data"]

        self.__in_boss_key = resp_data["in_boss_key"]
        self.__resource_id = resp_data["resource_id"]
        self.__upload_id = resp_data["upload_id"]
        self.__upload_urls = resp_data["upload_urls"]
        self.__per_size = resp_data["per_size"]
        self.__clips = len(resp_data["upload_urls"])

        logger.info(
            f"申请上传成功, 总计大小{resp_data['size'] // 1024}KB, {self.__clips}分片, 分片大小{resp_data['per_size'] // 1024}KB: {self.__in_boss_key}"
        )
        self.__upload_part()
        self.__commit_upload()

    def __upload_part(self) -> None:
        """上传音频数据"""
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
            logger.info(f"开始上传分片{clip}: {start_range}-{end_range}")
            resp = requests.put(
                self.__upload_urls[clip],
                data=self.file_binary[start_range:end_range],
                headers=self.headers,
            )
            resp.raise_for_status()
            etag = resp.headers.get("Etag")
            if etag is not None:
                self.__etags.append(etag)
            logger.info(f"分片{clip}上传成功: {etag}")

    def __commit_upload(self) -> None:
        """提交上传数据"""
        data = json.dumps(
            {
                "InBossKey": self.__in_boss_key,
                "ResourceId": self.__resource_id,
                "Etags": ",".join(self.__etags) if self.__etags else "",
                "UploadId": self.__upload_id,
                "model_id": "8",
            }
        )
        resp = requests.post(API_COMMIT_UPLOAD, data=data, headers=self.headers)
        resp.raise_for_status()
        resp = resp.json()
        self.__download_url = resp["data"]["download_url"]
        logger.info("提交成功")

    def create_task(self) -> str:
        """开始创建转换任务"""
        resp = requests.post(
            API_CREATE_TASK,
            json={"resource": self.__download_url, "model_id": "8"},
            headers=self.headers,
        )
        resp.raise_for_status()
        resp = resp.json()
        self.task_id = resp["data"]["task_id"]
        logger.info(f"任务已创建: {self.task_id}")
        return self.task_id or ""

    def result(self, task_id: Optional[str] = None):
        """查询转换结果"""
        resp = requests.get(
            API_QUERY_RESULT,
            params={"model_id": 7, "task_id": task_id or self.task_id},
            headers=self.headers,
        )
        resp.raise_for_status()
        resp = resp.json()
        return resp["data"]

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs: Any
    ) -> dict:
        def _default_callback(x, y):
            pass

        if callback is None:
            callback = _default_callback

        callback(0, "上传中")
        self.upload()

        callback(40, "创建任务中")

        self.create_task()

        callback(60, "正在转录")

        # 轮询检查任务状态
        for _ in range(500):
            task_resp = self.result()
            if task_resp["state"] == 4:
                break
            time.sleep(1)

        callback(100, "转录成功")

        logger.info("转换成功")
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
