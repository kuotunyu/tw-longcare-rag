"""文件一致性守門：.env.example 與 config.py 不得漂移。"""

import re

from twlongcare.config import REPO_ROOT


def test_env_example_matches_config() -> None:
    env_text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    env_vars = set(re.findall(r"^([A-Z0-9_]+)=", env_text, flags=re.M))

    src_text = (REPO_ROOT / "src" / "twlongcare" / "config.py").read_text(encoding="utf-8")
    read_vars = set(re.findall(r'os\.getenv\("([A-Z0-9_]+)"', src_text))

    assert env_vars == read_vars, f".env.example 與 config.py 讀取的變數不一致：{sorted(env_vars ^ read_vars)}"
