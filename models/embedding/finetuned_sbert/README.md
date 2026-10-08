---
tags:
- sentence-transformers
- sentence-similarity
- feature-extraction
- dense
- generated_from_trainer
- dataset_size:2124
- loss:CosineSimilarityLoss
widget:
- source_sentence: 紧线弧垂允许偏差：1、一般情况下允许偏差不应超过±2.5%，2、跨越通航河流的大跨越档弧垂允许偏差不应大于±1%，其正偏差不应超过1m
  sentences:
  - 为了确保电缆能顺利穿管并不损伤电缆护层，在电缆敷设前疏通管路并清除杂物是必要的。疏通时可用直径不小于0.85倍管孔直径、长度约600mm的钢管来回疏通，再用与管孔等直径的钢丝刷清除管内杂物
  - 导、地线弧垂允许偏差：220kV及以上线路为+3.0%、-2.5%
  - 锚孔直径D=(2.5～3)d，直径不小于90mm，尚应符合d+50mm的要求
- source_sentence: 尺寸偏差要求：结构高度偏差±（0.03d+0.3）mm，6片串结构高度偏差不大于±19mm
  sentences:
  - 管的内径不宜小于电缆外径或多根电缆包络外径的1.5倍，一般不宜小于100mm
  - 尺寸偏差要求：绝缘子串的结构高度偏差为±0.024nH（n表示6只绝缘子）。对于330kV及以上线路使用绝缘子，6个绝缘子串的结构高度偏差应不超过±19mm
  - 方位标志（桩）装设位置：电缆两端、电缆直线段50m～100m处，电缆接头及电缆改变方向的弯角处
- source_sentence: 温度类别覆盖的温度范围为：‐50℃～+50℃
  sentences:
  - 电缆接头安装时必须严格控制施工现场的温度、湿度与清洁程度。温度宜控制在10℃～30℃，当温度超出允许范围时，应采取适当措施
  - 每个封闭压力系统或隔室允许的相对年漏气率应不大于0.5%
  - 排管通道所选用排管内径不应小于1.5倍电缆外径，并不小于Φ150mm。同一段排管通道的排管内径选择不宜多余2种。
- source_sentence: 31500kV•A及以上的66kV变压器在运输中应装三维冲撞记录仪。
  sentences:
  - 220kV、330kV、500kV变压器在运输中应装三维冲撞记录仪。
  - 接地网电气完整性试验即对同一接地网的各相邻设备接地线之间的电气导通情况进行测量，以直流电阻值表示。首先选定一个很可能与主地网连接良好的设备的接地引下线为参考点，再测试周围电气设备接地部分与参考点之间的直流电阻。如果开始即有很多设备测试结果不良，宜考虑更换参考点。
  - 晶闸管级的保护触发和闭锁抽查试验，抽查数量不少于晶闸管级总数的20%
- source_sentence: 水底电缆技术要求：“c)水底电缆敷设应平放水底，不得悬空。条件允许时，应尽可能埋设在河床下，浅水区的埋深不宜小于0.5m，深水航道的埋深不宜小于2m。不能深埋时，应有防止外力破坏措施；
  sentences:
  - 现场交接试验，GB50150适用。
  - 防火墙的耐火极限不宜小于4h
  - 交接试验时，应在交流耐压试验的同时进行局放检测。
pipeline_tag: sentence-similarity
library_name: sentence-transformers
metrics:
- pearson_cosine
- spearman_cosine
model-index:
- name: SentenceTransformer
  results:
  - task:
      type: semantic-similarity
      name: Semantic Similarity
    dataset:
      name: val
      type: val
    metrics:
    - type: pearson_cosine
      value: 0.9172493331965504
      name: Pearson Cosine
    - type: spearman_cosine
      value: 0.8355570133146792
      name: Spearman Cosine
---

# SentenceTransformer

