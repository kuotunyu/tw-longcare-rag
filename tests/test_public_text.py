"""公開文案守門腳本 scripts/check_public_text.py 的守門測試。

重點是共同作者尾行：GitHub 的 Contributors 名單會把 Co-authored-by 的對象
一併列入，本專案要求該名單只有 repo 擁有者本人，因此這種尾行必須在
commit-msg hook 就被擋下，而不是事後才發現名單多了人（已推上去的 commit
要移除只能改寫歷史）。
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_public_text.py"


@pytest.fixture(scope="module")
def checker():
    """scripts/ 不是套件，以檔案路徑載入模組。"""
    spec = importlib.util.spec_from_file_location("check_public_text", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _msg_file(tmp_path: Path, text: str) -> str:
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_commit_msg_rejects_coauthor_trailer(checker, tmp_path) -> None:
    msg = _msg_file(
        tmp_path,
        "feat: 加一個小功能\n\n說明一句。\n\nCo-Authored-By: 某人 <someone@example.com>\n",
    )
    assert checker.main(["--msg-file", msg]) == 1


def test_commit_msg_rejects_coauthor_trailer_case_insensitive(checker, tmp_path) -> None:
    msg = _msg_file(tmp_path, "fix: 修一個問題\n\nco-authored-by: 某人 <x@example.com>\n")
    assert checker.main(["--msg-file", msg]) == 1


def test_commit_msg_accepts_clean_message(checker, tmp_path) -> None:
    msg = _msg_file(tmp_path, "feat: 加一個小功能\n\n說明一句。\n")
    assert checker.main(["--msg-file", msg]) == 0


def test_coauthor_check_does_not_apply_to_plain_files(checker, tmp_path) -> None:
    """尾行禁令只針對 commit 訊息；文件裡「說明不要加這種尾行」不該被誤擋。"""
    doc = tmp_path / "NOTES.md"
    doc.write_text("提醒：commit 訊息不要加 Co-authored-by 尾行。\n", encoding="utf-8")
    assert checker.main([str(doc)]) == 0
