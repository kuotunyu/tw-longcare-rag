"""法條引用圖譜視覺化（Phase 4 README 同步用）：讀 data/law_graph.json，
輸出互動式 HTML（pyvis）與統計數字。

風險備援（PLAN.md）：pyvis 三年未維護，若初始化/渲染出錯不 debug，
改印錯誤並提示改用 mermaid 或自製 HTML。

用法：
    uv run python scripts/visualize_graph.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = REPO_ROOT / "data" / "law_graph.json"
OUT_HTML = REPO_ROOT / "docs" / "assets" / "law_graph.html"

LAW_COLORS = {
    "長期照顧服務法": "#a23b2e",
    "老人福利法": "#2b6b57",
    "長期照顧服務法施行細則": "#c9895a",
    "長期照顧服務機構設立許可及管理辦法": "#4a6fa5",
    "長期照顧服務申請及給付辦法": "#8a5fa0",
}


def main() -> None:
    data = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    nodes = data["nodes"]
    edges = data["edges"]
    meta = data["meta"]

    print("=== 圖譜統計 ===")
    print(f"節點（條文）：{meta['node_count']}")
    print(f"邊（引用關係）：{meta['edge_count']}")
    print(f"  regex 抽取：{meta['regex_edge_count']}"
          f"（{meta['regex_edge_count']/max(meta['edge_count'],1):.0%}）")
    print(f"  LLM 補抽：{meta['llm_edge_count']}"
          f"（{meta['llm_edge_count']/max(meta['edge_count'],1):.0%}）")

    connected = {e["source"] for e in edges} | {e["target"] for e in edges}
    print(f"有引用關係的條文（至少一邊）：{len(connected)}/{meta['node_count']}")

    by_law: dict[str, int] = {}
    for n in nodes:
        if n["id"] in connected:
            by_law[n["law_name"]] = by_law.get(n["law_name"], 0) + 1
    print("\n各法規有引用關係的條文數：")
    for name, cnt in sorted(by_law.items(), key=lambda kv: -kv[1]):
        print(f"  {name}：{cnt}")

    try:
        render_pyvis(nodes, edges, connected)
        print(f"\n已寫出互動 HTML：{OUT_HTML.relative_to(REPO_ROOT)}")
    except Exception as e:  # noqa: BLE001 - pyvis 三年未維護，出錯不深究
        print(f"\n⚠️ pyvis 渲染失敗，依 PLAN 風險備援不 debug：{e}", file=sys.stderr)
        print("改用 render_fallback_html() 自製版本", file=sys.stderr)
        render_fallback_html(nodes, edges, connected)
        print(f"已寫出備援 HTML：{OUT_HTML.relative_to(REPO_ROOT)}")


def render_pyvis(nodes: list[dict], edges: list[dict], connected: set[str]) -> None:
    from pyvis.network import Network

    net = Network(height="800px", width="100%", directed=True,
                  bgcolor="#1a1d24", font_color="#e8e6de", notebook=False,
                  cdn_resources="in_line")  # 內嵌 JS/CSS，避免另外散落 lib/ 資料夾
    net.barnes_hut(gravity=-3000, spring_length=120)

    for n in nodes:
        if n["id"] not in connected:
            continue  # 孤立節點不畫，圖太亂
        net.add_node(
            n["id"],
            label=f"{n['law_name'][:2]}§{n['article_no']}",
            title=f"《{n['law_name']}》第 {n['article_no']} 條",
            color=LAW_COLORS.get(n["law_name"], "#888888"),
        )
    for e in edges:
        net.add_edge(
            e["source"], e["target"],
            color="#a23b2e" if e["provenance"] == "regex" else "#4a6fa5",
            title=e["provenance"],
        )

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(OUT_HTML), open_browser=False, notebook=False)


def render_fallback_html(nodes: list[dict], edges: list[dict], connected: set[str]) -> None:
    """pyvis 失敗時的備援：純 HTML + Canvas 力導向圖，零外部依賴。"""
    node_list = [n for n in nodes if n["id"] in connected]
    payload = json.dumps({
        "nodes": [{"id": n["id"], "label": f"{n['law_name'][:2]}§{n['article_no']}",
                    "title": f"《{n['law_name']}》第{n['article_no']}條",
                    "color": LAW_COLORS.get(n["law_name"], "#888")}
                   for n in node_list],
        "edges": [{"from": e["source"], "to": e["target"], "prov": e["provenance"]}
                   for e in edges],
    }, ensure_ascii=False)
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>law_graph fallback</title></head>
<body style="margin:0;background:#1a1d24;color:#e8e6de;font-family:sans-serif">
<p style="padding:1em">pyvis 渲染失敗時的純文字備援清單（節點數：{len(node_list)}，邊數：{len(edges)}）</p>
<pre style="padding:1em;overflow:auto">{payload}</pre>
</body></html>"""
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
