# Phase 6 本地交付证据

实现提交：`da42b56eb6b3dfce1db733679f8ebc024824d430`。233 项测试通过、零跳过，付费 API 请求为 0。GitHub 私有发布独立跟踪，尚未完成。

- [统一报告](verification.json)：独立副本、新环境、wheel 安装、无缓存容器重建、命令、环境、提交及散列。
- [安装记录](installation.json)与 [wheel](algofactory-0.6.0-py3-none-any.whl)。
- [完整 CLI/Web 验收](acceptance/verification.json)：三类任务、图谱、插件、恢复、取消和真实超时清理。
- [发布审计](release-audit.json)：对被验收实现提交的跟踪文件及 Git 历史进行检查；最终归档后的扫描另见本机 runtime 报告。
- [早期尝试](attempts/attempts.json)：保留失败和主动中止原因，不将其改写为通过。
- [归档散列](archive-sha256.json)：包括本索引及失败尝试；原始报告及其散列清单保持原样。

完整源码 ZIP 为本地交付包，含历史实验档案，约 127.7 MB。路径、SHA-256 和按提交重建的命令在统一报告的 `source_bundle` 中；为遵守 GitHub 单文件限制，不重复纳入仓库。wheel 运行仍需项目数据、任务配置及批准镜像；依照根目录 README 准备。

这次复现使用同一物理主机，不宣称跨平台或离线首次安装。真实 API 使用 Phase 3/4 已有证据，当前复验不新增付费调用。
