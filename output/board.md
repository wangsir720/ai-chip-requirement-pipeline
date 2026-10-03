# 需求流转状态看板

> 状态流转：Backlog → 待澄清 → 已拆解 → In Progress → 待验证 → Done

> 状态由严重度与适配判定共同推导：P1 且判定非「待人工核实」→ 可直接进 In Progress；字段不全 → 停在「待澄清」。**状态不是进度汇报，是下一动作。**

| 需求单号 | 芯片 | 模型 | 严重度 | 适配判定 | 状态 | 下一动作 |
|---|---|---|---|---|---|---|
| RAW-001 | TX8 | Qwen2.5-14B | P1 | 需实测验证 | 待澄清 | 向需求提出方补齐：framework |
| RAW-003 | REX1032 | YOLOv8n-detect | P1 | 需实测验证 | In Progress | 研发介入并按生成的测试脚本实测 |
| RAW-004 | REX81 | Qwen2.5-32B | P2 | 待人工核实 | 待澄清 | 向需求提出方补齐：framework |
| RAW-005 | TX8 | DeepSeek-V3 | P1 | 不推荐 | 待澄清 | 向需求提出方补齐：framework |
| RAW-007 | REX1032 | 未提取到 | P1 | 待人工核实 | 待澄清 | 向需求提出方补齐：model_name |
| RAW-008 | TX81 | 未提取到 | P3 | 待人工核实 | 待澄清 | 向需求提出方补齐：model_name, framework |
| RAW-010 | REX81 | 未提取到 | P2 | 待人工核实 | 待澄清 | 向需求提出方补齐：model_name, framework |
| RAW-011 | TX8 | DeepSeek-V3 | P2 | 不推荐 | 待澄清 | 向需求提出方补齐：framework |
| RAW-012 | TX8 | Qwen2.5-14B | P2 | 需实测验证 | 待澄清 | 向需求提出方补齐：framework |
| RAW-014 | REX1032 | Qwen2.5-32B | P3 | 不推荐 | 待澄清 | 向需求提出方补齐：framework, issue_type |
| RAW-015 | TX8 | Qwen2.5-7B | P1 | 需实测验证 | In Progress | 研发介入并按生成的测试脚本实测 |

## 风险同步

**P1 且字段不全（阻塞中）**：RAW-001, RAW-005, RAW-007

这类需求是进度风险的主要来源：严重度最高但因字段不全无法启动，
**越早澄清越好** —— 建议列入下一次跨部门对齐会议的固定议题。

---
生成命令：`python -m src.cli`
