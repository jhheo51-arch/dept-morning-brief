"""수집, 판단, 작성, 기록을 차례로 돈다. 한 단계가 실패해도 마지막 성공 결과로 화면을 채운다.

python -m brief.main [--date 2026-11-05]
"""
import argparse
import datetime as dt
import json
import shutil

from . import collect, judge, notify, samples, write
from . import inputs as I
from . import rules_config as C
from .collect import KST

ROOT = C.ROOT
BLOCKS = {"review": "리뷰 수집", "calendar": "날씨 예보 수집", "pilot": "시범 계산", "field": "현장 목록 판단",
          "sales": "매출 파일 읽기", "promos": "행사 파일 읽기", "promo_results": "행사 성과 계산",
          "touch": "접점 숫자 파일 읽기", "weekly": "주간 정리",
         "consult": "협의 초안"}
FILES = {"sales": "sales", "promos": "promotions", "pilot": "pilot_weekly", "field": "field_log",
         "touch": "touchpoint_daily"}


class LeakError(RuntimeError):
    pass


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def dirs(root):
    """설정의 입력, 화면, 기록 폴더를 root 기준으로 옮긴다(테스트는 임시 폴더를 root 로 준다)."""
    return tuple(root / p.relative_to(C.ROOT) for p in (C.INPUT_DIR, C.SITE_DIR, C.DATA_DIR))


def find_leaks(texts, root):
    """저장할 파일에 리뷰 원문이 들어갔는지 본다. 10자 이상 원문의 앞 20자로 찾는다."""
    probes = {t.strip()[:20] for t in texts if len(t.strip()) >= 10}
    _, site, data = dirs(root)
    hits = []
    for p in list(site.rglob("*")) + list(data.rglob("*")):
        if p.is_file() and p.suffix in {".json", ".js", ".md", ".html"}:
            body = p.read_text(encoding="utf-8")
            hits += [str(p) for s in probes if s in body]
    return hits


