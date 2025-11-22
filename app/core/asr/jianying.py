import datetime
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import requests

from app.config import VERSION

from .asr_data import ASRDataSeg
from .base import BaseASR
from .status import ASRStatus


class JianYingASR(BaseASR):
    """JianYing (CapCut) ASR API implementation.

    Uses ByteDance's JianYing cloud ASR service with AWS S3-style upload.
    """

    def __init__(
        self,
        audio_input: Union[str, bytes],
        use_cache: bool = False,
        need_word_time_stamp: bool = False,
        start_time: float = 0,
        end_time: float = 6000,
    ):
        super().__init__(audio_input, use_cache)
        self.audio_input = audio_input
        self.end_time = end_time
        self.start_time = start_time

        # AWS credentials
        self.session_token = None
        self.secret_key = None
        self.access_key = None

        # Upload details
        self.store_uri = None
        self.auth = None
        self.upload_id = None
        self.session_key = None
        self.upload_hosts = None

        self.need_word_time_stamp = need_word_time_stamp
        self.tdid = self._get_tid()

    def submit(self) -> str:
        """Submit the task"""
        url = "https://lv-pc-api-sinfonlinec.ulikecam.com/lv/v1/audio_subtitle/submit"
        payload = {
            "adjust_endtime": 200,
            "audio": self.store_uri,
            "caption_type": 2,
            "client_request_id": "45faf98c-160f-4fae-a649-6d89b0fe35be",
            "max_lines": 1,
            "songs_info": [
                {"end_time": self.end_time, "id": "", "start_time": self.start_time}
            ],
            "words_per_line": 16,
        }

        sign, device_time = self._generate_sign_parameters(
            url="/lv/v1/audio_subtitle/submit", pf="4", appvr="6.6.0", tdid=self.tdid
        )
        headers = self._build_headers(device_time, sign)
        response = requests.post(url, json=payload, headers=headers)
        resp_data = response.json()

        if resp_data.get("ret") != "0":
            error_msg = f"API Error: {resp_data.get('errmsg', 'Unknown error')} (ret: {resp_data.get('ret')})"
            raise ValueError(error_msg)

        query_id = resp_data["data"]["id"]
        return query_id

    def upload(self):
        """Upload the file"""
        self._upload_sign()
        self._upload_auth()
        self._upload_file()
        self._upload_check()
        uri = self._upload_commit()
        return uri

    def query(self, query_id: str):
        """Query the task"""
        url = "https://lv-pc-api-sinfonlinec.ulikecam.com/lv/v1/audio_subtitle/query"
        payload = {"id": query_id, "pack_options": {"need_attribute": True}}
        sign, device_time = self._generate_sign_parameters(
            url="/lv/v1/audio_subtitle/query", pf="4", appvr="6.6.0", tdid=self.tdid
        )
        headers = self._build_headers(device_time, sign)
        response = requests.post(url, json=payload, headers=headers)
        resp_data = response.json()

        if resp_data.get("ret") != "0":
            error_msg = f"API Error: {resp_data.get('errmsg', 'Unknown error')} (ret: {resp_data.get('ret')})"
            raise ValueError(error_msg)

        return resp_data

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs: Any
    ) -> dict:
        """Execute ASR workflow: upload -> submit -> query result."""

        self._check_rate_limit()

        if callback:
            callback(*ASRStatus.UPLOADING.with_progress(20))
        self.upload()

        if callback:
            callback(*ASRStatus.SUBMITTING.callback_tuple())
        query_id = self.submit()

        if callback:
            callback(*ASRStatus.QUERYING_RESULT.with_progress(60))
        resp_data = self.query(query_id)

        if callback:
            callback(*ASRStatus.COMPLETED.callback_tuple())

        return resp_data

    def _make_segments(self, resp_data: dict) -> List[ASRDataSeg]:
        if self.need_word_time_stamp:
            return [
                ASRDataSeg(w["text"].strip(), w["start_time"], w["end_time"])
                for u in resp_data["data"]["utterances"]
                for w in u["words"]
            ]
        else:
            return [
                ASRDataSeg(u["text"], u["start_time"], u["end_time"])
                for u in resp_data["data"]["utterances"]
            ]

    def _get_key(self):
        return f"{self.__class__.__name__}-{self.crc32_hex}-{self.need_word_time_stamp}"

    def _get_tid(self):
        i = str(datetime.datetime.now().year)[3]
        fr = 390 + int(i)
        ed = "3278516897751" if int(i) % 2 != 0 else f"{uuid.getnode():013d}"
        return f"{fr}{ed}"

    def _generate_sign_parameters(
        self, url: str, pf: str = "4", appvr: str = "6.6.0", tdid=""
    ) -> Tuple[str, str]:
        """Generate request signature and timestamp via remote service."""
        current_time = str(int(time.time()))
        data = {
            "url": url,
            "current_time": current_time,
            "pf": pf,
            "appvr": appvr,
            "tdid": self.tdid,
        }
        headers = {
            "User-Agent": f"VideoCaptioner/{VERSION}",
            "tdid": self.tdid,
            "t": current_time,
        }
        # Replace with your actual endpoint URL
        get_sign_url = "https://asrtools-update.bkfeng.top/sign"
        try:
            response = requests.post(get_sign_url, json=data, headers=headers)
            response.raise_for_status()
            response_data = response.json()
            sign = response_data.get("sign")
            if not sign:
                raise ValueError("No 'sign' in response")
        except requests.exceptions.RequestException as e:
            raise SystemExit(f"HTTP Request failed: {e}")
        except ValueError as ve:
            raise SystemExit(f"Invalid response: {ve}")
        return sign.lower(), current_time

    def _build_headers(self, device_time: str, sign: str) -> Dict[str, str]:
        """Build request headers with signature."""
        return {
            "User-Agent": "Cronet/TTNetVersion:d4572e53 2024-06-12 QuicVersion:4bf243e0 2023-04-17",
            "appvr": "6.6.0",
            "device-time": str(device_time),
            "pf": "4",
            "sign": sign,
            "sign-ver": "1",
            "tdid": self.tdid,
        }

    def _uplosd_headers(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36 Thea/1.0.1",
            "Authorization": self.auth,
            "Content-CRC32": self.crc32_hex,
        }
        return headers

    def _upload_sign(self):
        """Get upload sign"""
        url = "https://lv-pc-api-sinfonlinec.ulikecam.com/lv/v1/upload_sign"
        payload = json.dumps({"biz": "pc-recognition"})
        sign, device_time = self._generate_sign_parameters(
            url="/lv/v1/upload_sign", pf="4", appvr="6.6.0", tdid=self.tdid
        )
        headers = self._build_headers(device_time, sign)
        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status()
        login_data = response.json()
        self.access_key = login_data["data"]["access_key_id"]
        self.secret_key = login_data["data"]["secret_access_key"]
        self.session_token = login_data["data"]["session_token"]
        return self.access_key, self.secret_key, self.session_token

    def _upload_auth(self):
        """Get upload authorization"""
        if isinstance(self.audio_input, bytes):
            file_size = len(self.audio_input)
        else:
            file_size = os.path.getsize(self.audio_input)
        request_parameters = f"Action=ApplyUploadInner&FileSize={file_size}&FileType=object&IsInner=1&SpaceName=lv-mac-recognition&Version=2020-11-19&s=5y0udbjapi"

        t = datetime.datetime.utcnow()
        amz_date = t.strftime("%Y%m%dT%H%M%SZ")
        datestamp = t.strftime("%Y%m%d")
        headers = {"x-amz-date": amz_date, "x-amz-security-token": self.session_token}
        if self.secret_key is None:
            raise ValueError("Secret key not initialized")
        signature = aws_signature(
            self.secret_key, request_parameters, headers, region="cn", service="vod"
        )
        authorization = f"AWS4-HMAC-SHA256 Credential={self.access_key}/{datestamp}/cn/vod/aws4_request, SignedHeaders=x-amz-date;x-amz-security-token, Signature={signature}"
        headers["authorization"] = authorization
        response = requests.get(
            f"https://vod.bytedanceapi.com/?{request_parameters}", headers=headers
        )
        store_infos = response.json()

        self.store_uri = store_infos["Result"]["UploadAddress"]["StoreInfos"][0][
            "StoreUri"
        ]
        self.auth = store_infos["Result"]["UploadAddress"]["StoreInfos"][0]["Auth"]
        self.upload_id = store_infos["Result"]["UploadAddress"]["StoreInfos"][0][
            "UploadID"
        ]
        self.session_key = store_infos["Result"]["UploadAddress"]["SessionKey"]
        self.upload_hosts = store_infos["Result"]["UploadAddress"]["UploadHosts"][0]
        self.store_uri = store_infos["Result"]["UploadAddress"]["StoreInfos"][0][
            "StoreUri"
        ]
        return store_infos

    def _upload_file(self):
        """Upload the file"""
        url = f"https://{self.upload_hosts}/{self.store_uri}?partNumber=1&uploadID={self.upload_id}"
        headers = self._uplosd_headers()
        response = requests.put(url, data=self.file_binary, headers=headers)
        resp_data = response.json()
        assert resp_data["success"] == 0, f"File upload failed: {response.text}"
        return resp_data

    def _upload_check(self):
        """Check upload result"""
        url = f"https://{self.upload_hosts}/{self.store_uri}?uploadID={self.upload_id}"
        payload = f"1:{self.crc32_hex}"
        headers = self._uplosd_headers()
        response = requests.post(url, data=payload, headers=headers)
        resp_data = response.json()
        return resp_data

    def _upload_commit(self):
        """Commit the uploaded file"""
        url = f"https://{self.upload_hosts}/{self.store_uri}?uploadID={self.upload_id}&partNumber=1&x-amz-security-token={self.session_token}"
        headers = self._uplosd_headers()
        requests.put(url, data=self.file_binary, headers=headers)
        return self.store_uri


def sign(key: bytes, msg: str) -> bytes:
    """Generate HMAC-SHA256 signature."""
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def get_signature_key(
    secret_key: str, date_stamp: str, region_name: str, service_name: str
) -> bytes:
    """Generate AWS signature key."""
    k_date = sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = sign(k_date, region_name)
    k_service = sign(k_region, service_name)
    k_signing = sign(k_service, "aws4_request")
    return k_signing


def aws_signature(
    secret_key: str,
    request_parameters: str,
    headers: Dict[str, str],
    method: str = "GET",
    payload: str = "",
    region: str = "cn",
    service: str = "vod",
) -> str:
    """Generate AWS signature."""
    canonical_uri = "/"
    canonical_querystring = request_parameters
    canonical_headers = (
        "\n".join([f"{key}:{value}" for key, value in headers.items()]) + "\n"
    )
    signed_headers = ";".join(headers.keys())
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = f"{method}\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"

    amzdate = headers["x-amz-date"]
    datestamp = amzdate.split("T")[0]

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = f"{algorithm}\n{amzdate}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"

    signing_key = get_signature_key(secret_key, datestamp, region, service)
    signature = hmac.new(
        signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return signature
