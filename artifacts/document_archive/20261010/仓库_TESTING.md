# 后台测试与验收流程

本文档用于验证机器可读标准知识服务工具的代码、数据、知识图谱、本地 Qwen、检索、一致性评价、混合推理、候选指令、安全门禁、报告、审计与 HTTP 接口。每项测试均包含执行指令、预期结果和失败判定。固定顺序为：环境 → 快速门禁 → 数据契约 → 模型 → 检索与候选选择 → 安全与指令 → 端到端 → HTTP → 发布验收。当前自动化基线为 45 项测试全部通过。

## 测试分层与一键执行

| 层级 | 使用时机 | 范围 | 是否加载 Qwen 权重 |
| --- | --- | --- | --- |
| `fast` | 每次改代码后 | 语法、42 项轻量单元与集成测试 | 否 |
| `standard` | 提交或阶段验收前 | `fast`、3 项核验数据契约、6674份数据装配 | 否 |
| 人工完整验收 | 模型、数据、图谱或HTTP发布前 | `standard`、Qwen真实推理、重新构图、HTTP和业务样例 | 是，单独执行 |

推荐先运行自动测试脚本。脚本遇到任何失败立即停止，并在`artifacts/test_reports/<时间>/`生成日志、JUnit XML和结果摘要：

```powershell
conda activate p311
Set-Location D:\攻关项目\06-工具\standard_knowledge_service_outline
& .\scripts\run_test_flow.ps1 -Profile fast
& .\scripts\run_test_flow.ps1 -Profile standard
```

预期结果：最后显示“测试通过”和报告目录；`summary.json`中的`status`为`passed`。Qwen真实推理不放入一键流程，防止在内存不足机器上被系统直接终止，必须按T09–T12单独执行并保存结果。

## 1. 测试环境准备

### T01：进入项目并确认 Python 环境

推荐使用 Python 3.11；原版 Qwen-7B-Chat 依赖的 `tokenizers==0.13.3` 不适合 Windows Python 3.12。

```powershell
conda activate p311
Set-Location D:\攻关项目\06-工具\standard_knowledge_service_outline
$env:PYTHONPATH = "src"
python --version
python -c "import sys; print(sys.executable)"
```

预期结果：Python 版本为 `3.11.x`，解释器路径指向 `p311` 环境，而不是 WindowsApps、其他 Conda 环境或系统 Python。失败判定：版本为 3.12，或安装依赖与执行程序使用了不同解释器。

### T02：安装测试所需依赖

基础后台与 pytest：

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

需要测试本地 Qwen 时：

```powershell
python -m pip install -e ".[llm]"
```

需要同时测试图数据库、机器学习模型和 HTTP 服务时：

```powershell
python -m pip install -e ".[llm,graph,ml,api,test]"
```

预期结果：最后出现 editable 安装成功信息，不能出现 `failed-wheel-build-for-install`。Qwen 依赖应为 `transformers==4.32.0` 和 `transformers-stream-generator==0.0.4`。

### T03：记录软硬件环境

```powershell
python -c "import platform,sys; print({'python':sys.version,'executable':sys.executable,'platform':platform.platform()})"
python -c "import torch; print({'torch':torch.__version__,'cuda_available':torch.cuda.is_available(),'cuda_version':torch.version.cuda,'gpu':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None})"
Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory
```

预期结果：命令正常输出环境信息。本地完整 Qwen-7B-Chat 的权重约 15.4 GB；CPU `float32` 加载建议至少有约 24–32 GB 可用内存。如果 Qwen 加载进度中途直接返回 PowerShell 且没有 Python 异常，通常是内存不足导致进程被系统终止。

## 2. 静态与依赖边界测试

### T04：Python 语法检查

```powershell
python -c "import ast,pathlib; files=list(pathlib.Path('src').rglob('*.py'))+list(pathlib.Path('tests').rglob('*.py')); [ast.parse(p.read_text(encoding='utf-8'),filename=str(p)) for p in files]; print({'syntax_ok':len(files)})"
```

预期结果：输出 `syntax_ok`，当前基线不少于 110 个 Python 文件；没有 `SyntaxError`。

### T05：未完成代码检查

```powershell
rg -n "NotImplementedError|TODO:.*未实现" src
```

预期结果：无匹配。`rg` 返回退出码 1 表示没有找到内容，是通过状态。

### T06：论文项目运行时隔离检查

```powershell
rg -n "D:\\攻关项目\\lunwen|from\s+lunwen|import\s+lunwen" src tests
```

