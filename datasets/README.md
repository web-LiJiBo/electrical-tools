# 数据集目录

`lunwen/` 保存从 `代码/xiangmu/lunwen` 复制的论文数据资产：

- `data/2017.xlsx`：文本匹配、分类训练和评测的源数据集；
- `output_jsons/train|test`：大模型产生的原始条款分解 JSON；
- `output_jsons_new/train|test`：重新分配到固定训练集和测试集的条款分解 JSON。

工具默认使用 `output_jsons_new` 进行训练和评测，保留 `output_jsons` 用于数据来源追溯。
这些文件是数据资产，不应从运行时业务请求中直接覆盖。
