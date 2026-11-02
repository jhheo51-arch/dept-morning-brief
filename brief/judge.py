"""판단 단계. 규칙 4개(PRD 4.1~4.4). 모든 판단에 근거 숫자와 규칙 이름을 붙인다."""
import collections
import datetime as dt
import math

from . import rules_config as C

DOW = "월화수목금토일"


def _z(diff, se):
    return diff / se if se > 0 else 0.0


# 4.1 고객 접점 알림
def rule_reviews(rows, now, since):
    """since 이후 새 리뷰와 지난 4주, 7일, 30일 집계."""
    low = [r for r in rows if r["score"] <= 2]
    new = [r for r in low if r["at"] > since]
    span = max(1, math.ceil((now - since).total_seconds() / 86400))
    base_from = since - dt.timedelta(days=28)
    avg28 = sum(1 for r in low if base_from <= r["at"] <= since) / 28
    week_from = now - dt.timedelta(days=7)
    week = [r for r in low if r["at"] > week_from]
    topics = {t: sum(1 for r in new if t in r["topics"]) for t in C.TOPICS}
    blocked_new = sum(1 for r in new if r["blocked"])
    places = collections.Counter(p for r in week if r["blocked"] for p in r["places"])
    expected = avg28 * span
    alert = blocked_new >= 1 or len(new) > 2 * expected
    reasons = []
    if blocked_new >= 1:
        reasons.append(f"새 막힘 {blocked_new}건(1건 이상)")
    if len(new) > 2 * expected:
        reasons.append(f"새 1~2점 {len(new)}건이 4주 평균의 2배({2 * expected:.1f}건)를 넘음")
    days = [(now.date() - dt.timedelta(days=i)) for i in range(59, -1, -1)]
    daily = [{"date": d.isoformat(),
              "all": sum(1 for r in rows if r["at"].date() == d),
              "low": sum(1 for r in low if r["at"].date() == d),
              "blocked": sum(1 for r in low if r["at"].date() == d and r["blocked"])} for d in days]

    def total(part):
        return {"from": part[0]["date"], "to": part[-1]["date"],
                **{k: sum(x[k] for x in part) for k in ("all", "low", "blocked")}}
    return {
        "rule": "4.1 고객 접점 알림",
        "since": since.strftime("%Y-%m-%d %H:%M"),
        "span_days": span,
        "low_new": len(new),
        "topics_new": topics,
        "blocked_new": blocked_new,
        "avg28_per_day": round(avg28, 2),
        "diff_vs_avg": round(len(new) - expected, 1),
        "low_7d": len(week),
        "blocked_7d": sum(1 for r in week if r["blocked"]),
        "places_7d": dict(places.most_common()),
        "status": "확인 필요" if alert else "평소",
        "reasons": reasons or ["막힘 0건, 새 1~2점이 4주 평균의 2배 이하"],
        "series30": daily[30:],
        "daily60": daily,
        "totals30": total(daily[30:]),
        "totals_prev30": total(daily[:30]),
        "source": "Google Play 공개 리뷰(현대백화점 앱), 포트폴리오 5쪽과 같은 단어 규칙",
    }


# 4.2 이번 주 집객 달력
def _day(d, rain_mm, review_alert, is_today):
    key = d.isoformat()
    dow = d.weekday()
    holiday = dow >= 5 or key in C.HOLIDAYS
    rain = None if rain_mm is None else rain_mm >= C.RAIN_MM
    situation = [f"{DOW[dow]}요일"]
    if key in C.HOLIDAYS:
        situation.append(C.HOLIDAYS[key])
    situation.append("예보 없음" if rain is None else (f"비 {rain_mm}mm" if rain else "비 없음"))
    row = {"date": key, "situation": situation, "holiday": holiday, "rain": rain,
           "pilots": [], "channels": [], "times": [], "benefit": "", "basis": ""}
    if holiday and rain:
        row.update(pilots=[2], channels=[C.CHANNELS[0], C.CHANNELS[1], C.CHANNELS[3]],
                   times=["금요일 18시" if dow >= 5 else "전날 18시"],
                   benefit="실내 행사, 문화센터 원데이 클래스",
                   basis=f"비 온 휴일 여의도역 하차 {C.RAIN_HOLIDAY_RATIO}배(같은 달 휴일 중앙값 대비)")
    elif dow == 6 or (holiday and dow != 5):
        row.update(pilots=[2], channels=[C.CHANNELS[0], C.CHANNELS[2]], times=["전날 18시"],
                   benefit="팝업 마지막 날, 사은행사 마감",
                   basis=f"일요일 하차 {C.SUN_ALIGHT:,}명, 토요일 {C.SAT_ALIGHT:,}명보다 {-C.SUN_VS_SAT}% 적음")
    elif dow == 5:
        row.update(benefit="브랜드 할인",
                   basis=f"토요일 하차 {C.SAT_ALIGHT:,}명으로 휴일 중 가장 많아 따로 부르지 않음")
    else:
        row.update(pilots=[1], channels=[C.CHANNELS[0], C.CHANNELS[2]], times=["당일 17시"],
                   benefit="식품관 저녁 혜택, 문화센터 저녁 클래스",
                   basis=f"평일 17~20시 여의도역 승차 {C.WEEKDAY_EVENING_BOARD:,}명")
    if is_today and review_alert:
        row["pilots"] = [3] + row["pilots"]
        row["basis"] += ". 앱 리뷰 확인 필요라 3번 점검을 먼저 함"
    return row


