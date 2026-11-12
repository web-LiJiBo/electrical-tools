# 操作语义复核与查询完整性实施计划

Goal: 防止反向动作预览、纯查询漏项与再次误判；本地实施，未经新授权不上传。
Architecture: 首轮整句清单；操作在生成任何预览前做第二次整批语义复核；操作+条款把复核合并到现有建议请求。查询统一核对覆盖并按项汇总。
Tech Stack: Python/FastAPI、pytest、原生JavaScript/Node。
Spec: 本对话用户已批准的三项解决方案。

## 约束
普通操作2次，纯状态/能力查询1次，标准分析2次，混合操作和标准最多2次；不按项目数重复调用。第二阶段失败、缺项、冲突或条件顺序未被支持则阻断，不重写原清单。保持本地分支fix/semantic-review-20261112，main仍fe803d29。不上传、不提交，文件分工避免冲突。

## 任务
- [x] 新operation_review模块：构造复核包、严格结果校验、单次review调用、错误脱敏；独立红绿测试。
- [x] 查询覆盖/按项结果与混合查询完整性；取消单字先/再顺序拦截，依赖结构化顺序与二阶段复核；红绿测试。
- [x] analysis_pipeline/grounded_advice集成：预览前review，混合请求共用第二次调用；迁移受控fixtures并加调用次数回归。
- [x] 完整Python/Node回归、独立代码审阅、结果记录。

## 复核协议
原始请求、operations/queries及目录为数据，模型只核对不能改计划。
JSON: approved(bool), items(list，每个operation一项，index(int), matches_request(bool), reason(str), device_id(str), action(str), parameters(dict)), missing_requests(list[str]), has_negation(bool), has_conditions(bool), has_order(bool), reason(str)。所有索引恰好一次，身份/动作/参数须与输入完全一致；任一不匹配/缺项/否定/条件/顺序或approved不是true则不允许预览。允许返回诊断原因但不回显API异常。
模块接口：review_packet(query, understanding, catalog, conversation_context=None)->dict；validate_review(raw, operations)->dict统一status=approved/blocked；review_operations(client, packet)->dict status=approved/blocked/failed。常量REVIEW_PROMPT。
GroundedAdvice第二阶段封装JSON {operation_review:上述对象, advice:原建议协议}，避免建议污染原operations。没有正文来源时单独review，不谎称调用条款模型；API失败不自动再调用。

## 分工与审阅重点
模块代理只改operation_review.py和新专属unit tests；查询代理只改semantic_operations.py/simulation_query.py和新查询回归；主代理改pipeline/advice与公共fixtures/docs。接口由主代理固定，代理可提出更正但不跨文件编辑。
重点：启动/停止反向、漏索引、布尔冒充数字索引、复核试图修改参数、API错误密钥脱敏、两用户并发不串审查结果、二次接口失败不产生command ID、再次单项与真正先后依赖、纯查询关系主设备不误算目标。

交叉审阅新增P1（知识整句片段重新分类）已修复；最终772 Python+24 Node通过，6真实API各2次符合预期。仅本地，未提交上传。

发布授权：用户于2026-11-12明确要求上传本次代码和更新文档，授权将上述已验证改动同步到main；该授权覆盖本批次，不延伸至后续修改。
