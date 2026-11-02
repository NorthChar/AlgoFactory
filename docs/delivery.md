# 交付与复现

交付版本为 0.8.0。主入口是 [README](../README.md#quickstart)，无需公网服务器。私有仓库必须给接收者访问权限；源码内含同一套 Streamlit 工作台，运行结果在接收者自己的 runtime/ 中生成。

## 提交目录

- src/、tests/：运行实现与回归测试；tests/fixtures 保存必要的离线错误重放材料。
- data/：固定版本 BANKING77 原始数据、许可及算法能力材料。
- examples/：精选完整案例、失败/修复证据、知识样例和明确标注的节选。
- docs/：当前架构、使用说明、验收口径、原题及要求对照。
- scripts/、docker/、锁文件：环境准备、隔离执行与可重复检查。

内部讨论计划、旧阶段日志和重复实验已经移出当前目录；保留于 [整理前固定提交](https://github.com/NorthChar/AlgoFactory/tree/2758572d4167b9f66420b79ffd415f51819cb60e)。本机也保存了原目录备份。没有重写 Git 历史，因此普通完整克隆仍包含历史大文件；首次只需当前版本可使用 `git clone --depth 1 --branch v0.8.0 https://github.com/NorthChar/AlgoFactory.git`（标签发布后）。

## 独立复现方法

先完成 README 的依赖、镜像和原始数据导入。提交所有需要验证的代码后，在干净工作区运行：

```sh
.venv/bin/python scripts/verify_reproduction.py --output-dir runtime/reproduction-new
```

脚本从已提交代码创建独立浅克隆、新 Python 环境、按散列安装锁定依赖、构建并非 editable 安装 wheel、重新导入随仓库数据、执行完整 Docker 回归，再运行四种分类目标和两条需求的修复检查。输出目录必须全新。默认不调用真实 API，不访问最终测试。

该协议复用同机依赖缓存和已经批准的 Docker 镜像，不是第二台机器验证或无缓存镜像重建。接收者首次仍需按 README 在自己机器构建镜像。完整初装历史可在旧版本追溯，不能代替当前复现。

## 当前验证记录

[本次复现记录](evidence/release-080/README.md) 已通过，代码基线 `3dec1409ec5c6ac6de994e7c5bcfadb46f7afd0a`：

- 独立浅克隆、新 Python 环境、锁定依赖与 wheel 安装成功，确认加载的是新环境中的安装包。
- 307 项完整回归通过，零失败、零错误、零跳过，包含真实 Docker 与页面检查。
- 全量、三个类别、两个类别、单个意图四个工作台任务均完成验证、回写及隔离模型试用。
- 两条离线需求完成真实执行；逻辑回归案例通过显式注入故障验证修复。
- 本次新增付费 API 请求为 0。目标与需求复验仅使用验证集；完整回归中的测试用例包含最终测试路径。

当前源码、测试、依赖与复现基线一致，后续发布提交增加文档和证据。整理前真实 API 新目标记录另见 [目标验证](../examples/intent-goals/README.md)。

## 审计与提交

`python scripts/audit_release.py --output runtime/release-audit.json --history` 检查已跟踪文件、说明链接、题目原文散列、精选历史文件原样搬迁、完整案例清单及可达 Git 历史中的常见凭据模式。可显式提供 `--env-file .env` 以检查当前密钥是否意外写入，审计不输出密钥。该扫描不是对所有秘密形式的绝对保证。

发布时记录固定提交或标签，同时确认私有仓库可访问。工作台地址 127.0.0.1 仅在运行它的电脑本地有效；不属于可供老师远程打开的在线服务。
