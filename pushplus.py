import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

import requests

from config import (
    PUSHPLUS_ACCESS_KEY_URL,
    PUSHPLUS_API_URL,
    PUSHPLUS_CHANNEL,
    PUSHPLUS_ENABLED,
    PUSHPLUS_PUSH_MAX_RETRIES,
    PUSHPLUS_RETRY_DELAY,
    PUSHPLUS_SECRET_KEY,
    PUSHPLUS_SEND_RESULT_URL,
    PUSHPLUS_TOKEN,
    PUSHPLUS_VERIFY_ENABLED,
    PUSHPLUS_VERIFY_POLL_INTERVAL,
    PUSHPLUS_VERIFY_TIMEOUT,
)
from timezone_utils import get_tz

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
ACCESS_KEY_REFRESH_MARGIN = timedelta(minutes=5)
RATE_LIMIT_CODES = frozenset({900})

_access_key_lock = threading.Lock()
_access_key_cache: Optional[str] = None
_access_key_expires_at: Optional[datetime] = None
_access_key_unavailable = False


def is_delivery_verify_available() -> bool:
    return PUSHPLUS_VERIFY_ENABLED and not _access_key_unavailable


def build_push_title(prefix: str, report_label: str, content: str) -> str:
    report_date = ""
    for line in content.splitlines():
        if line.startswith("报告时间:"):
            report_date = line.split(":", 1)[1].strip().split()[0]
            break
    if report_date:
        return f"{prefix} | {report_label} {report_date}"
    return f"{prefix} | {report_label}"


