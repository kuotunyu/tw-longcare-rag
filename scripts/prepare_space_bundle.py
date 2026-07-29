"""組出可推送到 HF Space 的檔案子集（白名單複製，避免手動漏檔或誤帶敏感檔案）。

只複製 Space 執行期真正需要的東西：app.py、src/twlongcare/、五個小型資料檔、
space/README.md（含 Space frontmatter）→ README.md、space/requirements.txt →
requirements.txt。刻意不複製 data/chroma、data/bm25s（Space 冷啟動會自動重建，
見 retriever.py／index_build.py）、data/raw、models/、logs/、.env、tests/、docs/。

用法：
    uv run python scripts/prepare_space_bundle.py                # 預設輸出 dist/space-bundle/
    uv run python scripts/prepare_space_bundle.py --out <目錄>

產出後手動推送（首次）：
    cd dist/space-bundle
    git init
    git remote add space https://huggingface.co/spaces/<你的帳號>/<space名稱>
    git add . && git commit -m "deploy: 初次部署"
    git push space main
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# (來源相對路徑, 目的相對路徑)；來源是檔案就複製檔案，是目錄就整棵複製（跳過 __pycache__）
FILES = [
    ("app.py", "app.py"),
    ("src/twlongcare", "src/twlongcare"),
    ("data/laws.json", "data/laws.json"),
    ("data/contextual_cache.json", "data/contextual_cache.json"),
    ("data/chapter_summaries.json", "data/chapter_summaries.json"),
    ("data/law_graph.json", "data/law_graph.json"),
    ("data/testset.json", "data/testset.json"),
    ("data/law_version_manifest.json", "data/law_version_manifest.json"),
    ("data/versions/laws", "data/versions/laws"),
    ("space/README.md", "README.md"),
    ("space/requirements.txt", "requirements.txt"),
]


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(
            src, dst,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            dirs_exist_ok=True,
        )
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="dist/space-bundle")
    args = parser.parse_args()

    out_dir = (REPO_ROOT / args.out).resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    missing = []
    for rel_src, rel_dst in FILES:
        src = REPO_ROOT / rel_src
        if not src.exists():
            missing.append(rel_src)
            continue
        _copy(src, out_dir / rel_dst)
        print(f"複製：{rel_src} → {args.out}/{rel_dst}")

    if missing:
        print(f"\n⚠️ 缺少以下檔案，未複製：{missing}")
        raise SystemExit(1)

    total_size = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())
    n_files = sum(1 for f in out_dir.rglob("*") if f.is_file())
    print(f"\n完成：{n_files} 個檔案，共 {total_size / 1024:.0f} KB → {out_dir}")
    print("\n下一步（首次部署）：")
    print(f"  cd {args.out}")
    print("  git init")
    print("  git remote add space https://huggingface.co/spaces/<你的帳號>/<space名稱>")
    print("  git add . && git commit -m \"deploy: 初次部署\"")
    print("  git push space main")


if __name__ == "__main__":
    main()
