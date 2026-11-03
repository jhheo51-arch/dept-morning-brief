"""내 업무 파일 읽기. 엑셀(.xlsx, 첫 시트)이나 CSV(UTF-8 또는 엑셀 기본 cp949)를 받는다.

파일이 없으면 None 을 돌려 그 블록을 건너뛰고, 형식이 틀리면 파일 이름과 행 번호를 담은 InputError 를 낸다.
"""
import csv
import datetime as dt
import io
import re

from . import rules_config as C

# 파일 이름(확장자 제외), 꼭 있어야 하는 열, 있으면 쓰는 열
SCHEMAS = {
    "sales": (["날짜", "구분", "매출"], ["목표", "전년"]),
    "promotions": (["행사명", "시작일", "종료일"], ["장소", "매출 구분", "목표", "알릴 길", "VMD 상태", "담당", "메모"]),
    "pilot_weekly": (["주차", "그룹", "회원수", "방문 횟수"], ["수신 거부"]),
    "field_log": (["날짜", "접점"], ["결과", "메모"]),
    "touchpoint_daily": (["날짜", "접점", "지표", "값"], ["메모"]),
    "tasks": (["업무"], ["기한", "상태", "담당", "관련 행사", "완료일", "메모"]),
}
HELP = {
    "sales": {"날짜": "매출일(2026-11-01)", "구분": "전체, 식품, 패션처럼 보고 싶은 단위. '전체'가 없으면 나머지를 더함",
              "매출": "그날 매출(원). 천원 단위 파일이면 열 이름을 '매출(천원)'으로 두거나 설정 [sales] unit 에 적음",
              "목표": "그날 목표, 없으면 비움", "전년": "전년 같은 요일 매출, 없으면 비움"},
    "promotions": {"행사명": "행사 이름", "시작일": "2026-11-01", "종료일": "2026-11-09", "장소": "식품관, 문화센터 등",
                   "매출 구분": "행사 성과를 볼 sales 파일의 구분(식품 등). 비우면 전체 매출로 봄",
                   "목표": "행사 기간 전체의 그 매출 구분 매출 목표(원, '30억'처럼 적어도 됨). 없으면 비움",
                   "알릴 길": "앱 푸시, 문자 등. 비어 있으면 '알릴 길 미정'으로 알림", "VMD 상태": "요청 전, 협의 중, 완료",
                   "담당": "담당자나 협력 부서", "메모": "자유롭게"},
    "pilot_weekly": {"주차": "1, 2, 3...", "그룹": "받음(혜택을 보낸 회원) 또는 남겨둠(보내지 않은 회원)",
                     "회원수": "그룹 회원 수", "방문 횟수": "그 주 그룹 전체 방문 횟수", "수신 거부": "그 주 수신 거부 수"},
    "field_log": {"날짜": "다녀온 날", "접점": "config 의 touchpoints 이름과 같게",
                  "결과": "정상, 문제, 해결 중 하나", "메모": "본 것과 조치"},
    "touchpoint_daily": {"날짜": "집계한 날", "접점": "문화센터, 우수고객 라운지, 고객 상담실 등",
                         "지표": "수강 신청, 이용 수, 문의 앱 혜택처럼 접점 안에서 같은 이름으로", "값": "그날 숫자(건, 명)",
                         "메모": "자유롭게"},
    "tasks": {"업무": "할 일 한 줄(예: 주말 행사 문자 문구 확정)", "기한": "끝낼 날(2026-11-07 또는 11/07, 비워 두면 기한 없음)",
              "상태": "비우면 할 일. '완료'를 적으면 보관 목록으로 옮김", "담당": "담당자나 협력 부서",
              "관련 행사": "promotions 파일의 행사명", "완료일": "끝낸 날, 비우면 처음 완료로 본 날",
              "메모": "자유롭게"},
}
SKIP_WORDS = {"합계", "소계", "총계", "계", "누계"}  # 사내 내려받기 파일의 합계 줄
SKIP_END = ("합계", "소계", "총계")  # '식품 소계'처럼 끝에 붙는 경우
# 금액 단위. 열 이름 끝의 '(천원)'이나 설정 [sales] unit 으로 정하고, 읽을 때 원으로 바꾼다
UNITS = {"원": 1, "천원": 1e3, "만원": 1e4, "백만원": 1e6, "억원": 1e8}
MONEY = {"sales": ["매출", "목표", "전년"], "promotions": ["목표"]}
UNIT_HEAD = re.compile(r"^(.*?)\s*[(\[]\s*(천\s*원|백만\s*원|만\s*원|억\s*원|원)\s*[)\]]$")
# 한 칸에 적힌 값을 표준 열 두 개로 나누는 열(행사 기간 '11/04~11/10')
SPLIT = {"promotions": {"기간": ("시작일", "종료일")}}
BLANK_NUM = {"-", "–", "—", "－", "N/A", "n/a", "해당없음"}
# 완료 단어 앞뒤에 이런 말이 붙으면 끝나지 않은 것으로 본다('미완료', '완료 예정', '확정 대기', '끝나면 보고')
NOT_DONE_BEFORE = ("미", "未", "아직", "덜")
NOT_DONE_AFTER = ("예정", "대기", "필요", "전", "중", "나면", "못", "안", "않", "아님", "보류", "?")
RANGE = re.compile(r"(.+?)\s*(?:~|∼|〜|～|–|—|\s-\s|부터)\s*(.+?)(?:\s*까지)?")


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
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8-sig")  # 엑셀 'CSV UTF-8'
    except UnicodeDecodeError:
        text = raw.decode("cp949")  # 한국어 엑셀 기본 'CSV(쉼표로 분리)'
    return list(csv.reader(io.StringIO(text, newline="")))


