# `lunwen` 检索匹配方式及输入输出

## 1. 采用的论文代码

主实现来自 `lunwen/evaluate_consistency.py`，与 `代码/xiangmu/lunwen/evaluate_consistency.py` 内容一致。

核心调用链：

```text
用户自然语言问题
  → 大模型在线查询分解
  → JSON Schema校验与术语归一化
  → collect_rules_for_clause
  → collect_rules_for_clause_with_cache
  → find_best_entities_batch
  → get_rules_by_entities
  → rule_clause_combined_similarity
  → 返回Top-K规则
```

## 2. 大模型查询分解

论文代码假设 `parsed_json` 已经存在，`evaluate_consistency.py` 自身不负责在线调用大模型。完整工具需要在论文检索前增加查询分解。

大模型输入：

```json
{
  "query_text": "在220kV变压器运行中，绕组温升达到70K是否符合要求？",
  "scenario_hint": "设备运维",
  "conversation_context": []
}
```

大模型必须按严格JSON格式输出：

```json
{
  "intent": "compliance",
  "entities": [
    {"name": "变压器", "type": "电力设备", "desc": ""},
    {"name": "绕组温升", "type": "技术参数", "desc": ""}
  ],
  "actions": ["判断是否合规"],
  "constraints": [
    {"parameter": "绕组温升", "operator": "=", "value": 70, "unit": "K"}
  ],
  "standard_refs": [],
  "scenario": {
    "scenario_type": "设备运维",
    "device_type": "变压器",
    "voltage_level": "220kV",
    "operating_condition": "运行中"
  },
  "keywords": ["220kV", "变压器", "绕组温升"],
  "confidence": 0.95
}
```

分解后的 `entities` 进入论文实体链接；`constraints/actions/scenario/standard_refs` 用于候选规则过滤、结构化重排和后续合规推理。

大模型输出必须经过以下处理：

1. JSON Schema和必填字段校验；
2. 电力术语和单位归一化；
3. 原文数值与输出数值一致性检查；
4. 禁止补造原文不存在的标准编号、设备或阈值；
5. 分解失败或置信度不足时，回退到整段原文SBERT实体匹配，并输出告警。

当前本地模型加载目录为：

```text
models/llm/qwen--Qwen-7B-Chat/snapshots/master
```

代码采用延迟加载，创建分解器时不加载权重，第一次调用 `decompose()` 时才加载模型。

## 3. 单条文本在线检索的业务输入

对外服务只需要暴露以下字段：

```json
{
  "request_id": "请求唯一标识",
  "clause_text": "待匹配的标准条款、业务问题或场景描述",
  "parsed_json": {
    "entities": [
      {"name": "变压器", "type": "电力设备", "desc": "可选描述"}
    ]
  },
  "options": {
    "use_entity_linking": true,
    "top_k_entities": 26,
    "top_k_rules": 22,
    "use_rule_content_sim": true,
    "vector_weight": 0.8,
    "structural_weight": 0.2
  }
}
```

- `clause_text`：必填，是SBERT编码和结构匹配的主要文本。
- `parsed_json.entities`：可选。存在时逐个实体链接；不存在或为空时，直接用整段 `clause_text` 寻找图谱实体。
- Top-K和权重应由服务端配置管理，普通用户不必填写。
- 论文主程序使用Top-26实体、Top-22规则、向量权重0.8、结构权重0.2；源码模块默认值是5、10、0.7、0.3。最终采用哪组参数必须写入配置和审计记录。

## 4. 运行时内部输入

以下对象由服务启动阶段加载，不属于用户请求：

- Neo4j连接；
- 微调SBERT模型；
- 图谱实体名称及归一化向量；
- 规则向量缓存；
- 知识图谱全量规则（关闭实体链接时使用）；
- 缓存及检索参数指纹。

Neo4j至少需要 `(Entity)-[:HAS_RULE]->(Rule)`。`Entity`使用 `name/normalized/type/desc` 属性；`Rule`使用 `id/content/subject/action/condition/constraint/type` 属性。

## 5. 匹配过程

1. 大模型把原始问题分解为意图、实体、动作、约束、场景和标准引用。
2. 校验并归一化大模型JSON；无效时回退为原文检索。
3. 将分解实体或整段原文编码成SBERT向量。
4. 与图谱全部Entity向量计算余弦相似度，低于0.3的实体被过滤。
5. 沿匹配实体的 `HAS_RULE` 关系召回候选Rule。
6. 对每条规则计算规则内容向量相似度和结构相似度。
7. 按 `0.8 × 向量相似度 + 0.2 × 结构相似度` 排序，返回Top-22规则。

结构相似度由数值及单位匹配（0.4）、动作匹配（0.3）和条件关键词匹配（0.3）组成。

## 6. 原论文函数的直接输出

`collect_rules_for_clause(...)` 直接返回 `List[Dict]`：

```json
{
  "id": "规则ID",
  "content": "规则完整内容",
  "subject": "规则主体",
  "action": "动作",
  "condition": "触发或适用条件",
  "constraint": "数值或逻辑约束",
  "type": "规则类型",
  "vector": "内部numpy向量，不应直接对外输出"
}
```

原函数只使用分数排序，返回字典中没有保留实体相似度、向量分数、结构分数和综合分数。

## 7. 新工具建议的对外输出

适配器在不改变论文排序逻辑的前提下，应补充可解释分数和来源证据：

```json
{
  "request_id": "请求唯一标识",
  "decomposition": {
    "intent": "compliance",
    "scenario": {"device_type": "变压器", "voltage_level": "220kV"},
    "constraints": [{"parameter": "绕组温升", "operator": "=", "value": 70, "unit": "K"}],
    "valid": true,
    "fallback_used": false
  },
  "matched_entities": [
    {"name": "变压器", "similarity": 0.91}
  ],
  "rules": [
    {
      "rank": 1,
      "rule_id": "rule-001",
      "content": "……",
      "subject": "变压器",
      "action": "……",
      "condition": "……",
      "constraint": "……",
      "type": "强制",
      "vector_score": 0.88,
      "structural_score": 0.70,
      "combined_score": 0.844,
      "source": {
        "standard_id": "标准编号",
        "version": "版本",
        "clause_id": "来源条款ID",
        "chapter_path": "章节路径",
        "quote": "来源原文"
      }
    }
  ],
  "retrieval_fingerprint": "模型、图谱、Top-K和权重指纹",
  "warnings": []
}
```

论文当前的Rule节点查询没有返回来源条款和标准版本。要实现上述 `source`，需要在Neo4j查询中补充Rule到Document/Clause的来源关系。

## 8. 两条条款一致性匹配的输入输出

论文离线评估输入为：

- Excel四列：`id、clause1、clause2、label`；
- 两个结构化JSON：`{id}_clause1.json`、`{id}_clause2.json`；
- JSON至少包含 `entities、rules、relations`；
- 训练/测试JSON目录、Neo4j、SBERT模型及检索参数。

每个条款分别检索规则后生成：

- `R`：两个规则集合的双向最大语义相似度；
- `N`：两个规则集合的数值约束相似度。

在线一致性服务建议输出：

```json
{
  "is_consistent": true,
  "probability": 0.96,
  "features": {"R": 0.93, "N": 0.89},
  "attention_weights": {"R": 0.62, "N": 0.38}
}
```

批量评估函数实际返回 `accuracy、precision、recall、f1、auc、mode、use_entity_linking、model_path、attention_weights`，并保存ROC曲线。
