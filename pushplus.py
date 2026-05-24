import logging
from typing import Optional

import requests

from config import PUSHPLUS_API_URL, PUSHPLUS_CHANNEL, PUSHPLUS_ENABLED, PUSHPLUS_TOKEN

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15


def build_push_title(report_label: str, content: str) -> str:
    report_date = ""
    for line in content.splitlines():
        if line.startswith("报告时间:"):
            report_date = line.split(":", 1)[1].strip().split()[0]
            break
    if report_date:
        return f"体育热榜 | {report_label} {report_date}"
    return f"体育热榜 | {report_label}"


def send_report(
    title: str,
    content: str,
    session: Optional[requests.Session] = None,
) -> bool:
    if not PUSHPLUS_ENABLED:
        logger.warning("PushPlus disabled or PUSHPLUS_TOKEN not set, skip push")
        return False

    payload = {
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "txt",
        "channel": PUSHPLUS_CHANNEL,
    }

    try:
        if session is not None:
            response = session.post(
                PUSHPLUS_API_URL,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
        else:
            response = requests.post(
                PUSHPLUS_API_URL,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as exc:
        logger.error("PushPlus request failed: %s", exc)
        return False
    except ValueError as exc:
        logger.error("PushPlus invalid JSON response: %s", exc)
        return False

    code = result.get("code")
    if code == 200:
        logger.info("PushPlus push succeeded: %s", title)
        return True

    logger.error(
        "PushPlus push failed (code=%s): %s",
        code,
        result.get("msg", result),
    )
    return False
