#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""命令行入口：原始需求 -> 需求单 / 分析报告 / 看板 / SOP / 知识库 / 测试脚本。

    python -m src.cli              # 全流程，输出到 output/
    python -m src.cli --search chip_model TX8    # 知识库检索
    python -m src.cli --verify     # 跑一遍生成的测试脚本（CPU 模拟模式）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from .cleaner import load_raw_requests, run_pipeline
from .doc_assembler import (render_analysis_report, render_board, render_requirement_spec,
                            render_sop, save, save_csv, save_json)
from .extractor import extract, load_catalogs
from .kb_builder import build_from_requirements, search
from .script_gen import generate_all
from .validator import build_matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(ROOT, "output")
RAW_PATH = os.path.join(ROOT, "data", "raw_requests", "multi_source_demo.json")
SCRIPT_DIR = os.path.join(OUTPUT_DIR, "scripts")

ARTIFACTS = ["analysis_report.md", "board.md", "sop.md", "knowledge_base.json",
             "requirement_specs.md", "matrix.csv", "result.json"]

# 解决记录：自拟的「已闭环」问题。**待核实需求不在此列** —— 不进知识库。
RESOLUTIONS = {
    "RAW-001": {
        "cause": "batch=64 时 KV Cache 与激活值叠加超出单卡 32 GiB 显存，"
                 "根因定位方式：对比 batch=32/64 的显存占用曲线",
        "solution": "将推理批量降至 32；或启用 PagedAttention 类分页机制降低碎片；"
                    "若客户确需 64 批量，按 2 卡张量并行处理",
        "verification": "跑 output/scripts/verify_RAW-001.py，"
                        "断言 batch=64 时不出现 OOM 且吞吐不低于 batch=32 的 90%",
    },
    "RAW-003": {
        "cause": "根因未定位。已排除：显存（非 OOM）、芯片型号（其他模型正常）。"
                 "待研发确认是否为目标算子在 PyTorch 2.1 后端缺失",
        "solution": "临时回退至 PyTorch 1.13 验证业务；"
                    "同时向研发提交算子支持矩阵需求，等待确认",
        "verification": "对比 1.13 与 2.1 下同一模型的 GPU 利用率与吞吐；"
                        "回退方案下利用率应恢复至 60% 以上",
    },
    "RAW-008": {
        "cause": "文档按产品线组织而非按芯片型号组织，TX81 模组与 TX5 芯片的"
                 "驱动安装步骤不同但共用一份文档，导致客户按 TX5 步骤操作 TX81 失败",
        "solution": "按芯片型号拆分安装文档；文档首页增加型号对照表",
        "verification": "由未参与编写的同事按新文档在干净环境完成一次安装，"
                        "全程无需外部协助即视为通过",
    },
}


def _pipelines():
    catalogs = load_catalogs(ROOT)
    records = load_raw_requests(RAW_PATH)
    pipeline = run_pipeline(records, extract, catalogs)
    matrix = build_matrix(pipeline["unique"], *catalogs)
    kb = build_from_requirements(pipeline["unique"], RESOLUTIONS)
    scripts, skipped = generate_all(matrix["entries"])
    return pipeline, matrix, kb, scripts, skipped


