# Phase 6：冷启动与集成交付

状态：2026-10-30 本地冷启动与交付检查已通过。实现提交 `da42b56eb6b3dfce1db733679f8ebc024824d430` 上 233 项测试，0 失败、0 错误、0 跳过；三类 CLI、两类 Web、真实超时清理、恢复查看和已安装服务健康检查通过。新增付费 API 请求为 0。见[完整报告](../examples/phase6/verification.json)和[交付索引](../examples/phase6/README.md)。

GitHub 私有发布已完成：[NorthChar/AlgoFactory](https://github.com/NorthChar/AlgoFactory)，默认分支 `main`。2026-10-30 核对仓库 ID `1439244398`、所有者 ID `92282160`、私有属性，以及首次交付提交 `24098381010e2cec6d07974d71358de10cbee306` 与远端提交及文件树完全一致，29 个历史提交均已推送。见[发布证据](../examples/phase6-publication/publication.json)及[发布前审计](../examples/phase6-publication/pre-publication-audit.json)。后续收尾提交仅更新发布记录和文档，不改变受验实现。

GitHub 插件用于核对账号和仓库；因其没有新建仓库接口，使用 GitHub 官方 CLI 创仓并通过 Git 推送。CLI 首次设备登录领取凭据时直连超时，明确使用已有系统代理后登录成功。账号授权由用户在 GitHub 页面完成，没有向聊天发送密码或令牌。CLI 工具及本机登录配置位于被忽略的 runtime 目录，不随项目发布。

## 复现协议

`README.md` 按原题十项内容组织；`uv.lock`、带散列的三份 requirements 及构建工具固定版本。运行 `scripts/verify_phase6.py --output-dir runtime/phase6-cold-start` 前须提交全部输入，输出目录必须不存在。

脚本从已提交 Git 历史创建独立副本，禁止复制 `.env`、`.venv`、runtime；创建新 Python 环境，无缓存按散列安装依赖，构建并安装非 editable wheel；核对包实际加载路径。容器使用 Phase 5 已记录的固定基础镜像，禁用构建缓存。数据从归档 BANKING77 原始文件按散列重新导入。

随后执行完整 Phase 5 验收入口，覆盖全部测试、三类 CLI 任务、两类 Web 任务、插件、图谱、取消与实际超时；另外启动已安装 Streamlit 服务并探测健康状态。导出 Schema、源码 ZIP、wheel、命令日志与产物散列。新增付费 API 请求为零；真实 API 采用 Phase 3/4 已验收证据。

隔离范围为同一台物理主机上的独立工作目录和环境，仍使用已有 Python 解释器和 Docker 服务；不宣称已在第二台机器、其他操作系统或完全离线首次安装成功。

## 可追溯与发布检查

`scripts/audit_release.py` 检查 Git 跟踪文件、文档链接、原始资料散列、需求矩阵 CSV/Markdown 一致性、README 十项及历史产物散列。`--history` 扫描所有可达 Git blob；本机发布前使用 `--env-file .env` 仅在内存中比较当前密钥，不输出密钥内容。额外检查常见令牌/私钥模式和 100MB 单文件限制。此检查有明确范围，不保证识别所有可能的秘密信息。

只发布经检查的 Git 提交，不能上传整个工作目录。私有仓库创建后核验所有者、名称、私有属性、远端 HEAD 与本地提交；GitHub 连接和权限不可用时记录待完成，不将本地验收等同于已上传。

## Gate 收尾

| Gate | 交付证据与范围 | 当前状态 |
| --- | --- | --- |
| G1 完整性 | 十项 README、需求矩阵、可安装包、全量示例及检查 | 已验收，产物及远端代码库可定位 |
| G2 主流程 | Phase 2.5/3 Mock 及真实 API；生成到最终测试与回写 | 已验收，复用历史证据 |
| G3 独立验证 | 测试集边界、有界修复、同协议比较及三任务兼容；全量回归 | 已通过当前提交复验 |
| G4 加分机制 | Phase 4/5 经验、版本、图谱、解释、安全与框架复用 | 已验收，收益限制不变 |
| G5 可复现交付 | 冷启动记录、提交、依赖、私有 GitHub 远端 | 已验收，同机独立环境与私有远端均已核验 |

报告已归档至 `examples/phase6/verification.json`，已完成的私有发布独立记录于 `examples/phase6-publication/publication.json`。完整源码 ZIP 约 127.7 MB，保留在本地 runtime 目录，报告记录散列及重建命令；不重复提交这个超过 GitHub 单文件限制的压缩包。历史失败尝试保留且不更改原判定；`docs/source` 的原始内容不得改写。

## 尝试与修正

[尝试记录](../examples/phase6/attempts/attempts.json)保留前三次退出：依赖安装参数错误；为调整大型 ZIP 归档而主动停止；扫描器把测试中的私钥文件头误判为真实私钥。已修正参数、交付包布局及扫描规则，最终从新提交完整重跑通过。扫描误报不涉及真实密钥泄漏。最终产物的[归档清单](../examples/phase6/archive-sha256.json)覆盖原报告、日志、包及这些尝试记录。

## 最终范围

G1–G5 已在本文及既有阶段声明的范围内验收；未选择的加分项仍为 out_of_scope。冷启动是同机独立环境验证，真实 API 是 Phase 3/4 历史证据，经验普遍收益未得到证明。冷启动原报告中的 `separate_publication_check_required` 保留历史记录，由独立发布证据补齐；不改写当时的运行报告。
