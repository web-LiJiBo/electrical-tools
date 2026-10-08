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

文本匹配模型与现有分类权重已从 `代码/xiangmu/lunwen` 复制到本目录。源目录没有完整的
`attention_model.pt`，只有“不使用数值约束相似度”和“不使用规则集相似度”两个消融模型，
因此配置中将它们登记为候选模型，不将任意一个冒充完整分类模型。正式使用前仍需核验文件哈希和固定数据集评测结果。
