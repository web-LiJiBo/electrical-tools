# 语义操作清单与用户流程修复实施计划

Goal: 用户整句一次理解，多操作直接校验生成预览；标准分析最多额外一次模型。
Architecture: 模型清单 -> 确定性校验 -> 本地预览；条款检索后集中建议。
Tech Stack: Python/FastAPI、原生JavaScript、pytest、Node test。
Spec: 本次对话用户批准的完整方案。

## 约束
仅本地修改，不提交上传；独立场景身份，共享会话状态；保留原版本与逐项确认保护。

## 任务
- [x] 语义清单schema、模型目录上下文、后端直接消费与调用次数测试。
- [x] 精确数值、目标参数范围、不等式假设与最终建议一致性。
- [x] 模板候选全目录校验、原子保存、坏条目隔离、反馈类型。
- [x] 页面会话持久恢复、初始化环境兼容。
- [x] Python/Node完整回归、独立审阅、记录结果。

## 审阅重点
礼貌尾句；设备归属矛盾；否定条件与顺序；参数跨操作串用；模型失败不回退硬拆。

## 文件分工
核心理解代理负责decomposition/simulation_query/mixed_operation_preview/analysis_pipeline。
数值代理负责normalizer/action_parameters/real_clause_assessment/grounded_advice。
模板代理负责template_editor/simulation_catalog/routes及模板默认点位。
主代理负责original-simulation.js/index资源版本、初始化脚本及集成验证。
三个后端模块共享动作参数接口，保持现有resolve_action_parameters签名；新增清单在调用端适配。

Ruling: 使用本地fix/semantic-operation-plan-20261112分支，保留main原提交；共享目录分文件实施，禁止提交上传。

最终验证：Python648通过15跳过；Node23通过；真实API六问各1调用，符合预期。详见外部审阅记录20261112_语义清单修复。
