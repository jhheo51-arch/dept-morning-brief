"""내 업무 파일 읽기, 매출과 행사 규칙, 실제 시범 집계, 현장 주기, 내 데이터 모드 출력."""
import csv
import datetime as dt
import json
import re

import pytest

from brief import inputs as I
from brief import judge, main, notify, write
from brief import rules_config as C
from brief.collect import KST

TODAY = dt.date(2026, 11, 5)  # 목요일
NOW = dt.datetime(2026, 11, 5, 7, 0, tzinfo=KST)


def write_csv(folder, name, head, rows):
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f"{name}.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)


def sales_rows(folder, rows):
    write_csv(folder, "sales", ["날짜", "구분", "매출", "목표", "전년"], rows)
    return I.read_table("sales", folder)


def real_mode(tmp_path, extra=""):
    local = tmp_path / "local.toml"
    local.write_text('[run]\nmode = "real"\n[reviews]\napp_id = ""\n' + extra, encoding="utf-8")
    C.load([C.ROOT / "config.toml", local])


# 입력 검증
def test_missing_file_is_none_and_missing_column_is_clear(tmp_path):
    assert I.read_table("sales", tmp_path) is None
    write_csv(tmp_path, "sales", ["날짜", "매출"], [["2026-11-04", "100"]])
    with pytest.raises(I.InputError, match="구분 열이 없습니다"):
        I.read_table("sales", tmp_path)


def test_bad_number_names_file_and_row(tmp_path):
    rows = sales_rows(tmp_path, [["2026-11-04", "식품", "1,000,000", "", ""], ["2026-11-04", "패션", "많음", "", ""]])
    with pytest.raises(I.InputError, match=r"sales.csv 3행 '매출'"):
        judge.rule_sales(rows, TODAY)