def run(verify: bool = False) -> dict:
    pipeline, matrix, kb, scripts, skipped = _pipelines()

    # 需求单：每条一张，合并为一份文档
    specs = [render_requirement_spec(r, r["fields"]) for r in pipeline["unique"]]
    save("# 结构化需求单\n\n"
         "> 共 %d 张，每张字段带原文出处。\n"
         "> **需求样本为自拟、非真实业务数据**；芯片与模型信息取自公开资料。\n\n"
         "---\n\n%s" % (len(specs), "\n---\n\n".join(specs)),
         os.path.join(OUTPUT_DIR, "requirement_specs.md"))
    save(render_analysis_report(pipeline, matrix, kb),
         os.path.join(OUTPUT_DIR, "analysis_report.md"))
    save(render_board(pipeline, matrix), os.path.join(OUTPUT_DIR, "board.md"))
    save(render_sop(pipeline), os.path.join(OUTPUT_DIR, "sop.md"))
    save_json(kb, os.path.join(OUTPUT_DIR, "knowledge_base.json"))
    save_csv(
        [[e["requirement_id"], e["chip_model"], e["model_name"], e["framework"],
          e["verdict_label"], e.get("severity"), e["reason"]]
         for e in matrix["entries"]],
        ["需求单号", "芯片型号", "模型名称", "框架", "适配判定", "严重度", "判定理由"],
        os.path.join(OUTPUT_DIR, "matrix.csv"))

    for s in scripts:
        save(s["code"], os.path.join(SCRIPT_DIR, s["filename"]))

    save_json({
        "pipeline": {k: v for k, v in pipeline.items() if k != "unique"},
        "unique_requirements": [
            dict({k: v for k, v in r.items() if k != "fields"},
                 fields={fk: fv for fk, fv in r["fields"].items() if fk != "raw_text"})
            for r in pipeline["unique"]
        ],
        "matrix": matrix,
        "kb": {"entries": kb["entries"], "rejected": kb["rejected"],
               "pending": kb["pending"], "index": kb["index"]},
        "scripts": [{k: v for k, v in s.items() if k != "code"} for s in scripts],
        "scripts_skipped": skipped,
    }, os.path.join(OUTPUT_DIR, "result.json"))

    if verify:
        _verify_scripts(scripts)
    return {"pipeline": pipeline, "matrix": matrix, "kb": kb,
            "scripts": scripts, "scripts_skipped": skipped}


def _verify_scripts(scripts: list[dict]) -> None:
    """实际运行一个生成的脚本，确认 CPU 模拟模式真的能跑通。"""
    if not scripts:
        print("无可运行的脚本（全部需求待核实）")
        return
    sample = scripts[0]
    path = os.path.join(SCRIPT_DIR, sample["filename"])
    print("运行样例脚本：%s" % sample["filename"])
    r = subprocess.run([sys.executable, path, "--device", "cpu"],
                       capture_output=True, text=True, timeout=60)
    print("exit=%d" % r.returncode)
    print(r.stdout.strip()[:400])
    if r.stderr.strip():
        print("STDERR:", r.stderr.strip()[:300])


def _print_summary(res: dict) -> None:
    p, m, kb = res["pipeline"], res["matrix"], res["kb"]
    print("原始需求 %d 条 → 唯一 %d 条（去重 %d 条，%.1f%%）"
          % (p["raw_count"], p["unique_count"], p["duplicate_removed"],
             p["duplicate_rate"] * 100))
    print("必填字段平均完整率 %.0f%%" % (p["avg_completeness"] * 100))
    print("适配判定：%s" % " / ".join("%s %d" % (k, v) for k, v in m["verdict_counts"].items()))
    print("知识库入库 %d 条，拒收 %d 条，待解决 %d 条"
          % (kb["index"]["entry_count"], len(kb["rejected"]), len(kb["pending"])))
    print("测试脚本 %d 个，跳过 %d 个" % (len(res["scripts"]), len(res["scripts_skipped"])))
    print("已生成：output/{%s}" % ", ".join(ARTIFACTS))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="src.cli", description="AI 算力卡需求治理与适配验证管道")
    ap.add_argument("--search", nargs=2, metavar=("DIM", "VALUE"),
                    help="知识库检索，维度为 chip_model/model_name/framework/issue")
    ap.add_argument("--verify", action="store_true", help="实际运行一个生成的测试脚本")
    args = ap.parse_args(argv)

    if args.search:
        try:
            _, _, kb, _, _ = _pipelines()
            r = search(kb["entries"], args.search[0], args.search[1])
        except Exception as e:
            print("检索失败：%s: %s" % (type(e).__name__, e), file=sys.stderr)
            return 1
        print("维度 %s = %s，命中 %d 条" % (r["dimension"], r["value"], r["hit_count"]))
        for h in r["hits"]:
            print("  [%s] %s" % (h["linked_requirement"], h["phenomenon"][:70]))
            print("      原因：%s" % h["cause"][:70])
        return 0

    try:
        res = run(verify=args.verify)
    except Exception as e:
        print("执行失败：%s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1
    _print_summary(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
