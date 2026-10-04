# -*- coding: utf-8 -*-
"""适配判定：芯片 × 模型 × 框架 -> 支持 / 需调优 / 不推荐 / 待核实。

维护需求管理 SOP 与编写测试脚本之前的前置判定。

## 四条不可让步的规则

1. **每个判定必须引用 `data/` 的具体来源行**，不允许凭空结论。
2. **字段缺失即判 `unknown`（待核实）**，不用默认值、不用推测值填补。
3. **`unverified` 级来源不参与判定** —— 拿客户单方面描述去否定一个框架版本，
   责任不对等。此时只输出「需实测验证」档。
4. **不代替研发做切片决策** —— 只列候选方式与各自约束，决策权在研发。
"""
from __future__ import annotations

import math

NOT_FOUND = "未提取到"

# B-01：推理运行时显存余量系数（行业典型值，须按实际框架 profiling 校准）
RUNTIME_VRAM_FACTOR = 1.15

VERDICT_ORDER = ["supported", "needs_verification", "not_recommended", "unknown"]
VERDICT_LABEL = {
    "supported": "支持",
    "needs_verification": "需实测验证",
    "not_recommended": "不推荐",
    "unknown": "待人工核实",
}

# B-03：多卡切分候选方式。列出即交研发决策，本工具不代选
PARALLEL_STRATEGIES = [
    ("张量并行", "按权重矩阵切分，单层内跨卡协作；通信量最大，对互联带宽要求最高"),
    ("流水并行", "按层切分，不同卡处理不同层；通信量小，但需足够层数才能填满卡数"),
    ("专家并行", "仅适用于 MoE 架构，按专家切分；非 MoE 模型不适用"),
]


class ValidationError(Exception):
    pass


def _get(row: dict, key: str):
    v = (row.get(key) or "").strip()
    return v if v and v != "-" else None


