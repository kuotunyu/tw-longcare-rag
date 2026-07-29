"""Generate a prospective synthetic gate proxy with no human annotation.

Expected article IDs are fixed from source selection before question
generation.  The local LLM only paraphrases source text into a natural
question; it never chooses the label.  Existing eval articles and exact
questions are excluded.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from twlongcare.config import DATA_DIR, get_settings
from twlongcare.knowledge_base import atomic_write_json, sha256_json
from twlongcare.llm_text import extract_text
from twlongcare.pipeline import OLLAMA_NUM_CTX

SEED = 20260730
CYCLE2_SEED = 20260731
CYCLE2_ID = "prospective-v2-unseen-sources"
CALIBRATION_SINGLE = 35
CALIBRATION_MULTI = 5
CALIBRATION_AMBIGUOUS = 5
CALIBRATION_UNANSWERABLE = 5
HOLDOUT_SINGLE = 70
HOLDOUT_MULTI = 10
HOLDOUT_AMBIGUOUS = 10
HOLDOUT_UNANSWERABLE = 10
LONG_TAIL_COUNT = 15

_TRIVIAL_RE = re.compile(
    r"^(本法|本細則|本辦法)?[^。]{0,20}"
    r"(自(中華民國)?[^。]{0,20}施行|由(中央|地方)?主管機關(另)?定之|"
    r"依[^。]{0,60}(訂定|訂定之|定之))\s*[。.]?"
    r"(\r?\n[^。]{0,40}(施行|訂定之)[。.]?)?\s*$"
)
_FORBIDDEN_QUESTION_MARKERS = (
    "第1條",
    "第 1 條",
    "依本法",
    "依該法",
    "根據條文",
)
_TYPO_MAP = {
    "長照": "長炤",
    "機構": "機搆",
    "申請": "申晴",
    "補助": "補住",
    "許可": "許課",
    "服務": "服物",
    "主管機關": "主管機觀",
}
_AMBIGUOUS = (
    "這個情況到底可以嗎？",
    "那這樣有符合規定嗎？",
    "前面提到的那個要怎麼申請？",
    "這件事是不是一定要先核准？",
    "家裡遇到這種狀況該怎麼辦？",
    "那個期限到底是多久？",
    "這樣做會不會被處罰？",
    "如果沒有辦那個手續會怎樣？",
    "之前說的資格我有符合嗎？",
    "這種服務政府會幫忙嗎？",
    "那項費用到底是誰要負擔？",
    "這樣的場所可以直接開始營業嗎？",
    "如果超過那個時間還能補辦嗎？",
    "這種人員需要先取得什麼資格？",
    "剛才那種情形主管機關會怎麼處理？",
    "我說的那一種服務也算在裡面嗎？",
    "如果資料少了剛才提到的那份可以補嗎？",
    "這樣的身分到底有沒有申請資格？",
    "那個機構需要多久檢查一次？",
    "家人遇到同樣情況也能照這個方式辦嗎？",
    "這件事應該向中央還是地方申請？",
    "如果只是暫時發生也需要通報嗎？",
    "剛才提到的服務可以同時申請嗎？",
    "那種違規第一次就會被撤銷嗎？",
    "這個證明過期後還能繼續使用嗎？",
    "前面那項限制也適用居家服務嗎？",
    "如果本人不能辦可以請家屬代辦嗎？",
    "這樣的費用會依身分不同而改變嗎？",
    "那項資格是申請時有就好還是要一直維持？",
    "剛才說的例外情況包含我家這種狀況嗎？",
)
_UNANSWERABLE = (
    "遺產稅目前的免稅額是多少？",
    "公司資遣員工要提前幾天通知？",
    "酒駕被抓會有什麼刑事責任？",
    "房東提前終止租約要賠房客多少？",
    "健保有沒有補助成人牙齒矯正？",
    "勞退新制雇主每個月要提撥多少？",
    "綜合所得稅可以列報哪些扶養親屬？",
    "車禍後強制險最高可以賠多少？",
    "申請育嬰留職停薪需要什麼資格？",
    "買預售屋後想解約可以拿回多少錢？",
    "信用卡被盜刷後銀行一定要賠嗎？",
    "闖紅燈目前會被罰多少錢？",
    "離婚後未成年子女監護權怎麼判？",
    "網路購物七天鑑賞期有哪些例外？",
    "公司申請商標註冊需要多少費用？",
    "護照到期換發需要準備哪些文件？",
    "機車定期檢驗逾期會罰多少錢？",
    "勞工加班一小時的工資怎麼計算？",
    "申請建築執照通常需要哪些圖說？",
    "食品營養標示違規會被罰多少？",
    "公務員退休金的起支年齡是幾歲？",
    "外國人來台工作需要哪一種簽證？",
    "租屋押金依法最多可以收幾個月？",
    "汽車牌照稅逾期繳納會加多少滯納金？",
    "著作權侵權的損害賠償如何計算？",
    "成立股份有限公司最低資本額是多少？",
    "國民年金欠費可以分期繳納嗎？",
    "國內線班機取消時旅客可以要求什麼補償？",
    "申請農地變更使用需要哪些條件？",
    "寵物沒有植入晶片會受到什麼處罰？",
)


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def eval_content_from_paths(paths: list[Path]) -> tuple[set[str], set[str]]:
    article_ids: set[str] = set()
    questions: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in _walk(payload):
            question = item.get("question")
            if isinstance(question, str):
                questions.add(" ".join(question.split()).lower())
            for key in ("expected_parent_ids", "expected_article_ids"):
                ids = item.get(key)
                if isinstance(ids, list):
                    article_ids.update(str(value) for value in ids)
    return article_ids, questions


def existing_eval_content() -> tuple[set[str], set[str]]:
    paths = [DATA_DIR / "testset.json"]
    paths.extend((DATA_DIR / "eval").glob("*.json"))
    return eval_content_from_paths([
        path
        for path in paths
        if path.exists() and not path.name.startswith("prospective_")
    ])


def _article_id(article: dict) -> str:
    return f"{article['pcode']}-{article['article_no']}"


def _select_round_robin(
    articles: list[dict],
    count: int,
    *,
    rng: random.Random,
) -> list[dict]:
    by_pcode: dict[str, list[dict]] = defaultdict(list)
    for article in articles:
        by_pcode[article["pcode"]].append(article)
    for pool in by_pcode.values():
        rng.shuffle(pool)
    pcodes = sorted(by_pcode)
    selected: list[dict] = []
    while len(selected) < count:
        progressed = False
        for pcode in pcodes:
            if by_pcode[pcode] and len(selected) < count:
                selected.append(by_pcode[pcode].pop())
                progressed = True
        if not progressed:
            raise ValueError("not enough unused non-trivial articles")
    return selected


def select_sources(laws: dict, graph: dict) -> tuple[list[dict], list[tuple[dict, dict]]]:
    used_ids, _ = existing_eval_content()
    rng = random.Random(SEED)
    by_id = {
        _article_id(article): article
        for article in laws["articles"]
        if _article_id(article) not in used_ids
        and not _TRIVIAL_RE.match(article["content"].strip())
    }
    pair_count = CALIBRATION_MULTI + HOLDOUT_MULTI
    pair_candidates = []
    for edge in graph.get("edges", []):
        source, target = edge["source"], edge["target"]
        if source in by_id and target in by_id and source != target:
            pair_candidates.append((source, target))
    rng.shuffle(pair_candidates)
    pairs: list[tuple[dict, dict]] = []
    paired_ids: set[str] = set()
    for source, target in pair_candidates:
        if source in paired_ids or target in paired_ids:
            continue
        pairs.append((by_id[source], by_id[target]))
        paired_ids.update((source, target))
        if len(pairs) == pair_count:
            break
    if len(pairs) < pair_count:
        raise ValueError("not enough disjoint unused graph edges for multi-hop proxy")
    remaining = [
        article for article_id, article in by_id.items()
        if article_id not in paired_ids
    ]
    singles = _select_round_robin(
        remaining,
        CALIBRATION_SINGLE + HOLDOUT_SINGLE,
        rng=rng,
    )
    return singles, pairs


def select_cycle2_source_pools(
    laws: dict,
    graph: dict,
    *,
    excluded_article_ids: set[str],
) -> tuple[list[dict], list[dict], tuple[dict, dict]]:
    """Use only sources unseen by the locked set and invalid first proxy.

    The corpus is intentionally small.  After the first proxy only one fully
    unseen citation edge remains, so the edge is reserved for holdout.  Single
    source articles are partitioned before any question is generated and may
    produce several distinct phrasings within their own split.
    """
    rng = random.Random(CYCLE2_SEED)
    by_id = {
        _article_id(article): article
        for article in laws["articles"]
        if _article_id(article) not in excluded_article_ids
        and not _TRIVIAL_RE.match(article["content"].strip())
    }
    edge_candidates = [
        (edge["source"], edge["target"])
        for edge in graph.get("edges", [])
        if edge.get("source") in by_id
        and edge.get("target") in by_id
        and edge["source"] != edge["target"]
    ]
    rng.shuffle(edge_candidates)
    if not edge_candidates:
        raise ValueError("no fully unseen citation edge remains for cycle 2")
    source_id, target_id = edge_candidates[0]
    holdout_pair = (by_id[source_id], by_id[target_id])
    pair_ids = {source_id, target_id}
    remaining = [
        article
        for article_id, article in by_id.items()
        if article_id not in pair_ids
    ]
    if len(remaining) < 12:
        raise ValueError("not enough fully unseen sources for disjoint cycle 2")
    rng.shuffle(remaining)
    calibration_source_count = min(10, max(4, len(remaining) // 3))
    calibration_sources = remaining[:calibration_source_count]
    holdout_sources = remaining[calibration_source_count:]
    if not holdout_sources:
        raise ValueError("cycle 2 holdout source pool is empty")
    return calibration_sources, holdout_sources, holdout_pair


_SYSTEM = (
    "你是台灣長照法規測試題改寫器。輸入已先綁定正確來源法條；"
    "你只負責把來源內容改寫成一般民眾會問的一句繁體中文問題。"
    "不得選擇法條、不得加入來源沒有的事實。輸出必須是 JSON。"
)


def _batch_prompt(specs: list[dict]) -> str:
    compact = []
    for spec in specs:
        compact.append(
            {
                "id": spec["id"],
                "sources": [
                    {
                        "law": source["law_name"],
                        "content": source["content"][:700],
                    }
                    for source in spec["sources"]
                ],
                "multi_hop": len(spec["sources"]) > 1,
                "variation": spec.get("variation", 1),
            }
        )
    return (
        "請為每個 id 產生一句自然、具體、可由所有 sources 回答的口語問題。"
        "不要提法規全名、條號、來源或「根據條文」。multi_hop=true 時問題必須"
        "同時需要兩個 sources，不能只問其中之一。每題 8–55 個中文字，只能有"
        "一個問句。不同 id 即使 sources 相同，也必須依 variation 改問不同的"
        "條件、程序、義務、例外或效果，不可只換同義詞。輸出格式："
        "{\"items\":[{\"id\":\"...\",\"question\":\"...？\"}]}。\n"
        + json.dumps(compact, ensure_ascii=False)
    )


def _parse_items(text: str) -> dict[str, str]:
    cleaned = text.strip().removeprefix("```json").removeprefix("```")
    cleaned = cleaned.removesuffix("```").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model output has no JSON object")
    payload = json.loads(cleaned[start : end + 1])
    return {
        str(item["id"]): str(item["question"]).strip().strip("「」\"'")
        for item in payload.get("items", [])
    }


def _valid_question(
    question: str,
    known_questions: set[str],
    *,
    forbidden_law_names: tuple[str, ...] = (),
) -> bool:
    normalized = " ".join(question.split()).lower()
    return (
        8 <= len(question) <= 80
        and ("？" in question or "?" in question)
        and question.count("？") + question.count("?") == 1
        and not any(marker in question for marker in _FORBIDDEN_QUESTION_MARKERS)
        and not re.search(r"第\s*\d+(?:-\d+)?\s*條", question)
        and not any(name in question for name in forbidden_law_names)
        and normalized not in known_questions
    )


def _sanitize_question(
    question: str,
    *,
    forbidden_law_names: tuple[str, ...],
) -> str:
    cleaned = question.strip().strip("「」\"'").splitlines()[0].strip()
    cleaned = re.sub(r"^(問題|問句)\s*[：:]\s*", "", cleaned)
    for law_name in forbidden_law_names:
        cleaned = cleaned.replace(f"《{law_name}》", "").replace(law_name, "")
    cleaned = re.sub(r"第\s*\d+(?:-\d+)?\s*條", "", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    positions = [
        position
        for mark in ("？", "?")
        if (position := cleaned.find(mark)) >= 0
    ]
    if positions:
        cleaned = cleaned[: min(positions) + 1]
    elif cleaned:
        cleaned += "？"
    return cleaned


def generate_questions(
    specs: list[dict],
    *,
    cache_path: Path,
    model_name: str,
    known_questions: set[str] | None = None,
) -> dict[str, str]:
    from langchain_ollama import ChatOllama

    cache = (
        json.loads(cache_path.read_text(encoding="utf-8"))
        if cache_path.exists()
        else {}
    )
    model = ChatOllama(
        model=model_name,
        num_ctx=OLLAMA_NUM_CTX,
        temperature=0.4,
        format="json",
    )
    if known_questions is None:
        _, known_questions = existing_eval_content()
    else:
        known_questions = set(known_questions)
    specs_by_id = {spec["id"]: spec for spec in specs}
    generated = {}
    for key, value in cache.items():
        spec = specs_by_id.get(key)
        if spec is None:
            continue
        law_names = tuple(
            source["law_name"] for source in spec["sources"]
        )
        if _valid_question(
            value,
            known_questions,
            forbidden_law_names=law_names,
        ):
            generated[key] = value
    pending = [spec for spec in specs if spec["id"] not in generated]
    for offset in range(0, len(pending), 8):
        batch = pending[offset : offset + 8]
        parsed: dict[str, str] = {}
        for _ in range(2):
            reply = model.invoke(
                [
                    SystemMessage(content=_SYSTEM),
                    HumanMessage(content=_batch_prompt(batch)),
                ]
            )
            try:
                parsed = _parse_items(extract_text(reply.content))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            parsed = {
                spec_id: _sanitize_question(
                    question,
                    forbidden_law_names=tuple(
                        source["law_name"]
                        for source in specs_by_id[spec_id]["sources"]
                    ),
                )
                for spec_id, question in parsed.items()
                if spec_id in specs_by_id
            }
            if all(
                spec["id"] in parsed
                and _valid_question(
                    parsed[spec["id"]],
                    known_questions,
                    forbidden_law_names=tuple(
                        source["law_name"] for source in spec["sources"]
                    ),
                )
                for spec in batch
            ):
                break
        for spec in batch:
            question = parsed.get(spec["id"], "")
            law_names = tuple(
                source["law_name"] for source in spec["sources"]
            )
            if not _valid_question(
                question,
                known_questions,
                forbidden_law_names=law_names,
            ):
                for _ in range(3):
                    reply = model.invoke(
                        [
                            SystemMessage(content=_SYSTEM),
                            HumanMessage(content=_batch_prompt([spec])),
                        ]
                    )
                    try:
                        single = _parse_items(extract_text(reply.content))
                        question = _sanitize_question(
                            single.get(spec["id"], ""),
                            forbidden_law_names=law_names,
                        )
                    except (
                        KeyError,
                        TypeError,
                        ValueError,
                        json.JSONDecodeError,
                    ):
                        question = ""
                    if _valid_question(
                        question,
                        known_questions,
                        forbidden_law_names=law_names,
                    ):
                        break
            if not _valid_question(
                question,
                known_questions,
                forbidden_law_names=law_names,
            ):
                raise RuntimeError(
                    f"failed to generate valid question for {spec['id']}"
                )
            generated[spec["id"]] = question
            known_questions.add(" ".join(question.split()).lower())
        atomic_write_json(cache_path, generated)
        print(
            f"[prospective-generate] {min(offset + len(batch), len(pending))}/"
            f"{len(pending)}"
        )
    return generated


def _long_tail(question: str) -> str:
    for source, replacement in _TYPO_MAP.items():
        if source in question:
            return question.replace(source, replacement, 1)
    return "想請問一下，" + question


def build_specs(
    singles: list[dict],
    pairs: list[tuple[dict, dict]],
) -> tuple[list[dict], list[dict]]:
    calibration_specs: list[dict] = []
    holdout_specs: list[dict] = []
    for index, article in enumerate(singles[:CALIBRATION_SINGLE], start=1):
        calibration_specs.append(
            {"id": f"cal-single-{index:03d}", "sources": [article]}
        )
    for index, pair in enumerate(pairs[:CALIBRATION_MULTI], start=1):
        calibration_specs.append(
            {"id": f"cal-multi-{index:03d}", "sources": list(pair)}
        )
    for index, article in enumerate(
        singles[CALIBRATION_SINGLE:], start=1
    ):
        holdout_specs.append(
            {"id": f"hold-single-{index:03d}", "sources": [article]}
        )
    for index, pair in enumerate(pairs[CALIBRATION_MULTI:], start=1):
        holdout_specs.append(
            {"id": f"hold-multi-{index:03d}", "sources": list(pair)}
        )
    return calibration_specs, holdout_specs


def _repeated_specs(
    sources: list[dict],
    *,
    count: int,
    prefix: str,
) -> list[dict]:
    if not sources and count:
        raise ValueError(f"{prefix} has no sources")
    return [
        {
            "id": f"{prefix}-{index:03d}",
            "sources": [sources[(index - 1) % len(sources)]],
            "variation": 1 + (index - 1) // len(sources),
        }
        for index in range(1, count + 1)
    ]


def build_cycle2_specs(
    calibration_sources: list[dict],
    holdout_sources: list[dict],
    holdout_pair: tuple[dict, dict],
) -> tuple[list[dict], list[dict]]:
    calibration_specs = _repeated_specs(
        calibration_sources,
        count=CALIBRATION_SINGLE + CALIBRATION_MULTI,
        prefix="v2-cal-single",
    )
    holdout_specs = _repeated_specs(
        holdout_sources,
        count=HOLDOUT_SINGLE,
        prefix="v2-hold-single",
    )
    holdout_specs.extend(
        {
            "id": f"v2-hold-multi-{index:03d}",
            "sources": list(holdout_pair),
            "variation": index,
        }
        for index in range(1, HOLDOUT_MULTI + 1)
    )
    return calibration_specs, holdout_specs


def _materialize_generated(
    specs: list[dict],
    questions: dict[str, str],
    *,
    split: str,
) -> list[dict]:
    items = []
    single_counter = 0
    for spec in specs:
        is_multi = len(spec["sources"]) > 1
        question = questions[spec["id"]]
        stratum = "multi_hop" if is_multi else "single_hop"
        if split == "holdout" and not is_multi:
            single_counter += 1
            if single_counter <= LONG_TAIL_COUNT:
                question = _long_tail(question)
                stratum = "long_tail_typo"
        items.append(
            {
                "id": spec["id"],
                "question": question,
                "stratum": stratum,
                "answerable_from_corpus": True,
                "expected_route": (
                    "global_or_multi_hop" if is_multi else "single_hop"
                ),
                "expected_article_ids": [
                    _article_id(source) for source in spec["sources"]
                ],
                "source_laws": list(
                    dict.fromkeys(source["law_name"] for source in spec["sources"])
                ),
                "label_origin": "source_articles_fixed_before_question_generation",
            }
        )
    return items


def _fixed_negative_items(split: str, *, offset: int = 0) -> list[dict]:
    if split == "calibration":
        ambiguous = _AMBIGUOUS[
            offset:offset + CALIBRATION_AMBIGUOUS
        ]
        unanswerable = _UNANSWERABLE[
            offset:offset + CALIBRATION_UNANSWERABLE
        ]
    else:
        ambiguous = _AMBIGUOUS[
            offset + CALIBRATION_AMBIGUOUS:
            offset + CALIBRATION_AMBIGUOUS + HOLDOUT_AMBIGUOUS
        ]
        unanswerable = _UNANSWERABLE[
            offset + CALIBRATION_UNANSWERABLE:
            offset + CALIBRATION_UNANSWERABLE + HOLDOUT_UNANSWERABLE
        ]
    items = []
    for index, question in enumerate(ambiguous, start=1):
        items.append(
            {
                "id": f"{split}-ambiguous-{index:03d}",
                "question": question,
                "stratum": "ambiguous",
                "answerable_from_corpus": False,
                "expected_route": "corrective_candidate",
                "expected_article_ids": [],
                "label_origin": "deterministic_missing_referent_template",
            }
        )
    for index, question in enumerate(unanswerable, start=1):
        items.append(
            {
                "id": f"{split}-unanswerable-{index:03d}",
                "question": question,
                "stratum": "unanswerable",
                "answerable_from_corpus": False,
                "expected_route": "single_hop",
                "expected_article_ids": [],
                "label_origin": "deterministic_out_of_corpus_topic",
            }
        )
    return items


def build_datasets(
    laws: dict,
    graph: dict,
    questions: dict[str, str],
) -> tuple[dict, dict]:
    singles, pairs = select_sources(laws, graph)
    calibration_specs, holdout_specs = build_specs(singles, pairs)
    calibration_items = _materialize_generated(
        calibration_specs, questions, split="calibration"
    ) + _fixed_negative_items("calibration")
    holdout_items = _materialize_generated(
        holdout_specs, questions, split="holdout"
    ) + _fixed_negative_items("holdout")
    random.Random(SEED + 1).shuffle(calibration_items)
    random.Random(SEED + 2).shuffle(holdout_items)
    common = {
        "schema_version": "prospective-gate-proxy-v1",
        "synthetic_proxy": True,
        "represents_production_distribution": False,
        "seed": SEED,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "selection_policy": (
            "unused source articles and graph edges selected before question "
            "generation; existing eval articles/questions excluded"
        ),
    }
    calibration = {
        **common,
        "split": "calibration",
        "locked": True,
        "item_count": len(calibration_items),
        "items": calibration_items,
    }
    holdout = {
        **common,
        "split": "holdout",
        "locked": True,
        "read_policy": "read once after candidate threshold is frozen",
        "item_count": len(holdout_items),
        "items": holdout_items,
    }
    calibration["dataset_sha256"] = sha256_json(calibration_items)
    holdout["dataset_sha256"] = sha256_json(holdout_items)
    return calibration, holdout


def build_cycle2_datasets(
    questions: dict[str, str],
    calibration_specs: list[dict],
    holdout_specs: list[dict],
    *,
    prior_hashes: dict[str, str],
) -> tuple[dict, dict]:
    calibration_items = _materialize_generated(
        calibration_specs, questions, split="calibration"
    ) + _fixed_negative_items("calibration", offset=15)
    holdout_items = _materialize_generated(
        holdout_specs, questions, split="holdout"
    ) + _fixed_negative_items("holdout", offset=15)
    random.Random(CYCLE2_SEED + 1).shuffle(calibration_items)
    random.Random(CYCLE2_SEED + 2).shuffle(holdout_items)
    common = {
        "schema_version": "prospective-gate-proxy-v1",
        "cycle_id": CYCLE2_ID,
        "synthetic_proxy": True,
        "represents_production_distribution": False,
        "seed": CYCLE2_SEED,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "selection_policy": (
            "article sources unseen by locked eval and invalid cycle 1; "
            "calibration/holdout source pools fixed and disjoint before "
            "question generation; the sole unseen citation edge is holdout-only"
        ),
        "prior_invalid_dataset_sha256": prior_hashes,
    }
    calibration = {
        **common,
        "split": "calibration",
        "locked": True,
        "item_count": len(calibration_items),
        "items": calibration_items,
    }
    holdout = {
        **common,
        "split": "holdout",
        "locked": True,
        "read_policy": "read once after candidate threshold is frozen",
        "item_count": len(holdout_items),
        "items": holdout_items,
    }
    calibration["dataset_sha256"] = sha256_json(calibration_items)
    holdout["dataset_sha256"] = sha256_json(holdout_items)
    return calibration, holdout


def validate_datasets(
    calibration: dict,
    holdout: dict,
    *,
    strict: bool = True,
    excluded_article_ids: set[str] | None = None,
    excluded_questions: set[str] | None = None,
) -> dict:
    used_article_ids, used_questions = existing_eval_content()
    used_article_ids |= set(excluded_article_ids or ())
    used_questions |= set(excluded_questions or ())
    calibration_sources = {
        article_id
        for item in calibration["items"]
        for article_id in item["expected_article_ids"]
    }
    holdout_sources = {
        article_id
        for item in holdout["items"]
        for article_id in item["expected_article_ids"]
    }
    calibration_questions = {
        " ".join(item["question"].split()).lower()
        for item in calibration["items"]
    }
    holdout_questions = {
        " ".join(item["question"].split()).lower()
        for item in holdout["items"]
    }
    checks = {
        "calibration_count": len(calibration["items"]) == (
            CALIBRATION_SINGLE
            + CALIBRATION_MULTI
            + CALIBRATION_AMBIGUOUS
            + CALIBRATION_UNANSWERABLE
        ),
        "holdout_count": len(holdout["items"]) == (
            HOLDOUT_SINGLE
            + HOLDOUT_MULTI
            + HOLDOUT_AMBIGUOUS
            + HOLDOUT_UNANSWERABLE
        ),
        "source_splits_disjoint": calibration_sources.isdisjoint(holdout_sources),
        "questions_unique_within_calibration": (
            len(calibration_questions) == len(calibration["items"])
        ),
        "questions_unique_within_holdout": (
            len(holdout_questions) == len(holdout["items"])
        ),
        "question_splits_disjoint": calibration_questions.isdisjoint(
            holdout_questions
        ),
        "existing_eval_sources_excluded": not (
            calibration_sources | holdout_sources
        )
        & used_article_ids,
        "existing_eval_questions_excluded": not (
            calibration_questions | holdout_questions
        )
        & used_questions,
        "calibration_hash_valid": (
            calibration["dataset_sha256"]
            == sha256_json(calibration["items"])
        ),
        "holdout_hash_valid": (
            holdout["dataset_sha256"] == sha256_json(holdout["items"])
        ),
    }
    if strict and not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise ValueError(f"prospective proxy validation failed: {failed}")
    return {
        "schema_version": "prospective-proxy-validation-v1",
        "all_passed": all(checks.values()),
        "checks": checks,
        "calibration_source_count": len(calibration_sources),
        "holdout_source_count": len(holdout_sources),
        "excluded_source_count": len(used_article_ids),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="用本機 Ollama 產生 prospective synthetic gate proxy"
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--calibration-out",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--holdout-out",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--cycle",
        choices=["1", "2"],
        default="1",
        help="cycle 2 excludes every source/question used by invalid cycle 1",
    )
    args = parser.parse_args()
    laws = json.loads((DATA_DIR / "laws.json").read_text(encoding="utf-8"))
    graph = json.loads((DATA_DIR / "law_graph.json").read_text(encoding="utf-8"))
    if args.cycle == "1":
        cache_path = args.cache or (
            DATA_DIR / "eval" / "prospective_question_cache.json"
        )
        calibration_out = args.calibration_out or (
            DATA_DIR / "eval" / "prospective_proxy_calibration.json"
        )
        holdout_out = args.holdout_out or (
            DATA_DIR / "eval" / "prospective_proxy_holdout.json"
        )
        singles, pairs = select_sources(laws, graph)
        calibration_specs, holdout_specs = build_specs(singles, pairs)
        known_questions = existing_eval_content()[1]
        excluded_ids: set[str] = set()
        excluded_questions: set[str] = set()
    else:
        cache_path = args.cache or (
            DATA_DIR / "eval" / "prospective_v2_question_cache.json"
        )
        calibration_out = args.calibration_out or (
            DATA_DIR / "eval" / "prospective_v2_calibration.json"
        )
        holdout_out = args.holdout_out or (
            DATA_DIR / "eval" / "prospective_v2_holdout.json"
        )
        prior_paths = [
            DATA_DIR / "eval" / "prospective_proxy_calibration.json",
            DATA_DIR / "eval" / "prospective_proxy_holdout.json",
        ]
        if not all(path.exists() for path in prior_paths):
            raise FileNotFoundError("cycle 2 requires the retained cycle 1 datasets")
        prior_payloads = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in prior_paths
        ]
        prior_ids, prior_questions = eval_content_from_paths(prior_paths)
        locked_ids, locked_questions = existing_eval_content()
        excluded_ids = locked_ids | prior_ids
        excluded_questions = locked_questions | prior_questions
        calibration_sources, holdout_sources, holdout_pair = (
            select_cycle2_source_pools(
                laws,
                graph,
                excluded_article_ids=excluded_ids,
            )
        )
        calibration_specs, holdout_specs = build_cycle2_specs(
            calibration_sources,
            holdout_sources,
            holdout_pair,
        )
        known_questions = excluded_questions
    specs = calibration_specs + holdout_specs
    questions = generate_questions(
        specs,
        cache_path=cache_path,
        model_name=get_settings().ollama_model,
        known_questions=known_questions,
    )
    if args.cycle == "1":
        calibration, holdout = build_datasets(laws, graph, questions)
    else:
        calibration, holdout = build_cycle2_datasets(
            questions,
            calibration_specs,
            holdout_specs,
            prior_hashes={
                payload["split"]: payload["dataset_sha256"]
                for payload in prior_payloads
            },
        )
    validation = validate_datasets(
        calibration,
        holdout,
        excluded_article_ids=excluded_ids,
        excluded_questions=excluded_questions,
    )
    validation["cycle_id"] = calibration.get("cycle_id", "prospective-v1")
    atomic_write_json(calibration_out, calibration)
    atomic_write_json(holdout_out, holdout)
    atomic_write_json(
        holdout_out.with_name(
            f"{holdout_out.stem}_validation.json"
        ),
        validation,
    )
    print(
        f"[prospective-proxy] calibration={calibration['item_count']} "
        f"holdout={holdout['item_count']} synthetic_proxy=true"
    )


if __name__ == "__main__":
    main()
