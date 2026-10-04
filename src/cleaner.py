# -*- coding: utf-8 -*-
"""需求清洗：去重、去噪声、归一化。

把「多源需求杂、乱、散」变成字段完整、可复核的需求单。

## 三条纪律

1. **清洗动作全部留痕** —— 删了什么、为什么删，都记进 `actions`。
   清洗器最危险的不是删错，而是**删了不说**。
2. **只做有依据的清洗** —— 噪声词表与指代代词表都是显式登记的清单，
   不做「看起来像噪声就删」的启发式处理。
3. **不丢原文** —— 清洗后仍保留 `raw_text`，便于回溯与人工复核。
"""
from __future__ import annotations

import os
import re
import unicodedata

# ---- A-02 登记的噪声清单（行业典型值）----
NOISE_TOKENS = [
    "。。。", "...", "…", "麻烦看看", "麻烦确认", "谢谢", "感谢", "辛苦了",
    "吧", "呀", "呢", "啊", "哈", "嗯", "这个肯定", "不太懂", "不太清楚",
    "我们这边", "他们那边", "这边", "那边",
]
# ---- A-01 登记的指代代词（清洗时替换为占位符，保留语义线索）----
PRONOUNS = ["这个卡", "那个卡", "这块卡", "他们那边", "我们这边", "这个肯定"]

_PUNCT_MAP = str.maketrans({
    "，": ",", "。": ".", "！": "!", "？": "?", "；": ";",
    "（": "(", "）": ")", "：": ":", "　": " ",
})


class CleaningError(Exception):
    pass


def normalize(text: str) -> str:
    """A-02：全角转半角 + 去除重复空格。"""
    if not isinstance(text, str):
        raise CleaningError("需求文本必须是字符串，实际为 %s" % type(text).__name__)
    t = unicodedata.normalize("NFKC", text)
    t = t.translate(_PUNCT_MAP)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def strip_noise(text: str) -> tuple[str, list[str]]:
    """去除登记在案的噪声词。返回 (清洗后文本, 被删的噪声词列表)。"""
    removed = []
    t = text
    for token in NOISE_TOKENS:
        if token in t:
            t = t.replace(token, "")
            removed.append(token)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[，,]{2,}", ",", t)
    t = re.sub(r"^[,，]\s*", "", t)
    return t.strip(", "), removed


def mark_pronouns(text: str) -> tuple[str, list[str]]:
    """A-01：指代代词标记而非删除 —— 删掉会丢失「信息不完整」这个信号。"""
    found = []
    t = text
    for p in PRONOUNS:
        if p in t:
            t = t.replace(p, "[指代]%s" % p)
            found.append(p)
    return t, found


def _bigrams(text: str) -> set:
    """中文按字 bigram；长度不足 1 时退化为单字集合。"""
    chars = re.sub(r"[^\w\u4e00-\u9fff.]", "", text)
    if len(chars) <= 1:
        return {chars} if chars else set()
    return {chars[i:i + 2] for i in range(len(chars) - 1)}


