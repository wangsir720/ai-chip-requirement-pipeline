# 数据来源登记

> **抓取日期：2026-10-03**。本文件是 `data/` 下所有目录表的唯一出处。

## 可信等级

| 等级 | 含义 | 在判定中的作用 |
|---|---|---|
| `official` | 项目官方仓库 / 官方文档 | 可直接作为依据 |
| `secondary` | 媒体、聚合站、公开技术资料 | 可作为依据，结论中必须显示来源 |
| `unverified` | 孤证或未获官方确认 | **不参与自动判定**，仅列为待核实项 |

## 来源清单

| source_id | 等级 | 名称 | URL | 覆盖内容 |
|---|---|---|---|---|
| S1 | secondary | 公司官网产品与生态页 | https://www.tsingmicro.com | 产品线命名、架构表述、互联特性、RAISA 软件栈、FlagOS 生态 |
| S2 | secondary | 公开技术资料 | — | PyTorch 版本迁移路径、CUDA 兼容性表述 |
| S3 | official | FlagGems（FlagOS 生态官方算子库） | https://github.com/flagos-ai/FlagGems | FlagOS 原生算子支持、无需迁移 |
| S4 | official | FlagPerf（FlagOS 生态开源基准测试平台） | https://github.com/flagos-ai/FlagPerf | 适配矩阵的**维度设计参照**（算子级基准的组织方式） |
| S5 | official | FlagTree（FlagOS 统一编译器） | https://github.com/flagos-ai/FlagTree | 同一模型在不同芯片后端表现差异的技术成因 |
| S6 | official | Ultralytics YOLOv8 文档 | https://docs.ultralytics.com/models/yolov8/ | 视觉检测模型规模 |
| S7 | official | Qwen2.5 / DeepSeek 公开模型卡 | — | 模型参数量与显存需求量级 |

## 关键说明：数据时效与口径

1. **芯片架构参数多为「未查到」**：可重构架构的公开资料以产品宣传为主，
   详细的算力、带宽、互联规格未公开。表中留空即代表未查到，**不填推测值**。
2. **`operator_fallback_to_cpu_known=True`（PyTorch 2.1）标为 `unverified`**：
   该行为来自自拟需求样本中的客户描述，**非官方口径**。
   引擎据此只输出「需实测验证」档判定，不输出「不推荐」——
   理由是：拿客户单方面描述去否定一个框架版本，责任不对等。
3. **显存需求按权重下界估算**：`min_vram_gib` 取公开模型卡给出的量级，
   未计入 KV Cache 与运行时余量，因此是**下界**。这一点在输出中显式标注。

## 与既有作品集的边界

本项目**不做算力采购测算**（卡数 / TCO / BOM）—— 那是 `ai-compute-presales-workbench` 的范围。
本项目做的是它的**上游**：需求进流程之前的清洗、结构化、适配判定、测试脚本与知识沉淀。

已有的 `compatibility-validation-engine` 侧重「芯片规格冲突检测与证据链」，
本项目侧重「**多源需求治理**」—— 一个是数据目录质量，一个是需求管道质量，不重叠。
