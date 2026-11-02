# 可选择分类目标：验证摘要与真实 API 节选

[验证摘要](verification-summary.json) 记录整理前 307 项回归、四种 Mock + Docker 示例、三个派生任务的最终测试及隔离模型试用。不是所有类别组合的性能保证，也不代表本次整理后重新执行；当前提交版复现另见 [交付记录](../../docs/delivery.md)。

[真实 API 理解](live-understanding.json)、[被复核拒绝的首次提案](live-understanding-rejected.json)、[生成与验证摘要](live-generation.json) 保留成功与失败。总计 8 次请求：理解及复核 4 次，生成流程 4 次。该单意图案例完成验证、回写和试用，未执行最终测试。查看 [生成代码](generated/candidate.py) 和 [报告](generated/report.md)。

此目录是明确标注的节选，不是完整运行归档：未附模型、大型预测矩阵和全部数据库。文件原样复制，保留原本机路径、时间和引用；内嵌 runtime 路径无法在克隆后直接打开。[节选清单](excerpt-manifest.json) 给出原始路径和散列。完整端到端历史证据另见 [banking-classification](../banking-classification/comparison/report.md)。新任务可按 README 重新生成，Mock 复验无需密钥。