预期结果：无匹配。工具代码必须使用已复制到自身目录的模型、数据和算法，不得在运行时调用 `D:\攻关项目\lunwen`。

## 3. 自动化测试

### T07：运行全部 pytest

```powershell
python -m pytest -q
```

预期结果：当前基线为 `45 passed`、`0 failed`。测试覆盖基础契约、查询分解、场景、图谱、一致性、推理、反馈、检索、原始规则正文、候选条款二次选择、统一配置、核验数据契约、ILR、协议候选指令、安全门禁、端到端编排和 Qwen 加载参数。

失败判定：出现任意 `FAILED`、测试收集错误或导入错误。测试失败后不得用忽略失败的方式继续发布。

### T08：没有 pytest 时的兼容执行

```powershell
python -c "import pathlib,runpy,tempfile,inspect,traceback; from pathlib import Path; passed=0; failed=[]; root=Path('.');
for f in sorted((root/'tests').glob('test_*.py')):
 ns=runpy.run_path(str(f))
 for name,fn in ns.items():
  if name.startswith('test_') and callable(fn):
   try:
    (fn(Path(tempfile.mkdtemp())) if 'tmp_path' in inspect.signature(fn).parameters else fn()); passed+=1
   except Exception as exc: failed.append((f.name,name,repr(exc))); traceback.print_exc()
print({'passed':passed,'failed':len(failed),'failures':failed}); raise SystemExit(bool(failed))"
```

预期结果：`passed` 为45、`failed` 为0，进程退出码为0。该方式只作为pytest暂时不可用时的诊断手段，正式验收仍以pytest及JUnit报告为准。

## 4. 本地 Qwen 分层测试

### T09：模型文件和权重索引完整性

```powershell
python -c "import json,pathlib; p=pathlib.Path('models/llm/qwen--Qwen-7B-Chat/snapshots/master'); idx=json.loads((p/'model.safetensors.index.json').read_text(encoding='utf-8')); missing=sorted({v for v in idx['weight_map'].values() if not (p/v).is_file()}); print({'config':(p/'config.json').is_file(),'shards':len(set(idx['weight_map'].values())),'has_lm_head':'lm_head.weight' in idx['weight_map'],'missing':missing})"
```

预期结果：`config=true`、`shards=8`、`has_lm_head=true`、`missing=[]`。

进一步验证第 8 个分片中的输出层权重：

```powershell
python -c "from safetensors import safe_open; p='models/llm/qwen--Qwen-7B-Chat/snapshots/master/model-00008-of-00008.safetensors'; f=safe_open(p,framework='pt',device='cpu'); print({'has_lm_head':'lm_head.weight' in f.keys(),'shape':tuple(f.get_tensor('lm_head.weight').shape)})"
```

预期结果：`has_lm_head=true`，形状为 `(151936, 4096)`。

### T10：Qwen 依赖版本

```powershell
python -c "import importlib.metadata as m; print({'transformers':m.version('transformers'),'stream_generator':m.version('transformers-stream-generator'),'tiktoken':m.version('tiktoken'),'accelerate':m.version('accelerate')})"
```

预期结果：Transformers 为 `4.32.0`，stream-generator 为 `0.0.4`；其他依赖能正常显示版本。若出现 `DisjunctiveConstraint`，执行：

```powershell
python -m pip uninstall -y transformers transformers-stream-generator
python -m pip install "transformers==4.32.0" "transformers-stream-generator==0.0.4" tiktoken accelerate einops
```

### T11：本地 Qwen 实际分解

```powershell
python -m standard_knowledge_service_v2.main --query "海上风电集电线路发生过流时应如何处理" --scenario "海上风电"
```

预期过程：显示 `Loading checkpoint shards: 100%`，随后输出 JSON。预期关键字段：

```json
{
  "data": {
    "decomposition": {
      "source": "local_qwen",
      "valid": true
    }
  }
}
```

失败判定：`source` 为 `raw_text_fallback` 且 `errors` 中包含模型加载异常；分片加载中途无异常退出；输出不是可解析 JSON。`FutureWarning: _register_pytree_node` 只是兼容性警告，不作为失败。

### T12：Qwen 不可用时的安全降级

模型不可用、依赖缺失或内存不足时，系统允许进入降级路径。预期结果：`source=raw_text_fallback`、`confidence=0.35`，同时 `warnings` 明确记录失败原因；系统仍能检索，但不得伪造模型分解结果或生成可下发指令。

