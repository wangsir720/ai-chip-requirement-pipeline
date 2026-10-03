# -*- coding: utf-8 -*-
"""文档装配：需求单 / 分析报告 / SOP / 看板 / 知识库。

对应 JD 职责 1「结构化需求单」、职责 2「状态跟踪与风险同步」、
职责 3「需求管理 SOP」三类交付物。
"""
from __future__ import annotations

import csv
import json
import os

# 状态流转（对应职责 2 的 Backlog → Done）
STATUS_FLOW = ["Backlog", "待澄清", "已拆解", "In Progress", "待验证", "Done"]


def _table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
    return "\n".join(out)


def _origin(f: dict) -> str:
    """把字段的证据渲染成可读出处。

    证据有两种形态：单条（dict）与多条（list，多标签问题类型会出现）。
    两种都要处理，且都区分「原文抽取」与「样本自带」。
    """
    ev = f.get("evidence")
    if not ev:
        return "—"
    items = ev if isinstance(ev, list) else [ev]
    parts = []
    for e in items:
        if not e or not e.get("quote"):
            continue
        if e.get("start") == 0 and e.get("end") == 0:
            parts.append("样本自带（非原文抽取）")
        else:
            parts.append("原文「%s」位置 %s" % (e["quote"][:24], e["start"]))
    return "；".join(parts) if parts else "—"


def render_requirement_spec(rec: dict, fields: dict) -> str:
    """渲染单张结构化需求单。每个字段带原文出处。"""
    L = ["# 需求单 · %s" % rec["id"], ""]
    L.append("> 由 `src/doc_assembler.py` 自动装配。字段出处为需求原文的字符区间。")
    L.append("")

    rows = []
    for name in ("chip_model", "model_name", "framework", "issue_type",
                 "severity", "customer_industry", "source_channel"):
        f = fields.get(name, {})
        rows.append([FIELD_CN[name], f.get("value", "—"), _origin(f)])
    L.append(_table(["字段", "取值", "原文出处"], rows))
    L.append("")

    q = fields["_quality"]
    L.append("**必填字段完整率：%.0f%%**（%d/%d）" % (
        q["completeness"] * 100, q["required_filled"], q["required_total"]))
    if q["missing_fields"]:
        L.append("")
        L.append("缺失字段：%s —— 这些字段须向需求提出方补齐，**不用默认值填充**。"
                 % "、".join(q["missing_fields"]))
    L.append("")

    L.append("## 需求原文")
    L.append("")
    L.append("> %s" % rec.get("raw_text", ""))
    L.append("")
    L.append("## 清洗动作留痕")
    L.append("")
    L.append(_table(["动作", "说明"],
                    [[a["action"], a["detail"]] for a in rec.get("actions", [])]))
    L.append("")
    if rec.get("merged_from"):
        L.append("## 重复来源（已合并）")
        L.append("")
        L.append(_table(["原始单号", "来源", "接收日期", "文本相似度(辅助证据)"],
                        [[m["id"], m["source"], m["received_at"],
                          m.get("text_similarity", "-")]
                         for m in rec["merged_from"]]))
        L.append("")
    L.append("---")
    L.append("生成命令：`python -m src.cli`")
    L.append("")
    return "\n".join(L)


FIELD_CN = {
    "chip_model": "芯片型号",
    "model_name": "模型名称",
    "framework": "框架与版本",
    "issue_type": "问题类型",
    "severity": "严重度",
    "customer_industry": "客户行业",
    "source_channel": "来源渠道",
}


