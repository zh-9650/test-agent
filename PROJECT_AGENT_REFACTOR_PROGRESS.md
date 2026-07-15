# Smart Test Agent Agent 化重构进度记录

最后更新：2026-07-03

本文用于记录 `PROJECT_AGENT_SYSTEM_DESIGN.md` 落地进度。它不是新的设计文档，只记录已经完成、已经验证、当前限制和下一步计划。

## 当前阶段

当前处于设计文档 P0 / P1 / P2 落地完成阶段：

```text
P0 证据和可控性已落地；
P1 HITL / Memory 已形成可用闭环；
P2 checkpoint / resume policy / eval scoring 已落地。
```

按本轮 Agent 化落地计划估算，当前进度 100%：

- P0：完成。
- P1：完成。HITL request / decision / paused_for_review / resume 已闭环；Memory 已进入设计与执行主链路，并进入报告 provenance。
- P2：完成。阶段 checkpoint、resume policy、真实任务产物评分、工具错误码细化与报告观测已落地。
- P3+：仍按设计文档保持谨慎扩展，不在本轮 100% 验收范围内默认开启。

## 本轮已完成

### 1. RuntimeToolResult 生产化

新增位置：

- `core/runtime_tool_contract.py`

完成内容：

- 新增 `RuntimeToolResult` 作为生产运行时工具结果合同。
- 保留 `ActionResult` 给 `agents/ui/tools.py` 这类宽工具库使用。
- 新增运行阶段字段：`phase`。
- 新增权限字段：`permission_level`。
- 新增工具状态：`success`、`blocked`、`failed`、`timeout`、`not_found`、`noop`、`completion_rejected`。
- 新增结构化字段：`error_code`、`normalized_args`、`changed_signals`、`selector_resolution`、`duration_ms`、`evidence`、`hitl_required`、`hitl_reason`。

### 2. action policy 错误码结构化

修改位置：

- `core/runtime_action_policy.py`

完成内容：

- `ActionPolicyDecision` 增加 `error_code` 和 `permission_level`。
- policy 拦截统一产出 `policy.*` 错误码。
- 已覆盖：
  - `policy.action_not_mapping`
  - `policy.missing_tool`
  - `policy.unsupported_tool`
  - `policy.args_not_mapping`
  - `policy.missing_navigation_url`
  - `policy.forbidden_navigation_target`
  - `policy.cross_origin_navigation_blocked`
  - `policy.missing_selector`
  - `policy.generic_container_selector_blocked`
  - `policy.browser_chrome_selector_blocked`
  - `policy.missing_input_text`

### 3. Runtime 工具执行结构化

修改位置：

- `core/runtime.py`
- `core/runtime_session.py`

完成内容：

- `_execute_browser_action()` 从字符串结果升级为返回 `RuntimeToolResult`。
- exploration 和 execution 复用同一工具结果合同。
- 执行阶段继续使用 `feedback_text()` 兼容原有证据链和失败反馈逻辑。
- selector 异常分类为：
  - `selector.not_found`
  - `selector.ambiguous`
- Playwright 超时分类为：
  - `tool.timeout`
- 其他工具异常分类为：
  - `tool.exception`
- select 选项缺失分类为：
  - `tool.missing_select_option_value`
- case 级异常补充分类：
  - `case.attempt_timeout`
  - `case.execution_error`
- `input_text` 的证据字段只保存脱敏后的 `filled_value`。

### 4. TaskStep 兼容记录结构化工具结果

修改位置：

- `core/execution_store.py`

完成内容：

- 不改数据库表结构，符合设计文档第一阶段落库策略。
- `TaskStep.result` 保存 `RuntimeToolResult.feedback_text()`。
- `TaskStep.action_args` 保存 `normalized_args`。
- `TaskStep.change_report` 保存结构化工具结果摘要，包括：
  - `tool`
  - `phase`
  - `permission_level`
  - `status`
  - `error_code`
  - `url_changed`
  - `page_changed`
  - `before_url`
  - `after_url`
  - `duration_ms`
  - `selector_resolution`
  - `hitl_required`
  - `hitl_reason`
  - `evidence`

### 5. 报告展示工具失败码

修改位置：

- `core/run_report.py`
- `frontend/src/pages/Report.tsx`

完成内容：

- HTML 报告步骤表增加：
  - Tool status
  - Error code
- failed / incomplete / human_review_required case 展示主要工具失败码。
- 前端 Report 页面展示：
  - 工具状态
  - 错误码
  - 主要工具失败码

### 6. Eval 种子集

新增位置：

