"""판단 단계. 모든 판단에 근거 숫자와 규칙 이름을 붙인다. 기준값은 config.toml 에서 읽는다."""
import collections
import datetime as dt
import math

from . import inputs as I
from . import rules_config as C

DOW = "월화수목금토일"


def _z(diff, se):
    return diff / se if se > 0 else 0.0


def _pct(a, b):
    return round(a / b * 100, 1) if a is not None and b else None


def _growth(a, b):
    return round((a / b - 1) * 100, 1) if a is not None and b else None


def _won(n):
    """원 단위 금액을 읽기 쉬운 단위로. 1억 이상은 억, 그 밖은 만 원."""
    if n is None:
        return "-"
    if abs(n) >= 1e8:
        return f"{n / 1e8:,.1f}억 원"
    return f"{n / 1e4:,.0f}만 원"


def _src(file):
    return f"{file}(가상 시연 파일)" if C.SAMPLE else f"{file}(내 파일)"


# 매출 현황
def rule_sales(rows, today):
    """rows: inputs/sales 파일. 가장 최근 날짜(오늘 전)의 전체 매출을 목표와 전년에 견준다."""
    recs = []
    for r in rows:
        d = I.to_date(r["날짜"], r, "날짜")
        part = str(r["구분"] or "").strip()
        if not part:
            raise I.InputError(f"{I.where(r)} '구분' 값이 비어 있습니다")
        recs.append({"date": d, "part": part, "sales": I.to_num(r["매출"], r, "매출"),
                     "target": I.to_num(r.get("목표"), r, "목표", required=False),
                     "prev": I.to_num(r.get("전년"), r, "전년", required=False)})
    recs = [x for x in recs if x["date"] < today]
    if not recs:
        raise I.InputError("sales 파일에 오늘 전 날짜의 매출이 없습니다")
    total_name = C.SALES.get("total_name", "전체")
    by_day = collections.defaultdict(dict)
    for x in recs:
        by_day[x["date"]][x["part"]] = x

    def total_of(day):
        parts = by_day[day]
        if total_name in parts:
            return parts[total_name]
        vals = list(parts.values())

        def add(k):
            got = [v[k] for v in vals if v[k] is not None]
            return sum(got) if len(got) == len(vals) else None
        return {"date": day, "part": total_name, "sales": add("sales"), "target": add("target"), "prev": add("prev")}

    def metrics(x):
        return {"sales": x["sales"], "sales_text": _won(x["sales"]), "target": x["target"], "prev": x["prev"],
                "achieve_pct": _pct(x["sales"], x["target"]), "yoy_pct": _growth(x["sales"], x["prev"])}

    def sum_of(xs):
        out = {}
        for k in ("sales", "target", "prev"):
            got = [x[k] for x in xs if x[k] is not None]
            out[k] = sum(got) if got and len(got) == len(xs) else None
        return out

    day = max(by_day)
    days = sorted(by_day)
    totals = {d: total_of(d) for d in days}
    yoy_thr, tgt_thr = C.SALES.get("yoy_alert_pct", -10), C.SALES.get("target_alert_pct", 90)
    t = metrics(totals[day])
    mtd = metrics(sum_of([totals[d] for d in days if d.year == day.year and d.month == day.month]))
    last7 = metrics(sum_of([totals[d] for d in days if day - dt.timedelta(days=6) <= d <= day]))

    def flags(m):
        f = []
        if m["yoy_pct"] is not None and m["yoy_pct"] <= yoy_thr:
            f.append(f"전년 대비 {m['yoy_pct']}%(기준 {yoy_thr}% 이하)")
        if m["achieve_pct"] is not None and m["achieve_pct"] < tgt_thr:
            f.append(f"목표 달성 {m['achieve_pct']}%(기준 {tgt_thr}% 미만)")
        return f
    reasons = flags(t)
    parts = []
    for name, x in sorted(by_day[day].items(), key=lambda kv: -(kv[1]["sales"] or 0)):
        if name == total_name:
            continue
        m = metrics(x)
        parts.append({"part": name, **m, "flags": flags(m)})
    if last7["yoy_pct"] is not None and last7["yoy_pct"] <= yoy_thr:
        reasons.append(f"최근 7일 전년 대비 {last7['yoy_pct']}%")
    series = [{"date": d.isoformat(), "sales": totals[d]["sales"], "prev": totals[d]["prev"],
               "target": totals[d]["target"]} for d in days[-30:]]
    return {
        "rule": "매출 현황",
        "date": day.isoformat(),
        "stale_days": (today - day).days,
        "total": t, "mtd": mtd, "last7": last7,
        "parts": parts,
        "parts_flagged": [p["part"] for p in parts if p["flags"]],
        "status": "확인 필요" if reasons else "평소",
        "reasons": reasons or [f"전년 대비 {yoy_thr}% 초과, 목표 {tgt_thr}% 이상"],
        "series30": series,
        "yoy_alert_pct": yoy_thr, "target_alert_pct": tgt_thr,
        "rule_text": f"어제 또는 최근 7일 전년 대비 {yoy_thr}% 이하, 어제 목표 달성 {tgt_thr}% 미만이면 확인 필요",
        "source": _src(rows[0]["_file"]),
    }


