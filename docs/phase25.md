# Phase 2.5：BANKING77 主案例与客户流失兼容性

2026-10-29，承接 [ADR-001](decisions/0001-banking77-main-case.md)。实现已完成，阶段验收待运行；最终状态以 [G2.5](acceptance-gates.md) 和阶段 verification.json 为准。Phase 1/2 的历史证据不改写。

## 实现范围

同一 `run_workflow` 完成需求解析、知识提取与适用条件检索、方案及代码生成、静态检查、真实 Docker 执行、主机独立评分、报告和事务回写。`tasks.py` 提供固定的 BANKING77 / churn 配置；数据导入、特征、标签空间、候选模板及评分协议由主机绑定，LLM 不得重新定义。

- BANKING77：英文 text → intent，77 类已知意图；TF-IDF（词级 1–2 gram、sublinear_tf、最多 30,000 词项）+ LogisticRegression（C=4、max_iter=500、seed=42）。
- 客户流失：沿用原来的 1,500 行合成数据、固定 Logistic Regression 候选及 60/20/20 协议，只做兼容性检查。
- Mock 仅支持两个内置固定开发需求和手工编写的文档抽取 fixture；模型训练与评分实际执行。不声称理解任意需求或调用过真实外部 LLM。
- 本阶段一个候选、零次修复。比较与修复仍属 Phase 3，经验提炼/复用仍属 Phase 4。知识库保存真实结果，不创建 Experience。

## 数据版本、署名及处理口径