def render_analysis_report(pipeline: dict, matrix: dict, kb: dict) -> str:
    """需求分析与拆解报告（对应职责 1 的「分析与拆解」）。"""
    L = ["# 需求分析与拆解报告", ""]
    L.append("> 由 `src/doc_assembler.py` 自动装配。**需求样本为自拟，非真实业务数据。**")
    L.append("")

    L.append("## 1. 总量与质量")
    L.append(_table(
        ["指标", "值"],
        [["原始需求条数", pipeline["raw_count"]],
         ["重复需求条数", pipeline["duplicate_removed"]],
         ["去重率", "%.1f%%" % (pipeline["duplicate_rate"] * 100)],
         ["唯一需求数", pipeline["unique_count"]],
         ["必填字段平均完整率", "%.0f%%" % (pipeline["avg_completeness"] * 100)]]))
    L.append("")
    L.append("去重依据：结构化去重键（芯片 + 模型 + 首要问题类型）。")
    L.append("文本相似度仅作辅助证据，**不参与判定** —— 实测同义重复对与不同诉求对的")
    L.append("相似度区间重叠，纯文本相似度无法区分二者。")
    L.append("")

    L.append("## 2. 需求分布")
    by_sev = {}
    for r in pipeline["unique"]:
        by_sev.setdefault(r["severity"], []).append(r["id"])
    L.append(_table(["严重度", "条数", "需求单号"],
                    [[s, len(v), ", ".join(v)] for s, v in sorted(by_sev.items())]))
    L.append("")
    L.append("严重度由问题类型映射得出，**不做主观打分**；映射依据见 `extractor.py::SEVERITY_BASIS`。")
    L.append("")

    L.append("## 3. 适配判定汇总")
    L.append(_table(["判定", "条数"],
                    [[k, v] for k, v in matrix["verdict_counts"].items()]))
    L.append("")
    L.append("> %s" % matrix["scope_note"])
    L.append("")

    L.append("## 4. 字段缺失清单（须补齐）")
    missing = []
    for r in pipeline["unique"]:
        f = r.get("fields", {})
        q = f.get("_quality", {})
        if q.get("missing_fields"):
            missing.append([r["id"], ", ".join(q["missing_fields"])])
    if missing:
        L.append(_table(["需求单号", "缺失字段"], missing))
        L.append("")
        L.append("字段完整率是本项目的核心可测量指标：**每一条缺失都对应一个需要澄清的问题**。")
    else:
        L.append("无缺失。")
    L.append("")

    L.append("## 5. 知识库沉淀")
    L.append(_table(
        ["项", "值"],
        [["入库条目", kb["index"]["entry_count"]],
         ["拒收条目", len(kb["rejected"])],
         ["待解决（不入库）", len(kb["pending"])]]))
    L.append("")
    L.append("> %s" % kb["discipline_note"])
    L.append("")
    L.append("---")
    L.append("生成命令：`python -m src.cli`")
    L.append("")
    return "\n".join(L)


def render_board(pipeline: dict, matrix: dict) -> str:
    """需求流转状态看板（对应职责 2）。"""
    L = ["# 需求流转状态看板", ""]
    L.append("> 状态流转：%s" % " → ".join(STATUS_FLOW))
    L.append("")
    L.append("> 状态由严重度与适配判定共同推导："
              "P1 且判定非「待人工核实」→ 可直接进 In Progress；"
              "字段不全 → 停在「待澄清」。**状态不是进度汇报，是下一动作。**")
    L.append("")

    verdict_by_id = {e["requirement_id"]: e for e in matrix["entries"]}
    rows = []
    for r in pipeline["unique"]:
        v = verdict_by_id.get(r["id"], {})
        verdict = v.get("verdict_label", "—")
        sev = r["severity"]
        q = r.get("fields", {}).get("_quality", {})
        if q.get("missing_fields"):
            status, next_action = "待澄清", "向需求提出方补齐：%s" % ", ".join(q["missing_fields"])
        elif sev == "P1":
            status, next_action = "In Progress", "研发介入并按生成的测试脚本实测"
        elif verdict == "不推荐":
            status, next_action = "待验证", "确认多卡切分方式后重测"
        else:
            status, next_action = "已拆解", "排入版本计划"
        rows.append([r["id"], r["chip_model"], r["model_name"], sev, verdict, status, next_action])

    L.append(_table(["需求单号", "芯片", "模型", "严重度", "适配判定", "状态", "下一动作"], rows))
    L.append("")

    L.append("## 风险同步")
    L.append("")
    risks = [r for r in rows if r[3] == "P1" and r[5] == "待澄清"]
    if risks:
        L.append("**P1 且字段不全（阻塞中）**：%s" % ", ".join(r[0] for r in risks))
        L.append("")
        L.append("这类需求是进度风险的主要来源：严重度最高但因字段不全无法启动，")
        L.append("**越早澄清越好** —— 建议列入下一次跨部门对齐会议的固定议题。")
    else:
        L.append("无「P1 且字段不全」的阻塞项。")
    L.append("")
    L.append("---")
    L.append("生成命令：`python -m src.cli`")
    L.append("")
    return "\n".join(L)


