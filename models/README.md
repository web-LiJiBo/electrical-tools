# 项目模型目录

本目录仅存放“机器可读标准知识服务应用工具”的项目模型资产，与 `lunwen/` 论文复现实验目录严格分离。

预期结构：

```text
models/
├── llm/
│   └── qwen--Qwen-7B-Chat/    # 大模型查询分解与结构化抽取
├── embedding/
│   ├── finetuned_sbert/       # 论文微调文本匹配模型
│   └── sbert/                 # 论文对照文本匹配模型
├── consistency/
│   └── classifier_model/      # 论文现有的一致性消融分类器
└── manifests/
    ├── llm.json
    ├── embedding.json
    └── consistency.json
```

文本匹配模型与现有分类权重已从论文工程复制到本目录。当前主流程使用
`attention_model.pt`：权重元数据声明 `input_dim=3`、`hidden_dim=64`、`dropout_rate=0.3`，
网络包含三层注意力头、BatchNorm与两层分类头。运行时按“规则集相似度、数值约束相似度、
语义/关键词重叠相似度”的顺序输入三个特征。`attention_w/`下的文件仅用于消融对照，
不作为默认运行模型。项目默认环境安装 PyTorch；已配置权重无法加载时直接报错，不再静默降级。
正式对外发布前仍应补充文件哈希、特征定义和固定数据集评测结果的模型清单。