- `evals/seed_manifest.json`

完成内容：

- 新增 `eval_case_manifest.v1`。
- 固定 10 条 eval 种子，覆盖：
  - 需求事实抽取
  - 冲突需求
  - 权限 / 安全断言
  - 表单流程
  - 列表 / 表格验证
  - 错误提示
  - 状态流转
  - 不可自动执行用例
  - 执行失败恢复
  - 报告可信度

### 7. 工具错误码 taxonomy 和报告统计

修改位置：

- `core/runtime_tool_contract.py`
- `core/run_report.py`
- `frontend/src/pages/Report.tsx`

完成内容：

- 新增运行时工具失败状态集合 `RUNTIME_TOOL_FAILURE_STATUSES`。
- 新增 `ToolErrorTaxon` 和按错误码前缀归类的 `TOOL_ERROR_TAXONOMY`。
- 已覆盖分类：
  - `policy`：策略拦截
  - `selector`：元素定位
  - `tool`：工具执行
  - `case`：用例执行
  - `decision`：动作决策
  - `runtime`：运行时兜底
- HTML 报告新增 Tool error summary，按错误码汇总：
  - 分类
  - 次数
  - 关联用例
  - 分类说明
- 前端 Report 页面新增工具失败码统计表，并继续保留单个失败用例的主要工具失败码展示。

### 8. 显式工具结果 / policy 决策持久化

修改位置：

- `database/models.py`
- `database/connection.py`
- `core/runtime_tool_contract.py`
- `core/runtime.py`
- `core/execution_store.py`
- `api/schemas.py`
- `core/run_report.py`
- `frontend/src/types/index.ts`
- `frontend/src/pages/Report.tsx`

完成内容：

- `TaskStep` 新增 nullable JSONB 字段：
  - `tool_result`
  - `policy_decision`
- `RuntimeToolResult` 新增 `policy_decision` 字段。
- policy 拦截时保存 `allowed=false`、`reason`、`error_code`、`permission_level` 和 `normalized_action`。
- 非拦截工具调用保存 `allowed=true` 的准入摘要。
- `append_task_step()` 同时写入：
  - 兼容字段 `change_report`
  - 显式字段 `tool_result`
  - 显式字段 `policy_decision`
- HTML 报告和前端 Report 优先兼容读取 `change_report`，并可从 `tool_result` 兜底读取工具状态 / 错误码。
- `init_database()` 在无 Alembic 的当前策略下，使用 `ADD COLUMN IF NOT EXISTS` 兼容旧 `task_step` 表。

### 9. Eval runner

新增位置：

- `evals/runner.py`
- `evals/__init__.py`
- `evals/README.md`
- `data/evals/.gitkeep`

修改位置：

- `.gitignore`

完成内容：

- 新增 `python -m evals.runner`。
- 支持读取 `evals/seed_manifest.json`。
- 支持 schema 校验：
  - manifest version
  - case 必填字段
  - inputs / expected_assets / expected_execution / report_checks 结构
  - terminal status 合法性
  - case id 唯一性
- 支持轻量指标汇总：
  - case 数量和 ID
  - tag 分布
  - required assertions / case titles 覆盖率
  - allowed terminal statuses 分布
  - forbidden tools 覆盖率
  - max_tool_failures 范围和均值
  - report checks 覆盖率
- 默认输出到 `data/evals/eval_summary_<timestamp>.json`。
- `data/evals/*` 加入 `.gitignore`，只保留 `.gitkeep`，避免评估产物进入版本控制。

### 10. HITL request / decision 协议基础

修改位置：

- `database/models.py`
- `api/schemas.py`
- `core/execution_store.py`
- `api/app.py`
- `database/connection.py`

完成内容：

- 新增 `HumanReviewRequestRecord`。
- 新增 `HumanReviewDecisionRecord`。
- 新增服务函数：
  - `create_human_review_request()`
  - `list_human_review_requests()`
  - `decide_human_review_request()`
- 新增 API：
  - `GET /api/tasks/{task_id}/human-reviews`
  - `POST /api/tasks/{task_id}/human-reviews`
  - `POST /api/human-reviews/{request_id}/decisions`
- 决策状态支持：
  - `approved`
  - `edited`
  - `rejected`
- `reset_runtime_database()` 将 human review 两张表纳入运行时表重置顺序。
- 协议、持久化和 API 基础已完成；runtime pause / resume 闭环见后续第 12 节。

### 11. Memory 只读召回基础

新增位置：

- `core/memory_context.py`

修改位置：

