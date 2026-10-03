# -*- coding: utf-8 -*-
"""问题闭环知识库：结构化沉淀 + 多维检索。

对应 JD 职责 3「定期整理需求文档及技术工具集，建立问题闭环知识库」。

## 为什么是「闭环」而不是「知识记录」

记录历史问题很容易，**把问题真正闭环**要回答五件事（对应 `ENTRY_FIELDS`）：
现象 / 原因 / 解决步骤 / 验证方式 / 关联需求单号。

缺任何一项都不是闭环 —— 这条纪律写进了 `build_entry()` 的校验：
字段不全的条目**拒绝入库**并说明缺哪项。

## 检索维度

按芯片型号、模型、问题类型、框架检索。这四个维度是实际排障时的提问方式：
「TX8 上 Qwen 跑不起来」「PyTorch 2.1 有什么已知问题」—— 检索入口必须与提问方式对齐，
否则知识库建了也没人用。
"""
from __future__ import annotations

NOT_FOUND = "未提取到"

ENTRY_FIELDS = ["phenomenon", "cause", "solution", "verification", "linked_requirement"]

FIELD_LABEL = {
    "phenomenon": "现象",
    "cause": "原因",
    "solution": "解决步骤",
    "verification": "验证方式",
    "linked_requirement": "关联需求单号",
}

FIELD_GUIDE = {
    "phenomenon": "客户看到的表象，须包含可观察量（报错、吞吐、显存占用）",
    "cause": "根因分析。**未定位到根因时写「根因未定位」并说明已排查到哪一步**，不编",
    "solution": "具体操作步骤或配置变更，不写「重启试试」这类无信息量内容",
    "verification": "如何确认问题已解决：跑哪个脚本、看哪个指标、阈值是多少",
    "linked_requirement": "关联的需求单号，用于回溯需求来源",
}


class KbError(Exception):
    pass


def build_entry(requirement: dict, cause: str, solution: str,
                verification: str) -> dict:
    """构建一条知识库条目。**字段不全拒绝入库**并说明缺哪项。"""
    for k in ("id", "clean_text"):
        if k not in requirement:
            raise KbError("需求记录缺少字段 %s" % k)

    entry = {
        "phenomenon": requirement.get("clean_text", "").strip() or NOT_FOUND,
        "cause": (cause or "").strip() or "根因未定位",
        "solution": (solution or "").strip(),
        "verification": (verification or "").strip(),
        "linked_requirement": requirement["id"],
    }

    # 根因未定位是合法状态，但必须显式计入 partial，不能静默留空
    if entry["cause"] == "根因未定位":
        entry["partial"] = ["cause"]

    fields = requirement.get("fields") or {}
    entry["chip_model"] = fields.get("chip_model", {}).get("value", NOT_FOUND)
    entry["model_name"] = fields.get("model_name", {}).get("value", NOT_FOUND)
    entry["framework"] = fields.get("framework", {}).get("value", NOT_FOUND)
    entry["issue_labels"] = (fields.get("issue_type", {}) or {}).get("multi_label", [])

    if not entry["solution"]:
        entry["rejected"] = "解决步骤为空 —— 未解决的问题不入库，避免知识库变成问题堆积"
        return entry
    if not entry["verification"]:
        entry["rejected"] = "验证方式为空 —— 无法确认是否解决，不算闭环"
        return entry

    entry["rejected"] = ""
    entry["partial"] = sorted(set(entry.get("partial", [])))
    entry["completeness"] = round(
        sum(1 for f in ENTRY_FIELDS if entry[f] and entry[f] != NOT_FOUND) / len(ENTRY_FIELDS), 4)
    return entry


def index(entries: list[dict]) -> dict:
    """建立多维倒排索引。"""
    idx = {"chip_model": {}, "model_name": {}, "framework": {}, "issue": {}}
    for e in entries:
        if e.get("rejected"):
            continue
        keys = [
            ("chip_model", [e.get("chip_model", NOT_FOUND)]),
            ("model_name", [e.get("model_name", NOT_FOUND)]),
            ("framework", [e.get("framework", NOT_FOUND)]),
            ("issue", e.get("issue_labels") or []),
        ]
        for dim, vals in keys:
            for v in vals:
                if v and v != NOT_FOUND:
                    idx[dim].setdefault(v, []).append(e["linked_requirement"])
    return {
        "index": {k: {kk: sorted(set(vv)) for kk, vv in v.items()} for k, v in idx.items()},
        "entry_count": len([e for e in entries if not e.get("rejected")]),
        "rejected_count": len([e for e in entries if e.get("rejected")]),
        "dimensions": ["chip_model", "model_name", "framework", "issue"],
        "assumption_refs": ["A-03", "A-04"],
    }


def search(entries: list[dict], dim: str, value: str) -> dict:
    """按单一维度检索。dim 取值须在 `index()` 的 dimensions 内。"""
    if dim not in ("chip_model", "model_name", "framework", "issue"):
        raise KbError("检索维度须为 chip_model / model_name / framework / issue，实际为 %r" % dim)
    key = value.strip()
    if not key:
        raise KbError("检索值不能为空")
    hits = []
    for e in entries:
        if e.get("rejected"):
            continue
        pool = (e.get("issue_labels") or []) if dim == "issue" else [e.get(dim, NOT_FOUND)]
        if key in pool:
            hits.append({
                "linked_requirement": e["linked_requirement"],
                "phenomenon": e["phenomenon"],
                "cause": e["cause"],
                "solution": e["solution"],
                "verification": e["verification"],
                "completeness": e.get("completeness"),
            })
    return {
        "dimension": dim, "value": key, "hit_count": len(hits), "hits": hits,
        "note": "检索维度按实际排障提问方式设计：芯片/模型/框架/问题类型，"
                "使知识库的入口与提问方式对齐",
    }


def build_from_requirements(records: list[dict], resolutions: dict) -> dict:
    """由需求 + 解决记录构建知识库。

    `resolutions` 形如 {"RAW-001": {"cause": ..., "solution": ..., "verification": ...}}
    **未提供解决记录的需求不进知识库** —— 需求池里有 80% 是待核实项，
    把它们全塞进知识库，知识库就变成了问题堆积。
    """
    if not records:
        raise KbError("需求集为空，无法构建知识库")
    entries, missing = [], []
    for r in records:
        rid = r["id"]
        res = resolutions.get(rid)
        if not res:
            missing.append({"requirement_id": rid,
                            "reason": "未提供解决记录 —— 待核实需求不进知识库"})
            continue
        entries.append(build_entry(r, res.get("cause", ""),
                                   res.get("solution", ""),
                                   res.get("verification", "")))

    accepted = [e for e in entries if not e.get("rejected")]
    rejected = [{"requirement_id": e["linked_requirement"], "reason": e["rejected"]}
                for e in entries if e.get("rejected")]
    return {
        "entries": accepted,
        "rejected": rejected,
        "pending": missing,
        "index": index(entries),
        "field_guide": FIELD_GUIDE,
        "discipline_note": "闭环五要素缺任一项即拒收入库。"
                          "知识库的价值在于「下次遇到能直接用」，"
                          "而不是「记录过多少问题」。",
    }
