# 可查看的生成与验证案例

| 目录 | 内容与用途 |
| --- | --- |
| [banking-classification](banking-classification/comparison/report.md) | 真实 API 完整生成、失败修复、双候选比较、最终测试和知识回写；保留完整历史校验清单 |
| [mock-repair](mock-repair/report.md) | 固定 Mock 注入故障后真实执行与修复；不能当作真实模型自发错误 |
| [rejected-code](rejected-code/report.md) | 危险代码被静态检查拒绝的案例 |
| [experience-reuse](experience-reuse/historical-summary.json) | 一个经验启用运行、知识库、经验及历史开关对照摘要；摘要中的其余原始运行在历史版本中 |
| [knowledge](knowledge/knowledge.json) | 类型化知识 JSON 与 GraphML |
| [intent-goals](intent-goals/README.md) | 新增分类目标的验证摘要、真实 API 理解与代码生成节选 |

[provenance.json](provenance.json) 记录搬迁文件的原始路径、来源提交和逐文件散列。保留的历史文件按字节复制，内嵌原目录、命令和时间戳不改写；搬迁不代表重新执行历史实验。概率文件使用无损 gzip 存储，读取时核对解压内容散列。

当前版本不携带全部阶段实验和重复数据。它们仍可在 [整理前的固定版本](https://github.com/NorthChar/AlgoFactory/tree/2758572d4167b9f66420b79ffd415f51819cb60e/examples) 查看。需要执行旧脚本或核对旧完整清单时，应检出该版本，不能混用新代码与旧阶段命令。

这些记录用于说明和离线回归，不会自动重放 API 请求。新任务和训练模型保存在被忽略的 runtime/。当前版本复现方法见 [README](../README.md#quickstart)。
