"""由 ai-chip-requirement-pipeline 自动生成的验证脚本骨架

需求单号：RAW-014

【测什么】不推荐 —— 模型 Qwen2.5-32B 权重下界 48.0 GiB（含 1.15 运行时余量）超过单卡显存 32.0 GiB，单卡跑不动；至少需 2 卡（张量/流水并行，切分方式须研发确认）
【期望阈值】单卡跑不动，需先确定多卡切分方式再定阈值；切分方式影响通信开销，阈值无法在此阶段给出
【失败怎么判】多卡切分前不设阈值；切分确定后按单卡口径重测
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
MODEL = "Qwen2.5-32B"      # 待测模型，需替换为实际模型路径或名称
DEVICE = "cpu"            # cpu（模拟模式） / cuda（真实硬件）
BATCH = 1           # 批量大小
SEQ = 512             # 序列长度 / tokens
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
            "reason": "阈值 %s 已填写，但判定规则须按客户实际 SLO 定义" % THRESHOLD}


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
