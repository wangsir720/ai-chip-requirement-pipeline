# 需求管理 SOP

> 由 `src/doc_assembler.py` 自动装配。**每条规则均标注对应实现位置** —— 写了没实现的 SOP 是废话。

## 1. 需求录入
| 步骤 | 要求 | 实现位置 |
|---|---|---|
| 1. 登记来源 | 必须标明 email / jira / meeting_note / ticket | `cleaner.py::clean_record` 读 `source` 字段 |
| 2. 原文不得改写 | 原文单独存 `raw_text`，清洗结果另存 `clean_text` | `cleaner.py` 双字段保留 |
| 3. 上报人与客户行业 | 作为上下文单独存储，**不从原文猜测** | `extractor.py` 的 `customer_industry` 标注「样本自带」 |

## 2. 需求审核
| 检查项 | 判定标准 | 实现位置 |
|---|---|---|
| 必填字段完整 | 5 项必填字段（芯片/模型/框架/问题类型/严重度）全部有值 | `extractor.py::REQUIRED_FIELDS` |
| 字段必须有出处 | 每个抽取字段带原文字符区间 | `extractor.py` 的 `evidence` 字段 |
| 抽不到不填 | 填「未提取到」，**禁止用默认值** | `extractor.py::NOT_FOUND` |
| 指代必须标记 | 「这个卡」「他们那边」标记而非删除 | `cleaner.py::mark_pronouns` |

## 3. 需求清洗与去重
| 步骤 | 要求 | 实现位置 |
|---|---|---|
| 去噪声 | 只删登记在案的噪声词，删除动作必须留痕 | `cleaner.py::NOISE_TOKENS` + `actions` |
| 去重 | 按结构化去重键（芯片+模型+首要问题类型）合并 | `cleaner.py::_dedup_key` |
| 保留最早 | 主需求取最早到达的一条，其余记入 `merged_from` | `cleaner.py::deduplicate` |
| 相似度仅作证据 | 文本相似度写入日志但不参与判定 | `cleaner.py::similarity` |

### 为什么去重不用文本相似度判定

实测本项目样本：同义重复对的 bigram 相似度最低 **0.130**，
不同诉求对的最高 **0.140** —— 两者区间重叠，**任何阈值都会误判**。
这不是调参问题，是方法选错了。结构化去重键的依据是产品语义：
同一张卡 + 同一个模型 + 同一类问题 = 同一个需求。

## 4. 需求拆解与派发
| 步骤 | 要求 | 实现位置 |
|---|---|---|
| 严重度定级 | 由问题类型映射，不做主观打分 | `extractor.py::SEVERITY_BY_ISSUE` |
| 多标签分类 | 一条需求可命中多个问题类型，不压成单标签 | `extractor.py::ISSUE_RULES` |
| 状态推导 | 字段不全 → 待澄清；P1 → In Progress | `doc_assembler.py::render_board` |
| 下一动作 | 每个状态必须对应明确的下一步，**不做进度汇报** | `render_board` 的 `next_action` 列 |

## 5. 闭环与沉淀
| 步骤 | 要求 | 实现位置 |
|---|---|---|
| 解决记录 | 五要素齐全才入库，缺任一项拒收 | `kb_builder.py::ENTRY_FIELDS` + `rejected` |
| 根因未定位 | 允许入库但须显式标注，**不编根因** | `kb_builder.py` 的 `cause` 处理 |
| 多维检索 | 按芯片/模型/框架/问题类型检索 | `kb_builder.py::search` |
| 脚本生成 | 待核实需求不生成脚本 | `script_gen.py::generate_all` 的 skipped |

---
生成命令：`python -m src.cli`
