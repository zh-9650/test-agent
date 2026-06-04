# Handoff — System Problems 排查 + CDP 启用 (下一阶段)

**日期**: 2026-06-04
**Branch**: `dev/phase1-implementation`
**Last Commit**: `27c0a61` — fix(benchmark): capture traceback in runner error path + rewrite handoff (v2)
**Working dir**: `C:\Users\17381\Desktop\test_agent`

---

## 1. 一句话总结

Phase 2.0C+D + WebVoyager benchmark 代码全部落地，**但 0/10 的真实失败原因还没定位**。下一阶段的核心任务：用 traceback 捕获 + A/B 测试 + prompt 修复 把 10 个 case 的根因逐个挖出来，**同时**把休眠中的 CDP 模块接入执行路径。

**当前状态 = 评测器已对齐官方标准 + 6 个系统问题待排查 + CDP 等待 wiring。**

---

## 2. 接手后第一件事

```powershell
cd C:\Users\17381\Desktop\test_agent
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 1) 查看当前状态
git log --oneline -5
git status

# 2) 阅读主 handoff (这是上一份，含完整 system problems 清单)
#    重点看 §6: System Problems
code docs/handoff/2026-06-04-phase2.0CD-benchmark.md

# 3) 看上一份 benchmark 输出
code data/webvoyager_report_v3.md

# 4) 编译验证
python -c "import py_compile; files=['agents/ui/execution_graph.py','agents/ui/tools.py','core/interfaces.py','core/page_semantic.py','core/runtime.py','core/cdp_client.py','core/backend_node_map.py','tests/benchmarks/webvoyager_subset/runner.py']; [py_compile.compile(f, doraise=True) or print(f+' OK') for f in files]"

# 5) 跑受影响的测试
python -m pytest tests/agents/ui/test_action_result.py tests/agents/ui/test_assert_integration.py tests/agents/ui/test_screenshot_on_demand.py tests/core/test_backend_node_map.py tests/core/test_cdp_resolve.py tests/core/test_context_manager.py tests/core/test_dependency.py tests/core/test_parallel_executor.py tests/agents/ui/test_execution_graph.py -q
```

---

## 3. 上一份 (2026-06-04) 做了什么

主 handoff `2026-06-04-phase2.0CD-benchmark.md` 已详述。要点：

- **Phase 2.0C (用户主动触发)**: 5 个 CDP 模块 (`cdp_client.py` / `backend_node_map.py` / `context_manager.py` / `dependency.py` / `parallel_executor.py`) 已写完并单测通过，但**未接入 production tool path**。`get_cdp_session()` 当前无任何调用方。
- **Phase 2.0D**: `ActionResult` 加 8 字段 (browser-use parity) + screenshot-on-demand (默认 `L2_OBSERVE_SCREENSHOT=0`)。
- **WebVoyager benchmark**: 评测器对齐官方 LLM judge 协议，2 个 blocker bug 修好 (DB init + MiMo image format)，runner 加 traceback 捕获。
- **Benchmark 0/10**: 4 fail + 6 error。**评测器正确**，agent 行为有问题。

详细分类见主 handoff §6。

---

## 4. 6 个系统问题 (按优先级)

来自 `data/webvoyager_report_v3.md` 10 case 真实数据：

| # | 问题 | 范围 | 严重度 | 修复成本 |
|---|------|------|--------|---------|
| **P0** | 6 个 error 没 traceback (runner.py:319 旧版只记 `f"{type(e).__name__}: {e}"` 单行) | 所有 error 任务 | 🔴 阻塞 debug | **已修** (commit 27c0a61)，下次跑可见 `data/bench_errors/*.log` |
| **P1** | WV-005 / WV-010 失败在 graph 启动前 (0 L2_NODE_EVENT, 2-30s) | setup 阶段 | 🔴 阻塞 | 1-2h: 加 `page.goto` retry + `wait_until="networkidle"` |
| **P2** | WV-008 跑满 599s (接近 `max_steps * step_avg` 上限) | 长时间任务 | 🟡 慢 | 30min: 加 `time_budget_s` 或 bump `max_steps` |
| **P3** | WV-003 / WV-004 agent 捷径行为 (navigate 到 result URL 不填表) | 4 个 fail 里的 2 个 | 🟡 LLM 推理 | 1h: 加 system prompt rule |
| **P4** | WV-006 mark_task_complete 时 `extracted_content` 空，judge 收空 answer | mark 工具设计 | 🟡 评估失败 | 1-2h: 让 `mark_task_complete` 自动提取 page title/headline |
| **P5** | 5/10 站点是 anti-bot (CAPTCHA / popup / ERR_HTTP2)，无法解决 | scope 限制 | 🟢 不可修 | 跳过或换站 |

