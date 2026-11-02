"""내 업무 파일 읽기. 엑셀(.xlsx, 첫 시트)이나 CSV(UTF-8)를 받는다.

파일이 없으면 None 을 돌려 그 블록을 건너뛰고, 형식이 틀리면 파일 이름과 행 번호를 담은 InputError 를 낸다.
"""
import csv
import datetime as dt
import re

from . import rules_config as C

# 파일 이름(확장자 제외), 꼭 있어야 하는 열, 있으면 쓰는 열
SCHEMAS = {
    "sales": (["날짜", "구분", "매출"], ["목표", "전년"]),
    "promotions": (["행사명", "시작일", "종료일"], ["장소", "알릴 길", "VMD 상태", "담당", "메모"]),
    "pilot_weekly": (["주차", "그룹", "회원수", "방문 횟수"], ["수신 거부"]),
    "field_log": (["날짜", "접점"], ["결과", "메모"]),
}
HELP = {
    "sales": {"날짜": "매출일(2026-11-01)", "구분": "전체, 식품, 패션처럼 보고 싶은 단위. '전체'가 없으면 나머지를 더함",
              "매출": "그날 매출(원)", "목표": "그날 목표(원), 없으면 비움", "전년": "전년 같은 요일 매출(원), 없으면 비움"},
    "promotions": {"행사명": "행사 이름", "시작일": "2026-11-01", "종료일": "2026-11-09", "장소": "식품관, 문화센터 등",
                   "알릴 길": "앱 푸시, 문자 등. 비어 있으면 '알릴 길 미정'으로 알림", "VMD 상태": "요청 전, 협의 중, 완료",
                   "담당": "담당자나 협력 부서", "메모": "자유롭게"},
    "pilot_weekly": {"주차": "1, 2, 3...", "그룹": "받음(혜택을 보낸 회원) 또는 남겨둠(보내지 않은 회원)",
                     "회원수": "그룹 회원 수", "방문 횟수": "그 주 그룹 전체 방문 횟수", "수신 거부": "그 주 수신 거부 수"},
    "field_log": {"날짜": "다녀온 날", "접점": "config 의 touchpoints 이름과 같게",
                  "결과": "정상, 문제, 해결 중 하나", "메모": "본 것과 조치"},
}


class InputError(ValueError):
    pass


def find(name, folder=None):
    folder = folder or C.INPUT_DIR
    for ext in (".xlsx", ".csv"):
        p = folder / f"{name}{ext}"
        if p.exists():
            return p
    return None


def _cells(p):
    if p.suffix == ".xlsx":
        import openpyxl
        ws = openpyxl.load_workbook(p, read_only=True, data_only=True).worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    with open(p, encoding="utf-8-sig", newline="") as f:  # 엑셀에서 'CSV UTF-8'로 저장한 파일
        return list(csv.reader(f))


def read_table(name, folder=None):
    """[{열 이름: 값, '_row': 행 번호}] 또는 파일이 없으면 None."""
    p = find(name, folder)
    if p is None:
        return None
    try:
        cells = _cells(p)
    except UnicodeDecodeError:
        raise InputError(f"{p.name}: 글자가 깨집니다. 엑셀에서 'CSV UTF-8' 형식으로 다시 저장해 주세요") from None
    if not cells:
        raise InputError(f"{p.name}: 빈 파일입니다")
    head = [str(h).strip() if h is not None else "" for h in cells[0]]
    need, _ = SCHEMAS[name]
    lack = [c for c in need if c not in head]
    if lack:
        raise InputError(f"{p.name}: {', '.join(lack)} 열이 없습니다. 첫 줄에 필요한 열: {', '.join(need)}")
    rows = []
    for i, r in enumerate(cells[1:], start=2):
        if not any(v not in (None, "") for v in r):
            continue
        row = {h: (r[j] if j < len(r) else None) for j, h in enumerate(head) if h}
        row = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        row["_row"] = i
        row["_file"] = p.name
        rows.append(row)
    return rows


def where(row):
    return f"{row['_file']} {row['_row']}행"


def to_date(v, row, col):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    m = re.fullmatch(r"(\d{4})[-./ ]\s*(\d{1,2})[-./ ]\s*(\d{1,2})\.?", str(v or "").strip())
    if not m:
        raise InputError(f"{where(row)} '{col}' 값 '{v}'을 날짜로 읽지 못했습니다(예: 2026-11-01)")
    return dt.date(*map(int, m.groups()))


def to_num(v, row, col, required=True):
    if v is None or str(v).strip() == "":
        if required:
            raise InputError(f"{where(row)} '{col}' 값이 비어 있습니다")
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[,\s원명회건]", "", str(v))
    try:
        return float(s)
    except ValueError:
        raise InputError(f"{where(row)} '{col}' 값 '{v}'을 숫자로 읽지 못했습니다") from None


def group_of(v, row):
    s = str(v or "")
    if re.search(r"받|발송|보냄|send|test", s, re.I):
        return "sent"
    if re.search(r"남|대조|미발송|hold|control", s, re.I):
        return "hold"
    raise InputError(f"{where(row)} '그룹' 값 '{v}'은 '받음' 또는 '남겨둠'이어야 합니다")
