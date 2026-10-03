# -*- coding: utf-8 -*-
"""端到端测试：产物完整性、免责声明、SOP 与实现对应。"""
import json
import os
import subprocess
import sys

from src import cli

ARTIFACTS = ["analysis_report.md", "board.md", "sop.md", "knowledge_base.json",
             "requirement_specs.md", "matrix.csv", "result.json"]


def _doc(name):
    with open(os.path.join(cli.OUTPUT_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


def _run():
    return cli.run()


def test_all_artifacts_generated():
    _run()
    for name in ARTIFACTS:
        p = os.path.join(cli.OUTPUT_DIR, name)
        assert os.path.isfile(p), "缺少产物 %s" % name
        assert os.path.getsize(p) > 0, "产物为空 %s" % name


def test_scripts_written_to_output():
    res = _run()
    assert res["scripts"], "应至少生成一个测试脚本"
    for s in res["scripts"]:
        p = os.path.join(cli.SCRIPT_DIR, s["filename"])
        assert os.path.isfile(p), "缺少脚本 %s" % s["filename"]


def test_report_declares_self_built_data():
    cli.run()
    assert "自拟" in _doc("analysis_report.md"), "报告缺自拟声明"
    assert "非真实业务数据" in _doc("analysis_report.md"), "报告缺免责声明"
    specs = _doc("requirement_specs.md")
    assert "自拟" in specs and "非真实业务数据" in specs, \
        "需求单缺自拟声明或免责声明"


def test_report_states_no_real_hardware_test():
    cli.run()
    rep = _doc("analysis_report.md")
    assert "未做真卡实测" in rep, "必须声明未做真卡实测"


def test_sop_rules_reference_actual_implementation():
    """核心纪律：SOP 里每条规则都要指向真实存在的实现位置。"""
    cli.run()
    sop = _doc("sop.md")
    for ref in ("cleaner.py::", "extractor.py::", "kb_builder.py::",
                "script_gen.py::", "doc_assembler.py::"):
        assert ref in sop, "SOP 缺少实现引用：%s" % ref
    # 引用的模块必须真实存在
    for line in sop.splitlines():
        if ".py::" in line:
            import re as _re
            m2 = _re.search(r"([A-Za-z_]+\.py)::", line)
            assert m2, "无法解析 SOP 中的实现引用：%s" % line
            assert os.path.isfile(os.path.join(cli.ROOT, "src", m2.group(1))), \
                "SOP 引用了不存在的模块：%s" % m2.group(1)


def test_board_has_status_and_next_action():
    cli.run()
    b = _doc("board.md")
    assert "下一动作" in b
    assert "待澄清" in b, "字段不全的需求应停在待澄清"
    assert "风险同步" in b


def test_requirement_specs_contain_provenance():
    cli.run()
    specs = _doc("requirement_specs.md")
    assert "原文出处" in specs
    assert "样本自带" in specs, "应区分原文抽取与样本自带上下文"
    assert "必填字段完整率" in specs


def test_knowledge_base_only_contains_closed_entries():
    res = cli.run()
    kb = json.load(open(os.path.join(cli.OUTPUT_DIR, "knowledge_base.json"),
                       encoding="utf-8"))
    for e in kb["entries"]:
        assert e["solution"] and e["verification"], "入库条目必须闭环"
        assert not e.get("rejected")


def test_search_command_works(capsys):
    assert cli.main(["--search", "chip_model", "TX8"]) == 0
    out = capsys.readouterr().out
    assert "维度 chip_model = TX8" in out


def test_search_with_bad_dimension_returns_nonzero():
    assert cli.main(["--search", "bad_dim", "x"]) == 1


def test_generation_is_reproducible():
    a = cli.run()
    b = cli.run()
    assert a["pipeline"]["unique_count"] == b["pipeline"]["unique_count"]
    assert a["pipeline"]["avg_completeness"] == b["pipeline"]["avg_completeness"]
    assert [e["verdict"] for e in a["matrix"]["entries"]] == \
           [e["verdict"] for e in b["matrix"]["entries"]]


def test_result_json_serializable():
    cli.run()
    with open(os.path.join(cli.OUTPUT_DIR, "result.json"), encoding="utf-8") as f:
        json.load(f)


def test_no_sensitive_fields_in_outputs():
    cli.run()
    banned = ["合同金额", "客户名称", "内部报价", "账号密码", "有限公司"]
    for name in ("analysis_report.md", "board.md", "sop.md", "requirement_specs.md"):
        doc = _doc(name)
        for b in banned:
            assert b not in doc, "%s 出现敏感字段 %s" % (name, b)


def test_cli_verify_runs_generated_script():
    r = subprocess.run([sys.executable, "-m", "src.cli", "--verify"],
                       cwd=cli.ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-300:]
    assert "exit=0" in r.stdout, "生成的脚本未能在 CPU 上跑通"