---

## 5. 下一步行动 (按 ROI 排序)

### Action A: 跑 benchmark 拿 traceback (1-2h, 立即可做)

```powershell
# 这次跑会产出完整 stack trace
python tests/benchmarks/webvoyager_subset/runner.py --output data/webvoyager_report_v4.md

# 查看每个 error 的实际原因
Get-ChildItem data\bench_errors\*.log
```

**预期产出**: 6 个 error 的真实 stack trace。大多数应该是 Pydantic 校验失败 / LLM 超时 / Playwright timeout 之一。

### Action B: A/B 测试截图-on-demand (30min, 与 A 并行)

```powershell
# 当前默认 (on-demand)
python tests/benchmarks/webvoyager_subset/runner.py --output data/report_a.md

# 旧行为 (每步都截)
$env:L2_OBSERVE_SCREENSHOT = "1"
python tests/benchmarks/webvoyager_subset/runner.py --output data/report_b.md
```

**对比标准**: report_b 成功率是否 > report_a。如果 > 20%，把 `L2_OBSERVE_SCREENSHOT` 默认改回 `1` 或加视觉-aware prompt。

### Action C: 修 agent 捷径 prompt (1h, Action A 完成后做)

在 `agents/ui/prompts.py` 的 system prompt 里加：

```
【禁止行为】
- 禁止 navigate() 到带 query 参数的 result URL (如 ?q=xxx, /searchresults.html?...)。必须通过表单交互完成搜索/过滤。
- 遇到 popup 阻挡时，先尝试 dismiss popup (close button, ESC key, click outside)，再继续表单。
- 调用 mark_task_complete 前，必须先调用 extract() 提取最终答案到 extracted_content。
```

### Action D: 接入 CDP 模块 (4-8h, 下一 sprint)

**当前状态**: `core/cdp_client.py` / `backend_node_map.py` 单测通过，但生产 tool 路径仍走 Playwright `page.locator()`。

**接入步骤**:
1. 在 `tools.py:_resolve_element` 加分支: `if os.getenv("L2_USE_CDP") == "1": return await _resolve_via_cdp(page, target, task_id)` else 走 Playwright。
2. 实现 `_resolve_via_cdp`: 查 `BackendNodeMap.get(task_id, target_id)` → `cdp_session.send("DOM.resolveNode", {backendNodeId})` → 拿到 ElementHandle。
3. gate 改用 `L2_USE_CDP=1` 启动；先在 1-2 个 case 跑通，再开 10 case A/B。
4. 重新跑 benchmark，对比 CDP 路径 vs Playwright 路径的成功率 + locator 失败率 (B3.2 埋点)。

### Action E: 处理 WV-006 mark 提取问题 (1-2h, 与 C 并行)

在 `tools.py` 的 `mark_task_complete` / `mark_task_failed` 末尾加:

```python
# Auto-extract final answer from page
if not action_result.extracted_content:
    from core.page_semantic import extract_page_semantics
    page_info = await extract_page_semantics(page, task_id=task_id)
    # 取 page title + 第一条 headline / heading 文本
    extracted = page_info.get("title", "")
    if page_info.get("headlines"):
        extracted = f"{extracted} | {page_info['headlines'][0]}"
    action_result.extracted_content = extracted
```

---

## 6. 关键决策 / 不要重复踩的坑

1. **不要用 `Get-Process chrome* | Stop-Process -Force`** 清理 benchmark 进程。**会撞坏用户的真实 Chrome 浏览器**。只杀 Python 进程 + headless Chromium (`chrome-headless-shell` / `chromium`)。

2. **MiMo v2.5 image 格式必须 Anthropic-native** (`{"type":"image","source":{"type":"base64","media_type":"image/png","data":...}}`)。出现 `LLM调用失败: connection was closed in the middle of operation` 时，**永远是格式问题不是网络**。

3. **DB 必须先 `init_database()` 再 `graph.ainvoke()`**。runner.py 已加，但跑自定义测试时要记得。

4. **截图-on-demand 默认 OFF** (Phase 2.0D 改的)。视觉密集站点 (Booking / Google Flights / Amazon 商品页) 建议临时设 `L2_OBSERVE_SCREENSHOT=1`。

5. **CDP 模块是 dormant** — 没接入 tool path 前不消耗运行成本。

6. **Anti-bot 站点是 scope 限制** — 不是 bug，别花时间修 CAPTCHA。考虑加 anti-bot-friendly 站点进 benchmark suite。

7. **评测器是好的** — 别再花时间怀疑它。LLM judge 准确抓出了 agent 行为问题。

---

