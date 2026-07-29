"""抓取五部長照相關法規條文，輸出 data/laws.json。

來源三層策略（PLAN.md Phase 1、D6）：
1. api：官方 Open API 整包 ZIP——https://law.moj.gov.tw/api/ch/law/json（法律包，
   內含 ChLaw.json）與 /api/ch/order/json（命令包，ChOrder.json）。JSON 為 UTF-8
   with BOM，一律 utf-8-sig 解碼；以 LawURL 的 pcode 過濾選法（勿全文搜尋）；
   ArticleType=='A' 為條文、'C' 為編章節標題（維護 current-chapter 狀態寫 metadata）。
2. sendlaw：政府資料開放平臺 dataset 18289/18290 的 XML 整包
   （sendlaw.moj.gov.tw GetFile.ashx，ZIP 內 FalV.xml 等），結構為
   <法規><法規名稱>…<法規內容>（<編章節> 與 <條文><條號><條文內容>）。
3. html：解析 law.moj.gov.tw/LawClass/LawAll.aspx 靜態 HTML
   （div.h3.char-2 章節標題 + div.row 的 col-no / law-article 結構）。

ZIP 快取於 data/raw/（檔名帶 UpdateDate）。預設有快取就用快取——資料凍結原則
（D6）：P1 驗收後重抓＝回到 P1 gate 重走；--refresh 才強制重新下載。

用法：
    uv run python scripts/fetch_laws.py                # 自動：api → sendlaw → html
    uv run python scripts/fetch_laws.py --source html  # 指定來源
    uv run python scripts/fetch_laws.py --refresh      # 忽略快取重新下載
"""

from __future__ import annotations

import argparse
import html as html_lib
import io
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from twlongcare.config import DATA_DIR
from twlongcare.knowledge_base import publish_law_version

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = DATA_DIR / "raw"
OUT_PATH = DATA_DIR / "laws.json"

USER_AGENT = "Mozilla/5.0 (tw-longcare-rag; personal research project)"

# 五部目標法規；package 對應 Open API 的法律/命令分包（sendlaw 的 CF/CM 同分法）
TARGET_LAWS = [
    {"pcode": "L0070040", "package": "law", "name": "長期照顧服務法"},
    {"pcode": "D0050037", "package": "law", "name": "老人福利法"},
    {"pcode": "L0070043", "package": "order", "name": "長期照顧服務法施行細則"},
    {"pcode": "L0070044", "package": "order", "name": "長期照顧服務機構設立許可及管理辦法"},
    {"pcode": "L0070059", "package": "order", "name": "長期照顧服務申請及給付辦法"},
]

API_URLS = {
    "law": "https://law.moj.gov.tw/api/ch/law/json",
    "order": "https://law.moj.gov.tw/api/ch/order/json",
}
SENDLAW_URLS = {
    "law": "https://sendlaw.moj.gov.tw/PublicData/GetFile.ashx?DType=XML&AuData=CF",
    "order": "https://sendlaw.moj.gov.tw/PublicData/GetFile.ashx?DType=XML&AuData=CM",
}
LAWALL_URL = "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"
LAWSINGLE_URL = "https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode={pcode}&flno={flno}"


# ---------- 正規化 ----------

def normalize_article_no(raw: str) -> str:
    """「第 8-1 條」→「8-1」；「第 1 條」→「1」。"""
    return re.sub(r"[第條\s]", "", raw)


def normalize_update_date(raw: str) -> str:
    """「2026/7/10 上午 12:00:00」→「2026-07-10」。"""
    m = re.match(r"(\d{4})/(\d{1,2})/(\d{1,2})", raw.strip())
    if not m:
        raise ValueError(f"無法解析 UpdateDate：{raw!r}")
    y, mo, d = (int(x) for x in m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}"


def roc_date_to_iso8(text: str) -> str:
    """「民國 110 年 06 月 09 日」→「20210609」（與 API 的 LawModifiedDate 同格式）。"""
    m = re.search(r"民國\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日", text)
    if not m:
        return ""
    y, mo, d = (int(x) for x in m.groups())
    return f"{y + 1911:04d}{mo:02d}{d:02d}"


def pcode_of(law: dict) -> str | None:
    m = re.search(r"pcode=([A-Za-z0-9]+)", law.get("LawURL", ""))
    return m.group(1) if m else None


def to_crlf(text: str) -> str:
    """統一換行為 \\r\\n（與主來源 Open API JSON 的原生格式對齊）。

    XML parser 依 XML 1.0 規範會把文字節點的 \\r\\n 正規化為 \\n，若不補回，
    備援層產出的多行條文會與主來源不同、Phase 2 以 \\r\\n 為段落切點的
    chunking 將整批失效。
    """
    return re.sub(r"\r?\n", "\r\n", text)