- `core/skills/l2_pipeline.py`
- `core/skills/coverage_planner.py`
- `core/skills/condition_analyzer.py`

完成内容：

- 新增 `MemoryContext`。
- 新增 `recall_memory_context(target_url, limit=5)`：
  - domain 精确匹配优先
  - global 作为补充
  - 过滤空值
  - 过滤疑似 password / token / credential / private key / JWT 等敏感内容
- 新增 `format_memory_context_for_prompt()`。
- L2 设计阶段自动召回 MemoryContext。
- Memory 注入 coverage planning 和 condition analysis prompt。
- prompt 明确约束：
  - Memory 只能作为 hint
  - 不得作为 `RequirementFact` 来源
  - 不得进入 `source_references`
  - 不得进入 `source_registry`
  - 不得作为 traceability 依据
- `TestAssetPackage.runtime_hints` 记录：
  - `memory_context_hint_present`
  - `memory_context_policy`
  - `memory_context_refs`，仅包含 key / scope / source_domain / provenance 摘要，不保存 memory 原文。

### 12. HITL pause / review / resume 闭环

修改位置：

- `core/runtime_session.py`
- `core/task_lifecycle.py`
- `core/execution_store.py`
- `api/app.py`
- `frontend/src/pages/Monitor.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/types/index.ts`

完成内容：

- 用例最终进入 `human_review_required` 时自动创建 durable `HumanReviewRequest`。
- 任务执行完并发现 `human_review_required` 后，生命周期进入 `paused_for_review`，报告仍会生成。
- `POST /api/human-reviews/{request_id}/decisions` 可记录 `approved` / `edited` / `rejected`。
- `POST /api/tasks/{task_id}/resume` 会检查 pending review；全部处理后创建新 run 重跑非通过用例。
- 前端 Monitor 页面新增人工审查队列、批准 / 拒绝入口，以及暂停后恢复执行入口。
- 报告页新增跳转到“监控与审查”的入口。

### 13. 阶段 checkpoint 和 resume policy

修改位置：

- `database/models.py`
- `database/connection.py`
- `core/execution_store.py`
- `core/task_lifecycle.py`
- `api/schemas.py`
- `api/app.py`
- `frontend/src/types/index.ts`

完成内容：

- `Task` 新增 nullable JSONB：
  - `checkpoints`
  - `resume_policy`
- `init_database()` 使用 `ADD COLUMN IF NOT EXISTS` 兼容旧库。
- 生命周期每个 phase started / completed 都写入 checkpoint。
- 取消、失败、暂停审查都会写入终态 checkpoint。
- resume API 写入确定性恢复策略：
  - `mode`
  - `resumed_from_run_id`
  - `resume_case_ids`
  - `requires_resolved_human_reviews`

### 14. Eval runner 真实任务产物评分

修改位置：

- `evals/runner.py`

完成内容：

- 默认 manifest 校验和汇总路径保持兼容。
- 新增 `--task-id` / `--run-id` / `--eval-case-id`，可读取已持久化真实任务产物并评分。
- 新增 `--execute-case-id`，可从 manifest case 创建真实任务并执行后评分；该能力是显式 opt-in，默认不会打开浏览器或调用 LLM。
- 自动评分覆盖：
  - assets：required assertions / case titles、traceability、memory provenance。
  - execution：分母保持、终态合法性、禁用工具、工具失败数量上限。
  - report：报告存在、结果解释、traceability、human review、tool error summary。
  - checkpoint：任务 checkpoint 和 resume policy。
- 评分结果写入同一个 eval summary JSON 的 `task_evaluation` 字段。

### 15. Memory 接入 analyzing / executing / reporting

修改位置：

- `core/task_lifecycle.py`
- `core/runtime.py`
- `core/run_report.py`
- `frontend/src/pages/Report.tsx`
- `frontend/src/types/index.ts`

完成内容：

- 生命周期入口统一召回 MemoryContext，并注入 `enriched_config`。
- 设计阶段继续使用 hint-only MemoryContext。
- 执行阶段的动作决策 prompt 新增 MemoryContext 提示，但明确不是需求事实或通过依据。
- `TestAssetPackage.runtime_hints.memory_context_refs` 保留 provenance。
- HTML 报告和前端 Report 展示 Memory provenance。

### 16. 工具错误码细化到具体 code

修改位置：

- `core/runtime_tool_contract.py`
- `core/run_report.py`
- `frontend/src/pages/Report.tsx`

完成内容：

