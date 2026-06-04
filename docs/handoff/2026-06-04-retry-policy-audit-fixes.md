# 2026-06-04: 用例级重试 + 审计修复

## 概要

- **分支**: `dev/phase1-implementation`
- **Commits**: 5 个 (30b2312 → 7186537)
- **触发**: 同行反馈 (用例失败 3 次才算失败) + Opus 全项目审计

## Commit 清单

| # | Hash | 类型 | 内容 |
|---|------|------|------|
| 1 | 30b2312 | feat(retry) | 用例级 3 次重试 + human_review_required |
| 2 | 5ab3e19 | fix(audit) | Phase 2 perf — compaction 二次 LLM / sleep / count_tokens |
| 3 | 9a10220 | fix(audit) | Phase 3 stability — requirements / return types / Input 计数 / 密码脱敏 |
| 4 | 7186537 | chore(audit) | Phase 4 hygiene — 删脏文件 / 清空目录 / 端口统一 |
| 5 | b79ba94 | fix(audit) | Phase 1 blockers — BUG-01/02/08 (已在之前 commit) |

## Part A: 用例级重试 (核心新功能)

**策略**: 用例 fail → runtime 自动重跑整个用例, 最多 2 次重试 (总 3 次尝试).

**重试流程**:
1. 用例执行完毕, `_determine_status()` 判定为 "failed"
2. `_capture_failure_context()` 抓取:
   - 最后失败步骤的 action/target/args
   - assertion status + reasoning
   - 截图 (data/screenshots/{task_id}/retry{N}_step{M}.png)
   - a11y tree (page.accessibility.snapshot(), 截断到 10KB)
   - 当前 URL
3. `_reset_browser_state()` 完全重置浏览器 (cookies + storage + goto blank + goto target)
4. `_build_execution_state()` 构造新 state, failure_context 注入 SystemMessage 顶部
5. 重新执行用例 (从 step 1 开始)
6. 3 次都 fail → status="human_review_required", failure_context 持久化到 DB

**新 env var**: `MAX_TEST_CASE_RETRIES=2` (可配, 0=禁用重试)

**新 WebSocket 事件**:
- `test_case_retry` — 重试前推送 (attempt/max_retries/previous_reasoning/screenshot_path)
- `test_case_complete` — 新增 retry_count 字段

**新 TestResult 字段**:
- `retry_count: int` — 0=首次成功, 1-2=重试次数
- `failure_context: list[dict]` — 每次失败尝试的 context (供后续人工 review)

**status 扩展**: `"human_review_required"` 加入 TestResult.status Literal

**改动文件**:
- `core/interfaces.py` — TestResult 扩展
- `core/runtime.py` — 5 个新辅助方法 + retry loop 重构 (_execute_test_case + _execute_test_case_stream)
- `tests/core/test_runtime_retry.py` — 6 个测试 (T1-T6)
- `.env` — MAX_TEST_CASE_RETRIES=2

## Part B: Phase 2 性能修复

- **B1**: 移除 compaction 二次 LLM 调用 — `compact_history` 返回 `(RemoveMessages, summary)` tuple, observe_node 不再重复调 `_invoke_compact_llm`
- **B2**: 注入 `_compaction_summary` 到 decide_node messages — 拼到 system_prompt 顶部 (跟 session_summary 一样的方式)
- **B3**: 移除 `execute_node` 硬编码 `await asyncio.sleep(2)` — 限流由 LLM client retry 逻辑处理
- **B4**: 修 `context_manager.py` count_tokens 错 import — 从 `core.interfaces` 改到 `core.llm_client`

## Part C: Phase 3 稳定性

- **C1**: `requirements.txt` 加版本钉 + 补 `browser-use>=0.12.0` + `tiktoken>=0.13.0`
- **C2**: `request_human_intervention` 返回 dict (`{"success": bool, "result": str}`) — 与其他工具返回一致
- **C3**: `page_semantic.py` Input 重复计数 — `input:visible:not([type='checkbox']):not([type='radio'])` 排除专用选择器已覆盖的类型
- **C4**: 探索模式密码脱敏 — `prompts.py:490` 密码替换为 `****** (工具自动填充)`

## Part D: Phase 4 卫生

- **D1**: 删 6 个根目录脏文件 (check_db/debug/debug_explore/test_runtime_bug/test_tool/trigger_test)
- **D2**: 迁移 monitor_task.py → tests/scripts/, trigger_test.py → scripts/
- **D3**: 删 old/ (4.35MB) + pdf_images/ (7.29MB) + src/ (空) — 可从 git 恢复
- **D4**: 清 api/app.py 9x debug prints + api/websocket.py 死函数 stream_runtime_updates
- **D5**: 端口统一 8002 (monitor_task.py + trigger_test.py)

## 测试结果

- `tests/core/test_runtime_retry.py`: 6/6 ✓
- `tests/core/test_context_manager.py`: 更新 3 个 compact_history 测试 ✓
- `tests/agents/ui/test_assert_integration.py`: 10/10 ✓
- 全量回归 (agents/ui + core): 102/102 ✓

## 未提交的 other-AI 改动

`stash@{0}` 里有 other-AI 的 5 文件改动 (tools/cdp/llm/memory/runner + test_resolve_via_cdp), 待用户决定是否 pop.

## 后续 TODO

- [ ] other-AI stash pop / 丢弃决策
- [ ] WV-007 单用例冒烟 (验证 retry policy 兼容性)
- [ ] L2_USE_CDP=1 端到端测试
- [ ] .env 模型配置恢复 (当前全设为 mimo-v2.5, 应切回 qwen3.7-max/kimi/deepseek/glm)
- [ ] human_review_required 的 UI/API 层实现 (当前只持久化, 无 UI)
