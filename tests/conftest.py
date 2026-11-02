import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from brief import rules_config as C  # noqa: E402


@pytest.fixture(autouse=True)
def default_config():
    """내 PC의 config.local.toml 과 관계없이 저장소 기본 설정(시연)으로 테스트한다."""
    C.load([ROOT / "config.toml"])
    yield
    C.load([ROOT / "config.toml"])