def test_xlsx_and_date_formats(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.append(["날짜", "구분", "매출"])
    wb.active.append([dt.datetime(2026, 11, 4), "전체", 5_000_000])
    wb.active.append(["2026.11.03", "전체", "4,000,000원"])
    wb.save(tmp_path / "sales.xlsx")
    s = judge.rule_sales(I.read_table("sales", tmp_path), TODAY)
    assert s["date"] == "2026-11-04" and s["total"]["sales"] == 5_000_000 and s["mtd"]["sales"] == 9_000_000


# 매출
def test_sales_total_from_parts_and_alert(tmp_path):
    rows = sales_rows(tmp_path, [["2026-11-04", "식품", 85, 100, 100], ["2026-11-04", "패션", 100, 100, 100],
                                 ["2026-11-05", "식품", 999, 100, 100]])  # 오늘은 마감 전이라 뺀다
    s = judge.rule_sales(rows, TODAY)
    assert s["total"]["sales"] == 185 and s["total"]["achieve_pct"] == 92.5 and s["total"]["yoy_pct"] == -7.5
    assert s["status"] == "평소" and s["parts_flagged"] == ["식품"]
    rows = sales_rows(tmp_path, [["2026-11-04", "전체", 80, 100, 100], ["2026-11-04", "식품", 10, 10, 10]])
    s = judge.rule_sales(rows, TODAY)
    assert s["total"]["sales"] == 80 and s["status"] == "확인 필요" and len(s["reasons"]) >= 2


# 행사
def test_promos_vmd_deadline_and_channel(tmp_path):
    write_csv(tmp_path, "promotions", ["행사명", "시작일", "종료일", "알릴 길", "VMD 상태"], [
        ["가", "2026-11-07", "2026-11-10", "앱 푸시", "협의 중"],  # D-2, VMD 미완료
        ["나", "2026-11-07", "2026-11-10", "", "완료"],          # 알릴 길 없음
        ["다", "2026-11-12", "2026-11-15", "문자", "요청 전"],    # D-7, 요청 전이면 바로 경고
        ["바", "2026-11-06", "2026-11-08", "문자", "완료(10/30)"],  # 완료 단어가 들어 있으면 끝남
        ["라", "2026-10-01", "2026-10-30", "문자", "완료"],       # 끝난 행사
        ["마", "2026-11-20", "2026-11-25", "문자", "요청 전"],    # 7일 밖
    ])
    p = judge.rule_promos(I.read_table("promotions", tmp_path), TODAY)
    by = {i["name"]: i for i in p["items"]}
    assert set(by) == {"가", "나", "다", "바"}
    assert by["가"]["warns"] == ["VMD 협의 중(시작 D-2, 기준 D-3)"] and by["나"]["warns"] == ["알릴 길 미정"]
    assert by["다"]["warns"] == ["VMD 요청 전(시작 D-7, 지금 요청해야 D-3까지 끝남)"] and by["바"]["warns"] == []
    assert p["warn_count"] == 3 and p["status"] == "확인 필요"


def test_promos_end_before_start_is_error(tmp_path):
    write_csv(tmp_path, "promotions", ["행사명", "시작일", "종료일"], [["가", "2026-11-09", "2026-11-07"]])
    with pytest.raises(I.InputError, match="2행"):
        judge.rule_promos(I.read_table("promotions", tmp_path), TODAY)


# 실제 시범 집계
def test_pilot_from_weekly_file(tmp_path):
    rows = []
    for w in range(1, 5):
        rows += [[w, "받음", 18000, 1350, 70], [w, "남겨둠", 2000, 100, 6]]
    write_csv(tmp_path, "pilot_weekly", ["주차", "그룹", "회원수", "방문 횟수", "수신 거부"], rows)
    p = judge.rule_pilot(TODAY, weekly=I.read_table("pilot_weekly", tmp_path))
    assert not p["virtual"] and p["weeks_done"] == 4 and p["check_day"] and p["week_label"] == "4주차 점검일"
    assert p["visits_per_member_sent"] == 0.3 and p["visits_per_member_hold"] == 0.2
    assert p["new_ratio"] == 33.3 and p["decision"] == "넓힌다(현재 신호)" and "포아송" in p["source"]


def test_pilot_weekly_needs_both_groups(tmp_path):
    write_csv(tmp_path, "pilot_weekly", ["주차", "그룹", "회원수", "방문 횟수"], [[1, "받음", 100, 5]])
    with pytest.raises(I.InputError, match="함께"):
        judge.rule_pilot(TODAY, weekly=I.read_table("pilot_weekly", tmp_path))


# 현장 기록
def test_field_log_open_issue_then_overdue(tmp_path):
    write_csv(tmp_path, "field_log", ["날짜", "접점", "결과"], [
        ["2026-11-04", "고객 상담실", "문제"], ["2026-10-01", "주차 정산기", "정상"],
        *[["2026-11-04", n, "정상"] for n in C.FIELD_CHECKS if n not in ("고객 상담실", "주차 정산기")]])
    f = judge.rule_field(None, None, I.read_table("field_log", tmp_path), TODAY)
    assert [i["place"] for i in f["items"]] == ["고객 상담실", "주차 정산기"]
    assert "35일째" in f["items"][1]["why"]


def test_field_log_unknown_place_is_skipped(tmp_path):
    write_csv(tmp_path, "field_log", ["날짜", "접점", "결과"], [
        ["2026-11-04", "옥상 정원", "문제"], ["2026-11-04", "고객 상담실", "문제"]])
    f = judge.rule_field(None, None, I.read_table("field_log", tmp_path), TODAY)
    assert f["items"][0]["place"] == "고객 상담실"
    assert len(f["skipped"]) == 1 and "field_log.csv 2행" in f["skipped"][0] and "옥상 정원" in f["skipped"][0]


def test_csv_saved_by_korean_excel(tmp_path):
    (tmp_path / "field_log.csv").write_bytes("날짜,접점,결과\n2026-11-04,문화센터,문제\n".encode("cp949"))
    assert I.read_table("field_log", tmp_path)[0]["접점"] == "문화센터"


# 설정
def test_partial_touchpoints_gives_clear_error(tmp_path):
    local = tmp_path / "local.toml"
    local.write_text('[field]\ntouchpoints = [ { name = "VIP 주차장", every_days = 7, check = "x" } ]\n',
                     encoding="utf-8")
    with pytest.raises(C.ConfigError, match="목록 전체를 복사"):
        C.load([C.ROOT / "config.toml", local])
    local.write_text("[sales\n", encoding="utf-8")
    with pytest.raises(C.ConfigError, match="local.toml 형식 오류"):
        C.load([C.ROOT / "config.toml", local])


def test_local_config_overrides(tmp_path):
    real_mode(tmp_path, '[calendar]\nextra_holidays = { "2026-11-05" = "정기 휴점" }\n')
    assert C.MODE == "real" and not C.ALLOW_LLM and C.APP_ID == ""
    assert C.SITE_DIR == C.ROOT / "output" / "site" and C.INPUT_DIR == C.ROOT / "inputs"
    assert C.holiday_name(TODAY) == "정기 휴점"


# 내 데이터 모드 실행
def test_real_mode_writes_only_output(tmp_path, monkeypatch):
    real_mode(tmp_path)
    sales_rows(tmp_path / "inputs", [["2026-11-04", "전체", 80, 100, 100]])
    called = []
    monkeypatch.setattr(write, "llm_summary", lambda j: called.append(j))
    b = main.run(NOW, tmp_path, None, lambda d: {})
    assert called == []  # allow_llm 이 꺼져 있으면 Claude를 부르지 않는다
    assert b["mode"] == "real" and b["sales"]["status"] == "확인 필요" and b["review"] is None
    assert b["pilot"] is None and "pilot_weekly.xlsx" in b["missing"] and "promotions.xlsx" in b["missing"]
    assert b["top3"][0].startswith("매출 확인 필요") and "(가상)" not in b["top3"][0]
    assert (tmp_path / "output/site/index.html").exists() and (tmp_path / "output/site/data.js").exists()
    assert not (tmp_path / "docs").exists() and not (tmp_path / "data").exists()
    assert "외부에 공유하지 마세요" in (tmp_path / "output/site/brief.md").read_text(encoding="utf-8")


def test_real_mode_bad_file_shows_failure(tmp_path):
    real_mode(tmp_path)
    sales_rows(tmp_path / "inputs", [["어제", "전체", 80, 100, 100]])
    b = main.run(NOW, tmp_path, None, lambda d: {})
    f = b["failures"][0]
    assert f["step"] == "매출 파일 읽기" and "sales.csv 2행" in f["message"] and b["sales"] is None


def test_sample_mode_shows_virtual_sales_and_promos(tmp_path):
    b = main.run(NOW, tmp_path, lambda now: ([], []), lambda d: {}, lambda j: None)
    assert b["sales"] and b["promos"]["items"] and all("(가상)" in i["name"] for i in b["promos"]["items"])
    assert any("(가상)" in t for t in b["top3"]) and b["field"]["logged"]


# 알림
def test_webhook_payload(monkeypatch):
    sent = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout):
        sent.append(json.loads(req.data.decode("utf-8")))
        return Resp()
    b = {"date": "2026-11-05", "store_name": "내 점포", "top3": ["가", "나"], "failures": []}
    monkeypatch.delenv("BRIEF_WEBHOOK_URL", raising=False)
    assert notify.send(b, opener) is False and sent == []
    monkeypatch.setenv("BRIEF_WEBHOOK_URL", "https://hooks.example.test/x")
    assert notify.send(b, opener) is True
    assert sent[0] == {"text": "[아침 점검 2026-11-05] 내 점포\n1. 가\n2. 나"}


