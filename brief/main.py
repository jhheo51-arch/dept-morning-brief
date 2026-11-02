"""수집, 판단, 작성, 기록을 차례로 돈다. 한 단계가 실패해도 마지막 성공 결과로 화면을 채운다.

python -m brief.main [--date 2026-11-05]
"""
import argparse
import datetime as dt
import json
from pathlib import Path

from . import collect, judge, write
from .collect import KST

ROOT = Path(__file__).resolve().parent.parent
BLOCKS = {"review": "리뷰 수집", "calendar": "날씨 예보 수집", "pilot": "가상 시범 계산", "field": "현장 목록 판단"}


class LeakError(RuntimeError):
    pass


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def find_leaks(texts, root):
    """저장할 파일에 리뷰 원문이 들어갔는지 본다. 10자 이상 원문의 앞 20자로 찾는다."""
    probes = {t.strip()[:20] for t in texts if len(t.strip()) >= 10}
    hits = []
    for p in list((root / "docs").rglob("*")) + list((root / "data").rglob("*")):
        if p.is_file() and p.suffix in {".json", ".js", ".md", ".html"}:
            body = p.read_text(encoding="utf-8")
            hits += [str(p) for s in probes if s in body]
    return hits


def run(now=None, root=ROOT, review_fetch=None, weather_fetch=None, summarizer=None):
    now = now or dt.datetime.now(KST)
    today = now.date()
    data, docs = root / "data", root / "docs"
    (data / "history").mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    prev = _load(data / "latest.json")
    last_ok = dict(prev.get("last_ok", {}))
    failures, texts, out = [], [], {}
    review_fetch = review_fetch or collect.fetch_reviews
    weather_fetch = weather_fetch or collect.fetch_weather

    def fallback(key, err):
        failures.append({"step": BLOCKS[key], "error": type(err).__name__, "last_success": last_ok.get(key)})
        old = prev.get(key)
        if old:
            old = dict(old, stale=True)
        return old

    # 4.1
    try:
        rows, texts = review_fetch(now)
        since = dt.datetime.fromisoformat(prev["run_at"]) if prev.get("run_at") else now - dt.timedelta(days=1)
        out["review"] = judge.rule_reviews(rows, now, since)
        del rows
        last_ok["review"] = today.isoformat()
    except Exception as e:  # noqa: BLE001 수집 실패는 모두 대체 동작으로 넘긴다
        out["review"] = fallback("review", e)
    alert = bool(out["review"] and out["review"].get("status") == "확인 필요")

    # 4.2 예보가 없어도 요일과 공휴일로 달력을 만든다
    try:
        weather = weather_fetch(today)
        last_ok["calendar"] = today.isoformat()
    except Exception as e:  # noqa: BLE001
        fallback("calendar", e)
        weather = None
    out["calendar"] = judge.rule_calendar(today, weather, alert)

    # 4.3
    try:
        out["pilot"] = judge.rule_pilot(today, collect.simulate_pilot())
        last_ok["pilot"] = today.isoformat()
    except Exception as e:  # noqa: BLE001
        out["pilot"] = fallback("pilot", e)

    # 4.4
    out["field"] = judge.rule_field(out["review"], out["calendar"])

    judgment = {k: v for k, v in out.items() if v}
    slim = {k: ({kk: vv for kk, vv in v.items() if kk != "series30"} if v else v) for k, v in judgment.items()}
    summary = (summarizer or write.llm_summary)(slim)
    brief = {
        "date": today.isoformat(),
        "run_at": now.isoformat(timespec="minutes"),
        "top3": write.top_three(out["review"], out["calendar"], out["pilot"], out["field"]),
        "summary": summary or write.template_summary(out["review"], out["calendar"], out["pilot"]),
        "summary_by": "Claude(숫자 검사 통과)" if summary else "문장 틀",
        "failures": failures,
        "last_ok": last_ok,
        **out,
    }
    if out["review"] is None:
        brief["run_at"] = prev.get("run_at", brief["run_at"])  # 새 리뷰 기준 시각은 성공한 실행만 옮긴다

    # 기록. 날짜별 집계만 남긴다
    r = out["review"] or {}
    hist = {"date": brief["date"], "status": r.get("status"), "low_new": r.get("low_new"),
            "blocked_new": r.get("blocked_new"), "low_7d": r.get("low_7d"),
            "pilot": (out["pilot"] or {}).get("decision"), "failures": [f["step"] for f in failures]}
    (data / "history" / f"{brief['date']}.json").write_text(
        json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    history = [_load(p) for p in sorted((data / "history").glob("*.json"))[-30:]]

    (data / "latest.json").write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    (docs / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    (docs / "brief.md").write_text(write.brief_markdown(brief), encoding="utf-8")
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
    except Exception as e:
        # 예상 못 한 실패도 빈 화면 대신 마지막 성공 브리핑에 실패 표시를 붙인다
        prev = _load(ROOT / "data" / "latest.json")
        prev["error"] = {"at": dt.datetime.now(KST).isoformat(timespec="minutes"),
                         "step": type(e).__name__, "last_success": prev.get("date")}
        history = [_load(p) for p in sorted((ROOT / "data" / "history").glob("*.json"))[-30:]]
        (ROOT / "docs" / "data.js").write_text(
            "window.BRIEF = " + json.dumps({**prev, "history": history}, ensure_ascii=False) + ";\n",
            encoding="utf-8")
        raise
    print(write.brief_markdown(b))


if __name__ == "__main__":
    main()
