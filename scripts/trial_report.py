"""4주 시범 통과 기준 다섯 가지를 기록 파일로 센다(README "4주 시범 통과 기준").

화면에서 받은 판단 기록(judge_log.csv)과 시간 기록(time_log.csv), 직접 적는 놓친 일(missed.csv: 날짜,놓친 일),
실행 기록(기록 폴더 history/*.json의 실패 단계)을 읽어 기준마다 통과, 못 넘음, 셀 자료 없음을 적는다.
기준 숫자는 config.toml [trial]의 가정값이다. 숫자를 지어내지 않으려고 자료가 모자라면 판정하지 않는다.

    python -X utf8 scripts/trial_report.py --start 2026-11-09 --judge judge_log.csv --time time_log.csv --missed missed.csv
"""
import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brief import rules_config as C  # noqa: E402

DEFAULT = {"days": 28, "moved_pct": 50, "missed_per_week": 1, "saved_min": 10, "input_max_min": 10,
           "fail_per_week": 1, "min_days": 3}


def read_csv(path):
    """엑셀에서 다시 저장해도 읽히도록 BOM과 빈 줄을 건너뛴다. 파일이 없으면 None."""
    if not path:
        return None
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def _day(x):
    return dt.date.fromisoformat(str(x).strip()[:10])


def _num(x):
    try:
        return float(str(x).strip())
    except ValueError:
        return None


def _avg(xs):
    return round(sum(xs) / len(xs), 1) if xs else None


def report(start, judge_rows, time_rows, missed_rows, history, th=None):
    """기준마다 [기준, 값, 통과 기준, 결과]. 결과는 '통과', '못 넘음', '셀 자료 없음' 중 하나."""
    th = {**DEFAULT, **(th or {})}
    end = start + dt.timedelta(days=th["days"] - 1)
    weeks = th["days"] / 7

    def inside(d):
        return start <= d <= end
    rows = []

    j = [r for r in judge_rows or [] if inside(_day(r["날짜"]))]
    moved = [r for r in j if r["판단"].strip() == "움직였다"]
    pct = round(len(moved) / len(j) * 100, 1) if j else None
    rows.append(["확인 필요 항목 중 실제로 움직인 비율",
                 f"{pct}%({len(moved)}/{len(j)}건)" if j else "판단 기록 없음", f"{th['moved_pct']}% 이상",
                 "셀 자료 없음" if pct is None else ("통과" if pct >= th["moved_pct"] else "못 넘음")])

    if missed_rows is None:
        rows.append(["화면이 놓친 일", "놓친 일 기록 파일 없음", f"주 {th['missed_per_week']}건 이하", "셀 자료 없음"])
    else:
        n = len([r for r in missed_rows if inside(_day(r["날짜"]))])
        per = round(n / weeks, 1)
        rows.append(["화면이 놓친 일", f"{n}건, 주 {per}건", f"주 {th['missed_per_week']}건 이하",
                     "통과" if per <= th["missed_per_week"] else "못 넘음"])

    t = [(_day(r["날짜"]), _num(r.get("걸린 분", "")), _num(r.get("엑셀 넣은 분", ""))) for r in time_rows or []]
    before = [m for d, m, _ in t if m is not None and start - dt.timedelta(days=7) <= d < start]
    during = [m for d, m, _ in t if m is not None and inside(d)]
    b, a = _avg(before), _avg(during)
    if len(before) < th["min_days"] or len(during) < th["min_days"]:
        rows.append(["출근부터 팀장 보고까지", f"시범 전 {len(before)}일, 시범 중 {len(during)}일 기록",
                     f"시범 전 1주 평균보다 {th['saved_min']}분 이상 줄어듦", "셀 자료 없음"])
    else:
        rows.append(["출근부터 팀장 보고까지", f"시범 전 {b}분, 시범 중 {a}분, {round(b - a, 1)}분 줄어듦",
                     f"시범 전 1주 평균보다 {th['saved_min']}분 이상 줄어듦",
                     "통과" if b - a >= th["saved_min"] else "못 넘음"])

    inp = [x for d, _, x in t if x is not None and inside(d)]
    if len(inp) < th["min_days"]:
        rows.append(["엑셀 내려받아 넣는 시간", f"{len(inp)}일 기록", f"하루 {th['input_max_min']}분 이하", "셀 자료 없음"])
    else:
        over = len([x for x in inp if x > th["input_max_min"]])
        rows.append(["엑셀 내려받아 넣는 시간", f"하루 평균 {_avg(inp)}분, 기준 넘은 날 {over}일",
                     f"하루 {th['input_max_min']}분 이하", "통과" if _avg(inp) <= th["input_max_min"] else "못 넘음"])

    ran = {_day(h["date"]): h for h in history or [] if inside(_day(h["date"]))}
    if len(ran) < th["min_days"]:
        rows.append(["읽기 실패", f"실행 기록 {len(ran)}일", f"주 {th['fail_per_week']}회 이하", "셀 자료 없음"])
    else:
        bad = len([h for h in ran.values() if h.get("failures")])
        per = round(bad / weeks, 1)
        rows.append(["읽기 실패", f"실패한 날 {bad}일, 주 {per}회(실행 {len(ran)}일)", f"주 {th['fail_per_week']}회 이하",
                     "통과" if per <= th["fail_per_week"] else "못 넘음"])

    # 리뷰 알림이 맞았는지는 따로 셀 길이 없어, 판단 기록 중 리뷰 항목만 떼어 함께 보여 준다
    rv = [r for r in j if "리뷰" in r["항목"]]
    review = (f"리뷰 항목 {len(rv)}건 중 움직였다 {len([r for r in rv if r['판단'].strip() == '움직였다'])}건"
              if rv else "리뷰 항목 판단 기록 없음")
    return {"start": start.isoformat(), "end": end.isoformat(), "rows": rows, "verdict": verdict(rows),
            "review": review}