def test_init_templates(tmp_path):
    from brief import init
    made = init.make_templates(tmp_path)
    assert {p.name for p in made} == {f"{n}.xlsx" for n in I.SCHEMAS}
    assert init.make_templates(tmp_path) == []  # 있는 파일은 덮지 않는다
    for name in I.SCHEMAS:
        assert I.read_table(name, tmp_path) == []


# 열 이름 맞춤
def test_column_alias_title_rows_and_total_rows(tmp_path):
    real_mode(tmp_path, '[columns.sales]\n"날짜" = ["매출일자", "일자"]\n"매출" = "순매출"\n')
    write_csv(tmp_path, "sales", ["11월 매출 보고"], [[], ["매출일자", "구분", "순매출"],
                                                      ["2026-11-04", "식품", "100"], ["합계", "", "100"]])
    rows = I.read_table("sales", tmp_path)
    assert [r["날짜"] for r in rows] == ["2026-11-04"] and rows[0]["매출"] == "100"
    assert rows[0]["_row"] == 4  # 제목 줄을 건너뛰어도 엑셀 행 번호는 그대로
    write_csv(tmp_path, "sales", ["일자", "구분"], [["2026-11-04", "식품"]])
    with pytest.raises(I.InputError, match=r"\[columns.sales\]"):
        I.read_table("sales", tmp_path)


