"""리뷰 알림 규칙(4.1)을 백화점 3사 앱의 실제 Google Play 리뷰로 지난 2년 매일 아침 돌려 본다.

backtest_reviews.py 와 같은 계산을 3사, 730일로 넓힌 것이다. 원문, 작성자, 리뷰 ID는 저장하지 않고
앱별 건수와 알림이 뜬 날짜만 docs/backtest_3apps.json 에 쓴다. 알림일을 사람이 나눈 결과는
docs/backtest_judged_3apps.json 에 따로 있다.

    python -X utf8 scripts/backtest_3apps.py
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google_play_scraper import Sort, reviews  # noqa: E402

from brief import rules_config as C  # noqa: E402
from brief import collect, judge  # noqa: E402

APPS = {"현대": "com.ehyundai.mcard", "롯데": "com.innov.lottecoupon", "신세계": "com.F1.ShinSG"}
DAYS = 730


def flagged_days(rows, today):
    """today 까지 DAYS일 동안 매일 7시 실행을 흉내 낸다. 앞 28일은 기준 기간이라 판단하지 않는다."""
    first = today - dt.timedelta(days=DAYS)
    out = []
    for i in range(28, DAYS + 1):
        d = first + dt.timedelta(days=i)
        now = dt.datetime.combine(d, dt.time(7), collect.KST)
        r = judge.rule_reviews([x for x in rows if x["at"] <= now], now, now - dt.timedelta(days=1))
        if r["status"] == "확인 필요":
            out.append({"date": d.isoformat(), "low_new": r["low_new"], "blocked_new": r["blocked_new"]})
    return out


def main():
    C.load([ROOT / "config.toml"])
    now = dt.datetime.now(collect.KST)
    apps = {}
    for name, aid in APPS.items():
        rows, texts = collect.fetch_reviews(now, days=DAYS + 1, scraper=lambda tok, aid=aid: reviews(
            aid, lang="ko", country="kr", sort=Sort.NEWEST, count=200, continuation_token=tok))
        texts.clear()
        f = flagged_days(rows, now.date())
        apps[name] = {"app_id": aid, "reviews": len(rows), "low_reviews": sum(1 for r in rows if r["score"] <= 2),
                      "flagged_days": len(f), "flagged_by_blocked": sum(1 for x in f if x["blocked_new"] >= C.ALERT_BLOCKED),
                      "flagged": f}
        print(f"{name}: 리뷰 {len(rows)}, 1~2점 {apps[name]['low_reviews']}, 확인 필요 {len(f)}일"
              f"(막힘 때문 {apps[name]['flagged_by_blocked']}일)")
    result = {
        "note": "3사 앱 Google Play 공개 리뷰로 4.1 규칙을 매일 7시 실행했다고 보고 다시 계산. 원문, 작성자, 리뷰 ID 없음",
        "rule_text": f"막힘 {C.ALERT_BLOCKED}건 이상 또는 새 1~2점이 4주 평균의 {C.ALERT_MULTIPLE:g}배 초과",
        "days_per_app": DAYS - 27, "apps": apps, "made_at": now.isoformat(timespec="minutes"),
    }
    (ROOT / "docs" / "backtest_3apps.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
