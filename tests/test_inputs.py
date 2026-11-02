"""내 업무 파일 읽기, 매출과 행사 규칙, 실제 시범 집계, 현장 주기, 내 데이터 모드 출력."""
import csv
import datetime as dt
import json

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
        ["다", "2026-11-12", "2026-11-15", "문자", "요청 전"],    # D-7, 아직 경고 아님
        ["라", "2026-10-01", "2026-10-30", "문자", "완료"],       # 끝난 행사
        ["마", "2026-11-20", "2026-11-25", "문자", "요청 전"],    # 7일 밖
    ])
    p = judge.rule_promos(I.read_table("promotions", tmp_path), TODAY)
    by = {i["name"]: i for i in p["items"]}
    assert set(by) == {"가", "나", "다"}
    assert by["가"]["warns"] == ["VMD 협의 중(시작 D-2, 기준 D-3)"] and by["나"]["warns"] == ["알릴 길 미정"]
    assert by["다"]["warns"] == [] and p["warn_count"] == 2 and p["status"] == "확인 필요"


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