# 행사 성과
def test_promo_results_against_same_weekdays_before(tmp_path):
    days = [TODAY - dt.timedelta(days=k) for k in range(1, 20)]
    sales = sales_rows(tmp_path, [[d.isoformat(), "식품", 80 if d >= dt.date(2026, 11, 2) else 100, "", ""]
                                  for d in days])
    write_csv(tmp_path, "promotions", ["행사명", "시작일", "종료일", "매출 구분"], [
        ["가", "2026-11-02", "2026-11-08", "식품"],   # 진행 중, 11/02~11/04 를 10/26~10/28 과 견줌
        ["나", "2026-11-02", "2026-11-03", "리빙"],   # 리빙 매출이 없음
        ["다", "2026-11-07", "2026-11-09", "식품"],   # 아직 시작 전
        ["라", "2026-09-01", "2026-09-05", "식품"],   # 끝난 지 오래됨
    ])
    r = judge.rule_promo_results(I.read_table("promotions", tmp_path), sales, TODAY)
    by = {i["name"]: i for i in r["items"]}
    assert set(by) == {"가", "나"}
    assert by["가"]["base_from"] == "2026-10-26" and by["가"]["base_to"] == "2026-10-28" and by["가"]["to"] == "2026-11-04"
    assert by["가"]["growth"] == -20.0 and by["가"]["flag"] and r["status"] == "확인 필요"
    assert "견주지 않음" in by["나"]["note"] and not by["나"]["flag"]


# 접점 숫자
def test_touch_numbers_flag_and_small_values(tmp_path):
    rows = []
    for k in range(5):
        d = (dt.date(2026, 11, 4) - dt.timedelta(weeks=k)).isoformat()
        rows += [[d, "고객 상담실", "문의 앱 혜택", 20 if k == 0 else 10], [d, "문화센터", "취소", 4 if k == 0 else 1]]
    write_csv(tmp_path, "touchpoint_daily", ["날짜", "접점", "지표", "값"], rows)
    t = judge.rule_touch(I.read_table("touchpoint_daily", tmp_path), TODAY)
    by = {i["metric"]: i for i in t["items"]}
    assert by["문의 앱 혜택"]["change_pct"] == 100.0 and by["문의 앱 혜택"]["flag"]
    assert by["취소"]["change_pct"] is None and not by["취소"]["flag"]  # 평소 1은 min_value 5 미만
    assert [i["metric"] for i in t["flagged"]] == ["문의 앱 혜택"]
    f = judge.rule_field(None, None, None, TODAY, touch=t)
    assert f["items"][0]["place"] == "고객 상담실" and "문의 앱 혜택 20" in f["items"][0]["why"]


# 주간 정리와 새 블록
def test_sample_mode_new_blocks_and_weekly(tmp_path):
    b = main.run(NOW, tmp_path, lambda now: ([], []), lambda d: {}, lambda j: None)
    assert b["promo_results"]["items"] and b["touch"]["flagged"] and not b["failures"]
    titles = [s["title"] for s in b["weekly"]["sections"]]
    assert titles[:2] == ["매출", "행사 성과"] and b["weekly"]["to"] == "2026-11-04"
    md = (tmp_path / "docs" / "weekly.md").read_text(encoding="utf-8")
    assert md.startswith("# 주간 정리 2026-10-29 ~ 2026-11-04") and "가상" in md
    assert "·" not in md and "→" not in md


