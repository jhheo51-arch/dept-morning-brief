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
# yoy_alert_pct = -10       # 전년 대비 이 % 이하이면 확인 필요
# target_alert_pct = 90     # 목표 달성률이 이 % 미만이면 확인 필요

# [pilot]
# start = 2026-11-16        # 내 시범 시작일
# breakeven_pct = 25        # 내 본전 비율
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
        help_ws.append(["첫 시트(입력)만 읽습니다. 첫 줄 열 이름은 바꾸지 마세요. 빈 줄은 건너뜁니다."])
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
    print("\n다음: inputs/ 의 엑셀에 내 자료를 붙여 넣고 `python -m brief.main` 을 실행하면 "
          "output/site/index.html 이 생깁니다. 없는 파일의 블록은 건너뜁니다.")


if __name__ == "__main__":
    main()
