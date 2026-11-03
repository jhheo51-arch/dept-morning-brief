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
def sales_by_day(rows, today):
    """sales 파일을 {날짜: {구분: 값}} 으로. 오늘(마감 전)은 뺀다."""
    recs = []
    for r in rows:
        d = I.to_date(r["날짜"], r, "날짜")
        part = str(r["구분"] or "").strip()
        if not part:
            raise I.InputError(f"{I.where(r)} '구분' 값이 비어 있습니다")
        recs.append({"date": d, "part": part, "sales": I.to_num(r["매출"], r, "매출"),
                     "target": I.to_num(r.get("목표"), r, "목표", required=False),
                     "prev": I.to_num(r.get("전년"), r, "전년", required=False)})
    by_day = collections.defaultdict(dict)
    for x in recs:
        if x["date"] < today:
            by_day[x["date"]][x["part"]] = x
    return by_day


def total_of(by_day, day):
    """그날 전체 매출. 파일에 전체 구분이 없으면 나머지 구분을 더한다."""
    total_name = C.SALES.get("total_name", "전체")
    parts = by_day.get(day, {})
    if total_name in parts:
        return parts[total_name]
    vals = list(parts.values())

    def add(k):
        got = [v[k] for v in vals if v[k] is not None]
        return sum(got) if vals and len(got) == len(vals) else None
    return {"date": day, "part": total_name, "sales": add("sales"), "target": add("target"), "prev": add("prev")}


def rule_sales(rows, today):
    """rows: inputs/sales 파일. 가장 최근 날짜(오늘 전)의 전체 매출을 목표와 전년에 견준다."""
    by_day = sales_by_day(rows, today)
    if not by_day:
        raise I.InputError("sales 파일에 오늘 전 날짜의 매출이 없습니다")
    total_name = C.SALES.get("total_name", "전체")

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
    totals = {d: total_of(by_day, d) for d in days}
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
    # 어제 매출이 최근 같은 요일 평균의 일부뿐이면 중간 집계 파일일 수 있다. 이때는 구분별 경고를 내지 않고 파일부터 묻는다
    partial_pct = C.SALES.get("partial_pct", 50)
    same = [totals[d]["sales"] for d in days if d < day and (day - d).days % 7 == 0 and (day - d).days <= 28
            and totals[d]["sales"]]
    partial = None
    if same and t["sales"] is not None and t["sales"] < sum(same) / len(same) * partial_pct / 100:
        partial = round(t["sales"] / (sum(same) / len(same)) * 100, 1)
        reasons = [f"{day.month}/{day.day} 매출이 최근 같은 요일 평균의 {partial}%라 집계가 덜 된 파일일 수 있습니다. "
                   "새 파일을 받아 다시 돌려 주세요"]
    parts = []
    for name, x in sorted(by_day[day].items(), key=lambda kv: -(kv[1]["sales"] or 0)):
        if name == total_name:
            continue
        m = metrics(x)
        # 구분 최근 7일. 하루치 하락인지 이어지는 하락인지 가르는 데 쓴다. 7일이 다 있을 때만 센다
        w = [by_day[d][name] for d in days if day - dt.timedelta(days=6) <= d <= day and name in by_day[d]]
        parts.append({"part": name, **m, "flags": [] if partial else flags(m),
                      "last7_yoy_pct": metrics(sum_of(w))["yoy_pct"] if len(w) == 7 else None})
    if not partial and last7["yoy_pct"] is not None and last7["yoy_pct"] <= yoy_thr:
        reasons.append(f"최근 7일 전년 대비 {last7['yoy_pct']}%")
    series = [{"date": d.isoformat(), "sales": totals[d]["sales"], "prev": totals[d]["prev"],
               "target": totals[d]["target"]} for d in days[-30:]]
    return {
        "rule": "매출 현황",
        "date": day.isoformat(),
        "stale_days": (today - day).days,
        "partial_pct": partial,
        "total": t, "mtd": mtd, "last7": last7,
        "parts": parts,
        "parts_flagged": [p["part"] for p in parts if p["flags"]],
        # 세 단계. 전체가 기준을 넘으면 확인 필요, 전체는 괜찮고 구분만 넘으면 구분 확인. 화면, 요약, 기록이 모두 이 값을 쓴다
        "status": "확인 필요" if reasons else ("구분 확인" if any(p["flags"] for p in parts) else "평소"),
        "reasons": reasons or [f"전체는 전년 대비 {yoy_thr}% 초과, 목표 {tgt_thr}% 이상"
                            + (". 기준을 넘은 구분은 아래 표의 볼 점" if any(p["flags"] for p in parts) else "")],
        "series30": series,
        "yoy_alert_pct": yoy_thr, "target_alert_pct": tgt_thr,
        "rule_text": f"어제 또는 최근 7일 전년 대비 {yoy_thr}% 이하, 어제 목표 달성 {tgt_thr}% 미만이면 확인 필요. "
                     f"전체는 괜찮고 구분 하나라도 같은 기준을 넘으면 구분 확인. "
                     f"어제가 최근 같은 요일 평균의 {partial_pct}% 미만이면 덜 된 집계로 보고 구분 경고를 멈춤",
        "unit_note": I.unit_note(rows),
        "source": _src(rows[0]["_file"]) + (f". {I.unit_note(rows)}" if I.unit_note(rows) else ""),
    }