class DataVersionMismatch(RuntimeError):
    """law/order 分包資料版本不一致（違反 D6 資料凍結），必須中止而非降級。"""


# ---------- 下載與快取 ----------

def download(url: str, retries: int = 3, backoff_s: float = 10.0) -> bytes:
    """下載並重試：官方伺服器偶發整包檔案鎖定（實測 ChOrder 曾回 500 檔案使用中）。"""
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=300) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001 - 重試邏輯需攔所有網路錯誤
            last_err = e
            print(f"  下載失敗（{attempt}/{retries}）：{e}", file=sys.stderr)
            if attempt < retries:
                time.sleep(backoff_s)
    raise RuntimeError(f"下載 {url} 連續 {retries} 次失敗") from last_err


def cached_zip_path(package: str) -> Path | None:
    """回傳該分包最新的快取 ZIP（檔名帶 UpdateDate），無快取回 None。"""
    stem = "ChLaw" if package == "law" else "ChOrder"
    candidates = sorted(RAW_DIR.glob(f"{stem}-*.zip"))
    return candidates[-1] if candidates else None


def load_api_package(
    package: str, refresh: bool
) -> tuple[str, dict[str, dict], bytes | None]:
    """讀取 Open API 分包（快取優先）。

    回 (update_date, {pcode: law_dict}, zip_bytes)；zip_bytes 非 None 表示
    本次新下載、尚未寫入快取——快取寫入由 fetch_api_packages 在兩分包都
    成功後一併執行（交易性：避免 ChOrder 下載失敗時留下單邊新快取，
    下次執行默默混用兩個資料版本）。
    """
    cached = cached_zip_path(package)
    if cached and not refresh:
        print(f"  使用快取：{cached.name}")
        update_date, laws = parse_api_zip(cached.read_bytes())
        return update_date, laws, None
    print(f"  下載 {API_URLS[package]} …")
    zip_bytes = download(API_URLS[package])
    update_date, laws = parse_api_zip(zip_bytes)
    return update_date, laws, zip_bytes


def fetch_api_packages(refresh: bool) -> dict[str, tuple[str, dict[str, dict]]]:
    """兩分包都成功解析後才寫快取，回 {package: (update_date, laws)}。"""
    loaded = {pkg: load_api_package(pkg, refresh) for pkg in ("law", "order")}
    for pkg, (update_date, _laws, zip_bytes) in loaded.items():
        if zip_bytes is not None:
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            stem = "ChLaw" if pkg == "law" else "ChOrder"
            dest = RAW_DIR / f"{stem}-{update_date}.zip"
            dest.write_bytes(zip_bytes)
            print(f"  快取至：{dest.relative_to(REPO_ROOT)}")
    return {pkg: (v[0], v[1]) for pkg, v in loaded.items()}


def parse_api_zip(zip_bytes: bytes) -> tuple[str, dict[str, dict]]:
    """解析 Open API ZIP → (update_date, {pcode: law_dict})。"""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        jname = next(n for n in z.namelist() if n.lower().endswith(".json"))
        data = json.loads(z.read(jname).decode("utf-8-sig"))
    update_date = normalize_update_date(data["UpdateDate"])
    laws: dict[str, dict] = {}
    wanted = {t["pcode"] for t in TARGET_LAWS}
    for law in data["Laws"]:
        pc = pcode_of(law)
        if pc in wanted:
            laws[pc] = law
    return update_date, laws


# ---------- tier 2：sendlaw XML ----------

def parse_sendlaw_xml(xml_text: str) -> tuple[str, dict[str, dict]]:
    """解析 sendlaw XML 為與 Open API JSON 同形狀的 law_dict。"""
    root = ET.fromstring(xml_text)
    update_date = normalize_update_date(root.attrib.get("UpdateDate", ""))
    laws: dict[str, dict] = {}
    wanted = {t["pcode"] for t in TARGET_LAWS}

    def txt(el: ET.Element | None) -> str:
        return (el.text or "").strip() if el is not None else ""

    for law_el in root.iter("法規"):
        url = txt(law_el.find("法規網址"))
        m = re.search(r"pcode=([A-Za-z0-9]+)", url)
        if not m or m.group(1) not in wanted:
            continue
        articles: list[dict] = []
        content_el = law_el.find("法規內容")
        if content_el is not None:
            for child in content_el:
                if child.tag == "編章節":
                    articles.append({
                        "ArticleType": "C",
                        "ArticleNo": "",
                        "ArticleContent": (child.text or "").strip(),
                    })
                elif child.tag == "條文":
                    articles.append({
                        "ArticleType": "A",
                        "ArticleNo": txt(child.find("條號")),
                        "ArticleContent": to_crlf(txt(child.find("條文內容"))),
                    })
        laws[m.group(1)] = {
            "LawName": txt(law_el.find("法規名稱")),
            "LawURL": url,
            "LawModifiedDate": txt(law_el.find("最新異動日期")),
            "LawEffectiveDate": txt(law_el.find("生效日期")),
            "LawEffectiveNote": to_crlf(txt(law_el.find("生效內容"))),
            "LawAttachements": [],
            "LawArticles": articles,
        }
    return update_date, laws


