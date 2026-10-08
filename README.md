# 机器可读标准知识服务应用工具

本项目是面向新型电力系统标准知识服务的纯后台工具。它将一段自然语言需求转换为可追溯的标准条款、规则、场景候选指令、验证结论和事实报告。第一版只生成候选指令，不会连接设备或下发控制命令，所有结果中的 `dispatch_allowed` 固定为 `false`。

## 已实现能力

系统的后台主链如下：

```text
自然语言 → Qwen 分解/原文降级 → 场景上下文 → 实体/规则/条款检索
→ 知识图谱路径 → 一致性评价与混合推理 → 语义元组 → ILR
→ IEC 61850 或 Modbus 候选指令 → 多层验证与安全门禁 → 报告、审计与反馈
```

代码按功能位于 `src/standard_knowledge_service_v2`：

| 模块 | 作用 |
| --- | --- |
| `decomposition`、`scenarios` | DeepSeek API或本地 Qwen/可选LoRA适配器分解、原文安全降级、术语归一化，以及五类典型电力场景建模。 |
| `retrieval_engine`、`knowledge` | 从已复制的 JSON 读取条款、实体、规则；完成实体链接、规则召回、重排、证据构建及内存标准/图谱库。 |
| `knowledge_graph` | 将 JSON 构造成 Document、Entity、Rule 节点及 MENTIONS、CONTAINS_RULE、HAS_RULE 等关系；支持内存或可选 Neo4j 后端。 |
| `consistency_evaluation` | 数值约束、规则集合和结构相似度；可加载注意力分类模型，依赖不可用时使用透明权重分类器。 |
| `hybrid_reasoning` | 安全规则解释、图谱路径遍历与一致性结论融合；无法解析或事实不足时返回 `uncertain`。 |
| `instruction_engine` | 条款规则转语义元组、静态参数/动态行为/约束规则三层语义、If-Then、受控SWRL模板、ILR和 IEC 61850/Modbus 候选指令。 |
| `validation` | 条款适用性、语义、条款—指令、协议、逻辑、冲突和安全门禁验证。 |
| `reporting`、`audit`、`feedback` | 基于事实生成报告、记录审计、收集业务反馈并给出需人工审批的优化建议。 |
| `application`、`api` | 端到端编排、命令行入口和可选 HTTP API。 |

## 数据与模型

- 本地 Qwen：`models/llm/qwen--Qwen-7B-Chat/snapshots/master`
- 可选微调适配器：通过 `model_paths.llm_adapter` 指向本地 LoRA/PEFT 目录；未配置时使用基础模型。
- 检索模型：`models/embedding/finetuned_sbert`
- 一致性模型：`models/consistency/classifier_model/attention_model.pt`
- 标准分解数据：`datasets/lunwen/output_jsons_new/train` 与 `test`
- 校核后主数据：`datasets/lunwen/verified_json/json`；完整校核与修正记录见同目录的 `修正对照表.xlsx`、`修正对照表.csv` 和 `audit_summary.json`

训练集 JSON 已完成一次内存图谱构建：5,084 个文件全部成功，包含 17,566 个去重节点和 65,318 条关系。统计见 `artifacts/knowledge_graph/build_summary.json`。

`2017.xlsx` 是条款原文依据。文件名中的编号对应 Sheet1 第一列的条款对编号，而不是 Excel 物理行号；例如 `3347_clause1.json` 对应物理第 3338 行、第一列编号为 3347 的第一条款。后台装配优先使用已校核数据集；原来的 `output_jsons` 和 `output_jsons_new` 仅保留为不同训练/测试划分的原始来源。

## 安装与启动

要求 Python 3.11 或更高版本。在项目根目录执行：

```powershell
python -m pip install -e .
```

如需启动本地 Qwen、Neo4j、深度学习模型或 HTTP API，可按需安装：

```powershell
python -m pip install -e ".[llm,graph,ml,api]"
```

Qwen-7B-Chat 使用随模型附带代码声明的固定组合 `transformers==4.32.0` 与 `transformers-stream-generator==0.0.4`。不要与较新的 Transformers 混装；如曾安装过其他版本，请按 `TESTING.md` 的依赖修复命令重新安装。

命令行分析示例：

```powershell
$env:PYTHONPATH = "src"
python -m standard_knowledge_service_v2.main --query "海上风电集电线路发生过流时应如何处理" --scenario "海上风电"
```