def render_sop(pipeline: dict) -> str:
    """需求管理 SOP（对应职责 3）。

    每条规则都标注它在代码里的实际实现位置 —— 写了没实现的 SOP 是废话。
    """
    L = ["# 需求管理 SOP", ""]
    L.append("> 由 `src/doc_assembler.py` 自动装配。"
             "**每条规则均标注对应实现位置** —— 写了没实现的 SOP 是废话。")
    L.append("")

    L.append("## 1. 需求录入")
    L.append(_table(["步骤", "要求", "实现位置"],
                    [["1. 登记来源", "必须标明 email / jira / meeting_note / ticket",
                      "`cleaner.py::clean_record` 读 `source` 字段"],
                     ["2. 原文不得改写", "原文单独存 `raw_text`，清洗结果另存 `clean_text`",
                      "`cleaner.py` 双字段保留"],
                     ["3. 上报人与客户行业", "作为上下文单独存储，**不从原文猜测**",
                      "`extractor.py` 的 `customer_industry` 标注「样本自带」"]]))
    L.append("")

    L.append("## 2. 需求审核")
    L.append(_table(["检查项", "判定标准", "实现位置"],
                    [["必填字段完整", "5 项必填字段（芯片/模型/框架/问题类型/严重度）全部有值",
                      "`extractor.py::REQUIRED_FIELDS`"],
                     ["字段必须有出处", "每个抽取字段带原文字符区间",
                      "`extractor.py` 的 `evidence` 字段"],
                     ["抽不到不填", "填「未提取到」，**禁止用默认值**",
                      "`extractor.py::NOT_FOUND`"],
                     ["指代必须标记", "「这个卡」「他们那边」标记而非删除",
                      "`cleaner.py::mark_pronouns`"]]))
    L.append("")

    L.append("## 3. 需求清洗与去重")
    L.append(_table(["步骤", "要求", "实现位置"],
                    [["去噪声", "只删登记在案的噪声词，删除动作必须留痕",
                      "`cleaner.py::NOISE_TOKENS` + `actions`"],
                     ["去重", "按结构化去重键（芯片+模型+首要问题类型）合并",
                      "`cleaner.py::_dedup_key`"],
                     ["保留最早", "主需求取最早到达的一条，其余记入 `merged_from`",
                      "`cleaner.py::deduplicate`"],
                     ["相似度仅作证据", "文本相似度写入日志但不参与判定",
                      "`cleaner.py::similarity`"]]))
    L.append("")
    L.append("### 为什么去重不用文本相似度判定")
    L.append("")
    L.append("实测本项目样本：同义重复对的 bigram 相似度最低 **0.130**，")
    L.append("不同诉求对的最高 **0.140** —— 两者区间重叠，**任何阈值都会误判**。")
    L.append("这不是调参问题，是方法选错了。结构化去重键的依据是产品语义：")
    L.append("同一张卡 + 同一个模型 + 同一类问题 = 同一个需求。")
    L.append("")

    L.append("## 4. 需求拆解与派发")
    L.append(_table(["步骤", "要求", "实现位置"],
                    [["严重度定级", "由问题类型映射，不做主观打分",
                      "`extractor.py::SEVERITY_BY_ISSUE`"],
                     ["多标签分类", "一条需求可命中多个问题类型，不压成单标签",
                      "`extractor.py::ISSUE_RULES`"],
                     ["状态推导", "字段不全 → 待澄清；P1 → In Progress",
                      "`doc_assembler.py::render_board`"],
                     ["下一动作", "每个状态必须对应明确的下一步，**不做进度汇报**",
                      "`render_board` 的 `next_action` 列"]]))
    L.append("")

    L.append("## 5. 闭环与沉淀")
    L.append(_table(["步骤", "要求", "实现位置"],
                    [["解决记录", "五要素齐全才入库，缺任一项拒收",
                      "`kb_builder.py::ENTRY_FIELDS` + `rejected`"],
                     ["根因未定位", "允许入库但须显式标注，**不编根因**",
                      "`kb_builder.py` 的 `cause` 处理"],
                     ["多维检索", "按芯片/模型/框架/问题类型检索",
                      "`kb_builder.py::search`"],
                     ["脚本生成", "待核实需求不生成脚本",
                      "`script_gen.py::generate_all` 的 skipped"]]))
    L.append("")
    L.append("---")
    L.append("生成命令：`python -m src.cli`")
    L.append("")
    return "\n".join(L)


def save(text: str, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def save_csv(rows, header, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def save_json(obj, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    return path