def fetch_sendlaw_package(package: str) -> tuple[str, dict[str, dict]]:
    print(f"  下載 {SENDLAW_URLS[package]} …")
    raw = download(SENDLAW_URLS[package])
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            xname = next(n for n in z.namelist() if n.lower().endswith(".xml"))
            raw = z.read(xname)
    return parse_sendlaw_xml(raw.decode("utf-8-sig"))


# ---------- tier 3：LawAll.aspx HTML ----------

_HTML_CHAPTER_RE = re.compile(r'<div class="h3 char-\d+">\s*(?P<chap>[^<]+?)\s*</div>')
# col-no 內可能先出現附件迴紋針圖示（<i class="fa fa-paperclip">…）才到 <a>
_HTML_ROW_RE = re.compile(
    r'<div class="col-no">.*?<a [^>]*?flno=(?P<flno>[0-9-]+)[^>]*>(?P<no>[^<]+)</a>\s*</div>'
    r'<div class="col-data"><div class="law-article">(?P<body>.*?)</div>\s*</div></div>',
    re.S,
)
_HTML_LINE_RE = re.compile(r'<div class="line-[^"]*(?:\s[^"]*)?">(.*?)</div>', re.S)


def parse_lawall_html(html_text: str) -> dict:
    """解析單一法規全文頁為與 Open API JSON 同形狀的 law_dict。"""
    name = ""
    m = re.search(r"<title>\s*(.+?)-全國法規資料庫", html_text, re.S)
    if m:
        name = m.group(1).strip()
    modified = ""
    m = re.search(r"(?:修正|公布)日期：</th>\s*<td>(.*?)</td>", html_text, re.S)
    if m:
        modified = roc_date_to_iso8(m.group(1))

    seg = html_text
    m = re.search(r'law-reg-content', html_text)
    if m:
        seg = html_text[m.start():]

    events: list[tuple[int, str, dict]] = []
    for cm in _HTML_CHAPTER_RE.finditer(seg):
        events.append((cm.start(), "C", {"chap": cm.group("chap")}))
    for rm in _HTML_ROW_RE.finditer(seg):
        lines = [
            html_lib.unescape(t).strip()
            for t in _HTML_LINE_RE.findall(rm.group("body"))
        ]
        events.append((rm.start(), "A", {
            "no": rm.group("no").strip(),
            "content": "\r\n".join(x for x in lines if x),
        }))
    events.sort(key=lambda e: e[0])

    articles: list[dict] = []
    for _, kind, payload in events:
        if kind == "C":
            articles.append({
                "ArticleType": "C", "ArticleNo": "",
                "ArticleContent": payload["chap"],
            })
        else:
            articles.append({
                "ArticleType": "A", "ArticleNo": payload["no"],
                "ArticleContent": payload["content"],
            })
    return {
        "LawName": name,
        "LawURL": "",
        "LawModifiedDate": modified,
        "LawEffectiveDate": "",
        "LawEffectiveNote": "",
        "LawAttachements": [],
        "LawArticles": articles,
    }


def fetch_html_law(pcode: str) -> dict:
    url = LAWALL_URL.format(pcode=pcode)
    print(f"  下載 {url} …")
    html_text = download(url).decode("utf-8")
    time.sleep(1.0)  # 禮貌性延遲（備援路徑才會走到）
    return parse_lawall_html(html_text)


# ---------- 條文抽取（共用） ----------

def extract_articles(
    law: dict, pcode: str, source_update_date: str, fetched_at: str
) -> list[dict]:
    """law_dict → 條文 record 清單；'C' 列維護 current-chapter 狀態（可為 None）。"""
    records: list[dict] = []
    chapter: str | None = None
    for art in law["LawArticles"]:
        if art["ArticleType"] == "C":
            chapter = art["ArticleContent"].strip() or None
            continue
        if art["ArticleType"] != "A":
            continue
        flno = normalize_article_no(art["ArticleNo"])
        content = art["ArticleContent"].strip()
        if not flno or not content:
            continue
        records.append({
            "law_name": law["LawName"],
            "pcode": pcode,
            "chapter": chapter,
            "article_no": flno,
            "content": content,
            "url": LAWSINGLE_URL.format(pcode=pcode, flno=flno),
            "law_modified_date": law.get("LawModifiedDate", ""),
            "fetched_at": fetched_at,
            "source_update_date": source_update_date,
        })
    return records


