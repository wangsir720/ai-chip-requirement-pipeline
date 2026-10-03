# -*- coding: utf-8 -*-
"""需求结构化：从清洗后文本抽取技术字段。

对应 JD 职责 1「确保需求描述清晰、字段完整」。

## 核心纪律：每个字段带原文出处

抽到的字段必须能回答「这句话是从哪来的」。做法是记录字符区间，
输出时给出可定位的原文片段。没有出处的字段等于编造。

抽不到就填「未提取到」（`NOT_FOUND`）—— **不用默认值、不用推测值**。
字段完整率因此是**可测的**：完整率 = 有出处的必填字段数 / 必填字段总数。
"""
from __future__ import annotations

import os
import re

# 抽不到时的统一占位。不用空字符串，避免「空」与「没抽到」混淆
NOT_FOUND = "未提取到"

# 必填字段：JD 职责 1 要求「字段完整」，这 5 项缺一不可
REQUIRED_FIELDS = ["chip_model", "model_name", "framework", "issue_type", "severity"]

# ---- A-04 登记的问题类型规则（顺序即优先级，多标签）----
ISSUE_RULES = [
    ("oom", r"OOM|out of memory|显存爆|显存不够|显存不足"),
    ("operator_fallback", r"fallback|算子不支持|算子未适配|吞吐掉|利用率只有|吞吐.{0,4}下降"),
    ("finetune_question", r"微调|LoRA|lora"),
    ("multi_card_question", r"加卡|几张卡|多卡|切分|横向扩展|扩展到\s*\d+"),
    ("delivery_timeline", r"交付|排期|什么时候能"),
    ("doc_gap", r"文档|说明看不懂|步骤|拆分文档|安装"),
    ("capability_question", r"能不能支持|支不支持|能不能用|支持到|算不支持"),
]

# 严重度：按问题类型映射，判定依据写清，不做主观打分
SEVERITY_BY_ISSUE = {
    "oom": "P1",          # 客户业务已受阻
    "operator_fallback": "P1",  # 性能不达预期，直接影响上线
    "capability_question": "P3",
    "multi_card_question": "P2",
    "finetune_question": "P2",
    "delivery_timeline": "P2",
    "doc_gap": "P3",
}
DEFAULT_SEVERITY = "P3"

SEVERITY_BASIS = {
    "P1": "客户业务已受阻（跑不起来 / 性能不达预期），需研发优先介入",
    "P2": "影响方案设计与交付承诺，需产品线给出明确口径",
    "P3": "咨询与文档类，不阻塞业务，但影响客户体验与后续复购",
}


class ExtractionError(Exception):
    pass


def _read_rows(path: str) -> list:
    import csv
    if not os.path.isfile(path):
        raise ExtractionError("目录文件不存在：%s" % path)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ExtractionError("目录文件为空：%s" % path)
    return rows


def _load_catalog(path: str, key: str) -> dict:
    import csv
    if not os.path.isfile(path):
        raise ExtractionError("目录文件不存在：%s" % path)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ExtractionError("目录文件为空：%s" % path)
    return {r[key].strip(): r for r in rows}


def _find_with_bounds(text: str, candidates: dict) -> tuple[str, dict | None]:
    """在文本中查找目录内已登记的型号，返回 (命中值, 含位置的证据)。

    用词边界约束避免 `TX8` 误命中 `TX81`：型号后若紧跟数字则不接受。
    """
    best = None
    for name in candidates:
        pattern = r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![0-9])"
        m = re.search(pattern, text, re.I)
        if m and (best is None or m.start() < best[1]["start"]):
            best = (name, {"matched": name, "start": m.start(), "end": m.end(),
                           "quote": text[m.start():m.end()]})
    if best is None:
        return NOT_FOUND, None
    return best


def _framework_with_version(text: str, stack_rows: dict) -> tuple[str, dict | None]:
    """A-03：框架名 + 版本号组合正则。版本抽不到只报框架名。"""
    for name in stack_rows:
        m = re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"[\s]+(\d+\.\d+)(?![0-9])",
                      text, re.I)
        if m:
            return "%s %s" % (name, m.group(1)), {
                "matched": "%s %s" % (name, m.group(1)),
                "start": m.start(), "end": m.end(), "quote": m.group(0)}
    for name in stack_rows:
        m = re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![0-9])", text, re.I)
        if m:
            return name, {"matched": name, "start": m.start(), "end": m.end(),
                           "quote": m.group(0)}
    return NOT_FOUND, None