def _lacking(cols, name):
    """꼭 있어야 하는데 없는 열. 기간 한 칸이 있으면 시작일과 종료일은 있는 것으로 본다."""
    need, _ = SCHEMAS[name]
    covered = {c for k, pair in SPLIT.get(name, {}).items() if k in cols for c in pair}
    return [c for c in need if c not in cols and c not in covered]


def _is_total(r, idx):
    """첫 칸이나 꼭 있어야 하는 열에 '합계', '소계', '식품 소계' 같은 글자가 있으면 합계 줄로 본다."""
    vals = [r[j] for j in {0, *idx} if j < len(r)]
    return any(isinstance(v, str) and (v.replace(" ", "") in SKIP_WORDS or v.strip().endswith(SKIP_END)) for v in vals)


def read_table(name, folder=None, today=None):
    """[{열 이름: 값, '_row': 행 번호}] 또는 파일이 없으면 None. today 는 연도 없는 행사 기간을 읽을 때 쓴다."""
    p = find(name, folder)
    if p is None:
        return None
    try:
        cells = _cells(p)
    except UnicodeDecodeError:
        raise InputError(f"{p.name}: 글자가 깨집니다. 엑셀에서 'CSV UTF-8'이나 '엑셀 통합 문서(xlsx)'로 다시 저장해 주세요") from None
    if not cells:
        raise InputError(f"{p.name}: 빈 파일입니다")
    need, _ = SCHEMAS[name]
    # 사내 파일은 제목 줄이 위에 붙는 일이 많아 앞 10줄 안에서 머리글 줄을 찾는다
    tried = []
    for at, line in enumerate(cells[:10]):
        cols, units = standard_head(line, name)
        lack = _lacking(cols, name)
        if not lack:
            break
        tried.append((len(need) - len(lack), at, lack))
    else:
        # 가장 많이 맞은 줄을 머리글로 보고, 그 줄에서 실제로 빠진 열만 알린다
        hit, at, lack = max(tried, key=lambda t: (t[0], -t[1]))
        head = f"{at + 1}행 머리글에 {', '.join(lack)} 열이 없습니다" if hit else "앞 10줄에서 머리글 줄을 찾지 못했습니다"
        alt = "".join(f"({', '.join(pair)} 대신 '{k}' 한 칸도 됨)" for k, pair in SPLIT.get(name, {}).items())
        raise InputError(f"{p.name}: {head}. 필요한 열: {', '.join(need)}{alt}. "
                         f"사내 파일 열 이름이 다르면 설정의 [columns.{name}] 에 적어 주세요")
    scale = _scales(name, units)
    split = {k: pair for k, pair in SPLIT.get(name, {}).items() if k in cols and not all(c in cols for c in pair)}
    key_idx = [cols[c] for c in need + list(split) if c in cols]
    rows, last_date = [], None
    for i, r in enumerate(cells[at + 1:], start=at + 2):
        if not any(v not in (None, "") for v in r):
            continue
        if _is_total(r, key_idx):
            continue
        row = {h: (r[j] if j < len(r) else None) for h, j in cols.items()}
        row = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        row["_row"] = i
        row["_file"] = p.name
        if "날짜" in need:
            if row.get("날짜") in (None, ""):
                # 병합 셀로 내려받으면 같은 날 둘째 줄부터 날짜가 빈다. 다음 열(구분, 접점)도 비면 소계 같은 줄로 보고 건너뛴다
                if row.get(need[1]) in (None, "") or last_date is None:
                    continue
                row["날짜"] = last_date
            last_date = row["날짜"]
        for k, (a, b) in split.items():
            row[a], row[b] = to_period(row.get(k), row, k, today or dt.date.today())
        if scale:
            row["_scale"] = scale
        rows.append(row)
    return rows


