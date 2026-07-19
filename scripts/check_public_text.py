"""公開文案守門：掃描待公開文字，攔下禁詞、本機絕對路徑與金鑰樣式。

用法：
    uv run python scripts/check_public_text.py --staged             # pre-commit：掃 staged diff 新增行與檔名
    uv run python scripts/check_public_text.py --msg-file <路徑>    # commit-msg：掃 commit 訊息
    uv run python scripts/check_public_text.py README.md            # 掃指定檔案全文（發佈前手動檢查）

規則來源：
1. 內建通用樣式（本檔）：Windows 使用者絕對路徑、常見金鑰字樣（sk- / AIza / hf_ / ghp_）
2. 禁詞清單 ``.claude/private/redlist.txt``（不進 git）：一行一詞、``#`` 為註解，
   比對不分大小寫（純子字串、非 regex）。清單不存在時印警告但不擋。

發現違規 exit 1（git hook 據此擋下 commit），否則 0。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REDLIST_PATH = REPO_ROOT / ".claude" / "private" / "redlist.txt"

# 內建樣式的寫法刻意避免與自身原始碼互相匹配（否則本檔自己就 commit 不進去）
BUILTIN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Windows 使用者絕對路徑", re.compile(r"[A-Za-z]:[\\/]+Users\b")),
    ("疑似 OpenAI 金鑰", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("疑似 Google API 金鑰", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("疑似 Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("疑似 GitHub token", re.compile(r"\bghp_[A-Za-z0-9]{30,}")),
]


def load_redlist() -> list[str]:
    if not REDLIST_PATH.exists():
        rel = REDLIST_PATH.relative_to(REPO_ROOT)
        print(f"[public-copy-check] 警告：找不到 {rel}，僅套用內建樣式", file=sys.stderr)
        return []
    terms: list[str] = []
    for line in REDLIST_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line.lower())
    return terms


def scan_text(label: str, text: str, redlist: list[str]) -> list[str]:
    hits: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        low = line.lower()
        excerpt = line.strip()[:80]
        for term in redlist:
            if term in low:
                hits.append(f"{label}:{lineno} 禁詞「{term}」→ {excerpt}")
        for name, pat in BUILTIN_PATTERNS:
            if pat.search(line):
                hits.append(f"{label}:{lineno} {name} → {excerpt}")
    return hits


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=REPO_ROOT,
    )
    return proc.stdout


def scan_staged(redlist: list[str]) -> list[str]:
    """掃 staged diff 的新增行（不掃刪除行，移除禁詞的 commit 不該被擋）與檔名。"""
    hits: list[str] = []
    names = _git("diff", "--cached", "--name-only")
    hits += scan_text("staged-檔名", names, redlist)

    diff = _git("diff", "--cached", "--unified=0", "--no-color")
    current = "?"
    added: dict[str, list[str]] = {}
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            added.setdefault(current, []).append(line[1:])
    for path, lines in added.items():
        hits += scan_text(f"staged:{path}", "\n".join(lines), redlist)
    return hits


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - 舊終端不支援時照常執行
            pass

    redlist = load_redlist()
    hits: list[str] = []
    if "--staged" in argv:
        hits += scan_staged(redlist)
    elif "--msg-file" in argv:
        msg_path = Path(argv[argv.index("--msg-file") + 1])
        hits += scan_text("commit-msg", msg_path.read_text(encoding="utf-8", errors="replace"), redlist)
    else:
        for arg in argv:
            p = Path(arg)
            if p.is_file():
                hits += scan_text(str(p), p.read_text(encoding="utf-8", errors="replace"), redlist)
            else:
                print(f"[public-copy-check] 跳過（非檔案）：{arg}", file=sys.stderr)

    if hits:
        print("[public-copy-check] ❌ 發現不可公開內容：")
        for h in hits:
            print("  " + h)
        print("[public-copy-check] 修正後再試；誤判請調整 .claude/private/redlist.txt 或本檔內建樣式。")
        return 1
    print("[public-copy-check] ✅ 通過")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