## 5. 数据与知识图谱测试

### T13：原文—JSON 校核与校核集构图

日常回归先执行非破坏性数据契约测试：

```powershell
python -m pytest -q -m data
```

预期结果：3项通过，确认6674份JSON齐全、所有规则具有非空原始`content`、训练/测试拆分内容无差异，并核对961条人工复核记录。只有在原始Excel或分解JSON经过批准发生变化时，才重新生成校核数据。下面的`--clean`会覆盖现有生成目录，运行前应保存人工修订成果：

```powershell
python scripts/audit_json_decomposition.py --output datasets/lunwen/verified_json --clean
```

预期结果：`expected_json_files=6674`、`generated_json_files=6674`、`original_json_files_unique=6344`、`split_content_mismatch_count=0`。`修正对照表.xlsx` 与 `修正对照表.csv` 均含 6,676 条记录，其中包括 2 条 `skipped_blank_source_text` 原文空单元格记录。

再对校核后的 JSON 构图：

```powershell
python -m standard_knowledge_service_v2.knowledge_graph.create_graph datasets/lunwen/verified_json/json --summary artifacts/knowledge_graph/verified_build_summary.json
```

预期结果：命令退出码为 0，摘要满足下表基线。

| 指标 | 预期基线 |
| --- | ---: |
| `files_seen` | 6,674 |
| `files_succeeded` | 6,674 |
| `failures` | 空列表 |
| 实体记录 | 30,907 |
| 规则 | 11,850 |
| 显式关系 | 25,040 |
| 去重节点 | 21,850 |
| 总关系 | 81,008 |

任何 JSON 失败都必须进入 `failures`，不能静默丢弃。若数据集发生了经过批准的更新，应保存新旧统计差异并更新基线。

## 6. 检索与一致性评价测试

### T14：实体—规则检索烟雾测试

```powershell
python -c "from pathlib import Path; from standard_knowledge_service_v2.retrieval_engine import LocalLunwenRetrievalAdapter; from standard_knowledge_service_v2.retrieval import LunwenMatchingInput; a=LocalLunwenRetrievalAdapter.from_dataset(Path('datasets/lunwen/verified_json/json')); r=a.match(LunwenMatchingInput('气体密封性检测标准不大于1%/年',{'entities':[{'name':'气体密封性检测'}]},top_k_rules=3)); print({'entities':[(x.name,round(x.similarity,3)) for x in r.matched_entities[:3]],'rules':[(x.rule.rule_id,round(x.combined_score or 0,3),x.rule.content) for x in r.rules]})"
```

预期结果：首个实体为“气体密封性检测”、相似度为`1.0`，规则数量不超过3；每条返回规则的`content`均为非空原始正文。若数据经批准更新，不固定断言某个文件名，但必须人工核对前三条是否与查询主题相关。

### T14A：候选条款二次选择

```powershell
python -m pytest -q tests/test_content_reasoning_config.py::test_consistency_and_reasoning_can_replace_retrieval_top_one
```

预期结果：测试通过。该用例故意让不相关条款取得检索第一名，相关过流条款位于第二名；一致性评价和混合推理执行后，最终选择必须改为相关条款。失败说明主流程又退化为直接使用检索Top-1。

### T14B：统一配置装配

```powershell
python -c "from standard_knowledge_service_v2.bootstrap import build_application; a=build_application('configs/settings.example.yaml'); print({'units':len(a.facade.retriever.repository.units),'top_k':a.facade.retrieval_settings.selection_top_k,'qwen':str(a.facade.decomposer._decomposer.config.model_path)})"
```

预期结果：`units=6674`、`top_k=5`，Qwen路径指向工具目录中的`snapshots/master`。修改配置中的数据路径或阈值后，输出应同步改变；不存在的配置文件或数据目录必须明确报错。

### T15：数值约束一致与冲突

```powershell
python -c "from standard_knowledge_service_v2.consistency_evaluation import ConsistencyEvaluationService; s=ConsistencyEvaluationService(); a=s.compare('电压不大于1kV','电压不得大于1000V'); b=s.compare('温升不大于65K','温升不小于80K'); print({'equivalent':a.to_dict(),'conflict':b.to_dict()})"
```

预期结果：`equivalent.consistent=true`；`conflict.consistent=false`，并包含 `numeric_constraint` 冲突。若完整注意力模型无法加载，`model` 应明确标记透明权重降级分类器，不能把降级指标当成训练模型指标。

## 7. 混合推理、指令和安全测试

### T16：安全规则解释

