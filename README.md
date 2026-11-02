# AlgoFactory：银行咨询分类算法开发工作台

AlgoFactory 是一个基于 LLM 的算法开发原型。它围绕**银行客服英文咨询分类这一场景**，检索算法知识、生成 Python 代码，在隔离环境中训练与评估，根据错误进行有限修复，最后交付代码、模型、报告及可追溯的知识记录。

当前版本：**0.8.0**，见 [版本变更](CHANGELOG.md) 和 [交付与复现记录](docs/delivery.md)。

你可以在本地 Streamlit 工作台创建开发任务、查看生成过程并试用成果，也可以使用命令行。**不需要购买网页服务器；首次体验使用 Mock，无需 API Key。** 全程免费请选“离线示例与固定表达”及 Mock 生成；自然语言理解会调用 API，费用与代码生成分别计算。Mock 训练和评分仍真实执行。

**首次接手请从 [从零启动工作台](#quickstart) 开始，再按 [完成一次开发任务](#first-run) 操作。** 查看 [生成代码与报告](#deliverables)、[验证证据](#evidence) 或 [常见问题](#troubleshooting) 无需了解项目开发阶段。

## 1. 项目背景和目标

大模型生成一段代码，并不意味着代码能运行、效果达标或结果可追溯。本项目验证“理解需求 → 抽取与检索能力知识 → 规划 → 生成代码 → 执行评估 → 修复 → 知识沉淀”的闭环。

- **开发需求**：例如“请开发一个英文银行咨询分类算法，输出意图类别及概率，并验证效果”。
- **开发成果**：分类流水线代码、训练模型、四维验证报告、候选与修复记录。
- **成果试用**：例如输入 `I lost my bank card.`，让已训练模型预测问题类别；它与开发需求是两种不同输入，示意句不保证被模型判对。

当前支持全部 77 类分类、从已有意图中选 2–76 类分类、指定单个意图的属于/不属于识别，不提供客服自动回复或银行业务办理。用户可用自己的话描述需求，由大模型逐项整理、追问并复核，再经用户确认转成实际配置；也保留免费的离线固定表达。语义理解可能有误，必须核对方案。**不支持任意新业务、自有数据上传或新增业务标签**；允许在已有标签内筛选与重映射；合成客户流失和回归仅用于公共框架兼容检查。详见 [工作台指南](docs/workbench-guide.md)。

三个目标的操作、类别边界和复验方法见 [任务目标说明](docs/intent-goals.md)。单个意图可选“优先减少漏判”：调整训练权重/先验并改变候选排序，同时展示误报；不保证业务效果。

项目对应的 [题目原文](docs/source/exam-original.txt)、[需求与实现对照](docs/requirements-matrix.md) 和 [范围决策](docs/decisions/0001-banking77-main-case.md) 可用于审核。

## 2. 系统架构和模块设计

```text
开发者：提交分类算法需求
  → 知识角色：理解需求、抽取与检索算法知识
  → 构建角色：规划方案、生成 Python 分类流水线
  → 静态检查 → Docker 中训练、预测 → 主机独立评分
  → 必要时有限修复、比较候选 → 可选的选定版本最终测试
  → 保存代码、模型、报告与知识记录
  → 用户输入新咨询，试用本次生成的模型
```

| 构成 | 职责 | 主要实现 |
| --- | --- | --- |
| Streamlit / CLI | 创建任务，查看代码、报告、流程和试用结果 | `src/algofactory/web/`、`cli.py` |
| LLM Provider | 切换 Mock / API，管理结构化调用与预算 | `llm/` |
| Pydantic 契约 | 校验需求、方案、知识、预测等输入输出 | `schemas/` |
| SQLite / NetworkX | 存储知识与来源，导出和展示关系 | `knowledge/` |
| 工作流编排 | 单候选运行、多候选比较和有限修复 | `orchestrator.py`、`search.py` |
| Docker 沙箱 | 在批准的依赖环境中隔离执行生成代码 | `execution/` |
| 独立验证 | 主机计算指标，检查功能、稳定性与接口 | `validation/` |
| scikit-learn | TF-IDF 特征处理及分类模型的训练、预测 | 生成的 `build_pipeline(config)` |

表中简写路径均位于 `src/algofactory/`。选择 Python / scikit-learn 便于实现轻量 CPU 算法；SQLite 无需独立数据库服务；Pydantic 将接口要求变成可执行检查；Docker 约束执行环境；Streamlit 便于以 Python 提供本地入口。更多说明见 [架构与边界](docs/architecture.md)。

## 3. 知识图谱 Schema 和示例

知识库包含任务、能力、算法、数据集、实现、验证、失败和经验等实体。例如：

```text
Task ── REQUIRES ──→ Capability
Algorithm ── IMPLEMENTS ──→ Capability
Algorithm ── APPLICABLE_TO ──→ Task
```

实体保存稳定 ID、来源原文区间和 Schema 版本；验证记录关联代码散列、数据协议及运行 ID。当前使用结构化条件检索，没有向量检索。知识材料用于指导算法生成，咨询数据用于训练和评估，两者用途不同。

可直接阅读 [Schema 定义](src/algofactory/schemas/knowledge.py)、[知识 JSON 样例](examples/knowledge/knowledge.json) 和 [GraphML 样例](examples/knowledge/knowledge.graphml)。工作台的“开发过程”展示检索依据与回写证据，侧栏辅助工具提供知识图谱。

## 4. Agent 工作流设计

知识、构建、审查是三个逻辑角色，共享显式编排和契约；审查主要由确定性程序执行，目前不是多个独立自治 Agent 协商。API 模式使用 LLM 理解需求、抽取知识、规划、生成或修复代码；Mock 用固定响应检查同一套执行流程。

分类候选为 TF-IDF + Logistic Regression 和 TF-IDF + MultinomialNB。系统只依据验证集比较与修复；最终测试每次工作流仅允许选定版本评估一次，测试成绩不用于继续选择或修复。每候选最多两次修复，工作台默认一次，并进一步受请求预算限制。

通过的实现、失败记录及验证结果均可回写；失败回写不等于算法合格。经验只在有重测证据、适用协议匹配时复用。详细机制见 [架构与边界](docs/architecture.md) 和 [验收口径](docs/acceptance-gates.md)。

<a id="quickstart"></a>

## 5. 从零复现：环境准备、启动和首次操作

### 5.1 准备条件

本指南命令面向**已验证的 macOS Apple Silicon（ARM64）、Python 3.11 环境**，在终端执行。代码使用 Unix 文件锁；Windows 原生环境没有验证，不能只把命令路径改成 Windows 格式就视为支持。其他系统或架构仍需单独适配与验证。

| 需要准备什么 | 用途与检查 |
| --- | --- |
| Git 和仓库访问权限 | 下载源码及归档材料；私有仓库需所有者授权 |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | 安装锁定的 Python 依赖，安装后 `uv --version` 应正常输出 |
| [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/) | 安装 Apple Silicon 版本并启动，等待引擎就绪；只安装但不启动是不够的 |
| 网络与磁盘空间 | 首次安装依赖、拉取基础镜像需要网络；安装和运行会产生虚拟环境、镜像与训练产物 |

每个训练容器的默认内存上限为 4 GiB、CPU 上限为 2；Docker 和主机还需留出自身运行空间。这是执行配置，不是整机最低配置承诺。首次 Mock 体验不需要 `.env` 或密钥。

### 5.2 获取项目并安装依赖

```sh
git clone https://github.com/NorthChar/AlgoFactory.git
cd AlgoFactory
git rev-parse --short HEAD
uv sync --extra web --locked --python 3.11
.venv/bin/python --version
```

预期：项目目录生成 `.venv/`，Python 版本为 3.11。`uv.lock` 固定依赖，`--extra web` 安装工作台所需依赖；省略它可能无法启动界面。`git rev-parse` 输出的提交号用于记录复现版本。

**后续命令都在这个仓库根目录运行**，不要在 `src/` 或其他目录执行。复现同一个交付版本时，应使用同一 Git 提交；不能仅凭相同包版本号判断代码完全一致。

### 5.3 检查 Docker 并构建执行镜像

先启动 Docker Desktop，再运行：

```sh
.venv/bin/python -m algofactory.cli sandbox-status
.venv/bin/python scripts/prepare_sandbox.py --base-image python@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60
```

预期：第一条输出 Docker 的版本、架构及 `os_type: linux`；第二条完成镜像构建，生成 **`runtime/docker-image.json`**，记录本机批准镜像及代码/依赖散列。首次构建可能需要数分钟，等待命令成功退出后再继续。

镜像和批准文件必须在接收者自己的机器上准备，不能只复制开发者的 `runtime/docker-image.json`。后续重复启动工作台通常不必重建；执行器代码、依赖变化或本机镜像被删除后需要重新执行本步骤。

### 5.4 导入随仓库提供的数据

```sh
.venv/bin/python -m algofactory.cli prepare-banking77 --raw-dir data/banking77/raw
```

预期：生成 **`runtime/banking77-data/`**，其中包含数据清单 `manifest.json`、质量检查 `audit.json` 和划分后的数据。全量任务为 7,993 条训练、1,999 条验证、3,080 条最终测试。指定类别任务只在各原划分内筛选；单个意图任务保持条数、重新映射标签。

这一步从仓库归档的原始文件导入并校验散列，无需自行搜集数据。这是首次安装步骤。导入器拒绝覆盖非空目标目录；已经成功导入时，后续启动跳过本步骤即可。若导入中断，先把不完整目录移到备份位置再重试，不要手工修改样本或沿用不匹配的清单。

### 5.5 启动同一套工作台

```sh
.venv/bin/python -m streamlit run src/algofactory/web/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

保持这个终端运行，在浏览器打开 **[http://127.0.0.1:8501/](http://127.0.0.1:8501/)**。预期看到 AlgoFactory、银行咨询分类算法开发说明，以及“从这里开始 / 创建算法开发任务 / 我的开发任务”三个入口。

无需额外构建前端或使用 Gradio。网页由本机 Python 进程提供；关闭服务后网页不能继续使用。要停止页面服务，在该终端按 `Ctrl+C`。如果有后台开发任务正在运行，请先在工作台取消或等待完成，关闭页面服务不等于取消后台训练。

<a id="first-run"></a>

### 5.6 完成一次不产生 API 费用的开发任务

1. 点击“开始开发银行分类算法”，先选择开发目标及对应类别，再选择 **离线示例与固定表达（不产生 API 费用）**，填写开发需求。可先用页面示例：“开发英文银行咨询分类算法；输出77类意图及概率；只使用逻辑回归；仅使用单词特征；词表上限10000；逻辑回归C=1”。
2. 在离线模式点击“解析并检查需求”，核对执行配置及每一项的来源。支持的表达见页面说明；无法识别的句子也会阻止提交，不会猜测或自动回退。改为“比较逻辑回归和朴素贝叶斯”才能启用双候选。
3. 选择 **使用模板生成代码（此步不产生 API 费用）**（Mock），核对评估方式、修复次数和请求预算，勾选确认后点击“开始生成并验证”。任何需求或运行设置变动都会使确认失效。页面自动进入本次任务，刷新不会重复提交。
4. 完成后查看“结果与交付”：成功时应显示“验证集通过”，并提供生成代码与报告。未执行最终测试是本次默认设置的预期结果，不是漏跑。
5. 在“开发过程”查看需求、检索、方案、代码、评估、修复（若发生）及回写依据。
6. 点击“输入咨询，试用本次成果”，在“试用本次算法”输入一条自己编写的英文银行咨询，查看本次模型的预测。概率不是正确率保证，分类可能出错；试用不计入标准评估。

**用日常语言提出需求：** 配置好 API 后选“用自己的话描述”，点击“理解我的需求”才调用。每轮最多两次请求，最多三轮；可以回答追问并重新理解。核对建议及限制后再确认生成。理解请求与代码生成预算分开计算，选 Mock 生成也不会免去已经发生的理解费用。详见 [需求与补充问答](docs/workbench-guide.md)。

也可先在首页点击“查看已完成的银行分类开发任务”，只读浏览历史真实 API 案例。仅浏览不产生费用。历史模型未保存时，需要显式点击“准备此版本模型”后再试用：这是按旧代码重新训练，不是恢复历史权重。

**什么会相同，什么不会自动带过来？**

- 同一提交、锁定环境和数据协议提供同一套工作台、任务功能与归档报告。
- `runtime/` 不上传 Git：开发者本机的新任务列表、日志、训练模型、Docker 批准文件不会随克隆迁移。接收者创建任务后会生成自己的这些文件。
- 任务 ID、时间戳和本机路径会不同；真实 API 重新生成的代码也不保证相同。不能把页面复现理解为必须逐字复现大模型输出。
- 项目保留同机独立目录与新环境验证记录，尚未把它等同于在第二台机器或所有操作系统上验收通过。

**以后再次打开**：启动 Docker Desktop，在仓库根目录重新执行 5.5 的启动命令即可；依赖、镜像与数据无变化时，不必重复安装或导入。

详细操作见 [工作台使用指南](docs/workbench-guide.md)。

### 5.7 可选：命令行复现与真实 API

完成上面的环境、镜像和数据准备后，也可以直接运行同一后台流程：

```sh
.venv/bin/python -m algofactory.cli demo --task banking77 --mode mock --compare --validation-only --max-repairs 1 --llm-call-budget 24 --db runtime/cli-demo.sqlite
```

该命令自动创建新的 `runtime/runs/` 子目录，在输出中给出本次报告位置；CLI 运行不自动注册为工作台任务。要体验完整页面操作，按 5.6 在工作台提交。固定实验配置示例位于 `configs/`，用法见 [参数配置说明](docs/workbench-guide.md#参数选择与实验边界)。

如需真实 LLM 生成，在没有 `.env` 时从 `.env.example` 复制一份为 `.env`，按 [API 配置说明](docs/api-integration.md#本地配置) 填写接收者自己的接口、部署名和密钥，再在工作台选 API。不要覆盖已有配置，不要把密钥写入 `.env.example` 或提交仓库。API 会产生费用；本地历史报告无需密钥即可浏览。Mock 不会静默切换成付费 API。

### 5.8 验证安装和功能

完成数据与镜像准备后，另开一个终端，进入仓库根目录执行：

```sh
.venv/bin/python -m ruff check src tests scripts
ALGOFACTORY_DOCKER_TESTS=1 .venv/bin/python -m pytest -q
```

预期：检查无错误、测试无失败；**完整验收还要求没有跳过**。未启用容器测试的普通测试会跳过部分用例，不能据此宣称完整闭环通过。测试使用 Mock 或本机模拟 HTTP 服务，不调用付费 LLM；容器测试会实际运行算法。

需要执行四种分类目标的后台工作台任务与模型试用检查，可运行 `scripts/verify_intent_goals.py`；需求执行与修复检查使用 `scripts/verify_requirements.py`。独立副本、新 Python 环境和 wheel 安装复现见 [交付验证](docs/delivery.md)。这些检查默认不调用付费 API。

<a id="troubleshooting"></a>

### 5.9 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 克隆提示无权访问或找不到仓库 | 先获得私有仓库访问权限，并确认 Git 使用有权限的账号 |
| `uv` 不存在，或找不到 `streamlit` | 安装 uv；在仓库根目录重新执行带 `--extra web` 的依赖安装步骤 |
| `docker_missing` / `docker_unavailable` | 安装并启动 Docker Desktop，等待引擎就绪，再执行 `sandbox-status` |
| `sandbox_image_not_prepared` / `sandbox_image_missing` / `sandbox_image_stale` | 按 5.3 重新构建本机批准镜像，不要只复制批准文件 |
| `dataset_not_prepared` 或要求先导入数据 | 按 5.4 导入到默认目录，并从仓库根目录启动服务 |
| 构建镜像或安装依赖超时 | 检查本机到镜像及包仓库的网络/代理配置，完成安装后再启动任务 |
| 浏览器无法访问工作台 | 确认服务终端仍在运行；若 8501 被占用，换未使用端口，例如将命令中的端口改为 8502，并打开对应地址 |
| 更新代码后页面仍使用旧内容 | 停止并重新启动 Streamlit 服务，重新打开页面；不要仅刷新浏览器 |
| API 提示 `call_budget_exhausted` | 查看已有记录；确认是否需要增加本次请求上限再手动提交新任务，不自动续跑或扩额 |
| 新电脑没有开发者的任务或模型 | 属于正常现象；浏览归档报告或自行创建任务，历史模型按页面提示显式准备 |
| 试用模型分错咨询 | 流程通过不代表每句话都正确；保存样例，检查版本绑定及分类质量。当前不支持未知意图拒识 |

## 6. 数据与测试任务

BANKING77 原始有 **13,083 条英文咨询、77 类意图**。每条咨询带正确类别；数据不是客服回答库或客户交易流水。生成代码通过约定字段读取数据，训练分类器，再由主机用评估标签独立评分；不用于微调 GPT。

| 用途 | 数据协议 | 算法与指标 |
| --- | --- | --- |
| 完整业务任务：银行咨询分类 | 固定官方版本；训练侧去重、移除与测试重合项，再分层划分训练/验证；保留官方测试集 | TF-IDF + Logistic Regression / MultinomialNB；Macro-F1、Accuracy |
| 衍生业务任务：指定类别/单个意图 | 从固定 BANKING77 原划分内筛选或重映射；独立指纹、标签映射与评估协议 | 文本多分类或二分类；Macro-F1、Accuracy，二分类另报告正类 Precision/Recall/F1/ROC-AUC |
| 公共框架兼容：客户流失 | 固定种子生成 1,500 行；60/20/20 分层划分 | Logistic Regression；F1、ROC-AUC |
| 公共框架兼容：回归 | 固定种子生成 600 行；60/20/20 划分 | Ridge；MAE、RMSE（越低越好） |

数据来源为 PolyAI，作者 Iñigo Casanueva、Tadas Temcinas、Daniela Gerz、Matthew Henderson、Ivan Vulić（2020），论文 *Efficient Intent Detection with Dual Sentence Encoders*。保留 [原许可 CC BY 4.0](data/banking77/raw/LICENSE)，固定上游提交为 `57ec275d8078af65b7731c2a98be812d844a6d6b`；去重和划分是本项目处理，详见 [数据来源与导入](data/README.md)。客户流失与回归使用合成数据，不代表真实业务效果。

<a id="deliverables"></a>

## 7. 生成算法代码与交付物

直接查看 [真实 API 生成并修复的分类代码](examples/banking-classification/comparison/candidate.py) 和 [对应中文报告](examples/banking-classification/comparison/report.md)。代码使用统一的 `build_pipeline(config)` 接口，在配套环境中构建分类流水线；它不是可以脱离依赖和数据协议运行的完整网站。

工作台每次提交的主要产物位于 `runtime/web-jobs/<任务编号>/`：

| 位置或文件 | 内容 |
| --- | --- |
| `settings.json`、`state.json` | 提交配置、进度与结束状态 |
| `run/candidate.py` | 已产出的交付候选代码；失败早期可能尚未生成 |
| `run/report.md`、`run/report.json` | 中文报告和结构化结果 |
| `run/candidates/` | 比较模式的各候选、修复版本与执行证据 |
| `knowledge.sqlite` | 本次知识及验证记录 |

训练模型及来源清单随执行产物保存，由工作台校验并绑定到选定版本；历史补建模型另存。失败或中断的产物也会保留，下载到代码不代表通过验收。

**项目交付载体是 GitHub 仓库**，包含工作台源码、CLI、依赖、示例数据与知识材料、生成代码样例、验证报告、测试和运行文档。无需向接收者提供开发者的电脑或公开网页服务器。`.env`、`.venv/`、`runtime/` 和个人讲解材料不属于仓库交付内容。

<a id="evidence"></a>

## 8. 验证结果与复现证据

| 证据 | 证明什么 | 边界 |
| --- | --- | --- |
| [提交版复现](docs/delivery.md) | 当前版本的独立安装、完整回归和任务流程验证 | 以记录中的提交与执行范围为准 |
| [真实 API 完整闭环](examples/banking-classification/comparison/report.md) | 真实错误修复、两个候选比较、最终测试和回写；Macro-F1 0.878695、Accuracy 0.878247 | 历史 77 类固定协议，不是每条新咨询的正确率保证 |
| [可选择分类目标](examples/intent-goals/README.md) | 全量、指定类别、单个意图的验证摘要；真实 API 理解及单意图生成节选 | 未验证所有类别组合，真实 API 新样例未执行最终测试 |
| [经验复用对照](examples/experience-reuse/historical-summary.json) | 检索、来源链与检查机制可用 | 历史小规模对照未观察到修复次数或指标收益 |

[示例索引](examples/README.md) 标明完整案例和节选的区别。历史报告内的日期、路径及散列保持原样；不能把不同版本测试数相加或把历史记录说成当前重新执行。验证维度与判定规则见 [验收口径](docs/acceptance-gates.md)。

## 9. 挑战与解决方案

- **生成代码不适配输入**：真实案例中 TF-IDF 与 DataFrame 形状不匹配；保存执行错误、反馈修复，重新运行后再选择版本。
- **生成内容不符合规则**：结构化契约、来源引用、参数与静态语法检查、容器执行和确定性评分逐层约束。
- **评估泄漏**：冻结划分和门槛，预处理只在训练集拟合，评估标签留在主机，验证排名与最终测试分开。
- **无限修复或调用失控**：限制候选数、修复轮次、请求次数、输出长度和执行时间，停止后保留诊断材料。
- **经验收益被夸大**：复用有重测证据且匹配协议的经验，并进行开关对照；未观察到收益时明确记录负结果。
- **执行生成代码的风险**：非 root、只读文件系统、禁网、资源与时间限制；缺镜像拒绝执行。部分异常以模拟测试覆盖，不声称绝对安全或完成真实资源压测。
- **交付依赖开发者电脑**：固定依赖、数据与镜像来源，提供完整启动顺序及独立环境记录；本机任务与密钥不随源码迁移。

## 10. 后续方向与文档导航

优先检查新咨询试用的预测质量与标准评估路径一致性，再考虑跨运行实验比较、自动接口文档和资源分析。任意数据接入、新业务自动适配、真正自治多智能体、真实仓库能力抽取、Beam/MCTS、未知意图识别及生产部署尚未完成。

| 想了解什么 | 阅读入口 |
| --- | --- |
| 页面如何操作、参数怎么选 | [工作台使用指南](docs/workbench-guide.md) |
| 系统模块与输入输出契约 | [架构说明](docs/architecture.md) |
| API 接入与调用记录 | [API 配置说明](docs/api-integration.md#本地配置) |
| 原题完成情况与证据 | [需求矩阵](docs/requirements-matrix.md) |
| 版本变更 | [变更记录](CHANGELOG.md) |
| 交付组织、独立复现与历史归档 | [交付说明](docs/delivery.md)、[示例索引](examples/README.md) |

开发阶段计划和重复实验已移出当前交付目录，仍可通过 Git 历史追溯。按第 5 节即可启动工作台。

仓库：[NorthChar/AlgoFactory](https://github.com/NorthChar/AlgoFactory)，默认分支 `main`，访问需授权。交付时应记录对应提交号，确保源码、工作台和文档来自同一版本；本地未提交或未推送的修改不会出现在接收者的克隆中。