def test_consult_drafts_group_by_recipient(tmp_path):
    b = main.run(NOW, tmp_path, lambda now: ([], []), lambda d: {}, lambda j: None)
    drafts = {d["to"]: d for d in b["consult"]["drafts"]}
    assert "VMD 담당" in drafts and "채널 담당" in drafts and not b["failures"]
    # 성과가 낮은 행사는 VMD와 채널 둘 다에 간다
    for i in b["promo_results"]["items"]:
        if i["flag"]:
            assert all(any(i["name"] in x["fact"] for x in drafts[k]["items"]) for k in ("VMD 담당", "채널 담당"))
    # 접점 표시는 그 접점 담당에게
    for t in b["touch"]["flagged"]:
        assert f"{t['place']} 담당" in drafts
    # 초안 속 % 숫자는 모두 판단 결과에 있는 숫자
    judged = json.dumps({k: b[k] for k in ("sales", "promo_results", "touch")}, ensure_ascii=False)
    for d in drafts.values():
        for x in d["items"]:
            for n in re.findall(r"[+-]?(\d+(?:\.\d+)?)%", x["fact"]):
                assert n in judged, (n, x["fact"])
    md = (tmp_path / "docs" / "consult.md").read_text(encoding="utf-8")
    assert md.startswith("# 협의 초안 2026-11-05") and "가상" in md
    assert "·" not in md and "→" not in md


def test_plan_drafts_follow_calendar(tmp_path):
    b = main.run(NOW, tmp_path, lambda now: ([], []), lambda d: {}, lambda j: None)
    cards = {c["pilot"]: c for c in b["plan"]["cards"]}
    days = b["calendar"]["days"]
    # 시범마다 달력에서 그 시범이 처음 나오는 날을 고른다
    for n, c in cards.items():
        assert c["date"] == next(x["date"] for x in days if n in x["pilots"])
        assert c["target"] and c["copy_a"] and c["measure"]
    assert cards[1]["date"] == "2026-11-05" and cards[2]["date"] == "2026-11-08"
    assert any(b["pilot"]["decision"] in x for x in cards[1]["notes"])
    # 비 예보가 없는 날에는 비 문구를 쓰지 않는다
    assert "비 소식" not in cards[2]["copy_a"]
    rainy = main.run(NOW, tmp_path, lambda now: ([], []), lambda d: {"2026-11-08": 12.0}, lambda j: None)
    assert "비 소식" in {c["pilot"]: c for c in rainy["plan"]["cards"]}[2]["copy_a"]
    md = (tmp_path / "docs" / "plan.md").read_text(encoding="utf-8")
    assert md.startswith("# 집객 기획 초안 2026-11-05") and "·" not in md and "→" not in md


def test_offline_skips_network(tmp_path):
    def boom(*a):
        raise AssertionError("offline 인데 인터넷 수집을 부름")
    C.OFFLINE = True
    b = main.run(NOW, tmp_path, boom, boom, lambda j: None)
    assert b["review"] is None and not b["failures"]
    assert all(x["rain"] is None for x in b["calendar"]["days"])


# 페르소나 점검에서 나온 보완점
def test_thousand_won_header_and_config_unit(tmp_path):
    write_csv(tmp_path, "sales", ["날짜", "구분", "매출(천원)", "목표(천원)"], [["2026-11-04", "전체", "120,000", "100,000"]])
    s = judge.rule_sales(I.read_table("sales", tmp_path), TODAY)
    assert s["total"]["sales"] == 120_000_000 and s["total"]["target"] == 100_000_000 and "천원" in s["source"]
    real_mode(tmp_path, '[sales]\nunit = "천원"\n')
    write_csv(tmp_path, "sales", ["날짜", "구분", "매출"], [["2026-11-04", "전체", "5,000"], ["2026-11-03", "전체", "3백만원"]])
    s = judge.rule_sales(I.read_table("sales", tmp_path), TODAY)
    assert s["total"]["sales"] == 5_000_000 and s["mtd"]["sales"] == 8_000_000  # 칸에 적힌 단위가 설정보다 먼저
    # 설정의 사내 열 이름에 단위까지 적어도 맞는다
    real_mode(tmp_path, '[columns.sales]\n"매출" = "순매출액(천원)"\n')
    write_csv(tmp_path, "sales", ["날짜", "구분", "순매출액(천원)"], [["2026-11-04", "전체", "7"]])
    assert judge.rule_sales(I.read_table("sales", tmp_path), TODAY)["total"]["sales"] == 7_000


