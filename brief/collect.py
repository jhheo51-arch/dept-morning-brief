"""수집 단계. 리뷰 원문은 여기서 분류만 하고 바로 버린다. 밖으로는 건수 계산에 필요한 표시만 나간다."""
import datetime as dt
import json
import re
import urllib.request

import numpy as np

from . import rules_config as C

KST = dt.timezone(dt.timedelta(hours=9))


def classify(text):
    """리뷰 한 건을 주제 표시로 바꾼다. 원문은 돌려주지 않는다."""
    topics = [t for t, p in C.TOPICS.items() if re.search(p, text)]
    blocked = bool(re.search(C.TOPICS[C.BENEFIT], text) and re.search(C.APP_BLOCK, text))
    places = [k for k, p in C.TOUCHPOINT_WORDS.items() if re.search(p, text)] if blocked else []
    return {"topics": topics, "blocked": blocked, "places": places}


def to_kst(at):
    # google-play-scraper 는 실행 환경 시간대의 naive datetime 을 준다
    return at.astimezone(KST) if at.tzinfo is None else at.astimezone(KST)


def fetch_reviews(now, days=65, scraper=None):
    """지난 days일 리뷰를 받아 (요약 목록, 원문 목록)을 돌려준다.

    원문 목록은 저장 직전 유출 검사에만 쓰고 저장하지 않는다.
    """
    if scraper is None:
        from google_play_scraper import Sort, reviews

        def scraper(token):
            return reviews(C.APP_ID, lang="ko", country="kr", sort=Sort.NEWEST, count=200,
                           continuation_token=token)

    since = now - dt.timedelta(days=days)
    rows, texts, token = [], [], None
    while True:
        batch, token = scraper(token)
        for r in batch:
            at = to_kst(r["at"])
            if at < since:
                continue
            text = r.get("content") or ""
            texts.append(text)
            rows.append({"at": at, "score": int(r["score"]), **classify(text)})
        if not batch or to_kst(batch[-1]["at"]) < since or token is None:
            break
    return rows, texts


def fetch_weather(today, opener=urllib.request.urlopen):
    """Open-Meteo 7일 예보. 날짜별 낮(10~20시) 강수 합(mm)."""
    url = ("https://api.open-meteo.com/v1/forecast"
           f"?latitude={C.LAT}&longitude={C.LON}&hourly=precipitation"
           "&timezone=Asia%2FSeoul&forecast_days=7")
    with opener(url, timeout=20) as f:
        h = json.loads(f.read().decode("utf-8"))["hourly"]
    out = {}
    for t, mm in zip(h["time"], h["precipitation"]):
        if 10 <= int(t[11:13]) <= 20:
            out[t[:10]] = round(out.get(t[:10], 0.0) + (mm or 0.0), 1)
    return out


# 4.3 가상 시범. 모든 회원과 반응은 가상이며 아래 값은 직접 정한 설정값이다.
# virtual_promo.py 의 고객군 설정을 주 단위 평일 저녁 방문 확률로 반으로 나눠 쓰고,
# 포트폴리오 6쪽 1번처럼 방문이 줄어든 회원 위주로 대상을 좁혔다.
SEED = 2026
N_TARGET = 20_000
HOLDOUT = 0.10
SEGMENTS = {  # 비중, 행사 없을 때 주간 방문 확률, 행사로 늘어나는 확률
    "사다가 멈춘 우수고객": (0.60, 0.040, 0.035),
    "일반 회원": (0.40, 0.050, 0.010),
}
OPTOUT_WEEKLY = {"sent": 0.0040, "hold": 0.0030}  # 주간 푸시 수신 거부 확률


def simulate_pilot(weeks=C.PILOT_WEEKS):
    """가상 회원의 주별 방문과 수신 거부를 한 번에 만든다. 같은 SEED면 매일 같은 값이 나온다."""
    rng = np.random.default_rng(SEED)
    names = list(SEGMENTS)
    share = np.array([SEGMENTS[k][0] for k in names])
    seg = rng.choice(len(names), size=N_TARGET, p=share)
    send = rng.random(N_TARGET) >= HOLDOUT
    base = np.array([SEGMENTS[k][1] for k in names])[seg]
    lift = np.array([SEGMENTS[k][2] for k in names])[seg]
    visits = rng.random((N_TARGET, weeks)) < (base + lift * send)[:, None]
    p_out = np.where(send, OPTOUT_WEEKLY["sent"], OPTOUT_WEEKLY["hold"])
    optout_week = rng.random((N_TARGET, weeks)) < p_out[:, None]
    return {"send": send, "visits": visits, "optout": optout_week}
