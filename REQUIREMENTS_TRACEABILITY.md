# 需求—模块—证据映射

| 项目/报告要求 | 新大纲模块 | 可复用现有代码 | 验收证据 |
|---|---|---|---|
| 四层机器可读表达及XML/JSON/RDF互操作 | `ingestion.py`、`semantics.py` | 结构化抽取器、校验器 | Schema、转换样例、往返一致性测试 |
| 完整性、准确性、一致性和冲突检测 | `semantics.py`、`quality.py` | `validator.py`、数值约束模块 | 校验报告、错误明细、人工抽检记录 |
| 三库一体协同 | `repositories.py` | `StandardRepository`、`KnowledgeGraph` | 条款—实体—规则—数据实例溯源链 |
| 标准号、版本、设备、条件等结构化查询理解 | `retrieval.py` | 当前规则召回代码 | 查询解析集、字段识别准确率 |
| 大模型在线查询分解及严格JSON校验 | `retrieval.py`、`adapters.py` | `StructuredExtractor`、`excel_to_entity.py`提示模板 | 字段完整率、JSON有效率、分解失败回退率 |
| 论文实体链接与规则检索 | `retrieval.py`、`adapters.py` | `lunwen/evaluate_consistency.py` | Hit@K、MRR、规则召回率、时延、消融实验 |
| SBERT实体匹配、HAS_RULE遍历和规则重排 | `retrieval.py` | `find_best_entities_batch`、`get_rules_by_entities`、`collect_rules_for_clause` | 实体命中率、规则召回率、缓存指纹测试 |
| 证据重排、引用校验、忠实度和拒答 | `retrieval.py`、`quality.py` | 审计对象可部分复用 | 引用命中率、忠实度、拒答准确率 |
| 多维一致性判定 | `consistency.py` | 论文管线、注意力模型、数值约束 | 固定划分Accuracy/F1/AUC、预测明细 |
| 三层可执行语义与ILR | `semantics.py`、`instructions.py` | 静态参数、FSM、约束层、ILR | 语义保真度、逻辑完备性样例 |
| IEC 61850、Modbus等协议适配 | `instructions.py` | `protocol_adapter.py`、模板库 | 协议格式校验、隔离环境测试 |
| 规则推理+语义推理 | `reasoning.py` | `hybrid_engine.py` | 规则命中、推理路径、冲突明细 |
| 调度、运维、新能源并网等场景动态适配 | `services.py` | SKSM模块 | 场景用例、输入要素—标准响应记录 |
| 标准执行全流程可追溯 | `quality.py`、`contracts.py` | `audit.py` | 请求ID、版本、模型、证据、输出审计记录 |
| 执行监控和数字仿真 | `quality.py` | `quality_infrastructure.py`原型 | 仿真场景、边界测试、安全回退记录 |
| 应用工具1个、统一接口、可部署可扩展 | `contracts.py`、`bootstrap.py` | `service_layer/api.py` | OpenAPI、部署包、接口/稳定性测试 |

## 阶段边界

1. 现有论文指标是历史实验结果，不自动等于集成系统指标。
2. 现有数字孪生和执行监控代码为模拟原型，真实业务平台接入须单独验证。
3. 现有规则表达无法解析时“默认通过”的策略不得进入生产合规判断；新实现必须返回“不确定/需人工确认”。
4. 任何控制指令必须携带来源条款、标准版本、模板版本、协议配置和三层验证结果。