# ---------- 主流程 ----------

def fetch_all(source: str, refresh: bool) -> dict:
    """依指定來源（auto 為三層依序嘗試）取回五法，組出 laws.json 結構。"""
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tiers = ["api", "sendlaw", "html"] if source == "auto" else [source]

    last_err: Exception | None = None
    for tier in tiers:
        try:
            print(f"[來源：{tier}]")
            if tier == "api":
                per_pkg = fetch_api_packages(refresh)
            elif tier == "sendlaw":
                per_pkg = {pkg: fetch_sendlaw_package(pkg) for pkg in ("law", "order")}
            else:
                per_pkg = None  # html 逐法抓，無整包

            if per_pkg is not None:
                dates = {pkg: per_pkg[pkg][0] for pkg in per_pkg}
                if len(set(dates.values())) > 1:
                    raise DataVersionMismatch(
                        f"law/order 分包資料版本不一致：{dates}。"
                        "請用 --refresh 重新下載對齊後再執行（D6 資料凍結原則）"
                    )

            articles: list[dict] = []
            meta_laws: list[dict] = []
            for target in TARGET_LAWS:
                pcode = target["pcode"]
                if per_pkg is not None:
                    update_date, laws = per_pkg[target["package"]]
                    if pcode not in laws:
                        raise KeyError(f"{tier} 分包中找不到 pcode={pcode}")
                    law = laws[pcode]
                else:
                    update_date = ""  # html 頁面無整包 UpdateDate
                    law = fetch_html_law(pcode)
                if law["LawName"] != target["name"]:
                    raise ValueError(
                        f"{pcode} 名稱不符：預期 {target['name']!r}，"
                        f"取得 {law['LawName']!r}"
                    )
                recs = extract_articles(law, pcode, update_date, fetched_at)
                if not recs:
                    raise ValueError(f"{pcode} 抽不到任何條文")
                articles.extend(recs)
                meta_laws.append({
                    "law_name": law["LawName"],
                    "pcode": pcode,
                    "article_count": len(recs),
                    "chapter_count": sum(
                        1 for a in law["LawArticles"] if a["ArticleType"] == "C"
                    ),
                    "law_modified_date": law.get("LawModifiedDate", ""),
                    "law_effective_date": law.get("LawEffectiveDate", ""),
                    "law_effective_note": (law.get("LawEffectiveNote") or "").strip(),
                    "attachments_count": len(law.get("LawAttachements") or []),
                })
            return {
                "meta": {
                    "source": tier,
                    "source_update_date": articles[0]["source_update_date"],
                    "package_update_dates": (
                        {pkg: per_pkg[pkg][0] for pkg in per_pkg}
                        if per_pkg is not None else {}
                    ),
                    "fetched_at": fetched_at,
                    "license": "政府資料開放授權條款－第1版（OGDL v1.0）",
                    "laws": meta_laws,
                },
                "articles": articles,
            }
        except DataVersionMismatch:
            raise  # 版本混用是設定問題，降級到活資料只會更糟，直接中止
        except Exception as e:  # noqa: BLE001 - 逐層降級
            last_err = e
            print(f"  [{tier}] 失敗：{e}", file=sys.stderr)
    raise RuntimeError(
        "三層來源全部失敗。請手動下載整包 ZIP 放入 data/raw/（ChLaw-YYYY-MM-DD.zip / "
        "ChOrder-YYYY-MM-DD.zip）：https://law.moj.gov.tw/api/swagger/index.html"
    ) from last_err


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source", choices=["auto", "api", "sendlaw", "html"], default="auto"
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="忽略 data/raw/ 快取強制重新下載（注意 D6 資料凍結原則）",
    )
    args = parser.parse_args()

    result = fetch_all(args.source, args.refresh)
    publication = publish_law_version(result, out_path=OUT_PATH)

    state = "已發布新版本" if publication.changed else "內容未變，沿用現有版本"
    print(f"\n{state}：{publication.version}")
    print(f"immutable snapshot：{publication.snapshot_path}")
    print(
        "diff："
        f"new={len(publication.diff['new'])} "
        f"changed={len(publication.diff['changed'])} "
        f"deleted={len(publication.diff['deleted'])}"
    )
    print(f"來源：{result['meta']['source']}  "
          f"資料版本 UpdateDate：{result['meta']['source_update_date'] or '（html 無整包版本）'}")
    print(f"{'法規':<24} {'條數':>4} {'章節':>4} {'異動日期':>10}")
    for m in result["meta"]["laws"]:
        print(f"{m['law_name']:<24} {m['article_count']:>4} "
              f"{m['chapter_count']:>4} {m['law_modified_date']:>10}")
    print(f"{'合計':<24} {len(result['articles']):>4}")


if __name__ == "__main__":
    main()
