"""공개 시연용 가상 입력 파일. 내 파일과 같은 형식으로 samples/ 에 쓰고 같은 읽기 경로로 읽는다.

모든 숫자와 행사는 가상이다. 같은 날짜로 돌리면 같은 파일이 나온다.
"""
import csv
import datetime as dt

import numpy as np

# 구분별 하루 기준 매출(원, 가상), 요일 배수(월~일)
PARTS = {"식품": 210e6, "패션잡화": 340e6, "리빙": 120e6, "F&B": 90e6}
DOW_MULT = [0.85, 0.82, 0.86, 0.9, 1.05, 1.45, 1.3]
PROMOS = [  # 이름, 오늘 기준 시작, 끝, 장소, 알릴 길, VMD 상태, 담당
    ("겨울 아우터 기획전(가상)", -6, 4, "패션잡화 행사장", "앱 푸시, 문자", "완료", "패션팀"),
    ("식품관 저녁 타임 혜택(가상)", -2, 12, "식품관", "앱 푸시", "완료", "식품팀"),
    ("리빙 브랜드 팝업(가상)", -10, 1, "팝업 행사장", "매장 안내물", "완료", "리빙팀"),
    ("문화센터 원데이 클래스 주간(가상)", 2, 8, "문화센터", "", "협의 중", "문화센터"),
    ("사은 행사(가상)", 5, 11, "고객센터 옆", "앱 푸시, 문자", "요청 전", "영업기획"),
]


def _write(path, head, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)


def make(folder, today, days=60):
    rows = []
    for i in range(days, 0, -1):
        d = today - dt.timedelta(days=i)
        rng = np.random.default_rng(d.toordinal())
        drift = 0.93 if i <= 3 else 1.0  # 최근 사흘은 일부러 약하게 해서 경보가 보이게 한다
        for name, base in PARTS.items():
            prev = base * DOW_MULT[d.weekday()] * rng.normal(1, 0.06)
            sales = prev * rng.normal(1.03, 0.07) * drift
            target = prev * 1.05
            rows.append([d.isoformat(), name, round(sales, -4), round(target, -4), round(prev, -4)])
    _write(folder / "sales.csv", ["날짜", "구분", "매출", "목표", "전년"], rows)

    _write(folder / "promotions.csv", ["행사명", "시작일", "종료일", "장소", "알릴 길", "VMD 상태", "담당", "메모"],
           [[n, (today + dt.timedelta(days=s)).isoformat(), (today + dt.timedelta(days=e)).isoformat(),
             p, ch, v, o, "가상 행사"] for n, s, e, p, ch, v, o in PROMOS])

    log = [(-3, "우수고객 라운지", "정상"), (-5, "문화센터", "정상"), (-2, "고객 상담실", "해결 중"),
           (-9, "고객센터", "정상"), (-20, "주차 정산기", "정상"), (-4, "계산대", "정상"),
           (-6, "웨이팅 접수대", "정상"), (-1, "지하 연결 입구", "정상"), (-8, "팝업 행사장", "정상")]
    _write(folder / "field_log.csv", ["날짜", "접점", "결과", "메모"],
           [[(today + dt.timedelta(days=d)).isoformat(), p, r, "가상 기록"] for d, p, r in log])
    return folder