# 프로모션과 이벤트 점검
def rule_promos(rows, today):
    look, ready = C.PROMO.get("lookahead_days", 7), C.PROMO.get("vmd_ready_days", 3)
    done = set(C.PROMO.get("done_words", ["완료"]))
    items = []
    for r in rows:
        name = str(r["행사명"] or "").strip()
        if not name:
            raise I.InputError(f"{I.where(r)} '행사명' 값이 비어 있습니다")
        s, e = I.to_date(r["시작일"], r, "시작일"), I.to_date(r["종료일"], r, "종료일")
        if e < s:
            raise I.InputError(f"{I.where(r)} 종료일이 시작일보다 앞섭니다")
        if e < today or (s - today).days > look:
            continue
        vmd = str(r.get("VMD 상태") or "").strip()
        ch = str(r.get("알릴 길") or "").strip()
        if s > today:
            phase = f"D-{(s - today).days} 시작"
        elif s == today:
            phase = "오늘 시작"
        elif e == today:
            phase = "오늘 종료"
        else:
            phase = f"진행 중, 종료 D-{(e - today).days}"
        warns = []
        if (s - today).days <= ready and vmd not in done:
            warns.append(f"VMD {vmd or '상태 미기재'}" + (f"(시작 D-{(s - today).days}, 기준 D-{ready})" if s > today
                                                     else "(이미 시작)"))
        if not ch:
            warns.append("알릴 길 미정")
        if 0 < (e - today).days <= 1 and s < today:
            warns.append("내일 종료, 마감 안내 확인")
        items.append({"name": name, "start": s.isoformat(), "end": e.isoformat(), "phase": phase,
                      "place": r.get("장소") or "", "channel": ch, "vmd": vmd, "owner": r.get("담당") or "",
                      "memo": r.get("메모") or "", "warns": warns})
    items.sort(key=lambda x: (not x["warns"], x["start"]))
    warned = [i for i in items if i["warns"]]
    return {
        "rule": "프로모션 점검",
        "items": items,
        "running": sum(1 for i in items if i["start"] <= today.isoformat()),
        "upcoming": sum(1 for i in items if i["start"] > today.isoformat()),
        "warn_count": len(warned),
        "status": "확인 필요" if warned else "평소",
        "rule_text": f"시작 D-{ready}까지 VMD가 {', '.join(sorted(done))} 이 아니면 경고, 알릴 길이 비면 경고, {look}일 안 시작까지 봄",
        "source": _src(rows[0]["_file"]) if rows else "행사 파일",
    }


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
    mult, nblock = C.ALERT_MULTIPLE, C.ALERT_BLOCKED
    over_block, over_avg = blocked_new >= nblock, len(new) > mult * expected
    reasons = []
    if over_block:
        reasons.append(f"새 막힘 {blocked_new}건({nblock}건 이상)")
    if over_avg:
        reasons.append(f"새 1~2점 {len(new)}건이 4주 평균의 {mult:g}배({mult * expected:.1f}건)를 넘음")
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
        "app_name": C.APP_NAME,
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
        "status": "확인 필요" if reasons else "평소",
        "reasons": reasons or [f"막힘 {nblock}건 미만, 새 1~2점이 4주 평균의 {mult:g}배 이하"],
        "rule_text": f"막힘 {nblock}건 이상 또는 4주 평균의 {mult:g}배 초과면 확인 필요",
        "series30": daily[30:],
        "daily60": daily,
        "totals30": total(daily[30:]),
        "totals_prev30": total(daily[:30]),
        "source": f"Google Play 공개 리뷰({C.APP_NAME}), 포트폴리오 5쪽과 같은 단어 규칙",
    }


