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


def _v():
    return "(가상)" if C.SAMPLE else ""


def _sales_line(s):
    t = s["total"]
    bits = [f"{s['date'][5:].replace('-', '/')} 매출{_v()} {t['sales_text']}"]
    if t["achieve_pct"] is not None:
        bits.append(f"목표 {t['achieve_pct']}%")
    if t["yoy_pct"] is not None:
        bits.append(f"전년 대비 {t['yoy_pct']:+}%")
    return ", ".join(bits)


def _parts_line(s, n=2):
    """기준을 넘은 구분을 숫자와 함께. 예: 식품 전년 대비 -10.9%, F&B 목표 달성 85.0%"""
    bits = [f"{p['part']} {p['flags'][0].split('(')[0]}" for p in s["parts"] if p["flags"]][:n]
    more = len(s["parts_flagged"]) - len(bits)
    return ", ".join(bits) + (f" 외 {more}개" if more > 0 else "")


def top_three(out):
    """확인 필요 항목을 먼저, 그다음 오늘 할 일. 최대 세 줄. 확인 필요가 세 개를 넘으면 두 줄 뒤에 나머지를 종류별로 센다."""
    sales, promos, review, calendar, pilot, field, touch, res = (out.get(k) for k in (
        "sales", "promos", "review", "calendar", "pilot", "field", "touch", "promo_results"))
    urgent, usual = [], []
    tasks = out.get("tasks")
    if tasks and tasks["status"] == "확인 필요":
        hot = [i for i in tasks["items"] if i["warn"]]
        more = f" 외 {len(hot) - 1}건" if len(hot) > 1 else ""
        urgent.append(("업무", f"업무 {hot[0]['name']}: {hot[0]['phase']}{more}"))
    if sales:
        line = f"매출 {sales['status']}: {_sales_line(sales)}"
        if sales["status"] == "구분 확인":
            # 첫 줄에서 문제 구분의 숫자가 바로 보이게 구분을 앞에, 전체를 뒤에 둔다
            line = f"매출 구분 확인: {_parts_line(sales)}. 전체는 {_sales_line(sales)}"
        elif sales["parts_flagged"]:
            line += f". 볼 구분 {_parts_line(sales)}"
        if sales["status"] != "평소":
            urgent.insert(0, ("매출", line))  # 점장 보고의 첫 줄은 매출이다
        else:
            usual.append(line)
    if promos:
        warned = [i for i in promos["items"] if i["warns"]]
        if warned:
            i = warned[0]
            more = f" 외 {len(warned) - 1}건" if len(warned) > 1 else ""
            urgent.append(("행사", f"행사 {i['name']}: {', '.join(i['warns'])}{more}"))
        elif promos["items"]:
            usual.append(f"행사 진행 {promos['running']}건, 7일 안 시작 {promos['upcoming']}건, 경고 없음")
    if res and res["status"] == "확인 필요":
        i = next(i for i in res["items"] if i["flag"])
        why = (f"목표 대비 이대로면 {i['forecast_pct']}%" if i.get("low_target") and i.get("forecast_pct") is not None
               else f"목표의 {i['target_pct']}%로 끝남" if i.get("low_target")
               else f"{i['part']} 매출 앞 같은 요일 기간 대비 {i['growth']:+}%")
        urgent.append(("행사 성과", f"행사 성과 {i['name']}: {why}"))
    if touch and touch["flagged"]:
        t = touch["flagged"][0]
        more = f" 외 {len(touch['flagged']) - 1}건" if len(touch["flagged"]) > 1 else ""
        urgent.append(("접점 숫자", f"접점 숫자 {t['place']} {t['metric']}: {t['value']:,.0f}, 평소 대비 {t['change_pct']:+}%{more}"))
    if review:
        line = (f"앱 리뷰 {review['status']}: 새 1~2점 {review['low_new']}건, 막힘 {review['blocked_new']}건"
                f"(지난 7일 1~2점 {review['low_7d']}건)")
        if review["status"] == "확인 필요":
            urgent.append(("앱 리뷰", line))
        else:
            usual.append(line)
    if calendar:
        t = calendar["days"][0]
        what = f"{_pilot_names(t['pilots'])}, {', '.join(t['times'])} {', '.join(t['channels'])}"             if t["pilots"] and t["channels"] else (_pilot_names(t["pilots"]) or "맞는 시범 없음")
        usual.append(f"오늘({', '.join(t['situation'])}) {what}")
    if pilot and pilot.get("check_day"):
        urgent.append(("시범", f"시범 {pilot['week_label']}: {pilot['decision']}" + ("(가상 데이터)" if pilot["virtual"] else "")))
    if field and field["items"]:
        i = field["items"][0]
        usual.append(f"현장 {i['place']}: {i['check']}")
    if len(urgent) > 3:
        rest = list(dict.fromkeys(k for k, _ in urgent[2:]))
        return [t for _, t in urgent[:2]] + [f"그 밖에 확인 필요 {len(urgent) - 2}가지({', '.join(rest)})"]
    return ([t for _, t in urgent] + usual)[:3]


