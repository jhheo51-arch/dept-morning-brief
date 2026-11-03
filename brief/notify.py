"""알림. 설정한 환경변수에 웹훅 주소가 있을 때만 '오늘 볼 것'을 보낸다(Slack 수신 웹훅 형식 {"text": ...})."""
import json
import os
import urllib.request

from . import rules_config as C


def message(b):
    lines = [f"[아침 점검 {b['date']}] {b.get('store_name', '')}".rstrip()]
    lines += [f"{i}. {t}" for i, t in enumerate(b["top3"], 1)]
    if b["failures"]:
        lines.append("실패: " + ", ".join(f["step"] for f in b["failures"]))
    return "\n".join(lines)


def send(b, opener=urllib.request.urlopen):
    """보냈으면 True, 주소가 없거나 offline이면 False. 알림 실패는 점검 결과를 막지 않도록 호출한 쪽에서 잡는다."""
    if C.OFFLINE:  # offline은 인터넷에 전혀 나가지 않는다는 약속이라 웹훅도 막는다
        return False
    url = os.environ.get(C.WEBHOOK_ENV or "", "") if C.WEBHOOK_ENV else ""
    if not url:
        return False
    req = urllib.request.Request(url, data=json.dumps({"text": message(b)}, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with opener(req, timeout=15):
        pass
    return True
