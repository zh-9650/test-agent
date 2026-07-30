# Agent 协作说明

本仓库用于开发证据驱动、强约束的 Web 测试 Agent。所有 Agent 默认使用中文沟通，并在修改代码前读取与任务相关的项目文档、领域术语和架构决策。

## 文档入口

- 项目总览：`PROJECT.md`
- 目标架构：`PROJECT_AGENT_SYSTEM_DESIGN.md`
- 当前进度：`PROJECT_AGENT_REFACTOR_PROGRESS.md`
- 领域术语：`CONTEXT.md`
- 文档索引：`docs/README.md`
- 架构决策：`docs/adr/`

## 当前改造边界

- 当前优先事项是验证 v2 用例生成内核，不同时改造 Runtime、执行 Memory 或共享 Skill。
- 旧 `core/skills/l2_pipeline.py` 作为 v1 基线保留；v2 通过独立入口或显式 feature flag 验证。
- 模型验证、覆盖编译和用例质量门必须由确定性程序执行，不能只依赖提示词约束。
- 未通过真实样本的 v1/v2 盲测前，不切换默认公共路由。

## Agent skills

### Issue tracker

Issues、Wayfinder 地图和调查票存放在 GitHub 仓库 `zh-9650/test-agent`；外部 Pull Request 不作为需求入口。见 `docs/agents/issue-tracker.md`。

### Triage labels

使用默认五状态标签：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。见 `docs/agents/triage-labels.md`。

### Domain docs

使用单上下文布局：根目录 `CONTEXT.md` 与 `docs/adr/`。见 `docs/agents/domain.md`。
