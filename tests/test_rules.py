"""규칙 4개(4.1~4.4) 단위 테스트. 리뷰 문장은 테스트용으로 지어낸 짧은 문장이다."""
import datetime as dt

import numpy as np

from brief import collect, judge
from brief.collect import KST

NOW = dt.datetime(2026, 11, 5, 7, 0, tzinfo=KST)
SINCE = NOW - dt.timedelta(days=1)


def review(text, score, hours_ago):
    return {"at": NOW - dt.timedelta(hours=hours_ago), "score": score, **collect.classify(text)}


# 4.1
def test_classify_blocked_parking():
    c = collect.classify("주차 정산하려는데 로그인이 계속 풀림")
    assert c["blocked"] and "주차 정산기" in c["places"]
    assert set(c["topics"]) == {"로그인/본인인증", "매장에서 혜택 사용"}


def test_classify_not_blocked_without_app_word():
    c = collect.classify("쿠폰이 너무 적어요")
    assert not c["blocked"] and c["places"] == []


def test_review_blocked_means_alert():
    rows = [review("쿠폰 쓰려는데 앱이 안 열려요", 1, 3)]
    r = judge.rule_reviews(rows, NOW, SINCE)
    assert r["status"] == "확인 필요" and r["blocked_new"] == 1 and r["low_new"] == 1


def test_review_double_of_average_means_alert():
    old = [review("별로", 1, 24 * d) for d in range(3, 31, 3)]  # 4주 안에 9건, 하루 평균 약 0.32건
    new = [review("별로예요", 2, h) for h in (1, 2)]
    r = judge.rule_reviews(old + new, NOW, SINCE)
    assert r["blocked_new"] == 0 and r["low_new"] == 2
    assert r["status"] == "확인 필요"


def test_review_calm_and_high_scores_ignored():
    old = [review("별로", 1, 24 * d) for d in range(2, 29)]  # 하루 약 1건
    rows = old + [review("좋아요", 5, 2), review("별로", 2, 2)]
    r = judge.rule_reviews(rows, NOW, SINCE)
    assert r["low_new"] == 1 and r["status"] == "평소"
    assert len(r["series30"]) == 30 and r["series30"][-1]["date"] == "2026-11-05"


# 4.2
def test_calendar_weekday_sunday_saturday():
    today = dt.date(2026, 11, 5)  # 목요일
    c = judge.rule_calendar(today, {"2026-11-05": 0.0, "2026-11-07": 0.0, "2026-11-08": 0.0}, False)
    d = {x["date"]: x for x in c["days"]}
    assert d["2026-11-05"]["pilots"] == [1] and d["2026-11-05"]["times"] == ["당일 17시"]
    assert d["2026-11-07"]["pilots"] == [] and "31,905" in d["2026-11-07"]["basis"]
    assert d["2026-11-08"]["pilots"] == [2] and "29%" in d["2026-11-08"]["basis"]
    assert all("후보" in c["channel_note"] for _ in [0])


def test_calendar_rainy_weekend_and_no_forecast():
    today = dt.date(2026, 11, 5)
    c = judge.rule_calendar(today, {"2026-11-07": 12.5}, True)
    sat = c["days"][2]
    assert sat["rain"] and sat["pilots"] == [2] and sat["times"] == ["금요일 18시"] and "1.02배" in sat["basis"]
    assert c["days"][0]["pilots"][0] == 3  # 리뷰 확인 필요면 오늘 3번 먼저
    none = judge.rule_calendar(today, None, False)
    assert all(x["rain"] is None and "예보 없음" in x["situation"] for x in none["days"])


def test_calendar_weekday_holiday():
    c = judge.rule_calendar(dt.date(2026, 12, 25), {}, False)
    assert c["days"][0]["holiday"] and "성탄절" in c["days"][0]["situation"]


# 4.3
def fake_sim(lift, optout_sent, n=4000, weeks=10, seed=1):
    rng = np.random.default_rng(seed)
    send = rng.random(n) >= 0.5
    visits = rng.random((n, weeks)) < (0.05 + lift * send)[:, None]
    optout = rng.random((n, weeks)) < np.where(send, optout_sent, 0.003)[:, None]
    return {"send": send, "visits": visits, "optout": optout}


def test_pilot_before_start_and_check_days():
    assert judge.rule_pilot(dt.date(2026, 10, 12), fake_sim(0.03, 0.003))["decision"] == "집계 전"
    p = judge.rule_pilot(dt.date(2026, 11, 9), fake_sim(0.03, 0.003))
    assert p["check_day"] and p["weeks_done"] == 4 and p["virtual"]
    assert not judge.rule_pilot(dt.date(2026, 11, 10), fake_sim(0.03, 0.003))["check_day"]


def test_pilot_final_decisions():
    final_day = dt.date(2026, 12, 21)
    assert judge.rule_pilot(final_day, fake_sim(0.05, 0.003))["decision"] == "넓힌다"
    assert judge.rule_pilot(final_day, fake_sim(0.0, 0.003))["decision"] == "멈춘다"
    assert judge.rule_pilot(final_day, fake_sim(0.05, 0.03))["decision"] == "멈춘다"
    fix = judge.rule_pilot(final_day, fake_sim(0.015, 0.003, n=40000))
    assert fix["new_ratio"] < 25 and fix["decision"] == "고쳐서 다시"


def test_pilot_real_simulation_is_stable():
    a = judge.rule_pilot(dt.date(2026, 11, 9), collect.simulate_pilot())
    b = judge.rule_pilot(dt.date(2026, 11, 9), collect.simulate_pilot())
    assert a == b and a["decision"].endswith("(현재 신호)")


# 4.4
def test_field_from_blocked_parking_and_rainy_holiday():
    rows = [review("주차 정산 하려니 앱이 먹통", 1, 30)]
    r = judge.rule_reviews(rows, NOW, SINCE)
    c = judge.rule_calendar(dt.date(2026, 11, 8), {"2026-11-08": 5.0}, False)
    f = judge.rule_field(r, c)
    places = [i["place"] for i in f["items"]]
    assert places[0] == "주차 정산기" and "문화센터" in places and len(places) <= 3


def test_field_questions_come_from_fixed_list():
    from brief.rules_config import FIELD_CHECKS
    f = judge.rule_field(None, None)
    assert f["items"][0]["place"] == "고객센터"
    assert all(i["check"] == FIELD_CHECKS[i["place"]] for i in f["items"])