启动 HTTP 服务：

```powershell
$env:PYTHONPATH = "src"
python -m standard_knowledge_service_v2.main --serve
```

默认监听 `http://127.0.0.1:8000`。服务端支持 `/health`、`/analyze`、`/decompose`、`/search`、`/generate-instruction`、`/validate`、`/generate-report` 和 `/audit/{request_id}`。

## 输入

主入口为 `POST /analyze`，也可将同一对象传给 `AnalysisRequest`。最小输入只有 `query`；`scenario_hint`、业务参数、协议和对话上下文为可选字段。

```json
{
  "query": "海上风电集电线路发生过流时应如何处理？",
  "scenario_hint": "海上风电",
  "target_protocol": "IEC61850",
  "parameters": {
    "device_id": "CB-01",
    "operating_state": "运行",
    "device_type": "集电线路",
    "device_config": {
      "device_id": "CB-01",
      "logical_node": "PTRC1",
      "data_object": "Tr.general",
      "protocol": "IEC61850"
    }
  },
  "conversation_context": []
}
```

输入字段说明：

| 字段 | 是否必填 | 说明 |
| --- | --- | --- |
| `query` | 是 | 自然语言问题或业务场景描述。 |
| `scenario_hint` | 否 | 如“海上风电”；系统也会根据问题推断场景。 |
| `parameters` | 否 | 设备 ID、运行状态、电压等级、实际测量值等业务事实。 |
| `target_protocol` | 否 | `IEC61850` 或 `Modbus`；未提供时根据设备配置/模板选择。 |
| `parameters.device_config` | 生成协议候选指令时建议提供 | IEC 61850 需要 `device_id`、`logical_node`、`data_object`；Modbus 需要 `device_id`、`slave_id`、`coil_address`。 |

模型不可用或输出不合格 JSON 时，系统只从原文提取显式出现的实体、标准号、动作与数值，不会补造事实。

当前示例配置使用DeepSeek API进行临时测试。密钥只通过环境变量提供，不得写入配置文件：

```powershell
$env:DEEPSEEK_API_KEY = "<your-api-key>"
```

切回本地千问时，将`llm_decomposition.backend`改为`local_transformers`。

## 输出

`/analyze` 返回以下结构：

```json
{
  "request_id": "请求唯一标识",
  "status": "needs_human",
  "data": {
    "decomposition": "查询分解、来源和错误信息",
    "context": "场景上下文",
    "missing_fields": "缺失业务或设备配置字段",
    "matching": "匹配实体、规则排名和分数",
    "semantic": "主体—动作—对象—条件—约束",
    "ilr": "中间规则程序",
    "candidate_instruction": "协议候选指令",
    "validation": "适用性、语义、协议、逻辑验证与安全结论",
    "report": "结构化事实报告和 Markdown 正文"
  },
  "evidence": "条款证据列表",
  "warnings": "风险、降级和待人工确认提示"
}
```

`status` 含义：

- `needs_human`：验证完成，但必须由人工确认；这是完整配置下的正常第一版结果。
- `uncertain`：证据、业务事实、场景适用性或协议配置不足，不能得出可靠结论。
- `fail`：出现条款不适用、语义冲突、协议不合法或逻辑错误。

无论何种状态，`candidate_instruction.dispatch_allowed` 都是 `false`。用户反馈不会直接改写模型或生产配置，而是在 `feedback` 模块中形成待审批建议。

## 配置与安全原则

示例配置位于 `configs/settings.example.yaml`。所有模型和数据路径相对工具项目解析；运行代码不会导入或调用 `D:\攻关项目\lunwen`。Neo4j 密码必须通过环境变量提供，不得写入配置文件。

测试采用分层执行。日常修改运行快速门禁，提交或验收前运行包含6674份核验JSON契约检查的标准流程：

```powershell
& .\scripts\run_test_flow.ps1 -Profile fast
& .\scripts\run_test_flow.ps1 -Profile standard
```

当前自动化基线为45项全部通过。测试日志、JUnit结果、环境信息、配置/数据/模型指纹和总结会写入`artifacts/test_reports/<时间>/`。本地Qwen真实推理由于内存需求较高，不在一键脚本中自动运行。完整的模型、构图、HTTP、业务样例和发布验收步骤见[TESTING.md](TESTING.md)。
