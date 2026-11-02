"""판단 규칙에 쓰는 값. config.toml 을 읽고, config.local.toml 이 있으면 그 값으로 덮는다.

리뷰 주제 단어 규칙만 코드에 고정한다(포트폴리오 5쪽과 같은 규칙). 나머지는 설정 파일에서 바꾼다.
"""
import datetime as dt
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 포트폴리오 5쪽과 같은 단어 규칙(현대백화점-apply/analysis/review_topics.py 의 TOPICS)
TOPICS = {
    "로그인/본인인증": r"로그인|인증|가입|비밀번호|비번|패턴|기기변경",
    "앱 실행 오류": r"안\s?열|실행|먹통|오류|에러|멈|다운|무한|네트워크|켜지|하얀|느려|렉|업데이트",
    "매장에서 혜택 사용": r"쿠폰|카드|라운지|주차|웨이팅|대기|결제|할인|적립|포인트|영수증|입장|정산|문화센터|문센",
}
BENEFIT = "매장에서 혜택 사용"
APP_BLOCK = TOPICS["로그인/본인인증"] + "|" + TOPICS["앱 실행 오류"]


class ConfigError(ValueError):
    pass


def _merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def config_paths():
    """BRIEF_CONFIG 가 있으면 그 파일을, 없으면 config.local.toml 을 기본 설정 위에 덮는다."""
    paths = [ROOT / "config.toml"]
    local = Path(os.environ["BRIEF_CONFIG"]) if os.environ.get("BRIEF_CONFIG") else ROOT / "config.local.toml"
    if local.exists():
        paths.append(local)
    return paths


def load(paths=None):
    """설정을 읽어 이 모듈의 값을 바꾼다. 다른 모듈은 C.이름 으로 실행 시점 값을 읽는다."""
    cfg = {}
    for p in paths or config_paths():
        with open(p, "rb") as f:
            try:
                cfg = _merge(cfg, tomllib.load(f))
            except tomllib.TOMLDecodeError as e:
                raise ConfigError(f"{Path(p).name} 형식 오류: {e}") from None
    g = globals()
    g["CFG"] = cfg
    run = cfg["run"]
    g["MODE"] = run.get("mode", "sample")
    g["SAMPLE"] = MODE == "sample"
    g["STORE_NAME"] = run.get("store_name", "")
    g["ALLOW_LLM"] = run.get("allow_llm", SAMPLE)
    g["WEBHOOK_ENV"] = run.get("webhook_env", "")
    g["REPO_URL"] = run.get("repo_url", "")
    # 시연은 docs/ 와 data/ 에 쓰고(공개), 내 데이터는 output/ 에만 쓴다(.gitignore)
    g["INPUT_DIR"] = ROOT / ("samples" if SAMPLE else run.get("input_dir", "inputs"))
    g["SITE_DIR"] = ROOT / ("docs" if SAMPLE else run.get("output_dir", "output") + "/site")
    g["DATA_DIR"] = ROOT / ("data" if SAMPLE else run.get("output_dir", "output") + "/data")

    rv = cfg["reviews"]
    g["APP_ID"], g["APP_NAME"] = rv.get("app_id", ""), rv.get("app_name", "앱")
    g["ALERT_MULTIPLE"], g["ALERT_BLOCKED"] = rv.get("alert_multiple", 2.0), rv.get("alert_blocked", 1)

    w = cfg["weather"]
    g["LAT"], g["LON"], g["RAIN_MM"] = w["lat"], w["lon"], w.get("rain_mm", 3)

    g["CAL"] = cfg["calendar"]
    g["CHANNELS"], g["CHANNEL_NOTE"] = CAL["channels"], CAL.get("channel_note", "")
    g["PILOTS"] = {int(k): v for k, v in cfg["pilots"].items()}
    g["SALES"], g["PROMO"] = cfg["sales"], cfg["promotions"]

    p = cfg["pilot"]
    g["PILOT_START"] = p["start"] if isinstance(p["start"], dt.date) else dt.date.fromisoformat(p["start"])
    g["PILOT_WEEKS"], g["CHECK_WEEKS"] = p["weeks"], tuple(p["check_weeks"])
    g["BREAKEVEN"] = p["breakeven_pct"] / 100

    f = cfg["field"]
    g["FIELD"] = f
    # 점검 질문 고정 목록. 이 목록 밖의 문장은 만들지 않는다
    g["FIELD_CHECKS"] = {t["name"]: t["check"] for t in f["touchpoints"]}
    g["TOUCHPOINT_WORDS"] = f.get("review_words", {})
    missing = [n for n in list(TOUCHPOINT_WORDS) + [f.get(k) for k in
               ("weekday_place", "sunday_place", "rain_holiday_place", "alert_place")] if n and n not in FIELD_CHECKS]
    if missing:
        raise ConfigError(f"[field] touchpoints 에 없는 접점: {', '.join(dict.fromkeys(missing))}. "
                          "config.local.toml 에 touchpoints 를 적을 때는 config.toml 의 목록 전체를 복사한 뒤 더해 주세요")
    return cfg


_KR = None


def holiday_name(day):
    """대한민국 공휴일(holidays 라이브러리)과 설정의 extra_holidays. 공휴일이 아니면 None."""
    global _KR
    extra = CAL.get("extra_holidays", {})
    if day.isoformat() in extra:
        return extra[day.isoformat()]
    if _KR is None:
        import holidays
        _KR = holidays.KR(language="ko")
    return _KR.get(day)


try:
    load()
except ConfigError as e:  # 실행 창과 run.log 에 한 줄로 남긴다
    raise SystemExit(f"설정 오류: {e}") from None
