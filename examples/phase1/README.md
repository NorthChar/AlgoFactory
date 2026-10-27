# Phase 1 实际运行证据

实现提交：`bae207ac71987dfcea60af02f400656add3dab28`。

- 测试：78 项通过，0 失败、0 错误、0 跳过。
- 知识示例：1 份文档，6 个实体，7 条关系；检索得到 3 个二分类候选算法。
- 验证：原文引用、事务回滚、幂等导入、关闭重开、JSON/GraphML 往返、Mock/API 共同契约及本地 HTTP 测试。
- 安装：独立虚拟环境，带散列锁定依赖和 wheel 安装；包内 12 个源码/资源文件与提交内容一致，4 个 CLI 命令通过。
- 范围：固定 Mock 知识流程与本地 API 契约测试；真实外部 API 和算法执行闭环尚未验收。

[verification.json](verification.json) 记录环境、命令、逐文件及产物散列。测试在提交前完成，随后逐文件与上述提交核对并绑定；没有重复执行或改写测试结果。

[installation.json](installation.json) 记录独立安装及实际 CLI 输出；[knowledge.json](knowledge.json)、[knowledge.graphml](knowledge.graphml) 和 knowledge.sqlite 是同一知识快照。[retrieval.json](retrieval.json) 包含检索与原文证据。

复现：在项目根目录执行 `.venv/bin/python scripts/verify_phase1.py --output-dir runtime/phase1`。
