# Issue Tracker：GitHub

本仓库的 Issues、Wayfinder 地图和调查票存放在 GitHub 仓库 [`zh-9650/test-agent`](https://github.com/zh-9650/test-agent)。

## 工具约定

- Codex 中优先使用已连接的 GitHub App 执行其支持的 Issue 操作。
- 命令行操作使用 GitHub CLI `gh`；使用前必须确认 `gh auth status` 成功。
- 当前开发机尚未安装 `gh`。在需要 GitHub App 未覆盖的子 Issue、依赖或标签管理操作前，先安装并登录 `gh`。
- 不从 Git 凭据存储中提取或打印访问令牌。

## 基本操作

- 创建、读取、评论、更新和关闭 Issue 时，从仓库远端推导 `zh-9650/test-agent`，不要依赖聊天记忆。
- 多行 Issue 正文使用真实 Markdown，不把转义后的 `\n` 当换行。
- 外部 Pull Request 不作为需求入口；PR 只承担代码交付和审查。

## Wayfinder 操作

- **地图**：一个带 `wayfinder:map` 标签的 Issue，只保存 Destination、Notes、Decisions so far、Not yet specified 和 Out of scope。
- **调查票**：地图的子 Issue，使用 `wayfinder:research`、`wayfinder:prototype`、`wayfinder:grilling` 或 `wayfinder:task` 标签。
- **子 Issue**：优先使用 GitHub 原生 sub-issue；不可用时，在地图任务列表中链接调查票，并在调查票正文顶部写 `Part of <map-link>`。
- **阻塞关系**：优先使用 GitHub 原生 issue dependencies；不可用时，在被阻塞调查票正文顶部写 `Blocked by: <issue-link>`。
- **领取**：开始调查前先把调查票分配给当前执行者；未分配、未阻塞、仍开启的调查票才属于 frontier。
- **解决**：把结论写入调查票评论，关闭调查票，并在地图 `Decisions so far` 中追加一行结论摘要与链接。
- **引用方式**：面向人的文本始终使用 Issue 标题作为名称，编号和链接只嵌在标题中。

## Wayfinder 当前目的

当前地图用于找到通往《test_agent v2 用例生成内核实施规格》的路线。地图默认只解决实施前仍未明确的决策，不直接交付代码、Runtime 改造或共享 Skill 切换。

当前地图：[`Wayfinder：完成 test_agent v2 用例生成内核实施规格`](https://github.com/zh-9650/test-agent/issues/1)。