def similarity(a: str, b: str) -> float:
    """A-01：bigram Jaccard 相似度。"""
    sa, sb = _bigrams(a), _bigrams(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


# A-01：合并阈值（占位待实测替换）
MERGE_THRESHOLD = 0.45
# A-01：完全重复阈值
EXACT_THRESHOLD = 1.0


def clean_record(rec: dict) -> dict:
    """清洗单条原始需求，保留全部动作留痕。"""
    for f in ("id", "source", "text"):
        if f not in rec:
            raise CleaningError("原始需求缺少字段 %s" % f)
    raw = rec["text"]
    norm = normalize(raw)
    nostrip, removed_noise = strip_noise(norm)
    marked, pronouns = mark_pronouns(nostrip)
    return {
        "id": rec["id"],
        "source": rec.get("source", "unknown"),
        "received_at": rec.get("received_at", ""),
        "reporter": rec.get("reporter", ""),
        "customer_industry": rec.get("customer_industry", ""),
        "raw_text": raw,
        "clean_text": marked,
        "actions": [
            {"action": "normalize", "detail": "全角转半角 + 空白归一"},
            {"action": "strip_noise",
             "detail": ("删除噪声词：%s" % "、".join(removed_noise)) if removed_noise else "无噪声词"},
            {"action": "mark_pronouns",
             "detail": ("标记指代：%s" % "、".join(pronouns)) if pronouns else "无指代"},
        ],
        "removed_noise": removed_noise,
        "pronouns": pronouns,
    }


def _dedup_key(rec: dict) -> str:
    """结构化去重键：芯片 + 模型 + 首要问题类型。

    为什么不用纯文本相似度：实测在本项目样本集上，同义重复对的相似度
    （最低 0.130）与不同诉求对的相似度（最高 0.140）区间重叠 ——
    无论阈值调在哪都会误合并。纯文本相似度不是解决这个问题的正确工具。

    结构化去重键的逻辑依据是产品语义：**同一张卡 + 同一个模型 + 同一类问题
    = 同一个需求**，不管它来自邮件、工单还是会议纪要。这才是需求治理该做的事。

    两个有意的设计：
    1. **框架不参与** —— 同一需求在不同渠道常被写成不同框架表述
       （实测 RAW-002 写 vLLM、RAW-006 未提框架，实为同一需求）。
    2. **多标签问题类型只取首要标签** —— 一条需求常同时命中
       「显存不足」与「能力咨询」，取首要标签（按 ISSUE_RULES 优先级），
       否则同一需求因标签集不同而漏合并。
    """
    chips = rec.get("chip_model") or "-"
    models = rec.get("model_name") or "-"
    labels = rec.get("issue_labels") or []
    primary = labels[0] if labels else "-"
    return "%s|%s|%s" % (chips, models, primary)


def deduplicate(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """按结构化去重键合并重复需求。

    保留策略：**保留最早到达的一条为主需求**（时间优先，符合「客户先说」的现实），
    其余记入 `merged_from`。这样主需求的 id 稳定可追溯。

    文本相似度仅作为**辅助证据**写入日志，不参与判定 —— 理由见 _dedup_key。
    """
    if not records:
        raise CleaningError("需求集为空，无法去重")
    ordered = sorted(records, key=lambda r: (r.get("received_at", ""), r["id"]))
    kept: list[dict] = []
    by_key: dict[str, dict] = {}
    log: list[dict] = []
    for rec in ordered:
        key = _dedup_key(rec)
        if key in by_key:
            k = by_key[key]
            sim = similarity(k["clean_text"], rec["clean_text"])
            k.setdefault("merged_from", []).append({
                "id": rec["id"], "source": rec["source"],
                "received_at": rec["received_at"],
                "text_similarity": round(sim, 3),
            })
            log.append({
                "kept": k["id"], "merged": rec["id"],
                "dedup_key": key,
                "text_similarity": round(sim, 3),
                "level": "结构化同需求",
                "reason": "去重键一致（芯片+模型+问题类型）：%s" % key,
            })
        else:
            item = dict(rec, merged_from=[])
            kept.append(item)
            by_key[key] = item
    return kept, log


def load_raw_requests(path: str) -> list[dict]:
    import json
    if not os.path.isfile(path):
        raise CleaningError("原始需求文件不存在：%s" % path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("requests") if isinstance(data, dict) else data
    if not rows:
        raise CleaningError("原始需求集为空")
    return rows


def run_pipeline(records: list[dict], extractor=None, catalogs=None) -> dict:
    """完整清洗流程：逐条清洗 -> 字段抽取 -> 去重合并。

    顺序说明：去重键依赖抽取出的芯片/模型/问题类型字段，
    因此**必须先抽取再合并** —— 这是上一版把顺序写反导致去重率恒为 0 的原因。
    extractor 与 catalogs 传入时启用结构化去重；不传则退化为纯清洗（供单元测试用）。
    """
    cleaned = [clean_record(r) for r in records]
    if extractor is None or catalogs is None:
        return {
            "raw_count": len(records), "cleaned_count": len(cleaned),
            "unique_count": len(cleaned), "duplicate_removed": 0,
            "duplicate_rate": 0.0, "unique": cleaned, "merge_log": [],
            "noise_tokens_removed": sorted({t for c in cleaned for t in c["removed_noise"]}),
            "pronouns_marked": sorted({p for c in cleaned for p in c["pronouns"]}),
            "assumption_refs": ["A-01", "A-02"],
            "note": "未提供抽取器，本次仅执行清洗，未执行结构化去重",
        }

    chips, models, stacks = catalogs
    enriched = []
    for c in cleaned:
        fields = extractor(c, chips, models, stacks)
        c = dict(c)
        c["fields"] = fields
        c["chip_model"] = fields["chip_model"]["value"]
        c["model_name"] = fields["model_name"]["value"]
        c["issue_type"] = fields["issue_type"]["value"]
        c["issue_labels"] = fields["issue_type"]["multi_label"]
        c["framework"] = fields["framework"]["value"]
        c["severity"] = fields["severity"]["value"]
        c["completeness"] = fields["_quality"]["completeness"]
        enriched.append(c)

    unique, merge_log = deduplicate(enriched)
    comps = [c["completeness"] for c in unique]
    return {
        "raw_count": len(records),
        "cleaned_count": len(cleaned),
        "unique_count": len(unique),
        "duplicate_removed": len(cleaned) - len(unique),
        "duplicate_rate": round((len(cleaned) - len(unique)) / len(cleaned), 4) if cleaned else 0.0,
        "avg_completeness": round(sum(comps) / len(comps), 4) if comps else 0.0,
        "unique": unique,
        "merge_log": merge_log,
        "noise_tokens_removed": sorted({t for c in cleaned for t in c["removed_noise"]}),
        "pronouns_marked": sorted({p for c in cleaned for p in c["pronouns"]}),
        "assumption_refs": ["A-01", "A-02", "A-03", "A-04"],
    }