# 4.2 이번 주 집객 달력
def _channels(*idx):
    return [C.CHANNELS[i] for i in idx if i < len(C.CHANNELS)]


def _day(d, rain_mm, review_alert, is_today):
    key = d.isoformat()
    dow = d.weekday()
    hname = C.holiday_name(d)
    holiday = dow >= 5 or hname is not None
    rain = None if rain_mm is None else rain_mm >= C.RAIN_MM
    situation = [f"{DOW[dow]}요일"]
    if hname:
        situation.append(hname)
    situation.append("예보 없음" if rain is None else (f"비 {rain_mm}mm" if rain else "비 없음"))
    row = {"date": key, "situation": situation, "holiday": holiday, "rain": rain,
           "pilots": [], "channels": [], "times": [], "benefit": "", "basis": ""}
    cal = C.CAL
    if holiday and rain:
        # 주말 비 예보는 금요일 저녁에 미리 알린다
        row.update(pilots=[2], channels=_channels(0, 1, 3),
                   times=["금요일 18시" if dow >= 5 else cal["sunday_time"]],
                   benefit=cal["rain_benefit"], basis=cal["rain_holiday_basis"])
    elif dow == 6 or (holiday and dow != 5):
        row.update(pilots=[2], channels=_channels(0, 2), times=[cal["sunday_time"]],
                   benefit=cal["sunday_benefit"], basis=cal["sunday_basis"])
    elif dow == 5:
        row.update(benefit=cal["saturday_benefit"], basis=cal["saturday_basis"])
    else:
        row.update(pilots=[1], channels=_channels(0, 2), times=[cal["weekday_time"]],
                   benefit=cal["weekday_benefit"], basis=cal["weekday_basis"])
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
        "pilot_names": {str(k): v for k, v in C.PILOTS.items()},
        "channel_note": C.CHANNEL_NOTE,
        "rain_rule": f"낮(10~20시) 강수 {C.RAIN_MM}mm 이상이면 비 온 날",
        "source": "Open-Meteo 7일 예보(CC BY 4.0), 공휴일은 holidays 라이브러리(대한민국), 요일 근거는 설정 파일 문장",
    }


# 4.3 시범 점검
def pilot_from_sim(sim, weeks_done):
    send = sim["send"]
    v = sim["visits"][:, :weeks_done].sum(axis=1)
    o = sim["optout"][:, :weeks_done].any(axis=1)
    vs, vh = v[send], v[~send]
    return {"n_sent": len(vs), "n_hold": len(vh), "mean_sent": float(vs.mean()), "mean_hold": float(vh.mean()),
            "se": math.sqrt(vs.var(ddof=1) / len(vs) + vh.var(ddof=1) / len(vh)),
            "out_sent": float(o[send].mean()), "out_hold": float(o[~send].mean())}


