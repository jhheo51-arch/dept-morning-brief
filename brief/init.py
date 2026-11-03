"""내 업무용 준비. inputs/ 에 엑셀 양식을, 루트에 config.local.toml 을 만든다. 있는 파일은 덮지 않는다.

python -m brief.init
"""
import sys

from . import inputs as I
from . import rules_config as C

LOCAL = """# 내 설정. config.toml 의 값 중 바꿀 것만 적습니다. 이 파일은 저장소에 올라가지 않습니다.
[run]
mode = "real"
store_name = "내 점포"
# 매출 같은 내부 숫자가 외부 API로 나가므로 꺼 둡니다. 회사 보안 기준을 확인한 뒤에만 켭니다.
allow_llm = false
# 인터넷에 전혀 나가지 않습니다(앱 리뷰와 날씨 예보를 건너뛰고 요일과 공휴일로만 달력을 만듦).
# 회사 IT에서 외부 접속(Google Play, Open-Meteo)을 허용받은 뒤에 false 로 바꿉니다.
offline = true
repo_url = ""

# [reviews]
# app_id = ""             # 리뷰를 안 볼 때는 빈 문자열

# [weather]
# lat = 37.5216           # 내 점포 좌표
# lon = 126.9242

# [calendar]                # 기본 문장은 여의도 점포 시연용입니다. 내 점포 근거로 바꿉니다
# weekday_basis = "평일 17~20시 매출 비중 ..."
# sunday_basis = "..."
# extra_holidays = { "2026-11-16" = "정기 휴점" }

# [sales]
# unit = "천원"             # 사내 파일 금액이 천원 단위면. 열 이름이 '매출(천원)'이면 적지 않아도 됩니다
# yoy_alert_pct = -10       # 전년 대비 이 % 이하이면 확인 필요
# target_alert_pct = 90     # 목표 달성률이 이 % 미만이면 확인 필요

# [pilot]
# start = 2026-11-16        # 내 시범 시작일
# breakeven_pct = 25        # 내 본전 비율

# [promotions]
# result_days = 14          # 끝난 뒤 며칠까지 행사 성과를 보여 줄지
# result_low_pct = -5       # 앞 같은 요일 기간 대비 이 % 이하이면 확인 필요(가정값)
# target_low_pct = 95       # 행사 목표 대비 예상(진행 중) 또는 달성률(끝남)이 이 % 미만이면 확인 필요(가정값)

# [touchpoint_daily]
# change_pct = 30           # 평소(직전 4주 같은 요일 평균)보다 이 % 넘게 다르면 확인 필요
# min_value = 5             # 평소 값이 이보다 작으면 % 판단을 하지 않음

# 사내 BI나 공유 폴더가 파일을 날마다 떨어뜨리면 그 경로를 적습니다. 가장 최근 파일을 읽습니다.
# [sources]
# sales = "D:/BI_export/일매출_*.xlsx"

# 사내 파일 열 이름이 양식과 다르면 여기에 적습니다. 왼쪽이 양식 열 이름, 오른쪽이 내 파일 열 이름입니다.
# [columns.sales]
# "날짜" = ["매출일자", "일자"]
# "매출" = "순매출"
"""


def make_templates(folder):
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    folder.mkdir(parents=True, exist_ok=True)
    made = []
    for name, (need, opt) in I.SCHEMAS.items():
        p = folder / f"{name}.xlsx"
        if p.exists() or (folder / f"{name}.csv").exists():
            continue
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "입력"
        ws.append(need + opt)
        for c in ws[1]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="E3F3F0")
            ws.column_dimensions[c.column_letter].width = 16
        help_ws = wb.create_sheet("설명")
        help_ws.append(["열", "꼭 필요", "적는 법"])
        for col in need + opt:
            help_ws.append([col, "예" if col in need else "아니요", I.HELP[name].get(col, "")])
        help_ws.column_dimensions["C"].width = 70
        help_ws.append([])
        help_ws.append(["첫 시트(입력)만 읽습니다. 열 이름은 양식대로 두는 것이 가장 쉽습니다. 사내 파일 열 이름이 다르면 config.local.toml 의 [columns] 에 적습니다. 열 이름 줄 위의 제목 줄(10줄까지), 합계와 소계 줄, 빈 줄은 건너뜁니다. 날짜 칸이 병합되어 비어 있으면 윗줄 날짜를 씁니다. 금액이 천원 단위면 열 이름을 '매출(천원)'처럼 둡니다. 행사 기간이 한 칸('11/04~11/10')이면 열 이름을 '기간'으로 둡니다."])
        wb.save(p)
        made.append(p)
    return made


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    local = C.ROOT / "config.local.toml"
    if not local.exists():
        local.write_text(LOCAL, encoding="utf-8")
        print(f"만듦: {local}")
    else:
        print(f"있음(그대로 둠): {local}")
    for p in make_templates(C.ROOT / "inputs"):
        print(f"만듦: {p}")
    how = "run_brief.bat" if C.FROZEN else "python -m brief.main"
    print(f"\n다음: inputs/ 의 엑셀에 내 자료를 붙여 넣고 `{how}` 을 실행하면 "
          "output/site/index.html 이 생깁니다. 없는 파일의 블록은 건너뜁니다.")


if __name__ == "__main__":
    main()
