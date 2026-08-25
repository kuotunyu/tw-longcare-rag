"""文件一致性守門：.env.example 與 config.py 不得漂移。"""

import re

from twlongcare.config import REPO_ROOT


def test_env_example_matches_config() -> None:
    env_text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    env_vars = set(re.findall(r"^([A-Z0-9_]+)=", env_text, flags=re.M))

    src_text = (REPO_ROOT / "src" / "twlongcare" / "config.py").read_text(encoding="utf-8")
    read_vars = set(re.findall(r'os\.getenv\("([A-Z0-9_]+)"', src_text))
    read_vars.update(
        re.findall(r'_runtime_path\("([A-Z0-9_]+)"', src_text)
    )

    assert env_vars == read_vars, f".env.example 與 config.py 讀取的變數不一致：{sorted(env_vars ^ read_vars)}"


def test_deployment_lineage_records_publication_contract() -> None:
    lineage_path = REPO_ROOT / "docs" / "deployment-lineage.md"
    assert lineage_path.is_file(), "缺少 deployment lineage 文件"

    text = lineage_path.read_text(encoding="utf-8")
    required_sections = (
        "## Canonical source",
        "## Space deployment",
        "## Frozen data and model boundary",
        "## Verification procedure",
        "## Rollback and update policy",
    )
    required_markers = (
        "https://github.com/kuotunyu/tw-longcare-rag",
        "https://huggingface.co/spaces/steven0226/tw-longcare-rag",
        "2026-07-17-e941dcc3e345",
        "GitHub is the source of truth",
        "white-listed deployment subset",
        "Rollback",
    )

    for marker in (*required_sections, *required_markers):
        assert marker in text, f"deployment lineage 缺少必要標記：{marker}"