```powershell
python -c "from standard_knowledge_service_v2.hybrid_reasoning import SafeRuleEngine; e=SafeRuleEngine(); print({'pass':e.evaluate(['温升 <= 65'],{'温升':60})[0].value,'fail':e.evaluate(['温升 <= 65'],{'温升':70})[0].value,'missing':e.evaluate(['温升 <= 65'],{})[0].value,'unparsed':e.evaluate(['执行任意代码()'],{})[0].value})"
```

预期结果：依次为 `pass`、`fail`、`uncertain`、`uncertain`。无法解析的表达式和缺少事实绝不能默认通过。

### T17：缺少协议配置

```powershell
python -c "from standard_knowledge_service_v2.domain import ScenarioContext; from standard_knowledge_service_v2.instruction_engine.models import SemanticTuple; from standard_knowledge_service_v2.instruction_engine import InstructionGenerationService; c=InstructionGenerationService().generate(SemanticTuple('集电线路','trip','集电线路'),ScenarioContext('offshore_wind','集电线路'),{},'IEC61850'); print(c)"
```

预期结果：`missing_fields` 至少包含 `device_id`、`logical_node`、`data_object`；`payload={}`；`dispatch_allowed=false`。

### T18：完整 IEC 61850 候选指令

```powershell
python -c "from standard_knowledge_service_v2.domain import ScenarioContext; from standard_knowledge_service_v2.instruction_engine.models import SemanticTuple; from standard_knowledge_service_v2.instruction_engine import InstructionGenerationService; cfg={'device_id':'CB-01','logical_node':'PTRC1','data_object':'Tr.general','protocol':'IEC61850'}; c=InstructionGenerationService().generate(SemanticTuple('集电线路','trip','集电线路'),ScenarioContext('offshore_wind','集电线路'),cfg,'IEC61850'); print(c)"
```

预期结果：`protocol='IEC61850'`、`target='CB-01'`，载荷包含 `service='MMS'`、`logical_node='PTRC1'` 和 `data_object='Tr.general'`；`dispatch_allowed` 仍为 `false`。

## 8. 端到端测试

### T19：最小自然语言输入

```powershell
python -m standard_knowledge_service_v2.main --query "气体密封性检测标准不大于1%/年"
```

预期结果：输出合法JSON，至少包含`request_id`、`status`、`decomposition`、`context`、`matching`、`selected_rule`、`candidate_assessments`、`evidence`、`validation`和`report`。`selected_rule.content`必须与首条证据的`quote`一致，报告正文必须出现相同原始条款正文；每个候选评价需包含`retrieval_score`、`consistency`、`reasoning`和`selection_score`。缺少设备配置时允许`status=uncertain`；所有情况下`candidate_instruction.dispatch_allowed=false`。

### T20：包含设备与协议配置的完整调用

```powershell
python -c "from standard_knowledge_service_v2.bootstrap import build_application; from standard_knowledge_service_v2.contracts import AnalysisRequest; app=build_application('configs/settings.example.yaml'); req=AnalysisRequest('海上风电集电线路发生过流时应如何处理','海上风电',parameters={'device_id':'CB-01','operating_state':'运行','device_type':'集电线路','device_config':{'device_id':'CB-01','logical_node':'PTRC1','data_object':'Tr.general','protocol':'IEC61850'}},target_protocol='IEC61850'); out=app.facade.analyze(req); print({'request_id':out.request_id,'status':out.status,'selected':out.data.get('selected_rule',{}),'candidate_count':len(out.data.get('candidate_assessments',[])),'evidence':len(out.evidence),'dispatch_allowed':out.data.get('candidate_instruction',{}).get('dispatch_allowed'),'audit':bool(app.audit_store.get(out.request_id))})"
```

预期结果：`request_id`非空、`selected.content`非空、`candidate_count`为1–5、`evidence>=1`、`dispatch_allowed=false`、`audit=true`。由于当前数据集的条款覆盖和模板匹配可能不足，`status`可以是`needs_human`、`uncertain`或`fail`，但不得是声称已执行控制的状态。

## 9. HTTP 服务测试

### T21：启动服务

```powershell
python -m standard_knowledge_service_v2.main --serve
```

预期结果：Uvicorn 启动并监听 `http://127.0.0.1:8000`，终端保持运行；没有模型调用时不会主动加载 Qwen。

### T22：健康检查

