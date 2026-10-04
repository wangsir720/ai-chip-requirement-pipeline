# -*- coding: utf-8 -*-
"""测试脚本生成器：把适配判定转成可执行的验证脚本骨架。

把适配判定转成可执行的验证脚本骨架。

## 为什么生成的是「骨架」而不是可直接投产的脚本

三个理由，都是硬理由不是谦虚：

1. **阈值必须按客户实际模型标定** —— 本项目没有客户的模型与数据，
   写死阈值等于给出一个假的基准。
2. **判定为 `unknown` / `needs_verification` 的需求本就需先核实** ——
   脚本先跑起来，结论后填。
3. **本项目无算力卡** —— 生成的脚本默认 CPU 模拟模式，
   真实硬件上需替换设备选择与阈值。

生成的脚本包含：测什么、期望阈值、失败怎么判、怎么复现。
这三项是脚本可用的底线：逻辑清晰、性能考量、失败判据。

## 为什么用 `%` 格式化而不是 `str.format`

模板正文是 Python 代码，天然含大量 `{}`（字典字面量）。
`str.format` 要求把每个 `{` 写成 `{{`，漏一个就抛
`ValueError: Single '}' encountered`，且报错不指向具体位置。
改用 `%` 格式化后，模板里的 `{}` 无需任何转义。
"""
from __future__ import annotations

import re

# 生成脚本里允许出现的占位符；出现其他占位说明模板有 bug
_ALLOWED_PLACEHOLDERS = {"MODEL", "DEVICE", "BATCH", "SEQ", "THRESHOLD"}

_SCRIPT_TEMPLATE = '''"""由 ai-chip-requirement-pipeline 自动生成的验证脚本骨架

需求单号：%(req_id)s

【测什么】%(verdict_label)s —— %(reason)s
【期望阈值】%(threshold_note)s
【失败怎么判】%(failure_note)s
【CPU 模拟模式】本脚本默认 --device cpu，可在无算力卡环境完整复现流程。
     真实硬件上用 --device cuda 替换；注意阈值须按实际模型重新标定。
【不做什么】本脚本不判定产品是否合格，只产出可复核的测量数据。
     最终结论由研发与产品线共同确认。
"""
import argparse
import json
import sys
import time

# ---- 以下为待标定参数（本项目无客户模型，阈值一律留 None，不填估计值）----
MODEL = "%(model)s"      # 待测模型，需替换为实际模型路径或名称
DEVICE = "cpu"            # cpu（模拟模式） / cuda（真实硬件）
BATCH = %(batch)d           # 批量大小
SEQ = %(seq)d             # 序列长度 / tokens
THRESHOLD = None          # 期望阈值，须按实际模型标定后替换


def measure(batch, seq):
    """测量给定批量与序列长度下的吞吐与延迟。

    模拟模式下返回固定值并显式标注 —— 模拟数据绝不能被当成实测结论。
    """
    t0 = time.time()
    if DEVICE == "cpu":
        payload = {"mode": "simulated", "batch": batch, "seq": seq}
    else:
        payload = {"mode": "measured", "batch": batch, "seq": seq}
    payload["elapsed_s"] = round(time.time() - t0, 4)
    return payload


def check(result):
    """按阈值判定通过与否。阈值未标定时不判定，只报未标定。"""
    if THRESHOLD is None:
        return {"verdict": "未标定",
                "reason": "THRESHOLD 为 None —— 阈值须按实际模型标定后判定"}
    return {"verdict": "待判定",
            "reason": "阈值 %%s 已填写，但判定规则须按客户实际 SLO 定义" %% THRESHOLD}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default=DEVICE, choices=["cpu", "cuda"])
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--seq", type=int, default=SEQ)
    args = ap.parse_args()

    result = measure(args.batch, args.seq)
    result["check"] = check(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


class ScriptGenError(Exception):
    pass


def _safe_name(text: str) -> str:
    """把任意文本转成合法文件名。"""
    s = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", text or "unknown")
    return s.strip("_") or "unknown"


def threshold_note_for(verdict: str) -> str:
    """按判定档给出阈值标定建议。**不给具体数值** —— 无客户模型，数值只能是编的。"""
    if verdict == "supported":
        return ("显存余量充足，阈值建议以客户实际 SLO 为准："
                "定 P95 端到端延迟上限与最小吞吐。数值须按客户模型实测标定")
    if verdict == "needs_verification":
        return ("显存余量或算子行为存在不确定性，阈值须分两轮标定："
                "第一轮测客户真实上下文与批量下的显存与吞吐，"
                "第二轮据此设定 SLO 后再判定")
    if verdict == "not_recommended":
        return ("单卡跑不动，需先确定多卡切分方式再定阈值；"
                "切分方式影响通信开销，阈值无法在此阶段给出")
    return "需求字段不全，**阈值无从标定** —— 先补齐需求单字段"


def failure_note_for(verdict: str) -> str:
    if verdict == "supported":
        return ("低于吞吐下限或高于延迟上限即判失败；"
                "同时观察显存占用是否越界（越界说明并发假设不成立）")
    if verdict == "needs_verification":
        return ("首轮仅产出测量数据不作判定；若实测出现 OOM 或吞吐骤降，"
                "按「算子未适配」方向升级排查")
    if verdict == "not_recommended":
        return "多卡切分前不设阈值；切分确定后按单卡口径重测"
    return "字段不全，脚本仅用于验证环境可用性，不产出性能结论"


def generate(entry: dict, batch: int = 1, seq: int = 512) -> dict:
    """为一条需求生成测试脚本。"""
    for k in ("requirement_id", "verdict", "chip_model", "model_name"):
        if k not in entry:
            raise ScriptGenError("判定结果缺少字段 %s，无法生成脚本" % k)

    body = _SCRIPT_TEMPLATE % {
        "req_id": entry["requirement_id"],
        "verdict_label": entry.get("verdict_label", entry["verdict"]),
        "reason": entry.get("reason", "-").replace("%", "%%"),
        "threshold_note": threshold_note_for(entry["verdict"]),
        "failure_note": failure_note_for(entry["verdict"]),
        "model": entry["model_name"],
        "batch": batch,
        "seq": seq,
    }

    # 生成后自检：占位符必须与白名单一致
    found = set(re.findall(r"^([A-Z_]+) =", body, re.M))
    unknown = found - _ALLOWED_PLACEHOLDERS
    if unknown:
        raise ScriptGenError("生成的脚本含未登记的占位符：%s" % ", ".join(sorted(unknown)))

    return {
        "requirement_id": entry["requirement_id"],
        "filename": "verify_%s.py" % _safe_name(entry["requirement_id"]),
        "verdict": entry["verdict"],
        "code": body,
        "runnable_on_cpu": True,
        "threshold_calibrated": False,
        "calibration_note": "THRESHOLD 为 None —— 须按客户实际模型标定。"
                            "本项目无客户模型，不给估计值。",
        "assumption_refs": ["B-01", "B-03"],
    }


def generate_all(entries: list[dict], batch: int = 1,
                 seq: int = 512) -> tuple[list[dict], list[dict]]:
    """只对可执行的判定档生成脚本。

    `unknown` 档不生成 —— 字段不全时生成一个测不了的东西，比不生成更糟。
    """
    out, skipped = [], []
    for e in entries:
        if e["verdict"] == "unknown":
            skipped.append({
                "requirement_id": e["requirement_id"],
                "reason": "判定为待人工核实，字段不全时不生成脚本 —— "
                          "生成一个测不了的东西比不生成更糟",
            })
            continue
        out.append(generate(e, batch, seq))
    return out, skipped
