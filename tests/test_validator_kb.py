# -*- coding: utf-8 -*-
"""validator / script_gen / kb_builder 测试。"""
import os

import pytest

from src.cleaner import clean_record, load_raw_requests, run_pipeline
from src.extractor import extract, load_catalogs
from src.kb_builder import (ENTRY_FIELDS, KbError, build_entry, build_from_requirements,
                            index, search)
from src.script_gen import ScriptGenError, generate, generate_all, threshold_note_for
from src.validator import (PARALLEL_STRATEGIES, ValidationError, build_matrix, judge)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw_requests", "multi_source_demo.json")
CATALOGS = load_catalogs(ROOT)
CHIPS, MODELS, STACKS = CATALOGS


def _fields(chip, model, framework="未提取到"):
    """构造一个已抽取的字段字典（绕过抽取器，专注判定逻辑）。"""
    return {
        "chip_model": {"value": chip, "evidence": None},
        "model_name": {"value": model, "evidence": None},
        "framework": {"value": framework, "evidence": None},
        "issue_type": {"value": "test", "multi_label": ["test"], "evidence": None},
        "severity": {"value": "P2", "evidence": None, "basis": "test"},
        "customer_industry": {"value": "未提取到", "evidence": None},
        "source_channel": {"value": "test", "evidence": None},
        "raw_text": {"value": "", "evidence": None},
        "_quality": {"required_total": 5, "required_filled": 5, "missing_fields": [],
                     "completeness": 1.0, "assumption_refs": []},
    }


# ---------------- validator ----------------

def test_small_model_on_32gb_is_supported():
    v = judge(_fields("TX8", "Qwen2.5-7B"), CHIPS, MODELS, STACKS)
    assert v["verdict"] == "supported"
    assert v["evidence"], "判定必须带证据链"


def test_large_model_is_not_recommended_with_multicard():
    v = judge(_fields("TX8", "DeepSeek-V3"), CHIPS, MODELS, STACKS)
    assert v["verdict"] == "not_recommended"
    assert v["multi_card"]["cards_needed"] > 1
    assert v["multi_card"]["strategies"], "须列出切分候选"
    assert "研发" in v["multi_card"]["decision_owner"], "不代替研发决策"


def test_tight_headroom_needs_verification():
    v = judge(_fields("TX8", "Qwen2.5-14B"), CHIPS, MODELS, STACKS)
    assert v["verdict"] == "needs_verification"
    assert "实测" in v["reason"]


def test_missing_fields_yield_unknown():
    v = judge(_fields("未提取到", "未提取到"), CHIPS, MODELS, STACKS)
    assert v["verdict"] == "unknown"
    assert "缺失" in v["reason"]


def test_unregistered_chip_yields_unknown_not_guess():
    v = judge(_fields("TX99", "Qwen2.5-7B"), CHIPS, MODELS, STACKS)
    assert v["verdict"] == "unknown"
    assert "未收录" in v["reason"]


def test_chip_without_public_vram_yields_unknown():
    """REX81 的公开资料未查到显存 —— 应判待核实，不猜。"""
    v = judge(_fields("REX81", "Qwen2.5-32B"), CHIPS, MODELS, STACKS)
    assert v["verdict"] == "unknown"
    assert "未查到" in v["reason"]


def test_unverified_fallback_never_yields_not_recommended():
    """B-02 责任对等原则：unverified 来源只能要求实测，不能判不推荐。"""
    v = judge(_fields("TX8", "YOLOv8n-detect", "PyTorch 2.1"), CHIPS, MODELS, STACKS)
    assert v["verdict"] != "not_recommended", \
        "unverified 来源不得用于判不推荐"
    detail = " ".join(e["detail"] for e in v["evidence"])
    assert "unverified" in detail, "证据链须显式标出该来源为 unverified"
    assert "不据此判不推荐" in v["reason"], "须在理由中写明责任边界"


def test_matrix_covers_four_verdicts():
    r = run_pipeline(load_raw_requests(RAW), extract, CATALOGS)
    m = build_matrix(r["unique"], *CATALOGS)
    assert m["verdict_counts"], "应有判定分布"
    assert m["total"] == r["unique_count"]
    for e in m["entries"]:
        assert e["verdict"] in ("supported", "needs_verification",
                                "not_recommended", "unknown")


def test_matrix_sorted_worst_first():
    r = run_pipeline(load_raw_requests(RAW), extract, CATALOGS)
    m = build_matrix(r["unique"], *CATALOGS)
    order = {"supported": 0, "needs_verification": 1, "not_recommended": 2, "unknown": 3}
    seq = [order[e["verdict"]] for e in m["entries"]]
    assert seq == sorted(seq), "最优判定应排在最前"


def test_matrix_requires_extracted_fields():
    with pytest.raises(ValidationError):
        build_matrix([{"id": "X"}], *CATALOGS)


def test_parallel_strategies_not_empty():
    assert len(PARALLEL_STRATEGIES) >= 3
    for n, d in PARALLEL_STRATEGIES:
        assert n and d