# 프로모션과 이벤트 점검
def rule_promos(rows, today):
    look, ready = C.PROMO.get("lookahead_days", 7), C.PROMO.get("vmd_ready_days", 3)
    done = C.PROMO.get("done_words", ["완료"])
    not_started = C.PROMO.get("not_started_words", ["요청 전"])
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
        is_done = I.is_done(vmd, done)
        if not is_done and (s - today).days <= ready:
            warns.append(f"VMD {vmd or '상태 미기재'}" + (f"(시작 D-{(s - today).days}, 기준 D-{ready})" if s > today
                                                     else "(이미 시작)"))
        elif not is_done and any(w in vmd for w in not_started):
            warns.append(f"VMD {vmd}(시작 D-{(s - today).days}, 지금 요청해야 D-{ready}까지 끝남)")
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
        "rule_text": f"시작 D-{ready}까지 VMD 상태에 {', '.join(done)} 이 없으면 경고, {', '.join(not_started)} 이면 바로 경고, "
                     f"알릴 길이 비면 경고, {look}일 안 시작까지 봄",
        "source": _src(rows[0]["_file"]) if rows else "행사 파일",
    }


def rule_tasks(rows, today):
    """업무 목록. 상태에 완료 단어가 있으면 보관으로 넘기고, 열린 업무는 기한 순으로 세운다."""
    done = C.TASKS.get("done_words", ["완료"])
    soon = C.TASKS.get("soon_days", 3)
    items, closed = [], []
    for r in rows:
        name = str(r["업무"] or "").strip()
        if not name:
            raise I.InputError(f"{I.where(r)} '업무' 값이 비어 있습니다")
        due = I.to_day(r["기한"], r, "기한", today) if str(r.get("기한") or "").strip() else None
        state = str(r.get("상태") or "").strip()
        base = {"name": name, "due": due.isoformat() if due else None, "state": state, "owner": str(r.get("담당") or "").strip(),
                "promo": str(r.get("관련 행사") or "").strip(), "memo": str(r.get("메모") or "").strip()}
        if I.is_done(state, done):
            fin = I.to_day(r["완료일"], r, "완료일", today) if r.get("완료일") else None
            closed.append(dict(base, done_on=fin.isoformat() if fin else None))
            continue
        left = (due - today).days if due else None
        if left is None:  # 기한을 아직 못 정한 일은 경고 없이 맨 뒤에 둔다
            phase, warn = "기한 없음", False
        elif left < 0:
            phase, warn = f"기한 지남 {-left}일", True
        elif left == 0:
            phase, warn = "오늘 마감", True
        else:
            phase, warn = f"D-{left}", False
        items.append(dict(base, phase=phase, left=left, warn=warn, soon=left is not None and left <= soon))
    items.sort(key=lambda x: (x["due"] is None, x["due"] or "", x["name"]))
    dated = [i for i in items if i["left"] is not None]
    late = [i for i in dated if i["left"] < 0]
    return {
        "rule": "업무 목록",
        "items": items,
        "closed_now": closed,
        "overdue": len(late),
        "due_today": sum(1 for i in dated if i["left"] == 0),
        "soon": sum(1 for i in dated if 0 < i["left"] <= soon),
        "no_due": len(items) - len(dated),
        "status": "확인 필요" if any(i["warn"] for i in items) else "평소",
        "rule_text": f"기한이 지났거나 오늘이면 확인 필요, {soon}일 안이면 앞에 표시, "
                     f"상태에 {', '.join(done)} 이 있으면 보관",
        "source": _src(rows[0]["_file"]) if rows else "업무 파일",
    }


def _days_apart(a, b):
    if not a or not b:
        return 0 if a == b else 99
    return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)


def merge_task_archive(archive, tasks, today):
    """완료 업무를 보관 목록에 쌓는다. 엑셀에서 행을 지워도 남고, 상태를 다시 비우면 보관에서 뺀다."""
    keep = C.TASKS.get("archive_days", 90)
    box = {(a["name"], a["due"]): a for a in archive}
    for i in tasks["items"]:
        box.pop((i["name"], i["due"]), None)
    for c in tasks["closed_now"]:
        old = box.get((c["name"], c["due"]), {})
        if not old:  # 완료한 뒤 기한만 고친 경우. 같은 이름에 기한 차이가 7일 미만이면 같은 업무로 본다(매주 하는 일은 따로 남음)
            for k, a in list(box.items()):
                if k[0] == c["name"] and _days_apart(a["due"], c["due"]) < 7:
                    old = box.pop(k)
                    break
        box[(c["name"], c["due"])] = dict(c, done_on=c["done_on"] or old.get("done_on") or today.isoformat())
    cut = (today - dt.timedelta(days=keep)).isoformat()
    return sorted((a for a in box.values() if a["done_on"] >= cut), key=lambda a: (a["done_on"], a["name"]),
                  reverse=True)


# 행사 경고 종류별로 업무 이름에 이 말이 있으면 그 경고를 다루는 업무로 본다
TASK_LINK = {"VMD": ("VMD", "진열"), "알릴 길": ("알릴 길", "채널", "푸시", "문자", "배너"),
             "마감": ("마감 안내", "마감")}


def _warn_kind(w):
    return "VMD" if w.startswith("VMD") else "알릴 길" if w.startswith("알릴 길") else "마감" if "마감" in w else None