def standard_head(line, name):
    """머리글 줄을 ({표준 열 이름: 열 번호}, {표준 열 이름: 금액 단위}) 로.

    설정 [columns.파일이름] 의 표준 이름 = ["사내 이름", ...] 을 쓴다. 사내 열 하나를 표준 열 여럿에 짝지을 수 있다
    (하루짜리 행사만 적는 파일의 '행사일'을 시작일과 종료일 둘 다로). 열 이름 끝의 '(천원)' 같은 단위는 떼어 따로 돌려준다.
    """
    head, units = [], {}
    for j, h in enumerate(line):
        h = str(h).strip() if h is not None else ""
        m = UNIT_HEAD.fullmatch(h)
        if m and m.group(1):
            h, units[j] = m.group(1), m.group(2).replace(" ", "")
        head.append(h)
    cols = {}
    for j, h in enumerate(head):
        if h and h not in cols:
            cols[h] = j
    for std, names in C.COLUMNS.get(name, {}).items():
        names = [names] if isinstance(names, str) else names
        # 설정에 '순매출액(천원)'처럼 단위까지 적어도 맞는다
        names = [m.group(1) if (m := UNIT_HEAD.fullmatch(str(n).strip())) and m.group(1) else str(n).strip() for n in names]
        if std in cols:
            continue
        for j, h in enumerate(head):
            if h in names:
                cols[std] = j
                break
    return cols, {std: units[j] for std, j in cols.items() if j in units}


def _scales(name, units):
    """금액 열마다 원으로 바꿀 배수. 열 이름의 단위가 먼저이고, 없으면 설정 [sales] unit(매출 파일만)."""
    if name not in MONEY:
        return {}
    unit = str(C.SALES.get("unit", "") or "원").replace(" ", "") if name == "sales" else "원"
    if unit not in UNITS:
        raise InputError(f"설정 [sales] unit 값 '{unit}'을 모릅니다. {', '.join(UNITS)} 중 하나로 적어 주세요")
    out = {c: UNITS[units.get(c, unit)] for c in MONEY[name]}
    return out if any(v != 1 for v in out.values()) else {}


def unit_note(rows):
    """원이 아닌 단위로 읽었으면 화면에 남길 한 줄. 원 단위면 빈 글자."""
    scale = rows[0].get("_scale") if rows else None
    if not scale:
        return ""
    by = {}
    for c, v in scale.items():
        by.setdefault(next(k for k, x in UNITS.items() if x == v), []).append(c)
    return ", ".join(f"{', '.join(cs)} 열을 {u} 단위로 읽어 원으로 바꿈" for u, cs in by.items() if u != "원")


def is_done(text, words):
    """상태 칸이 끝난 일인지. 완료 단어가 있어도 앞뒤에 '미', '예정', '대기' 같은 말이 붙으면 끝나지 않은 것으로 본다.
    애매하면 끝나지 않은 쪽(경고가 나오는 쪽)으로 읽는다. 괄호 속 날짜 메모는 보지 않는다('완료(10/30)')."""
    s = str(text or "").strip()
    for w in words:
        i = s.find(w)
        while i >= 0:
            before, after = s[:i], re.sub(r"\([^)]*\)", "", s[i + len(w):])
            if not before.endswith(NOT_DONE_BEFORE) and "아직" not in before \
                    and not any(b in after for b in NOT_DONE_AFTER):
                return True
            i = s.find(w, i + 1)
    return False


def where(row):
    return f"{row['_file']} {row['_row']}행"


DATE = re.compile(r"(\d{4})\s*(?:[-./]|년)\s*(\d{1,2})\s*(?:[-./]|월)\s*(\d{1,2})\s*일?\.?")
DATE8 = re.compile(r"(\d{4})(\d{2})(\d{2})")
DATE6 = re.compile(r"(\d{2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})\.?")  # '26.11.07'
MONTH_DAY = re.compile(r"(\d{1,2})\s*(?:[-./]|월)\s*(\d{1,2})\s*일?\.?")
TAIL = re.compile(r"\s*(?:\([^)]*\)|[월화수목금토일]요일|\d{1,2}:\d{2}(?::\d{2})?)\s*$")


def _strip_tail(s):
    """'2026-11-01(일)', '2026-11-01 00:00:00' 처럼 뒤에 붙은 요일과 시각을 뗀다."""
    while True:
        t = TAIL.sub("", s)
        if t == s:
            return s.strip()
        s = t


def to_date(v, row, col):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    s = str(int(v)) if isinstance(v, (int, float)) and not isinstance(v, bool) else _strip_tail(str(v or "").strip())
    if not s:
        raise InputError(f"{where(row)} '{col}' 값이 비어 있습니다")
    m = DATE.fullmatch(s) or DATE8.fullmatch(s)
    m6 = None if m else DATE6.fullmatch(s)
    try:
        if m:
            return dt.date(*map(int, m.groups()))
        if m6:
            y, mo, d = map(int, m6.groups())
            return dt.date(2000 + y, mo, d)
    except ValueError:
        pass
    raise InputError(f"{where(row)} '{col}' 값 '{v}'을 날짜로 읽지 못했습니다(예: 2026-11-01)")


