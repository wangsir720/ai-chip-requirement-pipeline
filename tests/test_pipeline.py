# -*- coding: utf-8 -*-
"""cleaner / extractor 测试 —— 重点验证「清洗留痕」与「不猜字段」。"""
import json
import os

import pytest

from src.cleaner import (CleaningError, clean_record, deduplicate, load_raw_requests,
                         normalize, run_pipeline, similarity, strip_noise)
from src.extractor import NOT_FOUND, ExtractionError, extract, load_catalogs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw_requests", "multi_source_demo.json")
CATALOGS = load_catalogs(ROOT)


def _raw():
    return load_raw_requests(RAW)


# ---------------- normalize / noise ----------------

def test_normalize_converts_fullwidth():
    assert normalize("订单，OK。") == "订单,OK."


def test_normalize_rejects_non_string():
    with pytest.raises(CleaningError):
        normalize(None)


def test_strip_noise_returns_what_was_removed():
    text, removed = strip_noise("这个肯定不行吧。。。麻烦看看")
    assert "吧" in removed and "麻烦看看" in removed
    assert "吧" not in text and "麻烦看看" not in text


def test_cleaning_actions_are_always_logged():
    r = clean_record({"id": "X1", "source": "email", "text": "客户说这个不行吧"})
    actions = {a["action"] for a in r["actions"]}
    assert actions == {"normalize", "strip_noise", "mark_pronouns"}
    for a in r["actions"]:
        assert a["detail"], "清洗动作必须写明做了什么"


def test_pronouns_are_marked_not_deleted():
    r = clean_record({"id": "X2", "source": "email", "text": "他们那边说这个卡不行"})
    assert r["pronouns"], "指代必须被标记"
    assert "[指代]" in r["clean_text"], "指代应保留标记而非删除"
    assert "他们那边" in r["raw_text"]


def test_missing_required_field_raises():
    with pytest.raises(CleaningError):
        clean_record({"id": "X3", "source": "email"})


def test_similarity_is_symmetric_and_bounded():
    a = "TX8 上 Qwen2.5-14B 推理显存不足"
    b = "TX8 跑 Qwen2.5-14B 显存不够"
    s1, s2 = similarity(a, b), similarity(b, a)
    assert s1 == s2, "相似度必须对称"
    assert 0.0 <= s1 <= 1.0


def test_similarity_of_empty_is_zero():
    assert similarity("", "abc") == 0.0


# ---------------- dedup ----------------

def test_dedup_merges_same_structured_key():
    recs = [
        {"id": "A", "received_at": "2026-01-01", "source": "jira", "clean_text": "TX8 跑 Qwen 显存爆",
         "chip_model": "TX8", "model_name": "Qwen2.5-14B", "issue_labels": ["oom"]},
        {"id": "B", "received_at": "2026-01-02", "source": "email", "clean_text": "TX8 Qwen 显存不够",
         "chip_model": "TX8", "model_name": "Qwen2.5-14B", "issue_labels": ["oom"]},
    ]
    kept, log = deduplicate(recs)
    assert len(kept) == 1 and kept[0]["id"] == "A", "应保留最早到达的一条"
    assert kept[0]["merged_from"][0]["id"] == "B"
    assert log[0]["dedup_key"] == "TX8|Qwen2.5-14B|oom"


def test_dedup_keeps_different_primary_issue():
    recs = [
        {"id": "A", "received_at": "2026-01-01", "source": "jira", "clean_text": "x",
         "chip_model": "TX8", "model_name": "Qwen2.5-14B", "issue_labels": ["oom"]},
        {"id": "B", "received_at": "2026-01-02", "source": "jira", "clean_text": "y",
         "chip_model": "TX8", "model_name": "Qwen2.5-14B", "issue_labels": ["finetune_question"]},
    ]
    kept, _ = deduplicate(recs)
    assert len(kept) == 2, "首要问题类型不同则不应合并"


def test_dedup_ignores_framework_difference():
    recs = [
        {"id": "A", "received_at": "2026-01-01", "source": "jira", "clean_text": "x",
         "chip_model": "TX8", "model_name": "Qwen2.5-14B", "issue_labels": ["oom"]},
        {"id": "B", "received_at": "2026-01-02", "source": "jira", "clean_text": "y",
         "chip_model": "TX8", "model_name": "Qwen2.5-14B", "issue_labels": ["oom"]},
    ]
    kept, _ = deduplicate(recs)
    assert len(kept) == 1