def template_summary(out):
    sales, promos, review, calendar, pilot, touch, res = (out.get(k) for k in (
        "sales", "promos", "review", "calendar", "pilot", "touch", "promo_results"))
    s = []
    if sales:
        if sales["status"] == "구분 확인":
            s.append(f"{_sales_line(sales)}로 전체는 기준 안이지만 {_parts_line(sales)}로 구분 확인이 필요합니다.")
        else:
            s.append(f"{_sales_line(sales)}로 {sales['status']}입니다.")
    if promos and promos["warn_count"]:
        s.append(f"행사 {len(promos['items'])}건 중 {promos['warn_count']}건에 경고가 있습니다.")
    if res and res["status"] == "확인 필요":
        s.append(f"행사 성과 {sum(i['flag'] for i in res['items'])}건이 낮습니다.")
    if touch and touch["flagged"]:
        s.append(f"접점 숫자 {len(touch['flagged'])}건이 평소와 다릅니다.")
    tasks = out.get("tasks")
    if tasks and tasks["items"]:
        s.append(f"열린 업무 {len(tasks['items'])}건 중 기한 지남 {tasks['overdue']}건, 오늘 마감 {tasks['due_today']}건입니다.")
    if review:
        t = review.get("totals30")
        s.append(f"앱 리뷰는 {review['status']}입니다. 새 1~2점은 {review['low_new']}건, 막힘은 "
                 f"{review['blocked_new']}건이고 "
                 + (f"최근 30일 1~2점은 {t['low']}건, 막힘은 {t['blocked']}건입니다." if t
                    else f"지난 7일 합계는 {review['low_7d']}건입니다."))
    elif C.APP_ID and C.OFFLINE:
        s.append("인터넷을 쓰지 않는 설정(offline)이라 앱 리뷰는 보지 않았습니다.")
    elif C.APP_ID:
        s.append("앱 리뷰는 수집하지 못해 판단을 건너뜁니다.")
    if calendar:
        t = calendar["days"][0]
        s.append(f"오늘은 {', '.join(t['situation'])}이라 "
                 + (f"{_pilot_names(t['pilots'])}에 맞춰 봅니다." if t["pilots"] else "따로 부를 시범이 없습니다."))
    if pilot:
        who = "가상 시범" if pilot.get("virtual") else "시범"
        s.append(f"{who}은 {pilot['week_label']} 기준이고 판단은 {pilot['decision']}입니다."
                 if pilot.get("weeks_done", 0) > 0 else f"{who}은 아직 집계 전입니다.")
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
        try:
            import anthropic
        except ImportError:  # exe 판은 anthropic 을 묶지 않는다
            return None
        client = anthropic.Anthropic()
    prompt = ("아래 JSON은 백화점 마케팅 담당자의 아침 점검 판단 결과입니다. 한국어 3문장으로 요약하세요. "
              "JSON에 없는 숫자는 쓰지 마세요. 확인 필요 항목을 먼저 쓰세요. 판단을 바꾸지 마세요. 가상 데이터는 가상이라고 밝히세요. "
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
    if b.get("lead"):
        lines += ["팀장 보고 한 장은 lead.md 에 있습니다.", ""]
    if (b.get("sales") or {}).get("unit_note"):
        lines += [f"매출 단위: {b['sales']['unit_note']}", ""]
    t = b.get("tasks")
    if t and t["items"]:
        head = "## 업무" + (f" ({t.get('stale_from') or '지난'} 결과, 오늘 읽기 실패)" if t.get("stale") else "")
        lines += [head] + [f"- {i['phase']} | {i['name']}" + (f" ({i['owner']})" if i["owner"] else "")
                                for i in t["items"][:C.TASKS.get("max_rows", 10)]] + [""]
    if b["failures"]:
        lines += [f"실패: {', '.join(f['step'] for f in b['failures'])}. "
                  "실패한 블록은 마지막 성공 결과를 보여 줍니다.", ""]
        lines += [f"- {f['message']}" for f in b["failures"] if f.get("message")]
    old = [f for f in b.get("files", []) if f["old"]]
    if old:
        lines += ["오늘 전에 바뀐 파일: " + ", ".join(f"{f['file']}({f['modified'][5:10].replace('-', '/')})" for f in old)
                  + ". 어제 자료가 맞는지 보고 쓰세요", ""]
    if b.get("missing"):
        lines += [f"아직 없는 파일: {', '.join(b['missing'])}(넣으면 그 블록이 나옵니다)", ""]
    if b.get("empty"):
        lines += [f"내용이 빈 파일: {', '.join(b['empty'])}(머리글 아래에 자료를 붙여 넣으면 나옵니다)", ""]
    lines += ["공개 데이터와 가상 데이터만 씁니다. 현대백화점 내부 자료가 아닙니다." if b.get("mode", "sample") == "sample"
              else "내 업무 파일로 만든 점검입니다. 외부에 공유하지 마세요.", ""]
    return "\n".join(lines)


def lead_markdown(b):
    L = b["lead"]
    return "\n".join([f"# 팀장 보고 한 장 {b['date']}", "", "```", L["text"], "```", "",
                      f"고르는 규칙: {L['rule_text']}.", "보내기 전에 숫자와 담당을 한 번 더 확인합니다.", ""])


def weekly_markdown(b):
    w = b["weekly"]
    lines = [f"# 주간 정리 {w['from']} ~ {w['to']}" + (f" | {b['store_name']}" if b.get("store_name") else ""), ""]
    for sec in w["sections"]:
        lines += [f"## {sec['title']}"] + [f"- {x}" for x in sec["lines"]] + [""]
    lines += [f"만든 날 {b['date']}. {w['source']}.",
              "가상 데이터로 만든 시연입니다." if b.get("mode", "sample") == "sample"
              else "내 업무 파일로 만든 초안입니다. 외부에 공유하지 마세요.", ""]
    return "\n".join(lines)


def consult_markdown(b):
    c = b["consult"]
    lines = [f"# 협의 초안 {b['date']}", ""]
    if not c["drafts"]:
        lines += ["오늘은 협의할 확인 필요 항목이 없습니다.", ""]
    for d in c["drafts"]:
        lines += [f"## {d['to']}", "", d["text"], ""]
    lines += [f"묶는 규칙: {c['rule_text']}.", "보내기 전에 문장을 다듬고, 숫자는 원본 파일과 한 번 더 맞춰 봅니다.", ""]
    return "\n".join(lines)


def plan_markdown(b):
    p = b["plan"]
    lines = [f"# 집객 기획 초안 {b['date']}", ""]
    if not p["cards"]:
        lines += ["이번 주 달력에 맞춰 볼 시범이 없습니다.", ""]
    for c in p["cards"]:
        lines += [f"## {c['pilot']}번 {c['name']} | {c['when']}", "",
                  f"- 왜 이날: {c['situation']}. {c['basis']}",
                  f"- 누구에게: {c['target']}",
                  f"- 무엇을: {c['benefit']}" + (f" (행사 파일: {', '.join(c['benefit_from'])})" if c.get("benefit_from")
                                                 else " [혜택 확정 후, 행사 파일에 없음]"),
                  f"- 알릴 길: {', '.join(c['channels'])}",
                  f"- 문구 A: {c['copy_a']}",
                  f"- 문구 B: {c['copy_b']}",
                  f"- 재는 법: {c['measure']}",
                  f"- 맡을 곳: {c['owner']}"]
        lines += [f"- 참고: {x}" for x in c["notes"]] + [""]
    lines += [f"고르는 규칙: {p['rule_text']}.", "초안입니다. 무엇을 할지는 담당자가 정합니다.", ""]
    return "\n".join(lines)