# ---------------- script_gen ----------------

def test_generated_script_runs_on_cpu(tmp_path):
    v = judge(_fields("TX8", "Qwen2.5-7B"), CHIPS, MODELS, STACKS)
    v["requirement_id"] = "RAW-TEST"
    s = generate(v)
    path = tmp_path / s["filename"]
    path.write_text(s["code"], encoding="utf-8")
    import subprocess
    import sys as _sys
    r = subprocess.run([_sys.executable, str(path), "--device", "cpu"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "生成的脚本必须能在 CPU 上跑通"
    assert '"mode": "simulated"' in r.stdout


def test_threshold_is_never_fabricated():
    import re
    for verdict in ("supported", "needs_verification", "not_recommended", "unknown"):
        note = threshold_note_for(verdict)
        # 无论哪档，都必须说明阈值从哪来或为何给不出
        assert any(k in note for k in ("标定", "无从标定", "无法在此阶段给出")), \
            "阈值说明未交代来源：%s" % note
        # 不得出现具体阈值数值
        assert not re.search(r"\d+\s*(ms|GB/s|tps)", note), \
            "无客户模型时不得给出具体阈值数值：%s" % note


def test_script_contains_all_three_answers():
    v = judge(_fields("TX8", "Qwen2.5-7B"), CHIPS, MODELS, STACKS)
    v["requirement_id"] = "RAW-T"
    code = generate(v)["code"]
    assert "【测什么】" in code
    assert "【期望阈值】" in code
    assert "【失败怎么判】" in code
    assert "THRESHOLD = None" in code, "阈值必须留空而非填估计值"


def test_unknown_verdict_gets_no_script():
    entries = [{"requirement_id": "RAW-X", "verdict": "unknown", "chip_model": "未提取到",
                "model_name": "未提取到"}]
    scripts, skipped = generate_all(entries)
    assert scripts == [] and len(skipped) == 1


def test_missing_key_raises():
    with pytest.raises(ScriptGenError):
        generate({"requirement_id": "X", "verdict": "supported"})


# ---------------- kb_builder ----------------

def _req(rid, text, chip="TX8", model="Qwen2.5-7B", labels=None):
    rec = clean_record({"id": rid, "source": "jira", "text": text})
    f = extract(rec, *CATALOGS)
    rec["fields"] = f
    rec["chip_model"] = f["chip_model"]["value"]
    rec["model_name"] = f["model_name"]["value"]
    rec["issue_labels"] = f["issue_type"]["multi_label"]
    return rec


def test_entry_requires_solution_and_verification():
    e = build_entry(_req("R1", "TX8 显存不够"), "根因未定位", "", "")
    assert e["rejected"], "缺解决步骤应拒收"
    assert "解决步骤" in e["rejected"]
    e2 = build_entry(_req("R1", "TX8 显存不够"), "根因未定位", "降批量", "")
    assert "验证方式" in e2["rejected"]


def test_unresolved_cause_is_allowed_but_flagged():
    e = build_entry(_req("R1", "TX8 显存不够"), "", "降批量", "跑脚本确认")
    assert not e["rejected"]
    assert e["cause"] == "根因未定位"
    assert "cause" in e["partial"], "根因未定位须显式标注"


def test_entry_has_all_five_fields():
    e = build_entry(_req("R1", "TX8 显存不够"), "批量过大", "降批量", "跑脚本确认")
    for f in ENTRY_FIELDS:
        assert e[f], "闭环字段缺失：%s" % f
    assert e["completeness"] == 1.0


def test_search_by_each_dimension():
    entries = [build_entry(_req("R1", "TX8 跑 Qwen2.5-7B 显存不够"), "批量过大",
                           "降批量", "跑脚本确认")]
    for dim, val in (("chip_model", "TX8"), ("model_name", "Qwen2.5-7B"),
                     ("issue", "oom")):
        r = search(entries, dim, val)
        assert r["hit_count"] == 1, "%s=%s 未命中" % (dim, val)


def test_search_rejects_bad_dimension():
    entries = [build_entry(_req("R1", "TX8 显存不够"), "a", "b", "c")]
    with pytest.raises(KbError):
        search(entries, "wrong_dim", "x")
    with pytest.raises(KbError):
        search(entries, "chip_model", "  ")


def test_pending_requirements_do_not_enter_kb():
    reqs = [_req("R1", "TX8 显存不够"), _req("R2", "TX8 显存不够")]
    kb = build_from_requirements(reqs, {"R1": {"cause": "a", "solution": "b",
                                                "verification": "c"}})
    assert kb["index"]["entry_count"] == 1
    assert len(kb["pending"]) == 1, "未提供解决记录的需求须列为待解决"


def test_kb_empty_requirements_raise():
    with pytest.raises(KbError):
        build_from_requirements([], {})


def test_index_skips_rejected_entries():
    entries = [build_entry(_req("R1", "TX8 显存不够"), "a", "", "c")]  # 拒收
    idx = index(entries)
    assert idx["entry_count"] == 0 and idx["rejected_count"] == 1