def pilot_from_weekly(rows):
    """inputs/pilot_weekly 집계로 같은 통계를 만든다. 회원별 자료가 없어 방문 수 분산은 포아송(평균=분산) 가정."""
    g = {"sent": {}, "hold": {}}
    for r in rows:
        w = int(I.to_num(r["주차"], r, "주차"))
        g[I.group_of(r["그룹"], r)][w] = {"n": I.to_num(r["회원수"], r, "회원수"),
                                         "v": I.to_num(r["방문 횟수"], r, "방문 횟수"),
                                         "o": I.to_num(r.get("수신 거부"), r, "수신 거부", required=False) or 0}
    weeks = sorted(set(g["sent"]) & set(g["hold"]))
    if not weeks:
        raise I.InputError("pilot_weekly 파일에 '받음'과 '남겨둠'이 함께 있는 주차가 없습니다")
    if weeks != list(range(1, weeks[-1] + 1)):
        raise I.InputError(f"pilot_weekly 주차가 1부터 이어지지 않습니다: {weeks}")
    st = {}
    for k in ("sent", "hold"):
        n = g[k][weeks[0]]["n"]
        st[k] = (n, sum(g[k][w]["v"] for w in weeks) / n, sum(g[k][w]["o"] for w in weeks) / n)
    (ns, ms, os_), (nh, mh, oh) = st["sent"], st["hold"]
    return len(weeks), {"n_sent": ns, "n_hold": nh, "mean_sent": ms, "mean_hold": mh,
                        "se": math.sqrt(ms / ns + mh / nh), "out_sent": os_, "out_hold": oh}