数据：PolyAI [task-specific-datasets](https://github.com/PolyAI-LDN/task-specific-datasets/tree/57ec275d8078af65b7731c2a98be812d844a6d6b)，固定提交 `57ec275d8078af65b7731c2a98be812d844a6d6b`，许可 [CC BY 4.0](https://github.com/PolyAI-LDN/task-specific-datasets/blob/57ec275d8078af65b7731c2a98be812d844a6d6b/LICENSE)。

署名：Iñigo Casanueva、Tadas Temcinas、Daniela Gerz、Matthew Henderson、Ivan Vulić，2020，[Efficient Intent Detection with Dual Sentence Encoders](https://arxiv.org/abs/2003.04807)。本项目保留原始数据与许可，进行了下述训练侧去重、划分和整数标签编码；不代表数据作者认可本项目，也不宣称与论文原始评测口径完全一致。

`prepare-banking77` 下载固定 URL，核验三个原始文件的内置 SHA-256；也可通过 `--raw-dir` 离线导入。`raw/` 原样保留 train.csv、test.csv、LICENSE，文件设为只读。`manifest.json` 保存来源、导入时间、导入器散列、原始/处理后散列、规则、类别顺序和划分。

处理顺序与 ADR 一致：

1. 文本按 strip → Unicode casefold → 连续空白合并进行重复判断；实际训练文本保持原样。
2. 相同归一化文本存在冲突标签则停止。去掉训练侧与官方测试集重叠的 7 行，再移除训练侧 4 行重复，共移除 11 行。
3. 清洗后训练池 9,992 行，按类别分层、seed=42 划分为训练 7,993 行、验证 1,999 行。
4. 官方测试集 3,080 行及原始顺序保持，内部 1 行重复单独披露；每类 40 行。
5. 77 个原始类别名按区分大小写的字典序映射为 0–76；所有划分均覆盖全部类别。`labels.json` 固定映射；`lineage.csv` 的 source_row 为原始文件中不含表头、从 0 开始的行号；`audit.json` 记录移除原因、测试重复与逐类数量。

每次运行从固定原始文件重建预期的处理数据并校验，重新计算文件散列后篡改清单也不能让修改过的划分通过。来源、许可和处理规则变化需另建版本，禁止覆写现有目录。归一化去重不代表已识别全部语义近似重复，也不代表人工复核全部标签。

## 验证与隔离边界

可信参考模型只读训练/验证数据，拟合词表与 IDF 仅用训练集，记录词表散列。先固定基线参数与校准规则；Macro-F1 门槛为 `max(0.50, floor((验证集基线 - 0.05) × 100) / 100)`，Accuracy 为描述性指标。初次基线验证 Macro-F1 约 0.873，对应冻结门槛 0.82。阈值不根据最终测试成绩修改。

Docker 保持非 root、禁网、只读根目录、移除 capabilities、120 秒、2 CPU / 4 GiB；仅挂载候选、配置、训练 CSV 和当前评估特征。验证/测试标签留在主机。新增 TF-IDF 构造器白名单，仍禁止任意导入、I/O 和顶层执行。77 类完整概率矩阵需要较大输出，固定响应上限从 2 MB 增为 32 MB，资源隔离保持原预算。

主机检查行号、预测范围、概率矩阵形状/有限值/范围/行和、类别顺序和固定种子重复结果。文本边界拒绝缺列、空文本、空白、非字符串和缺失值；未见词可输出有限概率。非法文本检查由可信 worker 输入校验负责，不宣称 TF-IDF 自身拒绝所有非法输入。

验证四维全部通过后写入 selection.json 和一次性 test-access.json，锁定代码、配置及数据身份，再执行一次最终测试；最终测试失败即停止。重复运行是相同冻结配置的复现检查，不用于挑选测试成绩。逐类 Precision/Recall/F1/support 与完整混淆矩阵保存为 validation-class-details.json / test-class-details.json。

检索同时约束任务类型、text/tabular 数据类型及本次来源文档，只有适用的 Algorithm/Capability 可进入规划。字段、目标、标签映射、划分、阈值不匹配即拒绝；原有经验不会自动进入另一任务。

## 运行与复现

先按根 README 安装 Python 3.11 依赖并启动 Docker Desktop。重现指定环境时，可将 verification.json / docker-image.json 中的 base_image_digest 传给 prepare_sandbox.py 的 --base-image 参数。在项目根目录执行：

```sh
.venv/bin/python scripts/prepare_sandbox.py
.venv/bin/python -m algofactory.cli prepare-banking77
.venv/bin/python -m algofactory.cli calibrate --dataset-dir runtime/banking77-data
.venv/bin/python -m algofactory.cli demo --task banking77 --mode mock --db runtime/phase25.sqlite
.venv/bin/python -m algofactory.cli demo --task churn --mode mock --db runtime/phase25.sqlite
```

原始文件已缓存时可用 `prepare-banking77 --raw-dir runtime/banking77-raw --output-dir runtime/banking77-data`。输入和输出目录不得包含旧产物。CLI 保留默认 `--task churn` 兼容旧调用，主案例演示显式选择 `--task banking77`。两任务可写入同一数据库。

全量验收需要提交后的干净实现源码、已准备的隔离镜像，以及可访问的固定数据来源（或 raw-dir）：

```sh
.venv/bin/python scripts/verify_phase25.py --raw-dir runtime/banking77-raw --output-dir runtime/phase25-verification
```

验收脚本执行代码检查、全部测试（包括真实容器，必需测试零跳过）、BANKING77 正常/重复/三类故障示例和客户流失兼容示例；核对客户流失与历史固定候选成绩一致；重开数据库并检查 GraphML 无损往返。保存时间、提交、代码/数据/产物散列、容器身份和环境。不会重写 examples/phase2。

完整概率 JSON 使用无损 gzip 保存，verification.json 的 predictions_archives 映射同时记录压缩前后 SHA-256。运行报告中的原文件散列应与解压后的字节比较；其余证据直接按路径核验。来源数据含英文公开样本，分发归档时应一起保留 raw/LICENSE 和本节署名。

## 验收限制

G2.5 只覆盖两个固定任务的 Mock 单候选流程。真实 API、自动修复、多候选比较、经验有效性对照、界面和全新机器冷启动仍待后续验收。超时/OOM/清理错误沿用模拟 Docker 响应测试，不冒充真实资源压力测试。