- `ToolErrorTaxon` 增加 `remediation`。
- 新增 `TOOL_ERROR_CODE_TAXONOMY`，覆盖常见具体错误码：
  - `policy.cross_origin_navigation_blocked`
  - `policy.generic_container_selector_blocked`
  - `selector.not_found`
  - `selector.ambiguous`
  - `tool.timeout`
  - `tool.missing_select_option_value`
  - `case.attempt_timeout`
  - `case.execution_error`
  - `decision.invalid_or_empty_action`
- HTML 报告和前端工具失败码统计表新增修复建议列。

## 已验证

已运行并通过：

```powershell
python -m compileall core api database agents main.py
python -m json.tool evals\seed_manifest.json
npm run build
npm run lint
```

本次追加工具错误码统计后，重新运行并通过：

```powershell
python -m compileall core api database agents main.py
npm run build
npm run lint
```

本次并行推进到约 50% 后，重新运行并通过：

```powershell
python -m compileall core api database agents main.py evals
python -m evals.runner --manifest evals\seed_manifest.json --output data\evals\latest.json
npm run build
npm run lint
```

本次推进到 100% 后，重新运行并通过：

```powershell
python -m compileall core api database evals
python -m evals.runner --manifest evals\seed_manifest.json --output data\evals\latest.json
npm run build
npm run lint
```

额外 smoke：

- HITL 路由已注册：
  - `/api/tasks/{task_id}/human-reviews`
  - `/api/human-reviews/{request_id}/decisions`
- SQLAlchemy metadata 已包含：
  - `task_step.tool_result`
  - `task_step.policy_decision`
  - `human_review_request`
  - `human_review_decision`
- MemoryContext 安全内容可进入 prompt，疑似 token 内容会被过滤。
- `RuntimeToolResult.policy_decision` 可正常 JSON 序列化。

额外做了轻量合同冒烟：

- 验证跨域导航会产出 `policy.cross_origin_navigation_blocked`。
- 验证 `RuntimeToolResult` 可正常实例化并识别失败状态。

`git diff --check` 无实际 whitespace 错误，仅有 Windows 环境下 LF/CRLF 提示。

## 当前设计决策

- 第一阶段已经结束，当前允许新增兼容性 nullable JSONB 字段。
- `tool_result JSONB` / `policy_decision JSONB` 已落地。
- `TaskStep.change_report` 继续作为旧数据和报告兼容字段保留。
- `mark_task_failed` 被视为工具成功执行，但 case 结果为 failed；这样避免把“模型主动判失败”和“工具执行失败”混成同一类错误。
- `PROJECT_AGENT_SYSTEM_DESIGN.md` 是本次依据文档，目前保持未跟踪状态，未在本轮重构中修改。

## 当前限制

- `page_changed` 目前主要基于 URL 变化，尚未接入完整 DOM diff。
- exploration 阶段虽然返回 `RuntimeToolResult`，但还没有独立持久化完整探索轨迹。
- 工具权限等级目前只给现有生产工具标注 L1，尚未扩展 L0/L2/L3 工具族。
- 工具错误码 taxonomy 已支持具体错误码解释和修复建议；仍可继续按真实运行数据扩充更多 code。
- HITL execution review 已接入 runtime pause / resume；文档级 manual review item 会进入审查队列，但不会自动改写已生成断言。
- Memory 已进入生命周期入口、designing、executing 和 reporting；仍保持只读、hint-only。
- eval runner 已可校验 seed manifest，也可对真实任务的 run/results/steps/report/checkpoint 做自动评分；真实执行通过 `--execute-case-id` 显式开启。
- 新增 human review 表后，旧数据库可通过 `create_all` 新建表；如果旧 `task_step` 缺少新列，启动时会自动补列。
- P3+ 的 L0/L2/L3 工具族、API/CDP 执行能力和 multi-agent 仍按设计保持后置，不作为本轮 100% 验收范围。

## 下一步建议

本轮计划已完成。后续如果继续扩展，建议进入 P3 前先用 `python -m evals.runner --task-id ... --eval-case-id ...` 对真实任务产物建立基线，再谨慎推进：

1. L0 只读工具族。
2. API 执行能力。
3. CDP / network inspection 作为 L2 工具，经 HITL 后开放。
4. screenshot_on_demand 的配额化场景接入。
5. multi-agent 评估仍需等单 agent eval 稳定后再开启。

## 维护规则

- 后续每次按设计文档落地一批改动，都在本文追加进度。
- 本文只记录事实，不写新的架构分歧结论。
- 若设计发生变化，应更新 `PROJECT_AGENT_SYSTEM_DESIGN.md`，本文只引用变化后的执行结果。