def link_tasks(promos, tasks, archive):
    """행사 경고와 업무를 잇는다. 관련 행사가 같고 업무 이름에 경고 종류의 말이 있으면 같은 일로 본다.
    끝낸 업무가 있으면 그 경고는 '처리함'으로 내리고, 열린 업무가 있으면 행사 줄에 그 업무와 기한을 붙인다."""
    if not promos or not tasks:
        return promos
    open_ = tasks["items"]
    done = list(tasks.get("closed_now", [])) + [a for a in archive or []
                                                if (a["name"], a["due"]) not in {(c["name"], c["due"]) for c in
                                                                                 tasks.get("closed_now", [])}]

    def match(t, promo, kind):
        rel = t.get("promo") or ""
        return rel and (rel == promo or rel in promo or promo in rel) and any(w in t["name"] for w in TASK_LINK[kind])
    for i in promos["items"]:
        keep, handled, linked = [], [], []
        for w in i["warns"]:
            kind = _warn_kind(w)
            fin = next((t for t in done if kind and match(t, i["name"], kind)), None)
            if fin:
                handled.append(f"{w.split('(')[0]}: 업무 '{fin['name']}' 완료로 처리함")
                continue
            keep.append(w)
            for t in open_:
                if kind and match(t, i["name"], kind):
                    line = f"업무 '{t['name']}' {t['phase']}" + (f", {t['owner']}" if t["owner"] else "")
                    if line not in linked:
                        linked.append(line)
        i["warns"], i["handled"], i["tasks"] = keep, handled, linked
    promos["items"].sort(key=lambda x: (not x["warns"], x["start"]))
    promos["warn_count"] = sum(1 for i in promos["items"] if i["warns"])
    promos["status"] = "확인 필요" if promos["warn_count"] else "평소"
    return promos


def rule_promo_results(promo_rows, sales_rows, today):
    """시작한 행사의 기간 매출(어제까지)을 바로 앞 같은 요일 기간과 견준다. 매출 구분이 있으면 그 구분만 본다."""
    keep, low = C.PROMO.get("result_days", 14), C.PROMO.get("result_low_pct", -5)
    total_name = C.SALES.get("total_name", "전체")
    by_day = sales_by_day(sales_rows, today)
    items = []
    for r in promo_rows:
        s, e = I.to_date(r["시작일"], r, "시작일"), I.to_date(r["종료일"], r, "종료일")
        last = min(e, today - dt.timedelta(days=1))
        if s >= today or last < s or (today - e).days > keep:
            continue
        part = str(r.get("매출 구분") or "").strip() or total_name
        days = [s + dt.timedelta(days=i) for i in range((last - s).days + 1)]
        shift = dt.timedelta(days=7 * math.ceil(len(days) / 7))
        base_days = [d - shift for d in days]

        def value(d, k="sales"):
            x = total_of(by_day, d) if part == total_name else by_day.get(d, {}).get(part)
            return x[k] if x else None
        now_v = [value(d) for d in days]
        base_v = [value(d) for d in base_days]
        prev_v = [value(d, "prev") for d in days]
        item = {"name": str(r["행사명"] or "").strip(), "part": part, "start": s.isoformat(), "end": e.isoformat(),
                "to": last.isoformat(), "days": len(days), "ended": e < today,
                "base_from": base_days[0].isoformat(), "base_to": base_days[-1].isoformat(), "flag": False}
        if None in now_v or None in base_v:
            gap = [d.isoformat() for d, v in zip(days + base_days, now_v + base_v) if v is None]
            item["note"] = f"sales 파일에 '{part}' 매출이 없는 날이 있어 견주지 않음({gap[0]} 등 {len(gap)}일)"
        else:
            item.update(sales=sum(now_v), base=sum(base_v), sales_text=_won(sum(now_v)), base_text=_won(sum(base_v)),
                        growth=_growth(sum(now_v), sum(base_v)),
                        yoy=_growth(sum(now_v), sum(prev_v)) if None not in prev_v else None)
            item["flag"] = item["growth"] is not None and item["growth"] <= low
        items.append(item)
    items.sort(key=lambda x: (not x["flag"], x["start"]))
    return {
        "rule": "행사 성과",
        "items": items,
        "status": "확인 필요" if any(i["flag"] for i in items) else "평소",
        "rule_text": f"행사 기간(어제까지) 매출을 바로 앞 같은 요일 기간과 견줌, {low}% 이하이면 확인 필요, "
                     f"끝난 뒤 {keep}일까지 보여 줌. 앞 기간에 다른 행사가 있었으면 차이가 작게 나옴",
        "source": f"{_src(promo_rows[0]['_file'])}, {_src(sales_rows[0]['_file'])}" if promo_rows else "",
    }