def run(now=None, root=ROOT, review_fetch=None, weather_fetch=None, summarizer=None):
    now = now or dt.datetime.now(KST)
    today = now.date()
    in_dir, docs, data = dirs(root)
    (data / "history").mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    if not C.SAMPLE:  # 내 데이터 화면은 output/site 에 따로 둔다. 화면 파일은 매번 새로 복사
        shutil.copyfile(C.BUNDLE / "docs" / "index.html", docs / "index.html")
    if C.SAMPLE:
        samples.make(in_dir, today)
    prev = _load(data / "latest.json")
    last_ok = dict(prev.get("last_ok", {}))
    failures, texts, out, missing = [], [], {}, []
    review_fetch = review_fetch or collect.fetch_reviews
    weather_fetch = weather_fetch or collect.fetch_weather

    def fallback(key, err):
        failures.append({"step": BLOCKS[key], "error": type(err).__name__,
                         "message": str(err) if isinstance(err, I.InputError) else "",
                         "last_success": last_ok.get(key)})
        old = prev.get(key)
        if old:
            old = dict(old, stale=True)
        return old

    def table(key):
        rows = I.read_table(FILES[key], in_dir)
        if rows is None:
            missing.append(f"{FILES[key]}.xlsx")
        return rows

    # 매출 현황, 행사 점검, 접점 숫자
    ok_rows = {}
    for key, rule in (("sales", judge.rule_sales), ("promos", judge.rule_promos), ("touch", judge.rule_touch)):
        try:
            rows = table(key)
            out[key] = rule(rows, today) if rows else None
            if rows:
                last_ok[key] = today.isoformat()
                ok_rows[key] = rows
        except I.InputError as e:
            out[key] = fallback(key, e)
    # 행사 성과는 행사 파일과 매출 파일을 둘 다 읽었을 때만
    out["promo_results"] = None
    if "sales" in ok_rows and "promos" in ok_rows:
        try:
            out["promo_results"] = judge.rule_promo_results(ok_rows["promos"], ok_rows["sales"], today)
        except I.InputError as e:
            out["promo_results"] = fallback("promo_results", e)

    # 4.1
    if C.APP_ID:
        try:
            rows, texts = review_fetch(now)
            since = dt.datetime.fromisoformat(prev["run_at"]) if prev.get("run_at") else now - dt.timedelta(days=1)
            out["review"] = judge.rule_reviews(rows, now, since)
            del rows
            last_ok["review"] = today.isoformat()
        except Exception as e:  # noqa: BLE001 수집 실패는 모두 대체 동작으로 넘긴다
            out["review"] = fallback("review", e)
    else:
        out["review"] = None
    alert = bool(out["review"] and out["review"].get("status") == "확인 필요")

    # 4.2 예보가 없어도 요일과 공휴일로 달력을 만든다
    try:
        weather = weather_fetch(today)
        last_ok["calendar"] = today.isoformat()
    except Exception as e:  # noqa: BLE001
        fallback("calendar", e)
        weather = None
    out["calendar"] = judge.rule_calendar(today, weather, alert)

    # 4.3 시연은 가상 시범, 내 데이터 모드는 pilot_weekly 파일이 있을 때만
    try:
        if C.SAMPLE:
            out["pilot"] = judge.rule_pilot(today, collect.simulate_pilot())
        else:
            weekly = table("pilot")
            out["pilot"] = judge.rule_pilot(today, weekly=weekly) if weekly else None
        if out["pilot"]:
            last_ok["pilot"] = today.isoformat()
    except Exception as e:  # noqa: BLE001
        out["pilot"] = fallback("pilot", e)

    # 4.4
    log = None
    try:
        log = table("field")
        out["field"] = judge.rule_field(out["review"], out["calendar"], log, today, out["touch"])
    except I.InputError as e:
        fallback("field", e)
        log = None
        out["field"] = judge.rule_field(out["review"], out["calendar"], touch=out["touch"])

    judgment = {k: v for k, v in out.items() if v}
    slim = {k: ({kk: vv for kk, vv in v.items() if kk not in ("series30", "daily60", "week")} if v else v)
            for k, v in judgment.items()}
    if summarizer is None:
        # 내 데이터 모드에서는 allow_llm 을 켠 경우에만 판단 결과가 외부 API로 나간다
        summarizer = write.llm_summary if C.ALLOW_LLM else (lambda j: None)
    summary = summarizer(slim)
    brief = {
        "date": today.isoformat(),
        "run_at": now.isoformat(timespec="minutes"),
        "mode": C.MODE,
        "store_name": C.STORE_NAME,
        "repo_url": C.REPO_URL,
        "top3": write.top_three(out),
        "summary": summary or write.template_summary(out),
        "summary_by": "Claude(숫자 검사 통과)" if summary else "문장 틀",
        "failures": failures,
        "missing": missing,
        "last_ok": last_ok,
        **out,
    }
    try:
        brief["weekly"] = judge.week_summary(today, out, log)
    except I.InputError as e:
        brief["weekly"] = fallback("weekly", e)
    try:
        brief["consult"] = judge.consult_drafts(today, out)
    except Exception as e:  # noqa: BLE001
        brief["consult"] = fallback("consult", e)
    if out["review"] is None and C.APP_ID:
        brief["run_at"] = prev.get("run_at", brief["run_at"])  # 새 리뷰 기준 시각은 성공한 실행만 옮긴다

    # 기록. 날짜별 집계만 남긴다
    r = out["review"] or {}
    hist = {"date": brief["date"], "status": r.get("status"), "low_new": r.get("low_new"),
            "blocked_new": r.get("blocked_new"), "low_7d": r.get("low_7d"),
            "pilot": (out["pilot"] or {}).get("decision"), "failures": [f["step"] for f in failures],
            "sales_status": (out["sales"] or {}).get("status"),
            "sales_yoy": ((out["sales"] or {}).get("total") or {}).get("yoy_pct"),
            "promo_warn": (out["promos"] or {}).get("warn_count"),
            "touch_flags": len((out["touch"] or {}).get("flagged", [])) if out["touch"] else None}
    (data / "history" / f"{brief['date']}.json").write_text(
        json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    if out["review"] and not out["review"].get("stale"):
        # 리뷰 작성일 기준 일별 건수. 첫 실행 전 기간도 채우고, 지난 날은 새 집계로 덮는다
        daily_path = data / "history" / "reviews" / "daily.json"
        daily_path.parent.mkdir(exist_ok=True)
        daily = {x["date"]: x for x in _load(daily_path).get("days", [])}
        daily.update({x["date"]: x for x in out["review"]["daily60"]})
        daily_path.write_text(json.dumps(
            {"note": "Google Play 공개 리뷰의 작성일별 건수(전체, 1~2점, 막힘). 원문, 작성자, 리뷰 ID 없음",
             "days": [daily[k] for k in sorted(daily)][-400:]}, ensure_ascii=False, indent=1), encoding="utf-8")
    history = [_load(p) for p in sorted((data / "history").glob("*.json"))[-30:]]

    (data / "latest.json").write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    (docs / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    (docs / "brief.md").write_text(write.brief_markdown(brief), encoding="utf-8")
    if brief["weekly"]:
        (docs / "weekly.md").write_text(write.weekly_markdown(brief), encoding="utf-8")
    if brief["consult"]:
        (docs / "consult.md").write_text(write.consult_markdown(brief), encoding="utf-8")
    (docs / "data.js").write_text("window.BRIEF = " + json.dumps({**brief, "history": history}, ensure_ascii=False)
                                  + ";\n", encoding="utf-8")

    leaks = find_leaks(texts, root)
    texts.clear()
    if leaks:
        raise LeakError(f"리뷰 원문이 파일에 들어감: {sorted(set(leaks))}")
    return brief


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="실행일을 바꿔 볼 때(YYYY-MM-DD), 시각은 07:00 KST")
    a = ap.parse_args()
    now = dt.datetime.fromisoformat(a.date + "T07:00:00+09:00") if a.date else None
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        b = run(now)
    except LeakError as e:
        # 저장하지 않는다. 워크플로가 data/, docs/ 변경을 되돌린다
        print(e, file=sys.stderr)
        sys.exit(3)
    except I.InputError as e:
        print(f"입력 파일 오류: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        # 예상 못 한 실패도 빈 화면 대신 마지막 성공 브리핑에 실패 표시를 붙인다
        _, site, data = dirs(ROOT)
        prev = _load(data / "latest.json")
        prev["error"] = {"at": dt.datetime.now(KST).isoformat(timespec="minutes"),
                         "step": type(e).__name__, "last_success": prev.get("date")}
        history = [_load(p) for p in sorted((data / "history").glob("*.json"))[-30:]]
        site.mkdir(parents=True, exist_ok=True)
        (site / "data.js").write_text(
            "window.BRIEF = " + json.dumps({**prev, "history": history}, ensure_ascii=False) + ";\n",
            encoding="utf-8")
        raise
    print(write.brief_markdown(b))
    try:
        if notify.send(b):
            print("알림을 보냈습니다.")
    except Exception as e:  # noqa: BLE001 알림 실패는 점검 결과를 막지 않는다
        print(f"알림 실패: {type(e).__name__}", file=sys.stderr)
    if not C.SAMPLE:
        print(f"화면: {dirs(ROOT)[1] / 'index.html'}")


if __name__ == "__main__":
    main()