def test_one_period_column_and_date_styles(tmp_path):
    write_csv(tmp_path, "promotions", ["행사명", "기간", "알릴 길", "VMD 상태"], [
        ["가", "11/7~11/10", "앱 푸시", "완료"],
        ["나", "2026.11.08 - 2026.11.09", "문자", "완료"],
        ["다", "11월 7일부터 9일까지", "문자", "완료"],
        ["라", "20261106(금)~20261108(일)", "문자", "완료"],
    ])
    p = judge.rule_promos(I.read_table("promotions", tmp_path, TODAY), TODAY)
    got = {i["name"]: (i["start"], i["end"]) for i in p["items"]}
    assert got == {"가": ("2026-11-07", "2026-11-10"), "나": ("2026-11-08", "2026-11-09"),
                   "다": ("2026-11-07", "2026-11-09"), "라": ("2026-11-06", "2026-11-08")}
    write_csv(tmp_path, "promotions", ["행사명", "일정"], [["가", "11/7~11/10"]])
    with pytest.raises(I.InputError, match="'기간' 한 칸도 됨"):
        I.read_table("promotions", tmp_path, TODAY)


def test_subtotal_in_any_column_and_merged_dates(tmp_path):
    write_csv(tmp_path, "sales", ["날짜", "구분", "매출"], [
        ["2026-11-04", "식품", "100"], ["", "패션", "200"], ["", "소계", "300"], ["", "", "300"],
        ["2026-11-03", "식품", "50"]])
    rows = I.read_table("sales", tmp_path)
    assert [(r["날짜"], r["구분"]) for r in rows] == [("2026-11-04", "식품"), ("2026-11-04", "패션"), ("2026-11-03", "식품")]


def test_empty_template_is_not_missing(tmp_path):
    real_mode(tmp_path)
    write_csv(tmp_path / "inputs", "promotions", ["행사명", "시작일", "종료일"], [])
    sales_rows(tmp_path / "inputs", [["2026-11-04", "전체", 80, 100, 100]])
    b = main.run(NOW, tmp_path, None, lambda d: {})
    assert "promotions.xlsx" in b["empty"] and "promotions.xlsx" not in b["missing"] and not b["failures"]


def test_offline_summary_says_why_reviews_are_off(tmp_path):
    C.OFFLINE = True
    b = main.run(NOW, tmp_path, None, None, lambda j: None)
    assert b["offline"] is True and "offline" in b["summary"]


def test_consult_merges_same_promo_for_same_person():
    out = {"promos": {"items": [{"name": "가", "place": "", "start": "2026-11-04", "end": "2026-11-05", "phase": "진행 중",
                                 "warns": ["VMD 협의 중(이미 시작)", "알릴 길 미정", "내일 종료, 마감 안내 확인"]}]}}
    d = {x["to"]: x["items"] for x in judge.consult_drafts(TODAY, out)["drafts"]}
    assert len(d["VMD 담당"]) == 1 and len(d["채널 담당"]) == 1
    assert "내일 종료" in d["채널 담당"][0]["fact"] and "마감 안내" in d["채널 담당"][0]["ask"]


def test_last_day_copy_only_when_a_promo_ends(tmp_path):
    b = main.run(NOW, tmp_path, lambda now: ([], []), lambda d: {}, lambda j: None)
    ends = {i["end"] for i in b["promos"]["items"]}
    for c in b["plan"]["cards"]:
        assert ("마지막 날" in c["copy_a"]) == (c["date"] in ends)
    for x in b["calendar"]["days"]:
        assert x["ending"] == [i["name"] for i in b["promos"]["items"] if i["end"] == x["date"]]