在另一个 PowerShell 终端执行：

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/health
```

预期结果：

```json
{"status":"ok","dispatch_allowed":false}
```

### T23：HTTP 分析与审计

```powershell
$body = @{query="海上风电集电线路发生过流时应如何处理"; scenario_hint="海上风电"} | ConvertTo-Json -Depth 8
$result = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/analyze -ContentType "application/json" -Body $body
$result | ConvertTo-Json -Depth 20
Invoke-RestMethod -Method Get -Uri ("http://127.0.0.1:8000/audit/" + $result.request_id)
```

预期结果：分析响应包含非空 `request_id`；审计接口返回相同 `request_id` 的输入和输出快照；候选指令仍不可下发。空 `query` 应返回 HTTP 422，不应返回服务器 500。

## 10. 业务反馈测试

### T24：反馈记录与优化建议

```powershell
python -c "from pathlib import Path; from tempfile import TemporaryDirectory; from standard_knowledge_service_v2.feedback import FeedbackRecord,FeedbackService,ErrorCategory; from standard_knowledge_service_v2.feedback.store import JsonlFeedbackStore;
with TemporaryDirectory() as d:
 s=FeedbackService(JsonlFeedbackStore(Path(d)/'feedback.jsonl'))
 [s.submit(FeedbackRecord(str(i),False,2,ErrorCategory.RETRIEVAL)) for i in range(2)]
 print({'snapshot':s.snapshot(),'proposals':[p.kind for p in s.optimization_proposals(minimum_samples=2)]})"
```

预期结果：样本数为 2，接受率为 0，生成 `retrieval_tuning` 建议；建议的 `requires_approval=true`，不得自动修改生产配置。

## 11. 回归与发布验收

每次修改模型、数据、检索权重、规则解释、指令模板、安全门禁或协议适配器后，至少重跑 T04–T08、T13–T20。修改 Qwen 加载代码或环境后，还需重跑 T09–T12。

发布必须同时满足：

| 验收项 | 通过标准 |
| --- | --- |
| 代码 | 语法检查通过，无 `NotImplementedError`。 |
| 自动化测试 | 当前45项或更新后的全部测试通过，0 failed。 |
| 数据与图谱 | 所有 JSON 处理成功，失败列表为空或每个失败均有处置记录。 |
| Qwen | 模型测试明确记录 `local_qwen` 或带原因的安全降级，不得静默失败。 |
| 检索证据 | 条款ID、`Rule.content`原文、来源路径和规则分数可追溯；证据与报告引用同一正文。 |
| 候选选择 | Top-K候选均保留一致性和推理轨迹，最终条款按配置权重选择，不直接固定采用Top-1。 |
| 配置 | 模型路径、数据路径、检索阈值、一致性阈值和选择权重均由YAML生效。 |
| 指令安全 | 所有候选指令 `dispatch_allowed=false`，缺少协议配置时不产生控制载荷。 |
| 不确定性 | 规则不可解析、事实缺失、条款冲突时返回 `uncertain` 或 `fail`。 |
| 审计与报告 | 请求可按 `request_id` 查询，报告事实与结构化结果一致。 |
| 项目隔离 | 不导入或调用论文项目目录，不包含真实设备下发路径。 |

测试产物应保存到 `artifacts/test_reports/<日期或版本>/`，至少包括环境版本、执行命令、测试日志、构图统计、模型/配置/数据指纹、评测指标、失败样例和修复结论。

## 12. 常见失败与处理

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `No module named tiktoken` | Qwen 依赖未装入当前解释器 | 在同一环境执行 `python -m pip install -e ".[llm]"`。 |
| `DisjunctiveConstraint` 导入失败 | Transformers 与 stream-generator 版本不兼容 | 固定为 4.32.0 与 0.0.4。 |
| `tokenizers` 要求 Rust | Python 3.12 没有旧版 tokenizers 轮子 | 使用 Python 3.11 环境。 |
| `KeyError: lm_head.weight` | 旧 Qwen 与自动设备映射不兼容 | 使用当前已修复的加载器，不传 `device_map="auto"`。 |
| 分片加载中途直接回到终端 | 可用内存不足或进程被系统终止 | 查看 `$LASTEXITCODE`，释放内存、使用 GPU/量化模型或降级。 |
| `source=raw_text_fallback` | 模型加载、生成或 JSON 校验失败 | 查看 `decomposition.errors`；该状态本身是安全降级。 |
| 检索到不相关条款 | 分解实体不足、词法降级或数据覆盖不足 | 先确认 `source=local_qwen`，再检查实体、场景过滤和检索分数。 |