def rule_calendar(today, weather, review_alert):
    """weather: 날짜별 낮 강수 합. 수집에 실패했으면 None."""
    rows = [_day(today + dt.timedelta(days=i), None if weather is None else weather.get(
        (today + dt.timedelta(days=i)).isoformat()), review_alert, i == 0) for i in range(7)]
    return {
        "rule": "4.2 이번 주 집객 달력",
        "days": rows,
        "channel_note": C.CHANNEL_NOTE,
        "rain_rule": f"낮(10~20시) 강수 {C.RAIN_MM}mm 이상이면 비 온 날",
        "source": "Open-Meteo 7일 예보(CC BY 4.0), 공휴일 인사혁신처, 하차와 승차는 포트폴리오 4쪽 집계 상수",
    }


# 4.3 시범 점검(가상)
def rule_pilot(today, sim):
    weeks_done = min((today - C.PILOT_START).days // 7, C.PILOT_WEEKS)
    check_day = any(today == C.PILOT_START + dt.timedelta(weeks=w) for w in C.CHECK_WEEKS)
    if weeks_done <= 0:
        label = "집계 전"
    elif check_day:
        label = f"{weeks_done}주차 점검일"
    else:
        label = f"{weeks_done}주 누적"
    out = {"rule": "4.3 시범 점검", "virtual": True, "start": C.PILOT_START.isoformat(),
           "week_label": label, "weeks_done": weeks_done, "check_day": check_day,
           "source": "가상 데이터(SEED 2026, 가상 회원 2만 명, 방문 확률은 설정값), 본전 25%는 가정값"}
    if weeks_done <= 0:
        out.update(decision="집계 전", reasons=["첫 주가 끝나지 않음"])
        return out
    send = sim["send"]
    v = sim["visits"][:, :weeks_done].sum(axis=1)
    o = sim["optout"][:, :weeks_done].any(axis=1)
    vs, vh = v[send], v[~send]
    diff = vs.mean() - vh.mean()
    z_visit = _z(diff, math.sqrt(vs.var(ddof=1) / len(vs) + vh.var(ddof=1) / len(vh)))
    new_ratio = diff / vs.mean() if vs.mean() > 0 else 0.0
    os_, oh = o[send].mean(), o[~send].mean()
    p = o.mean()
    z_out = _z(os_ - oh, math.sqrt(p * (1 - p) * (1 / len(vs) + 1 / len(vh))))
    sig_visit, sig_out = z_visit > 1.96, z_out > 1.645
    if sig_out:
        decision, why = "멈춘다", f"수신 거부가 남겨 둔 회원보다 높음(z {z_out:.2f})"
    elif not sig_visit:
        decision, why = "멈춘다", f"방문 차이가 유의하지 않음(z {z_visit:.2f})"
    elif new_ratio > C.BREAKEVEN:
        decision, why = "넓힌다", f"방문 차이 유의(z {z_visit:.2f}), 새 방문 비율이 본전 25%를 넘음"
    else:
        decision, why = "고쳐서 다시", f"방문 차이 유의(z {z_visit:.2f}), 새 방문 비율이 본전 25% 아래"
    final = weeks_done >= C.PILOT_WEEKS
    reasons = [why]
    if not final:
        reasons.append(f"최종 판단은 {C.PILOT_WEEKS}주차 끝, 지금은 {weeks_done}주 누적 신호")
    if weeks_done >= 4 and os_ > oh:
        reasons.append("4주차 점검 기준: 수신 거부가 남겨 둔 회원보다 높아 푸시를 격주로 줄임")
    out.update(
        sent=int(send.sum()), hold=int((~send).sum()),
        visits_per_member_sent=round(float(vs.mean()), 3), visits_per_member_hold=round(float(vh.mean()), 3),
        visit_diff=round(float(diff), 3), z_visit=round(z_visit, 2),
        new_ratio=round(float(new_ratio) * 100, 1), breakeven=round(C.BREAKEVEN * 100),
        optout_sent=round(float(os_) * 100, 2), optout_hold=round(float(oh) * 100, 2), z_optout=round(z_out, 2),
        decision=decision if final else f"{decision}(현재 신호)", final=final, reasons=reasons)
    return out


# 4.4 오늘 현장 점검 목록
def rule_field(review, calendar):
    items = []
    if review:
        for place, n in list(review.get("places_7d", {}).items())[:2]:
            items.append({"place": place, "check": C.FIELD_CHECKS[place],
                          "why": f"지난 7일 막힘 리뷰 {n}건에 관련 단어"})
    if calendar:
        t = calendar["days"][0]
        dow = dt.date.fromisoformat(t["date"]).weekday()
        if t["holiday"] and t["rain"]:
            place, why = "문화센터", "오늘 비 오는 휴일(실내 행사 후보)"
        elif t["holiday"] and dow == 6:
            place, why = "팝업 행사장", "오늘 일요일(6쪽 2번)"
        elif not t["holiday"]:
            place, why = "지하 연결 입구", "오늘 평일, 17~20시 퇴근길(6쪽 1번)"
        else:
            place = None
        if place:
            items.append({"place": place, "check": C.FIELD_CHECKS[place], "why": why})
    if review and review.get("status") == "확인 필요" and not any(i["place"] == "고객센터" for i in items):
        items.append({"place": "고객센터", "check": C.FIELD_CHECKS["고객센터"], "why": "앱 리뷰 확인 필요(6쪽 3번)"})
    if not items:
        items.append({"place": "고객센터", "check": C.FIELD_CHECKS["고객센터"], "why": "기본 점검(6쪽 3번)"})
    return {"rule": "4.4 오늘 현장 점검 목록", "items": items[:3],
            "source": "4.1과 4.2 결과, 점검 질문은 코드의 고정 목록"}
