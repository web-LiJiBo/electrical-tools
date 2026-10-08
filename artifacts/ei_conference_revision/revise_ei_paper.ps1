param(
  [string]$InputPath = "artifacts\\ei_conference_revision\\KG-HCR_EI会议论文润色版.docx"
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Add-ChildElement([System.Xml.XmlDocument]$Xml, [System.Xml.XmlElement]$Parent, [string]$Name) {
  $node = $Xml.CreateElement('w', $Name, 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')
  [void]$Parent.AppendChild($node)
  return $node
}

function Set-Attribute([System.Xml.XmlElement]$Node, [string]$Name, [string]$Value) {
  $attr = $Node.OwnerDocument.CreateAttribute('w', $Name, 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')
  $attr.Value = $Value
  [void]$Node.Attributes.SetNamedItem($attr)
}

function Set-ParagraphText([System.Xml.XmlDocument]$Xml, $Ns, [System.Xml.XmlElement]$Paragraph, [string]$Text) {
  $firstRunProps = $Paragraph.SelectSingleNode('.//w:rPr', $Ns)
  $pPr = $Paragraph.SelectSingleNode('w:pPr', $Ns)
  $children = @($Paragraph.ChildNodes)
  foreach ($child in $children) {
    if ($child -ne $pPr) { [void]$Paragraph.RemoveChild($child) }
  }
  $run = Add-ChildElement $Xml $Paragraph 'r'
  if ($firstRunProps) { [void]$run.AppendChild($firstRunProps.CloneNode($true)) }
  $t = Add-ChildElement $Xml $run 't'
  $space = $Xml.CreateAttribute('xml', 'space', 'http://www.w3.org/XML/1998/namespace')
  $space.Value = 'preserve'
  [void]$t.Attributes.SetNamedItem($space)
  $t.InnerText = $Text
}

function Set-ParagraphStyle([System.Xml.XmlDocument]$Xml, $Ns, [System.Xml.XmlElement]$Paragraph, [int]$HalfPoints, [bool]$Bold, [string]$Align, [int]$Before, [int]$After) {
  $pPr = $Paragraph.SelectSingleNode('w:pPr', $Ns)
  if (-not $pPr) { $pPr = Add-ChildElement $Xml $Paragraph 'pPr'; [void]$Paragraph.PrependChild($pPr) }
  $jc = $pPr.SelectSingleNode('w:jc', $Ns)
  if (-not $jc) { $jc = Add-ChildElement $Xml $pPr 'jc' }
  Set-Attribute $jc 'val' $Align
  $spacing = $pPr.SelectSingleNode('w:spacing', $Ns)
  if (-not $spacing) { $spacing = Add-ChildElement $Xml $pPr 'spacing' }
  Set-Attribute $spacing 'before' "$Before"
  Set-Attribute $spacing 'after' "$After"
  Set-Attribute $spacing 'line' '240'
  Set-Attribute $spacing 'lineRule' 'auto'
  foreach ($run in $Paragraph.SelectNodes('.//w:r', $Ns)) {
    $rPr = $run.SelectSingleNode('w:rPr', $Ns)
    if (-not $rPr) { $rPr = Add-ChildElement $Xml $run 'rPr'; [void]$run.PrependChild($rPr) }
    $fonts = $rPr.SelectSingleNode('w:rFonts', $Ns)
    if (-not $fonts) { $fonts = Add-ChildElement $Xml $rPr 'rFonts' }
    Set-Attribute $fonts 'ascii' 'Times New Roman'
    Set-Attribute $fonts 'hAnsi' 'Times New Roman'
    Set-Attribute $fonts 'eastAsia' 'SimSun'
    $sz = $rPr.SelectSingleNode('w:sz', $Ns)
    if (-not $sz) { $sz = Add-ChildElement $Xml $rPr 'sz' }
    Set-Attribute $sz 'val' "$HalfPoints"
    $szCs = $rPr.SelectSingleNode('w:szCs', $Ns)
    if (-not $szCs) { $szCs = Add-ChildElement $Xml $rPr 'szCs' }
    Set-Attribute $szCs 'val' "$HalfPoints"
    $b = $rPr.SelectSingleNode('w:b', $Ns)
    if ($Bold -and -not $b) { [void](Add-ChildElement $Xml $rPr 'b') }
    if (-not $Bold -and $b) { [void]$rPr.RemoveChild($b) }
  }
}

$input = (Resolve-Path $InputPath).Path
$workingRoot = Join-Path $env:TEMP ('kg_hcr_ei_' + [guid]::NewGuid().ToString('N'))
$zipPath = Join-Path $workingRoot 'paper.zip'
$expanded = Join-Path $workingRoot 'expanded'
New-Item -ItemType Directory -Path $workingRoot | Out-Null
Copy-Item -LiteralPath $input -Destination $zipPath
Expand-Archive -LiteralPath $zipPath -DestinationPath $expanded -Force

$documentXml = Join-Path $expanded 'word\\document.xml'
[xml]$xml = Get-Content -Raw -Encoding UTF8 -LiteralPath $documentXml
$ns = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
$ns.AddNamespace('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')
$paragraphs = @($xml.SelectNodes('//w:body/w:p', $ns))

# Revision is deliberately evidence-preserving: no new experimental values are introduced.
$replacements = @{
  16 = '摘要—电力标准条款的一致性评估是标准数字化、自动审查与知识服务的基础能力。现有字面匹配难以识别同义改写，单一语义向量又常忽略专业实体、适用条件以及数值和比较方向等决定性约束。为此，本文提出 KG-HCR（Knowledge Graph-enhanced Hybrid Retrieval and Constraint-aware Reranking）框架，将规则知识图谱增强的候选检索、排名级融合和字段级约束校验统一到可追溯的一致性判定链路中。该框架从条款对抽取实体、关系与规范性规则字段，训练面向电力标准的领域 SBERT，并仅使用训练集结构化记录构建规则知识图谱；推理时联合领域 SBERT 稠密检索、BM25 稀疏检索与图谱实体锚定召回，采用倒数秩融合整合候选，再依据主体、动作、条件、单位、数值和比较方向进行约束感知重排序。随后，以双向规则证据聚合和 31 维多粒度匹配特征驱动梯度提升分类器，输出一致性概率、支撑规则及冲突字段。在 595 对独立测试条款上的实验中，KG-HCR 获得 97.48% 的 Accuracy、97.22% 的 Precision、96.84% 的 Recall、97.03% 的 F1 和 0.9939 的 AUC。基线、消融、ROC 与案例分析共同表明，BM25、知识图谱、RRF 和约束感知重排序分别提升术语保真、结构关联、排名稳健性和条件冲突抑制能力。'
  17 = '关键词—电力标准；条款一致性评估；规则知识图谱；混合检索；倒数秩融合；约束感知重排序；可解释人工智能'
  19 = '新能源并网、电力电子装备接入和智能运维技术的快速演进持续提升电力系统的复杂度。电力标准以规范性条款约束设备设计、试验、运行与检修，是新型电力系统技术治理和标准数字化的重要依据[1]—[3]。在标准审查、条款整合与知识服务中，自动判断不同来源条款在技术对象、适用条件和阈值要求上是否一致，已成为把自然语言标准转化为机器可读规则的关键环节。'
  20 = '然而，条款一致性并非一般语义相似度任务。关键词匹配易受同义表达、缩写和上下文省略影响；句向量相似度则可能掩盖电压等级、设备型号、单位、数量级、否定词和上下界等决定性差异。电力标准条款通常同时包含主体、动作、适用条件和数值约束，即使两条文本语义接近，只要关键条件或比较方向不一致，工程含义便可能相反。因此，可靠评估必须同时兼顾语义等价、术语精确性、实体关联和字段约束。'
  21 = '本文提出 KG-HCR，将知识图谱增强检索、排名级融合、字段级约束校验和可解释分类串联为统一的证据闭环。与仅使用句对分类或单路检索的方法相比，KG-HCR 先通过稠密、稀疏和图谱三路召回建立互补候选空间，再以 RRF 降低不同检索器分值尺度差异，最后以结构化字段与数值冲突对候选进行二次校准，并将双侧规则证据显式反馈给最终判定。'
  22 = '本文的主要贡献如下：'
  23 = '• 提出面向规范性电力条款的一体化一致性评估框架，将结构化规则抽取、领域 SBERT、规则知识图谱、候选融合、约束重排序和可解释判定连接为闭环流程。'
  24 = '• 设计 Dense—BM25—KG 三路混合召回与 RRF 融合机制，使语义改写、专业词项、单位数值和实体关系能够在同一候选空间中互补，并保留每条候选的来源证据。'
  25 = '• 提出字段级约束感知重排序和双向规则证据聚合，显式建模主体、动作、条件、单位、比较方向及数值冲突，减少“文本相近但工程约束不一致”的误判。'
  26 = '• 在真实电力标准差异条款数据上采用统一训练、验证与测试协议，报告基线比较、模块消融、ROC 曲线和可追溯案例，并分析数据划分和图谱覆盖范围对结论有效性的边界。'
  31 = '现有标准数字化研究主要关注条款的结构化表达、语义互操作和自动合规检查[2], [3]。电力知识图谱已服务于故障诊断、设备运维和电网知识服务，其质量、实体规范化与关系覆盖范围直接影响下游推理效果[4]—[6]。但面向规范性条款一致性评估时，图谱不应只承担背景知识存储角色，还需要为候选规则提供可检索、可核验的结构化证据。本文保留主体、动作、条件、约束和单位等字段，使图谱检索能够与后续冲突检查形成衔接。'
  33 = 'BM25 对标准号、设备名称、单位和数值具有较高的字面敏感性[7]；SBERT 及对比学习句向量适合处理同义改写和语序变化[8], [9]。DPR、ColBERT 和 RAG 分别从稠密表示、细粒度词项交互和外部证据利用角度推动了检索增强方法[10]—[12]。不过，通用混合检索通常以相关性为目标，较少显式处理规范性条款中的适用条件、数量级、比较方向和否定逻辑。RRF 以排名而非原始分数融合候选，在异构检索器之间具有稳健性[13]；本文进一步以结构化字段约束对其结果进行二次校准。'
  35 = '既有条款一致性研究多将任务处理为句对分类或相似度判定，误报原因往往难以定位到实体不一致、动作差异或阈值冲突。梯度提升模型能够刻画稠密分数、词项统计、实体重合与数值特征之间的非线性交互[14]。本文的区别在于：分类器并不直接依赖原始句对，而是基于双侧检索证据、字段匹配和冲突特征作出判断，并将结果组织为“结论—支撑规则—冲突字段”的可审计输出。'
  38 = '给定待评估条款对 (c_a, c_b)，目标是预测一致性标签 y ∈ {0, 1}，并返回支撑结论的规则证据集合。每条条款被规范化为包含 entities、relations 和 rules 的结构化 JSON，其中 rules 进一步包含主体、动作、条件、约束和单位字段。仅由训练集构建规则知识图谱 G = (V, E)，V 包含实体、关系和规则节点，E 表示实体—关系—规则之间的关联。系统分别从 c_a 与 c_b 生成候选证据集合，再计算双向匹配与冲突特征，输出一致性概率及其可追溯依据。'
  40 = '结构化抽取采用固定字段模式，将每条条款转换为实体、关系和规则三类记录。实体记录包含名称、类型和描述；关系记录包含源实体、目标实体和关系类型；规则记录包含原文、主体、动作、条件、约束、单位和关联实体。该统一表示将自然语言中的条件和阈值转化为可比较字段，并为图谱检索、约束校验和结果解释提供公共接口。'
  41 = '本研究仅使用训练集的有效 JSON 构建知识图谱，以避免测试条款直接进入候选知识库。导入前对实体名称和单位进行规范化，按文档、实体和规则标识去重，并将无法匹配的关系记录在质量日志中。最终得到 2240 条去重规则、2874 个实体和 4151 条关系。对于输入条款，系统先完成实体锚定，再在锚定实体及其一跳邻域中收集关联规则，以补充文本检索难以发现的领域关联。'
  45 = '训练采用 CosineSimilarityLoss，批量大小为 16，最多训练 10 个 epoch，warm-up steps 为 100，验证比例为 20%，evaluation steps 为 500，early-stopping patience 为 5。训练完成后的编码器同时用于稠密召回和规则证据相似度计算，从而避免检索空间与判定特征使用不一致的语义表示。'
  47 = '系统通过 BM25 获得稀疏词项分数，重点保留设备名称、标准号、电压等级、单位和数值等高精度命中[7]。图谱通道先将条款实体链接到规范化实体，再收集锚定实体及其一跳邻域关联的规则。每个通道保留前 K 个候选，并通过并集形成候选集合。'
  49 = '稠密通道处理语义等价，BM25 通道保障术语和数值命中，图谱通道补充实体与关系结构。由于不同通道的原始分值不可直接比较，本文将其转换为通道内排名，并采用 RRF 进行排名级融合。该设计使多路均获得较好名次的规则自然优先，同时降低单一路径异常高分对候选排序的影响。'
  52 = 'RRF 融合后的候选仍可能出现“主题相关而工程约束不匹配”的情况，因此需要进一步执行字段级约束校验。系统从输入条款和候选规则中提取主体、动作、条件、约束和单位字段，计算实体重合、字段相似、数值匹配、比较方向一致性和冲突计数。'
  55 = '其中，数值匹配同时考察单位归一化、数量级、上下界和比较方向；冲突项覆盖单位不兼容、阈值区间不相交及否定词相反等情形。重排序后保留 Top-10 规则作为最终证据。带独立约束召回通道的 Full 版本作为受控变体报告，用于区分字段约束作用与额外召回通道带来的影响。'
  58 = '设两条待评估条款的重排序规则集合分别为 R_a 和 R_b，系统计算任意规则对的语义相似度、实体重合度与字段一致性，并以单向最大匹配构成双向证据聚合。双向聚合能够减轻两侧规则数量不同造成的偏置，使一侧缺少充分支撑规则时不会被单边高分掩盖。'
  63 = '系统从稠密和稀疏最高分、RRF 统计量、实体重合、规则双向相似度、四类字段匹配、数值匹配/冲突和证据覆盖度构造 31 维特征。分类器采用 HistGradientBoostingClassifier，学习率为 0.05，最大迭代轮数为 250，最大叶节点数为 15，正则化系数为 1.0，并使用类别平衡权重。阈值仅在训练集内部验证子集上以 F1 最大化原则选择，测试集只用于一次最终评估。除标签外，系统同步返回 Top-10 规则、结构化字段和各通道召回来源。'
  68 = '实验数据来自《电网设备技术标准差异条款统一意见（2017）》相关资料，原始数据包含 3337 对带标签条款。经结构化记录完整性检查后，得到 3023 对可用于实验的条款，其中训练集 2428 对、测试集 595 对。训练集包含 1416 对不一致样本和 1012 对一致样本；测试集包含 342 对不一致样本和 253 对一致样本。所有数据清洗、图谱构建、模型训练和阈值选择均在训练集及其内部验证划分上完成，随机种子固定为 42。'
  69 = '知识图谱仅由训练集 JSON 构建，测试条款独立解析并映射到训练期知识空间。稠密、BM25 和图谱通道的候选规模均为 50，最终证据规模为 10。分类阈值在训练集内部按 85%/15% 划分验证子集，以 F1 最大化为准选择；测试集只评估一次。评价指标包括 Accuracy、Precision、Recall、F1 和 ROC-AUC，其中 F1 作为主指标，以兼顾一致和不一致条款的识别质量。'
  71 = '对比方法包括：（1）TF-IDF+LR，以词项统计和条款对交互特征训练逻辑回归；（2）BM25+LR，以稀疏检索统计特征判定；（3）Raw-SBERT+LR，使用通用句向量；（4）Domain SBERT+LR，使用本研究训练的领域向量；（5）KG-SBERT，使用本研究构建的规则图谱和语义/数值匹配特征；（6）KG-HCR Dense+BM25+KG，即本文主配置；（7）KG-HCR Full，在主配置上额外开启约束召回通道。逻辑回归基线采用类别平衡权重，所有方法共享同一训练、验证与测试划分以及阈值选择协议。'
  73 = '表 I 给出各方法在同一独立测试集上的结果。KG-HCR Dense+BM25+KG 在 Accuracy、Precision 和 F1 上均取得最佳，分别为 97.48%、97.22% 和 97.03%，AUC 为 0.9939。相较 Domain SBERT+LR，F1 提升 1.50 个百分点；相较 BM25+LR，F1 提升 9.50 个百分点。该结果说明，领域语义表示、专业词项保真和图谱实体关联并非简单替代关系，而是能在候选召回与证据聚合阶段形成互补。'
  75 = 'KG-HCR Full 的 Precision 为 97.59%，Recall 为 96.05%，F1 为 96.81%。额外约束召回使模型在部分边界样本上更保守，当前 Precision—Recall 平衡同时受到阈值与证据组合影响，因此本文将 Full 作为受控变体而非主结果。各主要方法的 AUC 均高于 0.99，性能差异主要来自概率阈值附近的排序质量和证据组合。'
  77 = '为识别各组成部分的边际贡献，表 II 分别移除稠密检索、BM25、知识图谱、约束特征、RRF 和重排序模块。Dense+BM25+KG 的 F1 为 97.03%，高于仅使用 Dense（96.86%）和 Dense+BM25（96.85%）。移除 BM25 后 F1 降至 96.12%，表明在电力标准中，专业术语、单位和数值的精确保真仍是语义匹配不可替代的组成部分。'
  82 = '去除 RRF、约束或重排序后，F1 分别为 96.44%、96.48% 和 96.11%。其中 w/o Rerank 的 AUC 降至 0.9920，表明未经字段校验的图谱候选更容易包含主题相关但场景不匹配的规则；约束特征能够减少“实体相同、条件不同”的误报。Full 版本略低于主配置，也说明约束信息应与其他召回通道联合校准，而非作为孤立启发式规则使用。'
  84 = '测试样本 14 的两条款分别为“油中溶解气体色谱分析的检测周期为必要时”和“测得的电阻值不应超过型式试验测得的最小电阻值的 1.2 倍”。模型输出一致概率为 8.8×10−5。前一条款的高分证据集中于检测周期和“必要时”条件，后一条款集中于电阻值、“不应超过”和“1.2 倍”约束；主体、动作和约束字段均不对齐，因此系统给出不一致结论，并可定位其冲突依据。'
  85 = '测试样本 1483 涉及乙炔、氢气、总烃及 220 kV/330 kV 分段阈值，模型输出一致概率为 0.999748。双侧证据均命中相关气体指标，字段解析确认单位、比较符和电压分段一致，因而给出一致判定。对于内容相同的交流电压试验条款（样本 939），模型输出概率为 0.9938，Top 规则保留“试验频率从 10 Hz 到 300 Hz”等关键条件。案例表明，KG-HCR 不仅能输出分类结果，还能提供可复核的支撑规则与字段级依据。'
  88 = '当前 pair-level 划分仍可能包含同源条款跨集合重复，因此结果主要刻画同分布条件下的有效性，而非完全跨来源泛化能力。按标准或条款分组的严格 disjoint split 将用于进一步检验跨来源性能。知识图谱覆盖范围受结构化抽取质量影响，异常单位、嵌套比较符和多条件逻辑会增加字段解析难度；Full 配置的轻微下降也提示启发式权重需要在更大规模、跨标准数据上重新校准。后续实验将报告标准级划分以及跨年度、跨设备类别的泛化结果。'
  91 = '本文提出 KG-HCR 电力标准条款一致性评估框架，将结构化规则抽取、领域 SBERT、规则知识图谱、BM25、RRF、约束感知重排序和双向证据聚合组织为可追溯的证据闭环。该框架在 595 对独立测试条款上取得 97.48% Accuracy、97.03% F1 和 0.9939 AUC，优于词法、通用语义和图谱语义匹配基线。实验与消融结果表明，BM25 对专业术语和数值保真尤为关键，规则知识图谱、RRF 与字段级约束进一步提升了证据覆盖、候选排序和条件冲突识别能力。'
  92 = '后续研究将围绕结构化抽取质量、严格数据划分和图谱覆盖范围开展跨标准验证，并检验隐式逻辑冲突和复杂多条件推理的泛化能力。进一步工作包括学习通道融合权重、进行数值区间归一化、构建冲突图推理和引入人工反馈闭环，以提升工程场景中的稳健性、可审计性和迁移能力。'
}

foreach ($key in $replacements.Keys) {
  $index = [int]$key - 1
  if ($index -lt 0 -or $index -ge $paragraphs.Count) { throw "Paragraph index $key is outside the document." }
  Set-ParagraphText $xml $ns $paragraphs[$index] $replacements[$key]
}

$headingIndexes = @(18, 29, 36, 66, 90, 93)
foreach ($i in $headingIndexes) { Set-ParagraphStyle $xml $ns $paragraphs[$i - 1] 24 $true 'left' 180 90 }
$subheadingIndexes = @(30, 32, 34, 37, 39, 42, 46, 52, 58, 67, 70, 72, 76, 83, 88)
foreach ($i in $subheadingIndexes) { Set-ParagraphStyle $xml $ns $paragraphs[$i - 1] 21 $true 'left' 120 60 }
Set-ParagraphStyle $xml $ns $paragraphs[0] 34 $true 'center' 0 180
foreach ($i in 15..91) {
  if ($headingIndexes -notcontains ($i + 1) -and $subheadingIndexes -notcontains ($i + 1)) {
    Set-ParagraphStyle $xml $ns $paragraphs[$i] 20 $false 'both' 0 72
  }
}

$settings = New-Object System.Xml.XmlWriterSettings
$settings.Encoding = New-Object System.Text.UTF8Encoding($false)
$settings.Indent = $false
$writer = [System.Xml.XmlWriter]::Create($documentXml, $settings)
$xml.Save($writer)
$writer.Close()

$coreXml = Join-Path $expanded 'docProps\\core.xml'
if (Test-Path -LiteralPath $coreXml) {
  [xml]$core = Get-Content -Raw -Encoding UTF8 -LiteralPath $coreXml
  $coreNs = New-Object System.Xml.XmlNamespaceManager($core.NameTable)
  $coreNs.AddNamespace('dc','http://purl.org/dc/elements/1.1/')
  $coreNs.AddNamespace('cp','http://schemas.openxmlformats.org/package/2006/metadata/core-properties')
  $title = $core.SelectSingleNode('//dc:title', $coreNs)
  if ($title) { $title.InnerText = 'KG-HCR for Power Standard Clause Consistency Assessment' }
  $subject = $core.SelectSingleNode('//dc:subject', $coreNs)
  if ($subject) { $subject.InnerText = 'Knowledge graph enhanced hybrid retrieval and constraint aware reranking' }
  $writer = [System.Xml.XmlWriter]::Create($coreXml, $settings)
  $core.Save($writer)
  $writer.Close()
}

$outputZip = Join-Path $workingRoot 'KG-HCR_EI会议论文润色版.zip'
$archive = [System.IO.Compression.ZipFile]::Open($outputZip, [System.IO.Compression.ZipArchiveMode]::Create)
try {
  Get-ChildItem -LiteralPath $expanded -Recurse -File | ForEach-Object {
    $segments = $_.FullName -split '[\\/]'
    $rootIndex = [Array]::LastIndexOf($segments, 'expanded')
    if ($rootIndex -lt 0 -or $rootIndex -ge ($segments.Length - 1)) { throw "Cannot create an OOXML-relative path for $($_.FullName)" }
    $relative = ($segments[($rootIndex + 1)..($segments.Length - 1)] -join '/')
    $entry = $archive.CreateEntry($relative, [System.IO.Compression.CompressionLevel]::Optimal)
    $inputStream = [System.IO.File]::OpenRead($_.FullName)
    $outputStream = $entry.Open()
    try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose(); $inputStream.Dispose() }
  }
} finally { $archive.Dispose() }
Copy-Item -LiteralPath $outputZip -Destination $input -Force
Remove-Item -LiteralPath $workingRoot -Recurse -Force
Write-Output "Revised document written to: $input"