def judge(fields: dict, chip_rows: dict, model_rows: dict, stack_rows: dict) -> dict:
    """对单条已结构化的需求做适配判定。"""
    chip = fields.get("chip_model", {}).get("value", NOT_FOUND)
    model = fields.get("model_name", {}).get("value", NOT_FOUND)
    stack = fields.get("framework", {}).get("value", NOT_FOUND)
    evidence = []
    unknown_reasons = []

    # 字段缺失即待核实
    missing = []
    if chip == NOT_FOUND:
        missing.append("chip_model")
    if model == NOT_FOUND:
        missing.append("model_name")
    if missing:
        unknown_reasons.append("必填字段缺失：%s" % "、".join(missing))

    if chip != NOT_FOUND and chip not in chip_rows:
        unknown_reasons.append("型号 %s 未收录于 data/chips/chip_matrix.csv" % chip)
    if model != NOT_FOUND and model not in model_rows:
        unknown_reasons.append("模型 %s 未收录于 data/models/model_matrix.csv" % model)

    if unknown_reasons:
        return {
            "chip_model": chip, "model_name": model, "framework": stack,
            "verdict": "unknown", "verdict_label": VERDICT_LABEL["unknown"],
            "reason": "；".join(unknown_reasons),
            "evidence": evidence,
            "multi_card": None,
            "assumption_refs": ["B-01", "B-03"],
        }

    chip_row = chip_rows[chip]
    model_row = model_rows[model]
    evidence.append({
        "what": "芯片规格",
        "detail": "%s（%s，显存 %s GiB，来源 %s，%s）"
                  % (chip, chip_row.get("product_line", "?"),
                     _get(chip_row, "vram_gib") or "未查到",
                     chip_row.get("source_id"), chip_row.get("credibility")),
    })
    evidence.append({
        "what": "模型规格",
        "detail": "%s（最小显存 %s GiB，来源 %s）"
                  % (model, _get(model_row, "min_vram_gib") or "未查到",
                     model_row.get("source_id")),
    })

    # ---- 显存判定（B-01） ----
    vram = _num(chip_row.get("vram_gib"))
    need_raw = _num(model_row.get("min_vram_gib"))
    need = need_raw * RUNTIME_VRAM_FACTOR if need_raw is not None else None

    if vram is None:
        verdict = "unknown"
        reason = ("芯片 %s 的公开资料未查到单卡显存（可重构架构的详细规格未公开），"
                  "无法做显存判定 —— 待人工核实" % chip)
    elif need is None:
        verdict = "unknown"
        reason = "模型 %s 未登记最小显存，无法判定" % model
    elif need > vram:
        cards = int(math.ceil(need / vram))
        verdict = "not_recommended"
        reason = ("模型 %s 权重下界 %.1f GiB（含 %.2f 运行时余量）超过单卡显存 %.1f GiB，"
                  "单卡跑不动；至少需 %d 卡（张量/流水并行，切分方式须研发确认）"
                  % (model, need_raw, RUNTIME_VRAM_FACTOR, vram, cards))
        evidence.append({
            "what": "多卡方案",
            "detail": "候选切分方式：%s"
                      % "；".join("%s —— %s" % (n, d) for n, d in PARALLEL_STRATEGIES),
        })
    else:
        headroom = (vram - need) / vram
        if headroom < 0.15:
            verdict = "needs_verification"
            reason = ("显存可容纳但余量仅 %.1f%%，低于 15%% 阈值，"
                      "需按客户实际上下文长度实测确认" % (headroom * 100))
        else:
            verdict = "supported"
            reason = ("显存余量 %.1f%%（需求下界 %.1f GiB / 单卡 %.1f GiB），高于 15%% 阈值"
                      % (headroom * 100, need, vram))
    evidence.append({
        "what": "显存口径",
        "detail": "需求 = 最小显存 %.0f GiB × 运行时余量 %.2f = %.2f GiB（**下界**，"
                  "未计入 KV Cache 与激活值）"
                  % (need_raw if need_raw is not None else 0,
                     RUNTIME_VRAM_FACTOR, need if need is not None else 0),
    })

    # ---- 框架判定（B-02） ----
    if stack != NOT_FOUND:
        # 优先按「框架+版本」精确匹配；匹配不到再退化为按框架名匹配。
        # 早期实现用 split()[0] 只取框架名，会把版本维度整个丢掉 ——
        # 而版本恰恰是 fallback 结论成立与否的关键。
        stack_row = stack_rows.get(stack) or stack_rows.get(stack.split()[0])
        if stack_row is None:
            evidence.append({
                "what": "框架",
                "detail": "框架 %s 未收录于 data/frameworks/stack_matrix.csv" % stack,
            })
        else:
            fallback = (stack_row.get("operator_fallback_to_cpu_known") or "").strip()
            cred = stack_row.get("credibility")
            evidence.append({
                "what": "框架支持",
                "detail": "%s（fallback 记录：%s，来源 %s，可信度 %s）"
                          % (stack, fallback or "未查到",
                             stack_row.get("source_id"), cred),
            })
            if fallback.lower() == "true" and cred == "unverified":
                if verdict == "supported":
                    verdict = "needs_verification"
                reason += ("；另有该框架算子 fallback 到 CPU 的记录，"
                           "但来源可信度为 unverified（来自客户单方描述），"
                           "**不据此判不推荐**，只要求实测验证")
            if (stack_row.get("migration_path") or "").strip() == "无需迁移":
                evidence.append({
                    "what": "迁移成本",
                    "detail": "FlagOS 原生算子库，来源 %s，标注为无需迁移" % stack_row.get("source_id"),
                })

    cards = None
    if vram and need and need > vram:
        cards = int(math.ceil(need / vram))

    return {
        "chip_model": chip,
        "model_name": model,
        "framework": stack,
        "verdict": verdict,
        "verdict_label": VERDICT_LABEL[verdict],
        "reason": reason,
        "evidence": evidence,
        "multi_card": {
            "cards_needed": cards,
            "strategies": [{"name": n, "note": d} for n, d in PARALLEL_STRATEGIES]
            if cards else [],
            "decision_owner": "切分方式由研发确认，本工具不代为决策",
        },
        "assumption_refs": ["B-01", "B-02", "B-03"],
    }


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_matrix(records: list[dict], chip_rows: dict, model_rows: dict,
                 stack_rows: dict) -> dict:
    """对全部唯一需求生成适配矩阵。"""
    entries = []
    for r in records:
        f = r.get("fields")
        if not f:
            raise ValidationError("需求 %s 缺少抽取结果，无法判定" % r.get("id"))
        v = judge(f, chip_rows, model_rows, stack_rows)
        v["requirement_id"] = r["id"]
        v["severity"] = r.get("severity")
        v["completeness"] = r.get("completeness")
        entries.append(v)
    order = {k: i for i, k in enumerate(VERDICT_ORDER)}
    entries.sort(key=lambda e: (order[e["verdict"]], e["requirement_id"]))

    counts = {}
    for e in entries:
        counts[e["verdict"]] = counts.get(e["verdict"], 0) + 1
    return {
        "entries": entries,
        "total": len(entries),
        "verdict_counts": {VERDICT_LABEL[k]: v for k, v in counts.items()},
        "scope_note": "全部判定基于公开资料与自拟样本，**未做真卡实测**。"
                      "显存需求为下界估算（未计入 KV Cache 与激活值）。",
    }