# 문화센터, 라운지, 상담실 같은 접점의 하루 숫자
def rule_touch(rows, today):
    """접점과 지표별로 최근 날짜 값을 직전 4주 같은 요일 평균과 견준다. 지난 7일 합도 그 앞 7일과 견준다."""
    thr, floor = C.TOUCH.get("change_pct", 30), C.TOUCH.get("min_value", 5)
    vals = collections.defaultdict(dict)
    for r in rows:
        d = I.to_date(r["날짜"], r, "날짜")
        place, metric = str(r["접점"] or "").strip(), str(r["지표"] or "").strip()
        if not place or not metric:
            raise I.InputError(f"{I.where(r)} '접점'과 '지표'는 비울 수 없습니다")
        v = I.to_num(r["값"], r, "값")
        if d < today:
            vals[(place, metric)][d] = vals[(place, metric)].get(d, 0) + v
    items, week = [], []
    end = today - dt.timedelta(days=1)
    for (place, metric), by in vals.items():
        day = max(by)
        base = [by[day - dt.timedelta(weeks=k)] for k in range(1, 5) if day - dt.timedelta(weeks=k) in by]
        avg = sum(base) / len(base) if base else None
        chg = _growth(by[day], avg) if avg and avg >= floor and len(base) >= 2 else None
        items.append({"place": place, "metric": metric, "date": day.isoformat(), "value": by[day],
                      "base": round(avg, 1) if avg is not None else None, "base_n": len(base), "change_pct": chg,
                      "flag": chg is not None and abs(chg) >= thr, "stale_days": (today - day).days})
        this = sum(v for d, v in by.items() if end - dt.timedelta(days=6) <= d <= end)
        last = sum(v for d, v in by.items() if end - dt.timedelta(days=13) <= d <= end - dt.timedelta(days=7))
        week.append({"place": place, "metric": metric, "this_week": this, "last_week": last,
                     "change_pct": _growth(this, last)})
    items.sort(key=lambda x: (not x["flag"], -abs(x["change_pct"] or 0), x["place"]))
    flagged = [i for i in items if i["flag"]]
    return {
        "rule": "접점 숫자",
        "items": items[:C.TOUCH.get("max_rows", 8)],
        "all_count": len(items),
        "flagged": flagged,
        "week": week,
        "status": "확인 필요" if flagged else "평소",
        "rule_text": f"최근 값이 직전 4주 같은 요일 평균보다 {thr}% 이상 늘거나 줄면 표시. 평균이 {floor} 미만이거나 "
                     "같은 요일 기록이 2주 미만이면 % 판단을 하지 않음",
        "source": _src(rows[0]["_file"]) if rows else "",
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


def fill_event(text, ending, fallback=""):
    """문장의 {행사} 자리를 그날 끝나는 행사 이름으로 채운다. 끝나는 행사가 없으면 fallback 문장을 쓴다."""
    if "{행사}" not in (text or ""):
        return text or ""
    return text.replace("{행사}", ", ".join(ending)) if ending else fallback


def rule_calendar(today, weather, review_alert, promos=None):
    """weather: 날짜별 낮 강수 합. 수집에 실패했으면 None. promos: 프로모션 점검 결과(끝나는 날을 달력에 잇는다)."""
    rows = [_day(today + dt.timedelta(days=i), None if weather is None else weather.get(
        (today + dt.timedelta(days=i)).isoformat()), review_alert, i == 0) for i in range(7)]
    items = (promos or {}).get("items", [])
    for row in rows:
        # 행사 파일에서 그날 끝나는 행사를 찾는다. 없으면 "마지막 날" 문구를 쓰지 않는다
        row["ending"] = [i["name"] for i in items if i["end"] == row["date"] and i["name"]]
        row["benefit"] = fill_event(row["benefit"], row["ending"], C.CAL.get("no_ending_benefit", ""))
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


def rule_field(review, calendar, log=None, today=None, touch=None):
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
    for t in (touch or {}).get("flagged", []):
        add(t["place"], f"{t['metric']} {t['value']:,.0f}, 평소 {t['base']:,.1f} 대비 {t['change_pct']:+}%")
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


# 주간 정리
def _md(x):
    """붙여 넣는 글의 날짜는 협의 초안과 같이 11/02 로 쓴다."""
    return x[5:].replace("-", "/")


def week_summary(today, out, field_log=None, archive=None):
    """지난 7일(어제까지)을 한 장으로. 오늘 판단 결과와 현장 기록에서 묶는다. 새로 세는 것은 기간 합과 일수뿐."""
    end = today - dt.timedelta(days=1)
    start = end - dt.timedelta(days=6)
    v = "(가상)" if C.SAMPLE else ""
    sections = []
    sales = out.get("sales")
    if sales:
        w = sales["last7"]
        days = [x for x in sales.get("series30", []) if start.isoformat() <= x["date"] <= end.isoformat()]
        low = [_md(x["date"]) for x in days
               if x["target"] and x["sales"] < x["target"] * sales["target_alert_pct"] / 100]
        lines = [f"7일 매출{v} {_won(w['sales'])}"
                 + (f", 목표 {w['achieve_pct']}%" if w["achieve_pct"] is not None else "")
                 + (f", 전년 대비 {w['yoy_pct']:+}%" if w["yoy_pct"] is not None else "")]
        lines.append(f"목표 {sales['target_alert_pct']}% 미만인 날 {len(low)}일" + (f"({', '.join(low)})" if low else ""))
        if sales["date"] != end.isoformat():
            lines.append(f"매출 파일 마지막 날이 {sales['date']}이라 7일 합은 그날까지입니다")
        sections.append({"title": "매출", "lines": lines})
    res = out.get("promo_results")
    if res and res["items"]:
        lines = []
        for i in res["items"]:
            if i.get("growth") is None:
                lines.append(f"{i['name']}: {i.get('note', '견줄 자료 없음')}")
                continue
            lines.append(f"{i['name']}({i['part']}, {_md(i['start'])}~{_md(i['to'])}): {i['sales_text']}, "
                         f"앞 같은 요일 기간 대비 {i['growth']:+}%" + (", 확인 필요" if i["flag"] else ""))
        sections.append({"title": "행사 성과", "lines": lines})
    promos = out.get("promos")
    if promos:
        nxt = [i for i in promos["items"] if i["start"] > today.isoformat()]
        lines = [f"{i['name']} {_md(i['start'])} 시작" + (f", {', '.join(i['warns'])}" if i["warns"] else "")
                 for i in nxt]
        sections.append({"title": "다음 7일 시작 행사", "lines": lines or ["없음"]})
    tasks = out.get("tasks")
    if tasks and not tasks.get("stale"):
        fin = [a for a in archive or [] if a.get("done_on") and start.isoformat() <= a["done_on"] <= today.isoformat()]
        lines = [f"끝낸 업무 {len(fin)}건, 남은 업무 {len(tasks['items'])}건(기한 지남 {tasks['overdue']}건)"]
        lines += [f"{_md(a['done_on'])} 완료: {a['name']}" for a in sorted(fin, key=lambda a: a["done_on"])]
        lines += [f"남음: {t['name']} ({t['phase']})" for t in tasks["items"] if t["warn"]]
        sections.append({"title": "업무", "lines": lines})
    if field_log is not None:
        week = []
        for r in field_log:
            d = I.to_date(r["날짜"], r, "날짜")
            if start <= d <= end:
                week.append((d, str(r["접점"] or "").strip(), str(r.get("결과") or "정상").strip(), r.get("메모") or ""))
        week.sort()
        cnt = collections.Counter(x[2] for x in week)
        lines = [f"현장 기록 {len(week)}건" + (f"({', '.join(f'{k} {n}건' for k, n in cnt.most_common())})" if week else "")]
        lines += [f"{_md(d.isoformat())} {p}: {res_}" + (f", {m}" if m else "") for d, p, res_, m in week
                  if res_ != "정상"]
        sections.append({"title": "현장 조치", "lines": lines})
    touch = out.get("touch")
    if touch and touch["week"]:
        lines = [f"{x['place']} {x['metric']} {x['this_week']:,.0f}"
                 + (f"(앞 7일 대비 {x['change_pct']:+}%)" if x["change_pct"] is not None else "")
                 for x in sorted(touch["week"], key=lambda x: (x["place"], x["metric"]))]
        sections.append({"title": "접점 숫자 7일 합" + v, "lines": lines})
    review = out.get("review")
    if review and not review.get("stale"):
        sections.append({"title": "앱 리뷰", "lines": [f"지난 7일 1~2점 {review['low_7d']}건, 막힘 {review['blocked_7d']}건"]})
    pilot = out.get("pilot")
    if pilot:
        sections.append({"title": "시범" + ("(가상)" if pilot.get("virtual") else ""),
                         "lines": [f"{pilot.get('week_label', '')}: {pilot['decision']}"]})
    sections.append({"title": "다음 주 점검", "lines": next_week_checks(today, out, start, end)})
    return {"rule": "주간 정리", "from": start.isoformat(), "to": end.isoformat(), "sections": sections,
            "source": "오늘 판단 결과와 현장 기록(field_log). 주간 보고 초안이며 문장은 담당자가 다듬습니다"}


WEEKDAYS = "월화수목금토일"


def next_week_checks(today, out, start, end):
    """오늘부터 7일 안에 챙길 것. 판단 결과에서 뽑은 항목 뒤에 설정 [weekly] checks의 요일별 반복 점검을 붙인다."""
    until = today + dt.timedelta(days=6)
    lines = []
    sales = out.get("sales")
    if sales and sales.get("partial_pct") is not None:
        lines.append(f"매출 파일 다시 받기: {_md(sales['date'])} 매출이 같은 요일 평균의 {sales['partial_pct']}%")
    tasks = out.get("tasks")
    if tasks and not tasks.get("stale"):
        lines += [f"{_md(t['due'])} 기한: {t['name']}" + (f" ({t['owner']} 담당)" if t["owner"] else "")
                  + (" 기한 지남" if t["left"] < 0 else "")
                  for t in tasks["items"] if t["left"] is not None and t["left"] <= 6]
    promos = out.get("promos")
    if promos:
        lines += [f"{_md(i['start'])} 시작 전 확인: {i['name']}, {', '.join(i['warns'])}" for i in promos["items"]
                  if today.isoformat() <= i["start"] <= until.isoformat() and i["warns"] and not i.get("handled")]
    res = out.get("promo_results")
    if res:
        lines += [f"결과 보고: {i['name']}, {_md(i['to'])} 끝" + (", 성과 낮음 원인 정리" if i["flag"] else "")
                  for i in res["items"] if start.isoformat() <= i["to"] <= end.isoformat()]
    repeat = []
    for c in C.WEEKLY.get("checks", []):
        day, _, what = str(c).partition(":")
        if day.strip() in WEEKDAYS and what.strip():
            d = today + dt.timedelta(days=(WEEKDAYS.index(day.strip()) - today.weekday()) % 7)
            repeat.append((d, f"{_md(d.isoformat())}({day.strip()}) {what.strip()}"))
        elif str(c).strip():
            repeat.append((until, str(c).strip()))
    lines += [x for _, x in sorted(repeat, key=lambda r: r[0])]
    return lines or ["없음"]


# 협의 초안
def consult_drafts(today, out):
    """오늘 확인 필요 항목을 받는 사람별 메모로 묶는다. 사실은 판단 결과의 숫자만, 요청은 정해진 문장만 쓴다."""
    who = C.CONSULT
    vmd, channel, app = who.get("vmd", "VMD 담당"), who.get("channel", "채널 담당"), who.get("app", "앱 운영 담당")
    v = "(가상)" if C.SAMPLE else ""
    memo = collections.defaultdict(list)

    def add(to, fact, ask, key=None):
        """같은 사람에게 가는 같은 행사 항목은 한 줄로 묶는다."""
        for x in memo[to]:
            if key and x.get("key") == key:
                x["fact"] += f", {fact.split(': ', 1)[-1]}"
                if ask not in x["ask"]:
                    x["ask"] += f" {ask}"
                return
        memo[to].append({"fact": fact, "ask": ask, "key": key})

    def md(x):
        return x[5:].replace("-", "/")
    promos = out.get("promos")
    for i in (promos or {}).get("items", []):
        where = f"{i['name']}, {i['place'] + ' ' if i['place'] else ''}{md(i['start'])}~{md(i['end'])}"
        for w in i["warns"]:
            if w.startswith("VMD"):
                add(vmd, f"{where}: {w}", "완료 예정일과 막힌 부분을 알려 주세요.", i["name"])
            elif w == "알릴 길 미정":
                add(channel, f"{where}: 알릴 길이 정해지지 않았습니다({i['phase']})", "쓸 수 있는 채널과 보낼 날짜를 정해 주세요.",
                    i["name"])
            else:
                add(channel, f"{where}: 내일 종료", "마감 안내 발송 여부를 확인해 주세요.", i["name"])
    res = out.get("promo_results")
    for i in (res or {}).get("items", []):
        if i["flag"]:
            fact = (f"{i['name']}, {i['part']} 매출 {md(i['start'])}~{md(i['to'])}: {i['sales_text']}{v}, "
                    f"앞 같은 요일 기간 대비 {i['growth']:+}%")
            add(vmd, fact, "진열 위치와 안내물을 바꿀 여지가 있는지 함께 보고 싶습니다. 원인은 아직 확인 전입니다.", i["name"])
            add(channel, fact, "알림 시간과 문구를 바꿀 여지가 있는지 함께 보고 싶습니다. 원인은 아직 확인 전입니다.", i["name"])
    sales = out.get("sales")
    for p in (sales or {}).get("parts", []):
        if p["flags"]:
            add(f"{p['part']} 영업 담당", f"{md(sales['date'])} {p['part']} 매출{v}: {', '.join(p['flags'])}",
                "그날 현장에서 달랐던 점(품절, 행사 종료, 날씨 등)이 있었는지 알려 주세요.")
    touch = out.get("touch")
    for t in (touch or {}).get("flagged", []):
        add(f"{t['place']} 담당", f"{md(t['date'])} {t['metric']}{v}: {t['value']:,.0f}, "
            f"평소(직전 같은 요일 평균) {t['base']:,} 대비 {t['change_pct']:+}%",
            "기록이 빠진 것인지 실제로 달라진 것인지 확인해 주세요.")
    me = C.TASKS.get("me", ["나", "본인"])
    soon = C.TASKS.get("soon_days", 3)
    for t in (out.get("tasks") or {}).get("items", []):
        if t["owner"] and t["owner"] not in me and t["left"] is not None and t["left"] <= soon:
            add(f"{t['owner']} 담당", f"업무 '{t['name']}': {t['phase']}(기한 {md(t['due'])})",
                "진행 상황과 막힌 부분을 알려 주세요.")
    review = out.get("review")
    if review and review["status"] == "확인 필요":
        add(app, f"새 1~2점 리뷰 {review['low_new']}건, 앱이 막혔다는 리뷰 {review['blocked_new']}건",
            "같은 시간대에 장애나 배포가 있었는지 알려 주세요.")
    drafts = []
    for to, items in memo.items():
        text = [f"{to}님, 오늘({today.isoformat()}) 아침 점검에서 같이 볼 것이 있어 공유드립니다.", ""]
        text += [f"{n}. {x['fact']}. {x['ask']}" for n, x in enumerate(items, 1)]
        text += ["", "숫자는 아침 점검 결과에서 옮겼습니다." + (" 가상 데이터로 만든 시연입니다." if C.SAMPLE else "")]
        items = [{k: v for k, v in x.items() if k != "key"} for x in items]
        drafts.append({"to": to, "count": len(items), "items": items, "text": "\n".join(text)})
    drafts.sort(key=lambda d: -d["count"])
    return {"rule": "협의 초안", "drafts": drafts,
            "rule_text": "VMD 경고는 VMD 담당, 알릴 길과 마감 안내는 채널 담당, 성과가 낮은 행사는 둘 다(같은 행사는 한 줄로), "
                         "구분 매출 경고는 그 구분 영업 담당, 접점 숫자 표시는 그 접점 담당, 리뷰 확인 필요는 앱 운영 담당, "
                         "남이 맡은 업무 중 기한이 지났거나 며칠 안 남은 것은 그 담당",
            "source": "오늘 판단 결과. 요청 문장은 정해진 목록이며 보내기 전에 담당자가 다듬습니다"}


def _sign(n):
    return "-" if n is None else f"{n:+}%"


def lead_report(today, out):
    """팀장에게 올릴 한 장. 결론 한 줄, 숫자 세 개, 원인 후보(확인 전), 오늘 조치와 담당, 정해 주실 것.
    문장은 판단 결과의 숫자로만 채우고, 원인은 후보로만 적는다."""
    v = "(가상)" if C.SAMPLE else ""

    def md(x):
        return x[5:].replace("-", "/")
    s = out.get("sales")
    thr = C.SALES.get("yoy_alert_pct", -10)
    head, numbers, causes, focus = "", [], [], None
    if not s:
        head = "매출 파일이 없어 오늘은 행사와 업무만 보고합니다."
    else:
        t, d = s["total"], md(s["date"])
        tl = f"목표 {t['achieve_pct']}%, 전년 대비 {_sign(t['yoy_pct'])}"
        numbers = [["어제 매출", t["sales_text"], tl],
                   ["월 누계", s["mtd"]["sales_text"], f"목표 {s['mtd']['achieve_pct']}%"],
                   ["최근 7일", f"전년 대비 {_sign(s['last7']['yoy_pct'])}", f"목표 {s['last7']['achieve_pct']}%"]]
        flagged = sorted([p for p in s["parts"] if p["flags"]], key=lambda p: p["yoy_pct"] if p["yoy_pct"] is not None else 0)
        if s["partial_pct"] is not None:
            head = f"{d} 매출 파일이 덜 된 집계로 보여(같은 요일 평균의 {s['partial_pct']}%) 새 파일을 받은 뒤 보고합니다."
        elif s["status"] == "확인 필요":
            head = f"{d} 전체 매출{v}이 {', '.join(r.split('(')[0] for r in s['reasons'])}로 기준을 넘었습니다."
            focus = flagged[0] if flagged else None
            if focus:
                head += f" 구분별로는 {focus['part']}({_sign(focus['yoy_pct'])})가 가장 낮습니다."
        elif s["status"] == "구분 확인":
            focus = flagged[0]
            head = (f"{d} 전체 매출{v}은 {tl}로 기준 안이지만 {focus['part']} 매출이 전년 대비 "
                    f"{_sign(focus['yoy_pct'])}, 목표 {focus['achieve_pct']}%로 낮습니다.")
            if len(flagged) > 1:
                head += f" {', '.join(p['part'] for p in flagged[1:])}도 기준을 넘었습니다."
        else:
            head = f"{d} 전체 매출{v}은 {tl}로 기준 안입니다."
        if focus:
            w = focus.get("last7_yoy_pct")
            if w is not None:
                causes.append(f"{focus['part']} 최근 7일 전년 대비 {_sign(w)}: "
                              + ("7일 전체도 낮아 이어지는 하락일 수 있습니다" if w <= thr
                                 else "7일로 보면 기준 안이라 하루치 하락인지 먼저 봅니다"))
            for i in (out.get("promo_results") or {}).get("items", []):
                if i["part"] != focus["part"] or (i["ended"] and (dt.date.fromisoformat(s["date"])
                                                                  - dt.date.fromisoformat(i["end"])).days > 7):
                    continue
                causes.append(f"같은 구분 행사 {i['name']}: {md(i['start'])}~{md(i['to'])} {i['sales_text']}{v}, "
                              f"앞 같은 요일 기간 대비 {i['growth']:+}%" + (f", {md(i['end'])} 끝남" if i["ended"] else ", 진행 중"))
            causes.append(f"전년 같은 날의 행사와 날씨는 이 도구에 없어 {focus['part']} 영업 담당에게 확인합니다")

    acts = []
    if focus:
        acts.append([f"{focus['part']} 영업 담당", f"{md(s['date'])} 품절, 행사 종료, 날씨 등 달랐던 점 확인"])
    tasks = out.get("tasks")
    done_promo = set()
    for i in (tasks or {}).get("items", []) if tasks and not tasks.get("stale") else []:
        if i["left"] is not None and i["left"] <= 0:
            acts.append([i["owner"] or "담당 미정", f"{i['name']}({i['phase']})"])
            done_promo.add(i.get("promo"))
    for i in (out.get("promos") or {}).get("items", []):
        if i["warns"] and i["name"] not in done_promo:
            acts.append([i["owner"] or "담당 미정", f"{i['name']}: {i['warns'][0]}"])
    for t in (out.get("touch") or {}).get("flagged", []):
        acts.append([f"{t['place']} 담당", f"{t['metric']}{v} 평소 대비 {t['change_pct']:+}%, 기록 누락인지 확인"])
    r = out.get("review")
    if r and r["status"] == "확인 필요":
        acts.append([C.CONSULT.get("app", "앱 운영 담당"), f"새 1~2점 {r['low_new']}건, 막힘 {r['blocked_new']}건, 장애나 배포 확인"])
    more = max(0, len(acts) - 4)
    acts = acts[:4]

    decide = []
    p = out.get("pilot")
    if p and p.get("check_day"):
        decide.append(f"시범 {p['week_label']} 점검일입니다. 현재 판단은 {p['decision']}이라 계속할지 정해 주세요")
    for i in (out.get("promo_results") or {}).get("items", []):
        if i["flag"] and not i["ended"]:
            decide.append(f"{i['name']}이 앞 같은 요일 기간 대비 {i['growth']:+}%라 진열이나 알림을 바꿀지 정해 주세요")
    if not decide:
        decide = ["오늘 정해 주실 것은 없습니다"]

    day = f"{today.month}/{today.day:02d}({'월화수목금토일'[today.weekday()]})"
    lines = [f"[{day} 아침 보고] {C.STORE_NAME}".rstrip(), "", f"결론: {head}"]
    if numbers:
        lines.append(f"숫자{v}: " + ", ".join(f"{a} {b}({c})" for a, b, c in numbers))
    if causes:
        lines += ["", "원인 후보(확인 전)"] + [f"- {c}" for c in causes]
    lines += ["", "오늘 조치"] + [f"{n}. {a}: {b}" for n, (a, b) in enumerate(acts, 1)]
    if not acts:
        lines.append("따로 챙길 일이 없습니다.")
    if more:
        lines.append(f"외 {more}건은 아침 점검 화면에 있습니다.")
    lines += ["", "정해 주실 것"] + [f"- {x}" for x in decide]
    if C.SAMPLE:
        lines += ["", "가상 데이터로 만든 시연입니다."]
    return {"rule": "팀장 보고 한 장", "headline": head, "numbers": numbers, "causes": causes, "actions": acts,
            "more": more, "decide": decide, "text": "\n".join(lines),
            "rule_text": "결론은 매출 세 단계(평소, 구분 확인, 확인 필요)와 덜 된 집계 여부로 고른다. 원인 후보는 같은 구분의 "
                         "최근 7일과 7일 안에 끝났거나 진행 중인 같은 구분 행사만 적고 원인으로 단정하지 않는다. 조치는 구분 영업 담당, "
                         "기한이 지났거나 오늘인 업무, 업무로 안 잡힌 행사 경고, 접점 숫자, 리뷰 순으로 4개까지",
            "source": "오늘 판단 결과(매출, 행사 성과, 업무, 행사, 접점 숫자, 리뷰, 시범)"}


def plan_drafts(today, out):
    """이번 주 달력에서 시범별로 가장 가까운 날을 골라 집객 기획 초안을 만든다. 문장은 설정의 재료만 쓴다."""
    cal = out.get("calendar") or {}
    names = cal.get("pilot_names", {})
    picked = {}
    for row in cal.get("days", []):
        for n in row["pilots"]:
            if str(n) not in picked and str(n) in C.PLAN:
                picked[str(n)] = row
    pilot = out.get("pilot") or {}
    low = [i for i in (out.get("promo_results") or {}).get("items", []) if i["flag"]]
    v = "(가상)" if C.SAMPLE else ""
    cards = []
    for n, row in picked.items():
        p = C.PLAN[n]
        d = dt.date.fromisoformat(row["date"])
        low_names = {i["name"] for i in low}
        end = [e for e in row.get("ending", []) if e not in low_names]
        notes = []
        cut = [e for e in row.get("ending", []) if e in low_names]
        if cut:
            notes.append(f"{', '.join(cut)}은 성과가 낮아 마지막 날 문구에서 뺐습니다. 마감 할인을 할지 따로 정합니다.")
        if n == "1" and pilot.get("decision") and pilot["decision"] != "집계 전":
            notes.append(f"진행 중인 시범{v} 신호는 {pilot['decision']}입니다. "
                         + ("문구 B나 대상 조건을 바꾼 안을 함께 올립니다." if not pilot["decision"].startswith("넓힌다")
                            else "대상을 넓힐 범위를 함께 정합니다."))
        if low and n != "3" and not cut:
            notes.append(f"성과가 낮았던 행사: {', '.join(i['name'] for i in low)}. 같은 혜택을 되풀이하지 않습니다.")
        # 혜택은 설정 문장이라 확정된 것이 아니다. 그날 걸친 행사 중 이름 첫 낱말(식품관, 문화센터 등)이 혜택 문장에 있으면
        # 행사 파일에 잡힌 혜택으로 보고, 없으면 문구 앞에 [혜택 확정 후]를 붙여 확정 전에 나가지 않게 한다
        hit = [i["name"] for i in (out.get("promos") or {}).get("items", [])
               if i["start"] <= row["date"] <= i["end"] and i["name"].split()[0] in row["benefit"]]
        hold = "" if hit else "[혜택 확정 후] "
        cards.append({
            "pilot": int(n), "name": names.get(n, ""), "benefit_from": hit, "hold": bool(hold),
            "date": row["date"], "when": f"{d.month}/{d.day}({DOW[d.weekday()]}) " + ", ".join(row["times"]),
            "situation": ", ".join(row["situation"]), "basis": row["basis"],
            "target": p.get("target", ""), "benefit": row["benefit"], "channels": row["channels"],
            "copy_a": hold + (fill_event(p["copy_a_rain"], end, p.get("copy_a_rain_none", "")) if row["rain"] and p.get("copy_a_rain")
                              else fill_event(p.get("copy_a", ""), end, p.get("copy_a_none", ""))),
            "copy_b": hold + fill_event(p.get("copy_b", ""), end, p.get("copy_b_none", "")),
            "measure": p.get("measure", ""), "owner": p.get("owner", ""), "notes": notes})
    cards.sort(key=lambda c: (c["date"], c["pilot"]))
    return {"rule": "집객 기획 초안", "cards": cards[:C.PLAN.get("max_cards", 3)],
            "rule_text": "이번 주 달력에서 시범마다 가장 가까운 날 하나. 대상, 문구, 재는 법은 설정 문장, "
                         "때와 혜택, 알릴 길은 달력 판단, '마지막 날' 문구는 행사 파일에서 그날 끝나는 행사가 있을 때만, "
                         "참고는 시범 신호와 성과가 낮은 행사. 혜택이 그날 걸친 행사 파일 항목과 맞지 않으면 문구 앞에 [혜택 확정 후]",
            "source": "이번 주 집객 달력, 시범 점검, 행사 성과. 무엇을 할지는 담당자가 정합니다"}
