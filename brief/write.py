"""작성 단계. 오늘 볼 것 세 가지, 3문장 요약(문장 틀 또는 Claude), 브리핑 Markdown."""
import json
import os
import re

from . import rules_config as C

MODEL = "claude-sonnet-5-5"
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
TERMS = re.compile(r"1~2점")  # 숫자가 아니라 용어로 쓰는 말


def _pilot_names(nums):
    return ", ".join(f"{n}번 {C.PILOTS[n]}" for n in nums)


def top_three(review, calendar, pilot, field):
    out = []
    if review:
        out.append(f"앱 리뷰 {review['status']}: 새 1~2점 {review['low_new']}건, 막힘 {review['blocked_new']}건"
                   f"(지난 7일 1~2점 {review['low_7d']}건)")
    if calendar:
        t = calendar["days"][0]
        what = f"{_pilot_names(t['pilots'])}, {', '.join(t['times'])} {', '.join(t['channels'])}" \
            if t["pilots"] and t["channels"] else (_pilot_names(t["pilots"]) or "맞는 시범 없음")
        out.append(f"오늘({', '.join(t['situation'])}) {what}")
    if pilot and pilot.get("check_day"):
        out.append(f"시범 {pilot['weeks_done']}주차 점검일: {pilot['decision']}(가상 데이터)")
    elif field and field["items"]:
        i = field["items"][0]
        out.append(f"현장 {i['place']}: {i['check']}")
    return out[:3]


def template_summary(review, calendar, pilot):
    s = []
    if review:
        s.append(f"앱 리뷰는 {review['status']}입니다. 새 1~2점은 {review['low_new']}건, 막힘은 "
                 f"{review['blocked_new']}건이고 지난 7일 합계는 {review['low_7d']}건입니다.")
    else:
        s.append("앱 리뷰는 수집하지 못해 판단을 건너뜁니다.")
    if calendar:
        t = calendar["days"][0]
        s.append(f"오늘은 {', '.join(t['situation'])}이라 "
                 + (f"{_pilot_names(t['pilots'])}에 맞춰 봅니다." if t["pilots"] else "따로 부를 시범이 없습니다."))
    if pilot:
        s.append(f"가상 시범은 {pilot['week']}주차이고 판단은 {pilot['decision']}입니다.")
    return " ".join(s)


def _numbers(text):
    return {n.replace(",", "").rstrip("0").rstrip(".") if "." in n else n.replace(",", "")
            for n in NUM.findall(text)}


def check_summary(summary, judgment):
    """요약에 나온 숫자가 모두 판단 JSON 안에 있고 금지 기호가 없으면 True."""
    if not summary or "·" in summary or "→" in summary:
        return False
    allowed = _numbers(json.dumps(judgment, ensure_ascii=False))
    return _numbers(TERMS.sub("", summary)) <= allowed


def llm_summary(judgment, client=None):
    """ANTHROPIC_API_KEY 가 있을 때만 Claude에 3문장 요약을 맡긴다. 숫자 검사를 통과하지 못하면 None."""
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        import anthropic
        client = anthropic.Anthropic()
    prompt = ("아래 JSON은 백화점 마케팅 담당자의 아침 점검 판단 결과입니다. 한국어 3문장으로 요약하세요. "
              "JSON에 없는 숫자는 쓰지 마세요. 판단을 바꾸지 마세요. 가상 데이터는 가상이라고 밝히세요. "
              "가운데 점과 화살표 기호는 쓰지 마세요. 요약 문장만 답하세요.\n\n"
              + json.dumps(judgment, ensure_ascii=False))
    try:
        msg = client.messages.create(model=MODEL, max_tokens=400,
                                     messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    except Exception:
        return None
    return text if check_summary(text, judgment) else None


def brief_markdown(b):
    lines = [f"# 아침 점검 {b['date']}", "", "## 오늘 볼 것"]
    lines += [f"{i}. {t}" for i, t in enumerate(b["top3"], 1)]
    lines += ["", "## 요약", b["summary"], ""]
    if b["failures"]:
        lines += [f"수집 실패: {', '.join(f['step'] for f in b['failures'])}. "
                  "실패한 블록은 마지막 성공 결과를 보여 줍니다.", ""]
    lines += ["공개 데이터와 가상 데이터만 씁니다. 현대백화점 내부 자료가 아닙니다.", ""]
    return "\n".join(lines)
