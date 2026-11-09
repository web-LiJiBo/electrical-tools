# Neo4j运行与增量同步

## 功能边界

Neo4j用于保存标准文档、实体、条款规则和来源关系，支持证据路径查询及有限深度的语义关系查询。图谱关系只用于检索和证据导航，不代表条款适用性结论，也不授予设备控制权限。

## 安装与配置

安装图数据库可选依赖：

```powershell
& .\.venv\Scripts\python.exe -m pip install -e ".[graph]"
```

启动Neo4j 5或6，并在启动工具前设置密码环境变量：

```powershell
$env:STANDARD_KNOWLEDGE_NEO4J_PASSWORD = "你的Neo4j密码"
```

主要配置位于`configs/settings.example.yaml`的`knowledge`部分：

- `graph_backend`：`neo4j`或`memory`；
- `neo4j_uri`、`neo4j_user`、`neo4j_database`：连接参数；
- `neo4j_password_env`：保存密码的环境变量名，配置文件不保存密码；
- `batch_size`：每次批量写入的记录数；
- `fallback_to_memory`：Neo4j不可用时是否明确降级到内存图；
- `sync_state_path`：最近一次同步状态的本地摘要文件。

离线配置`configs/settings.offline.yaml`固定使用`memory`，不依赖Neo4j。

## 启动同步过程

1. 检查Neo4j连接和目标数据库；
2. 创建Document、Entity、Rule和GraphSyncState节点的唯一约束；
3. 创建条款编号、标准编号、规则编号和实体规范名索引；
4. 对当前条款知识单元生成稳定指纹；
5. 指纹完全一致时跳过数据写入；
6. 指纹变化时比较每个条款的`source_hash`，只删除并重建新增或变更条款，同时删除已经移除的条款；
7. 使用`UNWIND`批量写入节点和关系；
8. 更新Neo4j中的GraphSyncState及本地同步摘要。

启动终端会明确显示以下状态之一：

- `Neo4j图谱未变化，跳过重建`；
- `Neo4j增量同步完成`并显示更新、删除和保留数量；
- `Neo4j不可用，已明确降级到内存图`并显示原因；
- 禁止降级时直接终止启动，不会伪装成Neo4j运行成功。

## 数据模型

- `Document`：条款知识单元及标准编号、版本、章节、来源路径和来源指纹；
- `Entity`：设备、参数、状态等标准实体；
- `Rule`：规则正文、动作、条件和约束；
- `GraphSyncState`：整库指纹、同步时间和节点关系数量；
- `MENTIONS`：文档提及实体；
- `CONTAINS_RULE`：文档包含规则；
- `HAS_RULE`：实体关联来源规则；
- 其他关系：沿用来源JSON中明确给出的关系类型。

所有关系带有`document_id`，用于条款变化时精确删除旧关系，避免残留失效边。

## 查询和安全

条款被选中后，系统通过Neo4j查询`Document -> CONTAINS_RULE -> Rule`证据路径，返回标准编号、章节、来源文件和原文。语义推理查询最多返回50个相邻关系，防止无界遍历。

知识图谱响应固定包含：

```json
{
  "backend": "neo4j",
  "neo4j_imported": true,
  "dispatch_allowed": false
}
```

即使图谱查询成功，也不能把图关系直接解释为真实设备操作许可。