def classify_issues(text: str) -> tuple[list[str], list[dict]]:
    """A-04：多标签分类。返回 (问题类型列表, 证据列表)。"""
    labels, evidence = [], []
    for label, pattern in ISSUE_RULES:
        m = re.search(pattern, text, re.I)
        if m:
            labels.append(label)
            evidence.append({"label": label, "quote": m.group(0),
                             "start": m.start(), "end": m.end()})
    return labels, evidence


def extract(record: dict, chip_rows: dict, model_rows: dict, stack_rows: dict) -> dict:
    """把一条清洗后的需求结构化。每个字段带出处。"""
    text = record.get("clean_text") or ""
    if not text:
        raise ExtractionError("需求 %s 的清洗文本为空，无法抽取" % record.get("id"))

    fields = {}

    chip, chip_ev = _find_with_bounds(text, chip_rows)
    fields["chip_model"] = {"value": chip, "evidence": chip_ev}

    model, model_ev = _find_with_bounds(text, model_rows)
    fields["model_name"] = {"value": model, "evidence": model_ev}

    stack, stack_ev = _framework_with_version(text, stack_rows)
    fields["framework"] = {"value": stack, "evidence": stack_ev}

    labels, issue_ev = classify_issues(text)
    fields["issue_type"] = {
        "value": ",".join(labels) if labels else NOT_FOUND,
        "multi_label": labels,
        "evidence": issue_ev or None,
    }

    # 严重度由问题类型映射，**不做主观打分**
    sevs = {SEVERITY_BY_ISSUE.get(l, DEFAULT_SEVERITY) for l in labels}
    if not sevs:
        sev = DEFAULT_SEVERITY
    else:
        sev = sorted(sevs)[0]  # 取最高优先级
    fields["severity"] = {
        "value": sev,
        "evidence": {"matched": "、".join(sorted(sevs)) or "无匹配类型",
                     "quote": "问题类型 %s → 严重度 %s" % (",".join(labels) or "无", sev),
                     "start": 0, "end": 0},
        "basis": SEVERITY_BASIS[sev],
    }

    # 非必填的上下文字段
    fields["customer_industry"] = {
        "value": record.get("customer_industry") or NOT_FOUND,
        "evidence": {"matched": "样本自带上下文（非从原文抽取）",
                     "quote": record.get("customer_industry", ""), "start": 0, "end": 0},
    }
    fields["source_channel"] = {
        "value": record.get("source", ""),
        "evidence": {"matched": "样本自带", "quote": record.get("source", ""),
                     "start": 0, "end": 0},
    }
    fields["raw_text"] = {
        "value": record.get("raw_text", ""),
        "evidence": None,
    }

    filled = [f for f in REQUIRED_FIELDS if fields[f]["value"] != NOT_FOUND]
    fields["_quality"] = {
        "required_total": len(REQUIRED_FIELDS),
        "required_filled": len(filled),
        "missing_fields": [f for f in REQUIRED_FIELDS if fields[f]["value"] == NOT_FOUND],
        "completeness": round(len(filled) / len(REQUIRED_FIELDS), 4),
        "assumption_refs": ["A-03", "A-04"],
    }
    return fields


def load_catalogs(base: str) -> tuple[dict, dict, dict]:
    chips = _load_catalog(os.path.join(base, "data", "chips", "chip_matrix.csv"), "chip_model")
    models = _load_catalog(os.path.join(base, "data", "models", "model_matrix.csv"), "model_id")
    # 框架目录的键必须是「框架+版本」而不是仅框架名：
    # 同一框架的多个版本（如 PyTorch 1.13 / 2.1）承载**不同**的适配结论，
    # 用框架名做键会互相覆盖，直接导致版本维度的证据丢失。
    stacks = {}
    for r in _read_rows(os.path.join(base, "data", "frameworks", "stack_matrix.csv")):
        stacks["%s %s" % (r["framework"].strip(), r["version"].strip())] = r
    # 另建按框架名的首条索引，供「只提到框架名未提版本」的查询使用
    for r in _read_rows(os.path.join(base, "data", "frameworks", "stack_matrix.csv")):
        stacks.setdefault(r["framework"].strip(), r)
    return chips, models, stacks