def _near_year(month, day, near):
    """연도 없는 날짜는 기준일에 가장 가까운 해로 본다(12월에 적은 '1/05'는 다음 해)."""
    got = []
    for y in (near.year - 1, near.year, near.year + 1):
        try:
            got.append(dt.date(y, month, day))
        except ValueError:
            continue
    if not got:
        raise ValueError
    return min(got, key=lambda d: abs((d - near).days))


def _one(s, near, row, col):
    if DATE.fullmatch(s) or DATE8.fullmatch(s) or DATE6.fullmatch(s):
        return to_date(s, row, col)
    m = MONTH_DAY.fullmatch(s)
    if not m:
        raise ValueError
    return _near_year(int(m.group(1)), int(m.group(2)), near)


def to_day(v, row, col, today):
    """업무 기한처럼 연도를 빼고 적기 쉬운 날짜. '11/07', '11월 7일'은 오늘과 가까운 해로 읽는다."""
    if isinstance(v, (dt.date, dt.datetime)):
        return to_date(v, row, col)
    if not str(v or "").strip():
        raise InputError(f"{where(row)} '{col}' 값이 비어 있습니다")
    try:
        return _one(_strip_tail(str(v or "").strip()), today, row, col)
    except ValueError:
        raise InputError(f"{where(row)} '{col}' 값 '{v}'을 날짜로 읽지 못했습니다(예: 2026-11-07 또는 11/07)") from None


def to_period(v, row, col, today):
    """'11/04~11/10', '2026-11-04 ~ 2026-11-10', '11월 4일부터 10일까지' 를 (시작일, 종료일)로."""
    if isinstance(v, (dt.date, dt.datetime)):  # 날짜 하나면 하루짜리 행사
        d = to_date(v, row, col)
        return d, d
    s = str(v or "").strip()
    m = RANGE.fullmatch(s)
    if not m and s.count("-") == 1 and "/" in s:  # '11/4-11/10'
        m = re.fullmatch(r"(.+?)-(.+)", s)
    bad = InputError(f"{where(row)} '{col}' 값 '{v}'을 기간으로 읽지 못했습니다(예: 2026-11-04~2026-11-10 또는 11/04~11/10)")
    if not m:
        raise bad
    a, b = (_strip_tail(x) for x in m.groups())
    try:
        start = _one(a, today, row, col)
        if re.fullmatch(r"\d{1,2}\s*일?", b):  # '11월 4일부터 10일까지'
            end = start.replace(day=int(re.sub(r"\D", "", b)))
        else:
            end = _one(b, start, row, col)
    except (ValueError, InputError):
        raise bad from None
    return start, end


def to_num(v, row, col, required=True):
    """숫자 칸을 읽는다. 금액 열은 _scale(열 이름이나 설정의 단위)대로 원으로 바꾼다."""
    if v is None or str(v).strip() == "":
        if required:
            raise InputError(f"{where(row)} '{col}' 값이 비어 있습니다")
        return None
    scale = (row.get("_scale") or {}).get(col, 1)
    if isinstance(v, (int, float)):
        return float(v) * scale
    t = re.sub(r"[,\s]", "", str(v))
    if t in BLANK_NUM:  # 사내 파일에서 '없음'을 '-'로 적는 칸
        if required:
            raise InputError(f"{where(row)} '{col}' 값이 비어 있습니다('{v}')")
        return None
    sign = 1
    if re.fullmatch(r"\(.+\)", t):  # 회계 표기 (1,200) 은 음수
        sign, t = -1, t[1:-1]
    if t[:1] == "△":  # △1,200 도 음수
        sign, t = -sign, t[1:]
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)(천원|백만원|만원|억원|원|백만|천|만|억|명|회|건)?", t)
    if not m:
        raise InputError(f"{where(row)} '{col}' 값 '{v}'을 숫자로 읽지 못했습니다")
    n, unit = float(m.group(1)) * sign, m.group(2)
    if unit in UNITS:  # 칸에 '1,234천원', '1.2억'처럼 단위가 적혀 있으면 그 단위를 따른다
        return n * UNITS[unit]
    if unit and unit + "원" in UNITS:
        return n * UNITS[unit + "원"]
    return n * scale


def group_of(v, row):
    s = str(v or "")
    if re.search(r"받|발송|보냄|send|test", s, re.I):
        return "sent"
    if re.search(r"남|대조|미발송|hold|control", s, re.I):
        return "hold"
    raise InputError(f"{where(row)} '그룹' 값 '{v}'은 '받음' 또는 '남겨둠'이어야 합니다")
