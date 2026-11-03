"""4주 시범 통과 기준 세기. 숫자는 테스트용으로 만든 기록이다."""
import datetime as dt
import sys

from brief import rules_config as C

sys.path.insert(0, str(C.ROOT / "scripts"))
import trial_report as T  # noqa: E402

START = dt.date(2026, 11, 9)


def days(n, first=START):
    return [(first + dt.timedelta(days=i)).isoformat() for i in range(n)]


def test_empty_records_are_not_judged():
    r = T.report(START, [], [], None, [])
    assert [x[3] for x in r["rows"]] == ["셀 자료 없음"] * 5
    assert r["verdict"].startswith("보류. 5개")


def test_all_five_pass_and_fail_counts(tmp_path):
    judge = [{"날짜": d, "항목": "확인: 리뷰 1~2점" if n % 4 == 0 else "확인: 매출", "판단": "움직였다" if n % 3 else "볼 필요 없었다"}
             for n, d in enumerate(days(28))]
    # 시범 전 1주 하루 45분, 시범 중 30분, 엑셀 8분
    time = ([{"날짜": d, "걸린 분": "45", "엑셀 넣은 분": ""} for d in days(7, START - dt.timedelta(days=7))]
            + [{"날짜": d, "걸린 분": "30", "엑셀 넣은 분": "8"} for d in days(28)])
    missed = [{"날짜": days(28)[3], "놓친 일": "x"}]
    hist = [{"date": d, "failures": ["행사 읽기"] if n == 10 else []} for n, d in enumerate(days(28))]
    r = T.report(START, judge, time, missed, hist)
    assert [x[3] for x in r["rows"]] == ["통과"] * 5 and r["verdict"].startswith("다섯 가지를 모두")
    assert r["rows"][0][1] == "64.3%(18/28건)"
    assert "45.0분" in r["rows"][2][1] and "15.0분 줄어듦" in r["rows"][2][1]
    assert r["review"].startswith("리뷰 항목 7건")
    # 시간이 안 줄고 엑셀이 길고 실패가 잦으면 셋 못 넘음, 그만 씀
    time = [dict(x, **{"걸린 분": "44", "엑셀 넣은 분": "15"}) if x["날짜"] >= START.isoformat() else x for x in time]
    hist = [dict(h, failures=["매출 읽기"]) for h in hist]
    r = T.report(START, judge, time, missed, hist)
    assert [x[3] for x in r["rows"]].count("못 넘음") == 3 and "그만 씁니다" in r["verdict"]
    md = T.markdown(r)
    assert md.startswith("# 4주 시범 결과 2026-11-09~2026-12-06") and "·" not in md and "→" not in md


def test_reads_csv_from_screen_export(tmp_path):
    p = tmp_path / "time_log.csv"
    p.write_text("﻿날짜,시작,보고 마침,걸린 분,엑셀 넣은 분\n2026-11-09,08:40,09:12,32,7\n\n", encoding="utf-8")
    rows = T.read_csv(p)
    assert rows == [{"날짜": "2026-11-09", "시작": "08:40", "보고 마침": "09:12", "걸린 분": "32", "엑셀 넣은 분": "7"}]
    assert T.read_csv(None) is None
    # 설정의 [trial] 값이 기본값과 같아 README 표와 어긋나지 않는다
    assert {k: C.CFG["trial"][k] for k in T.DEFAULT} == T.DEFAULT