def rule_pilot(today, sim=None, weekly=None):
    """weekly(내 시범 집계)가 있으면 그것으로, 없으면 가상 시범(sim)으로 판단한다."""
    virtual = weekly is None
    if virtual:
        weeks_done = min((today - C.PILOT_START).days // 7, C.PILOT_WEEKS)
        check_day = any(today == C.PILOT_START + dt.timedelta(weeks=w) for w in C.CHECK_WEEKS)
    else:
        weeks_done, stats = pilot_from_weekly(weekly)
        weeks_done = min(weeks_done, C.PILOT_WEEKS)
        check_day = weeks_done in C.CHECK_WEEKS
    if weeks_done <= 0:
        label = "집계 전"
    elif check_day:
        label = f"{weeks_done}주차 점검일"
    else:
        label = f"{weeks_done}주 누적"
    be = round(C.BREAKEVEN * 100)
    out = {"rule": "4.3 시범 점검", "virtual": virtual, "start": C.PILOT_START.isoformat(),
           "week_label": label, "weeks_done": weeks_done, "check_day": check_day, "check_weeks": list(C.CHECK_WEEKS),
           "source": (f"가상 데이터(SEED 2026, 가상 회원 2만 명, 방문 확률은 설정값), 본전 {be}%는 가정값" if virtual
                      else f"{_src(weekly[0]['_file'])}, 주별 집계라 방문 수 분산은 포아송 가정, 본전 {be}%는 설정값")}
    if weeks_done <= 0:
        out.update(decision="집계 전", reasons=["첫 주가 끝나지 않음"])
        return out
    if virtual:
        stats = pilot_from_sim(sim, weeks_done)
    ns, nh, ms, mh = stats["n_sent"], stats["n_hold"], stats["mean_sent"], stats["mean_hold"]
    diff = ms - mh
    z_visit = _z(diff, stats["se"])
    new_ratio = diff / ms if ms > 0 else 0.0
    os_, oh = stats["out_sent"], stats["out_hold"]
    p = (os_ * ns + oh * nh) / (ns + nh)
    z_out = _z(os_ - oh, math.sqrt(p * (1 - p) * (1 / ns + 1 / nh)))
    sig_visit, sig_out = z_visit > 1.96, z_out > 1.645
    if sig_out:
        decision, why = "멈춘다", f"수신 거부가 남겨 둔 회원보다 높음(z {z_out:.2f})"
    elif not sig_visit:
        decision, why = "멈춘다", f"방문 차이가 유의하지 않음(z {z_visit:.2f})"
    elif new_ratio > C.BREAKEVEN:
        decision, why = "넓힌다", f"방문 차이 유의(z {z_visit:.2f}), 새 방문 비율이 본전 {be}%를 넘음"
    else:
        decision, why = "고쳐서 다시", f"방문 차이 유의(z {z_visit:.2f}), 새 방문 비율이 본전 {be}% 아래"
    final = weeks_done >= C.PILOT_WEEKS
    reasons = [why]
    if not final:
        reasons.append(f"최종 판단은 {C.PILOT_WEEKS}주차 끝, 지금은 {weeks_done}주 누적 신호")
    if weeks_done >= 4 and os_ > oh:
        reasons.append("4주차 점검 기준: 수신 거부가 남겨 둔 회원보다 높아 푸시를 격주로 줄임")
    out.update(
        sent=int(ns), hold=int(nh),
        visits_per_member_sent=round(ms, 3), visits_per_member_hold=round(mh, 3),
        visit_diff=round(diff, 3), z_visit=round(z_visit, 2),
        new_ratio=round(new_ratio * 100, 1), breakeven=be,
        optout_sent=round(os_ * 100, 2), optout_hold=round(oh * 100, 2), z_optout=round(z_out, 2),
        decision=decision if final else f"{decision}(현재 신호)", final=final, reasons=reasons)
    return out


# 4.4 오늘 현장 점검 목록
def _last_visits(log, today, skipped):
    """접점별 마지막 방문일과 그때 결과. 설정에 없는 접점 줄은 건너뛰고 skipped 에 적는다."""
    last = {}
    for r in log or []:
        place = str(r["접점"] or "").strip()
        if place not in C.FIELD_CHECKS:
            skipped.append(f"{I.where(r)} 접점 '{place}': 설정에 없어 건너뜀")
            continue
        d = I.to_date(r["날짜"], r, "날짜")
        if d > today:
            continue
        if place not in last or d >= last[place]["date"]:
            last[place] = {"date": d, "result": str(r.get("결과") or "정상").strip(), "memo": r.get("메모") or ""}
    return last


def rule_field(review, calendar, log=None, today=None):
    items = []

    def add(place, why):
        if place and place in C.FIELD_CHECKS and not any(i["place"] == place for i in items):
            items.append({"place": place, "check": C.FIELD_CHECKS[place], "why": why})

    skipped = []
    last = _last_visits(log, today, skipped) if log is not None and today else {}
    if review:
        for place, n in list(review.get("places_7d", {}).items())[:2]:
            add(place, f"지난 7일 막힘 리뷰 {n}건에 관련 단어")
    for place, x in sorted(last.items(), key=lambda kv: kv[1]["date"]):
        if x["result"] in ("문제", "해결 중"):
            add(place, f"{x['date'].isoformat()} 방문 때 결과 '{x['result']}', 다시 확인")
    f = C.FIELD
    if calendar:
        t = calendar["days"][0]
        dow = dt.date.fromisoformat(t["date"]).weekday()
        if t["holiday"] and t["rain"]:
            add(f.get("rain_holiday_place"), "오늘 비 오는 휴일(실내 행사 후보)")
        elif t["holiday"] and dow == 6:
            add(f.get("sunday_place"), f"오늘 일요일(시범 2번 {C.PILOTS.get(2, '')})")
        elif not t["holiday"]:
            add(f.get("weekday_place"), f"오늘 평일(시범 1번 {C.PILOTS.get(1, '')})")
    if review and review.get("status") == "확인 필요":
        add(f.get("alert_place"), "앱 리뷰 확인 필요(시범 3번)")
    if log is not None and today:
        every = {t["name"]: t.get("every_days") for t in f["touchpoints"]}
        due = []
        for place, n in every.items():
            if not n:
                continue
            seen = last.get(place, {}).get("date")
            gap = (today - seen).days if seen else None
            if gap is None or gap > n:
                due.append((-(gap or 10**6), place, f"{gap}일째 방문 기록 없음(주기 {n}일)" if gap
                            else f"방문 기록 없음(주기 {n}일)"))
        for _, place, why in sorted(due):
            add(place, why)
    if not items:
        add(f.get("alert_place"), "기본 점검")
    return {"rule": "4.4 오늘 현장 점검 목록", "items": items[:f.get("max_items", 3)],
            "logged": log is not None, "skipped": skipped,
            "last_visits": {k: {"date": v["date"].isoformat(), "result": v["result"]} for k, v in last.items()},
            "source": "리뷰와 달력 결과, 현장 기록(field_log), 점검 질문은 설정 파일의 고정 목록"}
