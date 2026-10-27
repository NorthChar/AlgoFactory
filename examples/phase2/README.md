# Phase 2 验证证据

本目录由 scripts/verify_phase2.py 实际运行生成，采用固定 Mock LLM 响应及真实 Docker 算法执行。代码提交、时间、环境、命令和全部产物散列见 verification.json；101 项测试通过，零跳过。APIProvider 的模拟传输测试不代表真实外部服务调用。

- normal/：正常闭环的代码、检索证据、计划、协议、轨迹和四维报告。
- repeat/：固定输入重复运行，验证与测试指标完全一致。
- missing-interface/：真实容器检测到缺少 predict_proba，停止且不进入最终测试。
- unsafe-code/、invalid-response/：在执行前拒绝危险代码或非法响应。
- dataset/：合成 CSV、900/300/300 划分、数据散列及冻结门槛。
- knowledge.sqlite、knowledge.json、knowledge.graphml：持久化知识和实际运行结果，可重开与重载。
- docker-image.json：固定镜像 ID、基础镜像摘要、worker/依赖散列及容器环境。
- tests.xml、check-*.log：测试及 CLI 演示的真实记录，故障案例退出码 1 为预期。
- installation.json、installation.log、wheel-install/：同机全新虚拟环境安装 wheel 后实际 Docker 运行；wheel-install.sqlite 为该安装检查的独立知识库。

独立测试 F1 0.666667、ROC-AUC 0.816260、Precision 0.760870、Recall 0.593220。合成数据分数仅证明流程可用，不代表真实业务效果。每个独立 workflow 最终测试阶段一次，不根据测试成绩调参。

超时/OOM/清理失败分支使用模拟 Docker 响应测试，非实际资源压测。未验证真实 LLM API、自动修复、多候选比较或经验复用。复现使用新的输出目录，避免覆盖已归档证据；旧报告中的绝对路径是当时的运行位置。