def verdict(rows):
    res = [r[3] for r in rows]
    if "셀 자료 없음" in res:
        return f"보류. {res.count('셀 자료 없음')}개 기준은 셀 자료가 없습니다. 기록을 채운 뒤 다시 셉니다"
    fail = res.count("못 넘음")
    if not fail:
        return "다섯 가지를 모두 넘어 계속 씁니다"
    if fail >= 3:
        return f"{fail}개 기준을 못 넘어 그만 씁니다"
    return f"{fail}개 기준을 못 넘어 이유를 적고 기준이나 블록을 고친 뒤 4주를 다시 봅니다"


def markdown(r):
    lines = [f"# 4주 시범 결과 {r['start']}~{r['end']}", "", "| 기준 | 값 | 통과 기준(가정값) | 결과 |", "|---|---|---|---|"]
    lines += [f"| {' | '.join(x)} |" for x in r["rows"]]
    lines += ["", f"판정: {r['verdict']}.", "", f"리뷰 알림: {r['review']}. 맞았는지는 사람이 정한 판단 기록만 씁니다.", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="4주 시범 통과 기준 세기")
    ap.add_argument("--start", required=True, help="시범 첫날 YYYY-MM-DD")
    ap.add_argument("--judge", help="화면에서 받은 judge_log.csv")
    ap.add_argument("--time", help="화면에서 받은 time_log.csv")
    ap.add_argument("--missed", help="직접 적은 missed.csv(날짜,놓친 일)")
    ap.add_argument("--out", help="결과 md 파일. 없으면 화면에만 씁니다")
    a = ap.parse_args()
    C.load()
    history = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((C.DATA_DIR / "history").glob("*.json"))]
    r = report(_day(a.start), read_csv(a.judge), read_csv(a.time), read_csv(a.missed), history, C.CFG.get("trial"))
    text = markdown(r)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
