# electrical-tools 完成情况评估

评估日期：2026年10月8日。对象：[web-LiJiBo/electrical-tools](https://github.com/web-LiJiBo/electrical-tools)，main 提交 `9f4671796b9790d27f301345b9df77bc7f48b4de`。

## 结论

工具已形成阶段性原型：具备自然语言分解、场景识别、条款检索、候选评价、语义与ILR转换、候选协议指令、验证、报告、审计和演示页面。尚不能认定为任务书意义上的完整交付成果，也不宜直接用于可靠业务判断。核心原因是推理失败未约束最终结果、无关查询拒答不足，以及若干计划功能只有接口或未接入主流程。

不使用单一完成百分比：仓库没有经确认的功能权重与逐项验收结果，代码存在、测试通过与业务能力达标不能互相替代。

## 功能判定

| 范围 | 判定 | 依据与边界 |
| --- | --- | --- |
| 自然语言分解与意图识别 | 已实现基础功能 | 有DeepSeek、本地Qwen及原文降级路径；DeepSeek测试使用模拟响应，未实测外部服务。 |
| 五类场景 | 已实现场景定义 | 海上风电、变电站运维、故障隔离、新能源并网、电网调度；未见完整业务效果评测。 |
| 数据与构图 | 已形成底座 | 核验JSON 6674份；保存的构图摘要为21850个去重节点、81008条关系，后端为内存。 |
| 标准检索 | 部分完成 | 主流程使用中文单字/英文数字片段的文字相似度和结构重排；未加载SBERT，未通过Neo4j遍历召回。 |
| 一致性与混合推理 | 部分完成，有关键缺陷 | 有分类器、数值规则和轨迹；失败结果仅影响排序，没有成为最终结果的否决条件。 |
| 语义、ILR、协议候选指令 | 已实现基础功能 | IEC61850/Modbus生成结构化候选载荷，非真实协议连接；所有下发标志保持false。 |
| 报告、审计与反馈 | 部分完成 | 主流程包含报告与审计；反馈有独立模块，但没有对应HTTP入口或页面业务闭环。 |
| PDF/Excel/XML批量导入及XML/JSON/RDF互操作 | 尚未完整实现 | ingestion.py中主要为Protocol接口与省略号，没有完整导入和转换实现。离线校核脚本不能替代这些能力。 |
| 页面和HTTP | 已有演示实现 | 页面调用本地8000端口；有健康、分析、分解、检索、候选指令、验证、报告、审计路由；本次未启动页面与HTTP进行联调。 |
| 部署与验收 | 未完成证据闭环 | 有安装说明和测试手册，但未见发布版本、自动化工作流运行记录、完整性能/准确率/稳定性验收报告。 |

## 已复现的关键问题

### 1. 推理失败仍生成候选指令

在内存测试库中设定条款“线路电流不小于100A时应跳闸”，规则条件为`电流 >= 100`；输入实际电流20A，提供完整IEC61850候选配置并请求跳闸建议。

实测输出：`reasoning_status=fail`、`status=needs_human`、`candidate_generated=true`、`dispatch_allowed=false`。规则条件未满足，却生成候选控制载荷。虽然不会自动下发，但候选建议的业务可靠性不足。

原因：analysis_pipeline.py的_select_rule只用检索最低分和动作匹配判断eligible；一致性冲突、规则失败和缺失事实只作为评分或轨迹。最终安全判断未纳入该候选的混合推理状态。

### 2. 无关问题仍被标记为已回答

仅有“线路电流不大于100A”的内存测试库，输入“苹果的颜色是什么”。系统仍选择该电力条款并返回`answered`，候选的推理状态为fail。

配置`minimum_rule_score=0.0`，缺少可靠的相关性拒答门槛；知识查询的最终状态也未充分约束一致性和适用性。不能将返回条款或状态answered直接当成正确回答。

### 3. 配置和说明的能力未全部装配

配置声明embedding、Neo4j、标准版本过滤和三库协同，但bootstrap实际装配本地JSON检索，并构造没有SemanticReasoner的HybridReasoningEngine。当前主链不能据此宣称已实现SBERT语义检索、图谱路径推理和真实业务数据仓库协同。

### 4. 数据与模型仍有交付缺口

audit_summary.json记录`manual_review_count=961`、`needs_manual_review=622`。测试核对这些数量，没有证明待复核问题已经逐项关闭；“所有JSON有正文”也不等于抽取语义全部正确。

当前Git树中没有models/llm文件，因而仓库自身未交付README所描述的本地Qwen目录与8个权重分片。SBERT主要权重为Git LFS指针，应验证获取途径、权限和实际权重可用性。默认配置使用DeepSeek API，是否能运行还依赖外部密钥与服务。本次没有调用外部模型。

## 本次验证

- 通过GitHub读取固定提交的107个源代码文件、17个测试文件及配置等内容；在独立临时目录进行验证，没有修改原项目或远端仓库。
- 将本地核验JSON与远端6674个Git blob逐项比对；统一CRLF/LF换行后全部匹配，因此这些数据可用于本次核验。
- 在Python 3.12.7环境运行现有测试：59 passed、2 deselected。排除的是Qwen本地配置存在性、模型及原始数据资源存在性两项检查；本次验证快照未完整获取这些资源。
- 59项包含3项核验数据检查。DeepSeek测试使用模拟HTTP响应；未执行本地Qwen真实推理、真实DeepSeek调用、Neo4j联调、设备协议隔离环境验证、HTTP/页面联调或性能测试。
- 另行复现上述无关查询回答、规则失败仍生成候选指令的问题；现有测试未覆盖这些边界。
- 仓库保存的2026年8月30日JUnit确为45项通过，但现版本已收集61项测试，README和TESTING仍称45项。历史记录不能替代当前版本完整验收。
- 本次JUnit：D:/攻关项目/tmp/electrical-tools-audit-20261008/review-junit.xml。

## 与项目任务书的关系

本地《任务书》规定，课题3在2026年10月至12月研发机器可读标准知识服务应用工具1个并申请软著1项；最终项目周期至2027年6月。当前处于工具阶段研发时间窗，尚未到最终结题时间。

就代码而言可认定为“阶段性原型已形成、基础功能已打通”；不能认定为“应用工具已经完成验收”，也不能仅凭此仓库认定论文发表、专利受理、软著申请、标准或典型案例验证已完成。

## 建议补齐顺序

1. 优先修复失败推理、冲突、事实缺失与候选指令生成之间的门禁，增加无关问题拒答与相关性阈值，并补充回归用例。
2. 明确交付边界：若继续承诺SBERT、Neo4j、三库、导入和格式互操作，应补全实现和装配；同时完成标准号、版本过滤与来源定位。
3. 关闭961项人工复核记录，形成抽检结论、错误处置和版本冻结记录；补齐模型交付或明确在线模型运行依赖。
4. 以固定版本和评测集完成检索Hit@K/MRR、一致性Accuracy/F1/AUC、拒答、候选指令正确性、时延和稳定性评测，补齐各场景证据。
5. 更新测试基线，保存当前版本完整验收报告、部署说明和交付包，并独立核对软著等任务书成果。

## 主要仓库证据

- [主流程](https://github.com/web-LiJiBo/electrical-tools/blob/9f4671796b9790d27f301345b9df77bc7f48b4de/src/standard_knowledge_service_v2/application/analysis_pipeline.py)
- [主流程装配](https://github.com/web-LiJiBo/electrical-tools/blob/9f4671796b9790d27f301345b9df77bc7f48b4de/src/standard_knowledge_service_v2/bootstrap.py)
- [导入接口](https://github.com/web-LiJiBo/electrical-tools/blob/9f4671796b9790d27f301345b9df77bc7f48b4de/src/standard_knowledge_service_v2/ingestion.py)
- [实际检索实现](https://github.com/web-LiJiBo/electrical-tools/blob/9f4671796b9790d27f301345b9df77bc7f48b4de/src/standard_knowledge_service_v2/retrieval_engine/lunwen_adapter.py)
- [数据校核摘要](https://github.com/web-LiJiBo/electrical-tools/blob/9f4671796b9790d27f301345b9df77bc7f48b4de/datasets/lunwen/verified_json/audit_summary.json)
- [历史测试结果](https://github.com/web-LiJiBo/electrical-tools/blob/9f4671796b9790d27f301345b9df77bc7f48b4de/artifacts/test_reports/20260830-114729/pytest-junit.xml)
- [需求对应表](https://github.com/web-LiJiBo/electrical-tools/blob/9f4671796b9790d27f301345b9df77bc7f48b4de/REQUIREMENTS_TRACEABILITY.md)