def send_test_message(prefix: str = "体育热榜") -> Tuple[bool, str]:
    if not PUSHPLUS_ENABLED:
        logger.warning("PushPlus disabled or PUSHPLUS_TOKEN not set, skip test push")
        return False, "未配置 PUSHPLUS_TOKEN"

    tz = get_tz()
    now = datetime.now(tz)
    title = f"{prefix} | 测试消息"
    content = (
        "这是一条 PushPlus 测试消息。每推 10 条、或超过 24 小时没对话，要再发一条消息给 ClawBot 才能继续收推送\n"
        f"发送时间: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    ok = send_report_with_retry(title, content)
    if ok and is_delivery_verify_available():
        return True, "测试消息已送达微信（PushPlus 已确认）"
    if ok:
        return (
            True,
            "测试消息已提交 PushPlus；若微信未收到，请先在微信里给 ClawBot 发一条消息"
            "（绑定后首次及每 10 条推送后都需主动对话一次）",
        )
    if _access_key_unavailable:
        return (
            False,
            "发送失败：PUSHPLUS_SECRET_KEY 未授权或 IP 未在白名单，"
            "请在 PushPlus 个人中心检查密钥与开放接口设置",
        )
    return (
        False,
        "发送失败：请检查 Token、实名认证与 ClawBot 绑定激活状态",
    )


def _post_json(
    url: str,
    payload: dict,
    session: Optional[requests.Session] = None,
    headers: Optional[dict] = None,
) -> Tuple[Optional[dict], Optional[int]]:
    try:
        if session is not None:
            response = session.post(
                url,
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        else:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        response.raise_for_status()
        return response.json(), None
    except requests.RequestException as exc:
        logger.error("PushPlus request failed: %s", exc)
        return None, None
    except ValueError as exc:
        logger.error("PushPlus invalid JSON response: %s", exc)
        return None, None


def _get_json(
    url: str,
    session: Optional[requests.Session] = None,
    headers: Optional[dict] = None,
) -> Optional[dict]:
    try:
        if session is not None:
            response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        else:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        logger.error("PushPlus request failed: %s", exc)
        return None
    except ValueError as exc:
        logger.error("PushPlus invalid JSON response: %s", exc)
        return None


def _fetch_access_key(session: Optional[requests.Session] = None) -> Optional[str]:
    global _access_key_cache, _access_key_expires_at, _access_key_unavailable

    if _access_key_unavailable:
        return None

    if not PUSHPLUS_SECRET_KEY:
        logger.warning("PUSHPLUS_SECRET_KEY not set, cannot query delivery status")
        return None

    payload = {"token": PUSHPLUS_TOKEN, "secretKey": PUSHPLUS_SECRET_KEY}
    result, _ = _post_json(PUSHPLUS_ACCESS_KEY_URL, payload, session=session)
    if not result:
        return None

    code = result.get("code")
    if code in RATE_LIMIT_CODES:
        logger.error(
            "PushPlus access key request rate limited (code=%s): %s",
            code,
            result.get("msg", result),
        )
        return None
    if code in (401, 403):
        _access_key_unavailable = True
        logger.error(
            "PushPlus access key denied (code=%s): %s — check SecretKey and IP whitelist; "
            "delivery verification disabled for this session",
            code,
            result.get("msg", result),
        )
        return None
    if code != 200:
        logger.error(
            "PushPlus access key request failed (code=%s): %s",
            code,
            result.get("msg", result),
        )
        return None

    data = result.get("data") or {}
    access_key = data.get("accessKey")
    if not access_key:
        logger.error("PushPlus access key response missing accessKey")
        return None

    expires_in = int(data.get("expiresIn") or 7200)
    _access_key_cache = access_key
    _access_key_expires_at = datetime.now() + timedelta(seconds=expires_in)
    logger.debug("PushPlus access key refreshed, expires in %ds", expires_in)
    return access_key


def get_access_key(session: Optional[requests.Session] = None) -> Optional[str]:
    global _access_key_cache, _access_key_expires_at

    with _access_key_lock:
        if (
            _access_key_cache
            and _access_key_expires_at
            and datetime.now() < _access_key_expires_at - ACCESS_KEY_REFRESH_MARGIN
        ):
            return _access_key_cache
        return _fetch_access_key(session=session)


def send_report(
    title: str,
    content: str,
    session: Optional[requests.Session] = None,
) -> Optional[str]:
    """Submit a push request. Returns shortCode on acceptance, None on failure."""
    if not PUSHPLUS_ENABLED:
        logger.warning("PushPlus disabled or PUSHPLUS_TOKEN not set, skip push")
        return None

    payload = {
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "txt",
        "channel": PUSHPLUS_CHANNEL,
    }

    result, _ = _post_json(PUSHPLUS_API_URL, payload, session=session)
    if not result:
        return None

    code = result.get("code")
    if code in RATE_LIMIT_CODES:
        logger.error(
            "PushPlus push rate limited (code=%s): %s",
            code,
            result.get("msg", result),
        )
        return None
    if code == 200:
        short_code = result.get("data")
        if not short_code:
            logger.error("PushPlus push accepted but missing shortCode: %s", title)
            return None
        logger.info("PushPlus push submitted: %s (shortCode=%s)", title, short_code)
        return str(short_code)

    logger.error(
        "PushPlus push failed (code=%s): %s",
        code,
        result.get("msg", result),
    )
    return None


def query_delivery_status(
    short_code: str,
    session: Optional[requests.Session] = None,
) -> Optional[int]:
    """Return delivery status: 0 pending, 1 sending, 2 sent, 3 failed."""
    access_key = get_access_key(session=session)
    if not access_key:
        return None

    url = f"{PUSHPLUS_SEND_RESULT_URL}?shortCode={short_code}"
    result = _get_json(url, session=session, headers={"access-key": access_key})
    if not result:
        return None

    code = result.get("code")
    if code != 200:
        logger.warning(
            "PushPlus delivery query failed (code=%s): %s",
            code,
            result.get("msg", result),
        )
        return None

    data = result.get("data") or {}
    status = data.get("status")
    if status is None:
        return None

    status = int(status)
    if status == 3:
        error_message = data.get("errorMessage") or ""
        logger.warning(
            "PushPlus delivery failed for %s: %s",
            short_code,
            error_message or "unknown error",
        )
    return status


def wait_for_delivery(
    short_code: str,
    session: Optional[requests.Session] = None,
) -> Optional[int]:
    deadline = time.monotonic() + PUSHPLUS_VERIFY_TIMEOUT
    last_status: Optional[int] = None

    while time.monotonic() < deadline:
        status = query_delivery_status(short_code, session=session)
        if status is None:
            time.sleep(PUSHPLUS_VERIFY_POLL_INTERVAL)
            continue

        last_status = status
        if status == 2:
            logger.info("PushPlus delivery confirmed (shortCode=%s)", short_code)
            return status
        if status == 3:
            return status

        time.sleep(PUSHPLUS_VERIFY_POLL_INTERVAL)

    logger.warning(
        "PushPlus delivery poll timed out after %ds (shortCode=%s, last_status=%s)",
        PUSHPLUS_VERIFY_TIMEOUT,
        short_code,
        last_status,
    )
    return last_status


def _send_with_submit_retries(
    title: str,
    content: str,
    session: Optional[requests.Session] = None,
) -> bool:
    for attempt in range(1, PUSHPLUS_PUSH_MAX_RETRIES + 1):
        short_code = send_report(title, content, session=session)
        if short_code:
            logger.info("PushPlus push accepted on attempt %d: %s", attempt, title)
            return True
        if attempt < PUSHPLUS_PUSH_MAX_RETRIES:
            logger.warning(
                "PushPlus submit failed on attempt %d/%d, retrying in %ds",
                attempt,
                PUSHPLUS_PUSH_MAX_RETRIES,
                PUSHPLUS_RETRY_DELAY,
            )
            time.sleep(PUSHPLUS_RETRY_DELAY)
    return False


def send_report_with_retry(
    title: str,
    content: str,
    session: Optional[requests.Session] = None,
) -> bool:
    if not PUSHPLUS_ENABLED:
        logger.warning("PushPlus disabled or PUSHPLUS_TOKEN not set, skip push")
        return False

    if PUSHPLUS_VERIFY_ENABLED and PUSHPLUS_SECRET_KEY and not _access_key_unavailable:
        get_access_key(session=session)

    if not is_delivery_verify_available():
        if PUSHPLUS_VERIFY_ENABLED and _access_key_unavailable:
            logger.warning(
                "PushPlus delivery verification unavailable (access key denied), "
                "using submit-only retries"
            )
        else:
            logger.info("PushPlus delivery verification disabled, submit-only retries")
        return _send_with_submit_retries(title, content, session=session)

    for attempt in range(1, PUSHPLUS_PUSH_MAX_RETRIES + 1):
        short_code = send_report(title, content, session=session)
        if not short_code:
            if attempt < PUSHPLUS_PUSH_MAX_RETRIES:
                logger.warning(
                    "PushPlus submit failed on attempt %d/%d, retrying in %ds",
                    attempt,
                    PUSHPLUS_PUSH_MAX_RETRIES,
                    PUSHPLUS_RETRY_DELAY,
                )
                time.sleep(PUSHPLUS_RETRY_DELAY)
            continue

        status = wait_for_delivery(short_code, session=session)
        if status == 2:
            return True

        if attempt < PUSHPLUS_PUSH_MAX_RETRIES:
            logger.warning(
                "PushPlus delivery not confirmed on attempt %d/%d (status=%s), "
                "retrying in %ds",
                attempt,
                PUSHPLUS_PUSH_MAX_RETRIES,
                status,
                PUSHPLUS_RETRY_DELAY,
            )
            time.sleep(PUSHPLUS_RETRY_DELAY)

    logger.error(
        "PushPlus push failed after %d attempts: %s",
        PUSHPLUS_PUSH_MAX_RETRIES,
        title,
    )
    return False
