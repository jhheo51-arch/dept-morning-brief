"""수집 실패 시 대체 동작, 요약 숫자 검사, 리뷰 원문 미저장 검사."""
import datetime as dt
import json
import os
from pathlib import Path

import pytest

from brief import main, write
from brief.collect import KST

NOW = dt.datetime(2026, 11, 5, 7, 0, tzinfo=KST)
SENTINEL = "테스트전용문장 주차 정산하려는데 로그인이 안 돼서 돌아감"


def fake_reviews(now):
    raw = [{"at": now - dt.timedelta(hours=2), "score": 1, "content": SENTINEL},
           {"at": now - dt.timedelta(days=3), "score": 5, "content": "테스트전용문장 좋아요 아주 만족합니다"}]
    from brief.collect import classify
    return [{"at": r["at"], "score": r["score"], **classify(r["content"])} for r in raw], [r["content"] for r in raw]


def fail(*_):
    raise ConnectionError("network down")


def read_all(root):
    return "".join(p.read_text(encoding="utf-8") for p in root.rglob("*") if p.is_file())


def test_full_run_writes_brief_without_raw_text(tmp_path):
    b = main.run(NOW, tmp_path, fake_reviews, lambda d: {"2026-11-05": 0.0}, lambda j: None)
    assert b["review"]["blocked_new"] == 1 and b["review"]["status"] == "확인 필요"
    assert len(b["top3"]) == 3 and b["summary_by"] == "문장 틀"
    assert "테스트전용문장" not in read_all(tmp_path)
    for f in ["docs/data.js", "docs/brief.md", "docs/brief.json", "data/latest.json", "data/history/2026-11-05.json"]:
        assert (tmp_path / f).exists()
    md = (tmp_path / "docs/brief.md").read_text(encoding="utf-8")
    assert len(md) < 700  # 한 장, 2분 안에 읽히는 길이


def test_leak_guard_detects_planted_text(tmp_path):
    main.run(NOW, tmp_path, fake_reviews, lambda d: {}, lambda j: None)
    (tmp_path / "docs" / "oops.md").write_text(SENTINEL, encoding="utf-8")
    assert main.find_leaks([SENTINEL], tmp_path)


def test_collect_failure_uses_last_success(tmp_path):
    main.run(NOW, tmp_path, fake_reviews, lambda d: {}, lambda j: None)
    later = NOW + dt.timedelta(days=1)
    b = main.run(later, tmp_path, fail, fail, lambda j: None)
    steps = {f["step"]: f for f in b["failures"]}
    assert set(steps) == {"리뷰 수집", "날씨 예보 수집"}
    assert steps["리뷰 수집"]["last_success"] == "2026-11-05"
    assert b["review"]["stale"] and b["review"]["low_new"] == 1
    assert all(d["rain"] is None for d in b["calendar"]["days"])  # 예보 없이 요일로 달력
    assert b["field"]["items"] and b["pilot"]["decision"]
    page = (tmp_path / "docs/data.js").read_text(encoding="utf-8")
    assert "리뷰 수집" in page and "2026-11-06" in page


def test_collect_failure_without_history_still_writes_page(tmp_path):
    b = main.run(NOW, tmp_path, fail, fail, lambda j: None)
    assert b["review"] is None and b["top3"] and b["summary"]
    assert (tmp_path / "docs/data.js").exists()


def test_summary_numbers_must_exist_in_judgment():
    j = {"review": {"low_new": 2, "avg28_per_day": 0.18}, "pilot": {"new_ratio": 37.3}}
    assert write.check_summary("새 1~2점 2건, 새 방문 비율 37.3%입니다.", j)
    assert not write.check_summary("새 1~2점 3건입니다.", j)
    assert not write.check_summary("리뷰 2건 → 확인", j)


class FakeClient:
    def __init__(self, text):
        self.messages = self
        self.text = text

    def create(self, **_):
        block = type("B", (), {"type": "text", "text": self.text})()
        return type("M", (), {"content": [block]})()


def test_llm_summary_discarded_when_number_invented():
    j = {"review": {"low_new": 2}}
    assert write.llm_summary(j, FakeClient("새 1~2점 2건입니다.")) == "새 1~2점 2건입니다."
    assert write.llm_summary(j, FakeClient("새 1~2점 5건입니다.")) is None


def test_no_key_means_template(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert write.llm_summary({"a": 1}) is None


REPO = Path(__file__).resolve().parent.parent
RAW_KEYS = ("\"content\"", "\"userName\"", "\"reviewId\"", "\"replyContent\"", "\"userImage\"")


def repo_files():
    skip = {".git", ".pytest_cache", "__pycache__", ".venv"}
    return [p for p in REPO.rglob("*") if p.is_file() and not skip & set(p.relative_to(REPO).parts)
            and p.suffix in {".json", ".js", ".md", ".html", ".py", ".txt", ".yml", ".csv"}]


def test_repo_has_no_review_fields():
    for p in repo_files():
        if p.suffix == ".py":  # 코드는 필드 이름을 읽기만 한다
            continue
        body = p.read_text(encoding="utf-8")
        assert not any(k in body for k in RAW_KEYS), p


@pytest.mark.skipif(os.environ.get("LIVE_REVIEWS") != "1", reason="LIVE_REVIEWS=1 일 때만 실제 리뷰를 받아 검사")
def test_repo_has_no_live_review_text():
    """실제 최근 리뷰 원문을 받아 저장소 전체 파일에 들어 있지 않은지 본다. 원문은 메모리에만 둔다."""
    _, texts = __import__("brief.collect", fromlist=["x"]).fetch_reviews(dt.datetime.now(KST), days=400)
    probes = {t.strip()[:20] for t in texts if len(t.strip()) >= 10}
    assert probes
    hits = [str(p) for p in repo_files() for s in probes if s in p.read_text(encoding="utf-8")]
    assert hits == []