This is a [sentence-transformers](https://www.SBERT.net) model trained. It maps sentences & paragraphs to a 256-dimensional dense vector space and can be used for semantic textual similarity, semantic search, paraphrase mining, text classification, clustering, and more.

## Model Details

### Model Description
- **Model Type:** Sentence Transformer
<!-- - **Base model:** [Unknown](https://huggingface.co/unknown) -->
- **Maximum Sequence Length:** 64 tokens
- **Output Dimensionality:** 256 dimensions
- **Similarity Function:** Cosine Similarity
<!-- - **Training Dataset:** Unknown -->
<!-- - **Language:** Unknown -->
<!-- - **License:** Unknown -->

### Model Sources

- **Documentation:** [Sentence Transformers Documentation](https://sbert.net)
- **Repository:** [Sentence Transformers on GitHub](https://github.com/huggingface/sentence-transformers)
- **Hugging Face:** [Sentence Transformers on Hugging Face](https://huggingface.co/models?library=sentence-transformers)

### Full Model Architecture

```
SentenceTransformer(
  (0): Transformer({'max_seq_length': 64, 'do_lower_case': False, 'architecture': 'BertModel'})
  (1): Pooling({'word_embedding_dimension': 768, 'pooling_mode_cls_token': False, 'pooling_mode_mean_tokens': True, 'pooling_mode_max_tokens': False, 'pooling_mode_mean_sqrt_len_tokens': False, 'pooling_mode_weightedmean_tokens': False, 'pooling_mode_lasttoken': False, 'include_prompt': True})
  (2): Dense({'in_features': 768, 'out_features': 256, 'bias': True, 'activation_function': 'torch.nn.modules.activation.Tanh'})
)
```

## Usage

### Direct Usage (Sentence Transformers)

First install the Sentence Transformers library:

```bash
pip install -U sentence-transformers
```

Then you can load this model and run inference.
```python
from sentence_transformers import SentenceTransformer

# Download from the 🤗 Hub
model = SentenceTransformer("sentence_transformers_model_id")
# Run inference
sentences = [
    '水底电缆技术要求：“c)水底电缆敷设应平放水底，不得悬空。条件允许时，应尽可能埋设在河床下，浅水区的埋深不宜小于0.5m，深水航道的埋深不宜小于2m。不能深埋时，应有防止外力破坏措施；',
    '防火墙的耐火极限不宜小于4h',
    '现场交接试验，GB50150适用。',
]
embeddings = model.encode(sentences)
print(embeddings.shape)
# [3, 256]

# Get the similarity scores for the embeddings
similarities = model.similarity(embeddings, embeddings)
print(similarities)
# tensor([[ 1.0000, -0.0359, -0.1859],
#         [-0.0359,  1.0000,  0.0573],
#         [-0.1859,  0.0573,  1.0000]])
```

<!--
### Direct Usage (Transformers)

<details><summary>Click to see the direct usage in Transformers</summary>

</details>
-->

<!--
### Downstream Usage (Sentence Transformers)

You can finetune this model on your own dataset.

<details><summary>Click to expand</summary>

</details>
-->

<!--
### Out-of-Scope Use

*List how the model may foreseeably be misused and address what users ought not to do with the model.*
-->

## Evaluation

### Metrics

#### Semantic Similarity

* Dataset: `val`
* Evaluated with [<code>EmbeddingSimilarityEvaluator</code>](https://sbert.net/docs/package_reference/sentence_transformer/evaluation.html#sentence_transformers.evaluation.EmbeddingSimilarityEvaluator)

| Metric              | Value      |
|:--------------------|:-----------|
| pearson_cosine      | 0.9172     |
| **spearman_cosine** | **0.8356** |

<!--
## Bias, Risks and Limitations

*What are the known or foreseeable issues stemming from this model? You could also flag here known failure cases or weaknesses of the model.*
-->

<!--
### Recommendations

*What are recommendations with respect to the foreseeable issues? For example, filtering explicit content.*
-->

## Training Details

### Training Dataset

#### Unnamed Dataset

* Size: 2,124 training samples
* Columns: <code>sentence_0</code>, <code>sentence_1</code>, and <code>label</code>
* Approximate statistics based on the first 1000 samples:
  |         | sentence_0                                                                        | sentence_1                                                                        | label                                                          |
  |:--------|:----------------------------------------------------------------------------------|:----------------------------------------------------------------------------------|:---------------------------------------------------------------|
  | type    | string                                                                            | string                                                                            | float                                                          |
  | details | <ul><li>min: 11 tokens</li><li>mean: 48.9 tokens</li><li>max: 64 tokens</li></ul> | <ul><li>min: 9 tokens</li><li>mean: 48.24 tokens</li><li>max: 64 tokens</li></ul> | <ul><li>min: 0.0</li><li>mean: 0.42</li><li>max: 1.0</li></ul> |
* Samples:
  | sentence_0                                                                                                                                                                                                                                | sentence_1                                                                                                                                                 | label            |
  |:------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------|:-----------------|
  | <code>红外热像检测电缆终端、中间接头、电缆分支处及接地线（如可测），红外热像图显示应无异常温升、温差和/或相对温差。测量和分析方法参考DL/T664‐2008。检测时，应注意对电缆线路各处分别进行测量，避免遗漏测量部位；电缆带电运行时间应该在24小时以上，最好在设备负荷高峰状态下进行；尽量移开或避开电缆与测温仪之间的遮挡物，记录环境温度、负荷及其近3小时内的变化情况，以便分析参考。当电缆线路负荷较重（超过50%）时，应适当缩短红外热像检测周期</code> | <code>a)红外热像设备应图像清晰、稳定，工作可靠。具备超设定值报警以及必要的图像分析功能、热像储存、数据传输功能；具备单点或多点温度显示功能；显示空间分辨率应能满足绝热缺陷测温要求，或具备按照检测模式进行选择能力；b)红外热像设备的检测方法、判断依据及绝热效果评价应按DL/T907执行；</code> | <code>1.0</code> |
  | <code>管的内径不宜小于电缆外径或多根电缆包络外径的1.5倍，一般不宜小于100mm</code>                                                                                                                                                                                       | <code>电缆管配置及敷设。电缆管内径按设计规定，且不小于1.5倍电缆外径用尺检查。管内畅通检查光滑，无积水、杂物用0.85倍管内径拉线球检查</code>                                                                            | <code>1.0</code> |
  | <code>绝缘油水分限值要求：≤10mg/L</code>                                                                                                                                                                                                            | <code>拉线应采用镀锌钢绞线，其截面应按受力情况计算确定，且不应小于25mm2</code>                                                                                                           | <code>0.0</code> |
* Loss: [<code>CosineSimilarityLoss</code>](https://sbert.net/docs/package_reference/sentence_transformer/losses.html#cosinesimilarityloss) with these parameters:
  ```json
  {
      "loss_fct": "torch.nn.modules.loss.MSELoss"
  }
  ```

### Training Hyperparameters
#### Non-Default Hyperparameters

- `per_device_train_batch_size`: 16
- `num_train_epochs`: 10
- `fp16`: True
- `eval_strategy`: steps
- `per_device_eval_batch_size`: 16
- `multi_dataset_batch_sampler`: round_robin

#### All Hyperparameters
<details><summary>Click to expand</summary>

- `per_device_train_batch_size`: 16
- `num_train_epochs`: 10
- `max_steps`: -1
- `learning_rate`: 5e-05
- `lr_scheduler_type`: linear
- `lr_scheduler_kwargs`: None
- `warmup_steps`: 0
- `optim`: adamw_torch_fused
- `optim_args`: None
- `weight_decay`: 0.0
- `adam_beta1`: 0.9
- `adam_beta2`: 0.999
- `adam_epsilon`: 1e-08
- `optim_target_modules`: None
- `gradient_accumulation_steps`: 1
- `average_tokens_across_devices`: True
- `max_grad_norm`: 1
- `label_smoothing_factor`: 0.0
- `bf16`: False
- `fp16`: True
- `bf16_full_eval`: False
- `fp16_full_eval`: False
- `tf32`: None
- `gradient_checkpointing`: False
- `gradient_checkpointing_kwargs`: None
- `torch_compile`: False
- `torch_compile_backend`: None
- `torch_compile_mode`: None
- `use_liger_kernel`: False
- `liger_kernel_config`: None
- `use_cache`: False
- `neftune_noise_alpha`: None
- `torch_empty_cache_steps`: None
- `auto_find_batch_size`: False
- `log_on_each_node`: True
- `logging_nan_inf_filter`: True
- `include_num_input_tokens_seen`: no
- `log_level`: passive
- `log_level_replica`: warning
- `disable_tqdm`: False
- `project`: huggingface
- `trackio_space_id`: trackio
- `eval_strategy`: steps
- `per_device_eval_batch_size`: 16
- `prediction_loss_only`: True
- `eval_on_start`: False
- `eval_do_concat_batches`: True
- `eval_use_gather_object`: False
- `eval_accumulation_steps`: None
- `include_for_metrics`: []
- `batch_eval_metrics`: False
- `save_only_model`: False
- `save_on_each_node`: False
- `enable_jit_checkpoint`: False
- `push_to_hub`: False
- `hub_private_repo`: None
- `hub_model_id`: None
- `hub_strategy`: every_save
- `hub_always_push`: False
- `hub_revision`: None
- `load_best_model_at_end`: False
- `ignore_data_skip`: False
- `restore_callback_states_from_checkpoint`: False
- `full_determinism`: False
- `seed`: 42
- `data_seed`: None
- `use_cpu`: False
- `accelerator_config`: {'split_batches': False, 'dispatch_batches': None, 'even_batches': True, 'use_seedable_sampler': True, 'non_blocking': False, 'gradient_accumulation_kwargs': None}
- `parallelism_config`: None
- `dataloader_drop_last`: False
- `dataloader_num_workers`: 0
- `dataloader_pin_memory`: True
- `dataloader_persistent_workers`: False
- `dataloader_prefetch_factor`: None
- `remove_unused_columns`: True
- `label_names`: None
- `train_sampling_strategy`: random
- `length_column_name`: length
- `ddp_find_unused_parameters`: None
- `ddp_bucket_cap_mb`: None
- `ddp_broadcast_buffers`: False
- `ddp_backend`: None
- `ddp_timeout`: 1800
- `fsdp`: []
- `fsdp_config`: {'min_num_params': 0, 'xla': False, 'xla_fsdp_v2': False, 'xla_fsdp_grad_ckpt': False}
- `deepspeed`: None
- `debug`: []
- `skip_memory_metrics`: True
- `do_predict`: False
- `resume_from_checkpoint`: None
- `warmup_ratio`: None
- `local_rank`: -1
- `prompts`: None
- `batch_sampler`: batch_sampler
- `multi_dataset_batch_sampler`: round_robin
- `router_mapping`: {}
- `learning_rate_mapping`: {}

</details>

### Training Logs
| Epoch | Step | val_spearman_cosine |
|:-----:|:----:|:-------------------:|
| 1.0   | 133  | 0.8356              |


### Framework Versions
- Python: 3.12.12
- Sentence Transformers: 5.3.0
- Transformers: 5.3.0
- PyTorch: 2.11.0+cpu
- Accelerate: 1.13.0
- Datasets: 4.8.4
- Tokenizers: 0.22.2

## Citation

### BibTeX

#### Sentence Transformers
```bibtex
@inproceedings{reimers-2019-sentence-bert,
    title = "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks",
    author = "Reimers, Nils and Gurevych, Iryna",
    booktitle = "Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing",
    month = "11",
    year = "2019",
    publisher = "Association for Computational Linguistics",
    url = "https://arxiv.org/abs/1908.10084",
}
```

<!--
## Glossary

*Clearly define terms in order to be accessible across audiences.*
-->

<!--
## Model Card Authors

*Lists the people who create the model card, providing recognition and accountability for the detailed work that goes into its construction.*
-->

<!--
## Model Card Contact

*Provides a way for people who have updates to the Model Card, suggestions, or questions, to contact the Model Card authors.*
-->