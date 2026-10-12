# 动作前置条件修正记录

日期：2026年10月8日。对应GitHub基线：`9f4671796b9790d27f301345b9df77bc7f48b4de`。

## 问题与修正前行为

跳闸条款的触发条件为“电流 >= 100”，实际输入20。旧流程的规则推理已返回fail，但失败只影响排序分数；选中的条款仍进入协议模板生成，最终返回needs_human且包含控制载荷。最终验证没有接收实际触发条件的判定结果。

## 实施内容

1. 新增ActionPreconditionEvaluator，以Rule.condition和明确标记为precondition的附加约束判定动作前置条件。只使用显式业务事实，不使用协议配置或模型补出的测量值。
2. 候选选择优先使用前置条件通过的相关候选；若没有可用动作，保留条款用于解释、报告和溯源，但生成器不产生控制载荷。新增control_eligible与action_preconditions供审计。
3. InstructionGenerationService.generate在协议适配器调用前重新判定条件；直接调用时也必须通过关键字参数facts提供业务事实。InstructionService.generate_for_clause同步传递facts。
4. CandidateInstruction新增precondition_status和precondition_trace。失败或未知时payload为空，只返回阻断原因、缺失信息和条款证据。
5. 最终SafetyGate纳入action_preconditions。协议及条款—动作验证器识别被阻断的结果，不把“主动不生成载荷”误报为协议字段错误。
6. 新增Constraint.role。precondition为操作前置要求；compliance为独立合规评价；unspecified或未知用途将动作判为uncertain。JSON规则通过constraint_role传递用途。未自动重写或批量标注现有数据。
7. 不将查询文本与条款的综合一致性分数作为实际测量条件。合规约束不满足可以触发明确规定的告警动作；不会将所有违规检测一律变成动作禁止。
8. 保持自动下发关闭。本次没有重新引入已删除的无关问题拒答功能。

## 修正前后示例

| 情形 | 修正前 | 修正后 |
| --- | --- | --- |
| 电流20，触发阈值100 | 推理fail，仍有跳闸载荷，needs_human | fail，载荷为空，保留原因和证据 |
| 电流120，触发阈值100 | 可生成候选载荷 | 前置条件pass，可生成候选载荷，needs_human |
| 未提供电流 | 缺少事实仍可能生成载荷 | uncertain，载荷为空，要求补充事实 |
| 实测值带无法确认的单位 | 未纳入统一生成门禁 | uncertain，不静默丢弃单位 |
| 温升超过65触发告警，合规要求温升<=65 | 综合推理fail未明确区分含义 | 显式compliance约束独立记录；触发条件满足则可生成告警候选 |
| 附加前置要求不满足 | 仅参与混合评价或未约束生成 | fail，不生成载荷 |
| 约束用途未标明 | 没有明确区分 | uncertain，不生成载荷 |
| 询问“什么情况下需要跳闸” | 仓库版本已有知识/指令意图区分 | 仓库版本仍可解释条件，缺少实测值不阻断知识解释 |

## 验证结果

- 本地工具：68 passed，0 failed，完整测试报告为本地测试.xml。
- 仓库当前版本快照：83 passed，2 deselected，0 failed，报告为仓库版本测试.xml。排除的2项为本地模型配置及原始资源存在性检查；评审快照没有完整复制这些资源。
- 本次新增23项共同回归检查，并在仓库快照新增1项知识解释检查。覆盖条件真/假/未知、无效数值、布尔类型、单位未归一、直接调用绕过、协议配置冒充事实、阈值引用、候选优先级、约束用途、告警、证据与审计。
- 调整既有正向测试：必须显式提供电流与额定值，明确测试约束用途；不再将缺少实测事实的调用视为可生成控制载荷。
- 修正后行为.json保存真实执行的结构化示例及请求ID、条件轨迹、载荷和审计保存结果。
- 本次未执行真实设备、Neo4j、外部模型或浏览器联调；不宣称完成生产验收。

## 代码与兼容边界

主要修改：application/analysis_pipeline.py、application/instruction_service.py、instruction_engine/instruction_generator.py、instruction_engine/models.py、instruction_engine/semantic_extractor.py、新增instruction_engine/preconditions.py、domain.py、retrieval_engine/clause_retriever.py及两个验证器。

条件解释仍限于白名单单一比较表达式、布尔等值与显式阈值事实引用；复合自然语言、缺失字段、无效数值或无法确认的单位返回uncertain。不存在自动推断额定值、单位转换或将空条件默认为已满足的行为。

旧数据中的附加约束默认用途为unspecified，需要校核后标明用途，不能将真正的操作前提误标为compliance。此字段是数据契约变化，不是已经完成的数据语义校核。

本地旧工具与GitHub当前快照的意图识别能力不同；知识解释不生成指令的回归证据针对GitHub当前版本，不宣称旧工具已补齐相同意图能力。

## 留存文件与远端状态

- 修正前代码快照.json：主要模块修改前内容。
- 修正前补充快照.json：其余模块修改前内容。
- 修正后行为.json：执行示例。
- 本地测试.xml、仓库版本测试.xml：JUnit验证报告。
- GitHub修正补丁.patch：针对上述固定GitHub版本的实现、测试与修正说明补丁。

改动已保存到本地工具和GitHub版本评审快照。此前GitHub写入连接返回403，本次未继续尝试写入远端；远端main尚未同步。补丁已通过针对基线版本的可应用性检查。