def test_dedup_empty_raises():
    with pytest.raises(CleaningError):
        deduplicate([])


# ---------------- extractor ----------------

def test_extracted_fields_have_provenance():
    c = clean_record(_raw()[1])
    f = extract(c, *CATALOGS)
    for name in ("chip_model", "model_name"):
        ev = f[name]["evidence"]
        assert ev, "%s 缺出处" % name
        assert ev["quote"], "%s 出处缺原文片段" % name


def test_missing_field_is_not_guessed():
    rec = {"id": "X", "source": "ticket", "text": "客户问下批次的交付时间"}
    c = clean_record(rec)
    f = extract(c, *CATALOGS)
    assert f["chip_model"]["value"] == NOT_FOUND, "抽不到必须填未提取到"
    assert f["model_name"]["value"] == NOT_FOUND
    assert f["chip_model"]["evidence"] is None


def test_tx8_does_not_false_match_tx81():
    rec = {"id": "X", "source": "ticket", "text": "TX81 模组安装有问题"}
    c = clean_record(rec)
    f = extract(c, *CATALOGS)
    assert f["chip_model"]["value"] == "TX81", "TX81 不应被 TX8 抢匹配"


def test_completeness_is_measurable():
    c = clean_record(_raw()[1])
    f = extract(c, *CATALOGS)
    q = f["_quality"]
    assert q["required_total"] == 5
    assert 0.0 <= q["completeness"] <= 1.0
    assert len(q["missing_fields"]) == 5 - q["required_filled"]


def test_issue_is_multilabel():
    rec = {"id": "X", "source": "email",
           "text": "TX8 跑 Qwen2.5-14B 显存不够，能不能支持 70B，要加几张卡"}
    f = extract(clean_record(rec), *CATALOGS)
    labels = f["issue_type"]["multi_label"]
    assert "oom" in labels and "multi_card_question" in labels, \
        "一条需求应可命中多个问题类型，实际为 %s" % labels


def test_severity_derived_from_issue_not_subjective():
    rec = {"id": "X", "source": "ticket", "text": "TX8 显存爆了"}
    f = extract(clean_record(rec), *CATALOGS)
    assert f["severity"]["value"] == "P1"
    assert f["severity"]["basis"], "严重度必须写明依据"


def test_customer_industry_marked_as_context_not_extracted():
    rec = {"id": "X", "source": "jira", "text": "显存不够", "customer_industry": "金融"}
    f = extract(clean_record(rec), *CATALOGS)
    ev = f["customer_industry"]["evidence"]
    assert "样本自带" in ev["matched"], "须标明该字段来自样本上下文而非原文抽取"
    assert ev["start"] == 0 and ev["end"] == 0


def test_empty_clean_text_raises():
    with pytest.raises(ExtractionError):
        extract({"id": "X", "clean_text": ""}, *CATALOGS)


def test_pipeline_runs_end_to_end():
    r = run_pipeline(_raw(), extract, CATALOGS)
    assert r["raw_count"] == 15
    assert r["unique_count"] < r["raw_count"], "应发生去重"
    assert r["duplicate_removed"] == r["raw_count"] - r["unique_count"]
    assert 0 < r["avg_completeness"] <= 1.0
    for u in r["unique"]:
        assert u["fields"]["_quality"]["completeness"] == u["completeness"]


def test_pipeline_without_extractor_skips_dedup():
    r = run_pipeline(_raw())
    assert r["duplicate_removed"] == 0
    assert "未提供抽取器" in r["note"]


def test_sample_data_has_no_sensitive_fields():
    raw = json.load(open(RAW, encoding="utf-8"))
    text = " ".join(r["text"] for r in raw["requests"])
    for banned in ("客户名称", "合同金额", "内部报价", "账号密码"):
        assert banned not in text
    # 样本中不应出现具体公司名（除芯片型号所属公司与模型名）
    for banned in ("有限公司", "股份"):
        assert banned not in text
