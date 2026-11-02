"""고객 접점 알림 규칙(4.1)을 실제 Google Play 리뷰로 지난 1년 매일 아침 돌려 본다.

매일 7시에 실행했다면 며칠 "확인 필요"가 떴을지 센다. 원문, 작성자, 리뷰 ID는 저장하지 않고
날짜별 건수와 판단 결과만 docs/backtest_reviews.json 에 쓴다.

    python -X utf8 scripts/backtest_reviews.py
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brief import rules_config as C  # noqa: E402
from brief import collect, judge  # noqa: E402

DAYS = 365


def backtest(rows, today):
    """today 전날까지 DAYS일 동안 매일 7시 실행을 흉내 낸다. 앞 28일은 기준 기간이라 판단하지 않는다."""
    first = today - dt.timedelta(days=DAYS)
    out = []
    for i in range(28, DAYS + 1):
        d = first + dt.timedelta(days=i)
        now = dt.datetime.combine(d, dt.time(7), collect.KST)
        seen = [r for r in rows if r["at"] <= now]
        r = judge.rule_reviews(seen, now, now - dt.timedelta(days=1))
        out.append({"date": d.isoformat(), "low_new": r["low_new"], "blocked_new": r["blocked_new"],
                    "status": r["status"]})
    return out


def main():
    C.load([ROOT / "config.toml"])
    now = dt.datetime.now(collect.KST)
    rows, texts = collect.fetch_reviews(now, days=DAYS + 1)
    texts.clear()
    days = backtest(rows, now.date())
    flagged = [x for x in days if x["status"] == "확인 필요"]
    weeks = len(days) / 7
    result = {
        "note": "Google Play 공개 리뷰로 4.1 규칙을 매일 7시 실행했다고 보고 다시 계산. 원문, 작성자, 리뷰 ID 없음",
        "app_name": C.APP_NAME,
        "rule_text": f"막힘 {C.ALERT_BLOCKED}건 이상 또는 새 1~2점이 4주 평균의 {C.ALERT_MULTIPLE:g}배 초과",
        "from": days[0]["date"], "to": days[-1]["date"], "days": len(days),
        "low_reviews": sum(x["low_new"] for x in days),
        "blocked_reviews": sum(x["blocked_new"] for x in days),
        "flagged_days": len(flagged),
        "flagged_by_blocked": sum(1 for x in flagged if x["blocked_new"] >= C.ALERT_BLOCKED),
        "per_week": round(len(flagged) / weeks, 2),
        # 1~2점이 드문 앱은 4주 평균이 0에 가까워 1건만 와도 2배를 넘는다
        "all_low_flagged": sum(x["low_new"] for x in flagged) == sum(x["low_new"] for x in days),
        "flagged": flagged,
        "made_at": now.isoformat(timespec="minutes"),
    }
    (ROOT / "docs" / "backtest_reviews.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    print(f"{result['from']}~{result['to']} {result['days']}일 중 확인 필요 {result['flagged_days']}일"
          f"(막힘 때문 {result['flagged_by_blocked']}일), 주당 {result['per_week']}일")


if __name__ == "__main__":
    main()