## 7. 怎么验证 (5 步)

```powershell
# 1. Git log 确认在正确位置
git log --oneline -3
# 期望: 27c0a61 → e7d6ee0 → 2a436d9

# 2. 编译检查
python -c "import py_compile; files=['tests/benchmarks/webvoyager_subset/runner.py','agents/ui/execution_graph.py','core/cdp_client.py']; [py_compile.compile(f, doraise=True) or print(f+' OK') for f in files]"

# 3. 跑受影响的测试
python -m pytest tests/agents/ui/test_action_result.py tests/agents/ui/test_assert_integration.py tests/agents/ui/test_screenshot_on_demand.py tests/core/test_backend_node_map.py tests/core/test_cdp_resolve.py tests/core/test_context_manager.py tests/core/test_dependency.py tests/core/test_parallel_executor.py tests/agents/ui/test_execution_graph.py -q

# 4. 跑 benchmark 拿 traceback (Action A)
python tests/benchmarks/webvoyager_subset/runner.py --output data/webvoyager_report_v4.md
ls data/bench_errors/  # 应该有 6 个 .log

# 5. 看 A/B 对比 (Action B)
python tests/benchmarks/webvoyager_subset/runner.py --output data/report_a.md
$env:L2_OBSERVE_SCREENSHOT = "1"
python tests/benchmarks/webvoyager_subset/runner.py --output data/report_b.md
```

---

## 8. 已知风险

1. **Action A 跑 10 case 需 30-50 min** (avg 241s/case)。计划时间。
2. **Action D (CDP 接入) 风险高** — Playwright locator 路径已稳定，CDP 路径可能引入新问题。建议小范围 A/B (1-2 case) 再扩。
3. **LLM judge 自身慢** (5-10s/call) — 100 case 评测需 8-15 min judge 时间。考虑加 `--no-judge` 快速模式做开发迭代。
4. **MiMo v2.5 偶发 SSE 断流** — Anthropic SDK 默认重试 2 次，单次 LLM call 实际可能 30-60s。如果 assert_node 持续超时，调大 SDK timeout 或加 circuit breaker。
5. **测试套件 377 个** — 跑全套需 >5min (live LLM 测试)。CI 上跑完整套，本地迭代只跑受影响的子集。

---

## 9. 相关文件 (按重要性)

### 必读
1. `docs/handoff/2026-06-04-phase2.0CD-benchmark.md` — 主 handoff，**含完整 system problems 清单 (§6)**
2. `docs/handoff/2026-06-04-evaluator-benchmark.md` — 评测器专项 handoff (v1, Bug A/B 详解)
3. `data/webvoyager_report_v3.md` — 上次 benchmark 输出 (含 LLM judge 详细 verdict)
4. `data/bench_v3_stderr.txt` — 上次 stderr (已被截断, 只剩 timing log, **不要再依赖这个**)

### 改动文件 (本阶段)
5. `tests/benchmarks/webvoyager_subset/runner.py:319` — traceback 捕获入口
6. `agents/ui/execution_graph.py:579` — MiMo image format 修复
7. `core/interfaces.py` — `ActionResult` +8 字段
8. `core/cdp_client.py` / `backend_node_map.py` / `context_manager.py` — 等待接入

### Roadmap 参考
9. `docs/master-roadmap.md` — Phase 2.0C 触发条件定义处
10. `docs/phase2.0B.md:130-133` — 2.0C 前置条件
11. `INDUSTRY_COMPARISON_2026.md` / `DEEP_DIVE_L2_VS_BROWSERUSE.md` — CDP 决策依据

---

## 10. 环境

- **Working dir**: `C:\Users\17381\Desktop\test_agent`
- **Python**: 3.11
- **LLM endpoint**: `https://token-plan-cn.xiaomimimo.com/anthropic` (MiMo v2.5, Anthropic-compatible)
- **Models**:
  - `qwen3.7-max` — planning
  - `kimi-k2.6` (execution) / `deepseek-v4-flash` (simple) / `glm-5.1` (complex) → 全部 routed to `mimo-v2.5`
  - Benchmark judge → `mimo-v2.5` (multimodal)
- **DB**: PostgreSQL `postgresql://postgres:123456@localhost:5432/smart_test`
- **Test target** (dev validation): `http://192.168.31.155/login?redirect=/ai-talk/index` (user: `test_c`, pass: `123456`)
- **关键 env vars**:
  - `L2_OBSERVE_SCREENSHOT=0` — 截图 on-demand (默认 OFF)
  - `L2_SCREENSHOT_COMPRESSED=1` — JPEG 压缩
  - `L2_USE_CDP=0` — CDP 路径 (待 wiring)
