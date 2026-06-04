# AI Browser Agent Landscape & Our Project — 2026 Comparison

> **总入口文档**：行业广度对比（2026 玩家、基准测试、最佳实践）。
>
> 配套阅读：
> - **`DEEP_DIVE_L2_VS_BROWSERUSE.md`** — 架构级深度对比（修订自 Gemini 报告，2026-06-04）
> - Supersedes: `BROWSER_USE_VS_OUR_ARCH.md` (pre-CDP), `IMPROVEMENT_PLAN_vs_BrowserUse.md`, `CODE_COMPARISON_AND_IMPROVEMENTS.md`

---

## 1. 2026 Perception Layer: The Converged Answer

The single biggest architecture decision in 2026 is **how the agent perceives the page**. The industry has converged:

| Perception Method | Token Cost | Latency | Reliable? | Used By |
|---|---|---|---|---|
| Accessibility Tree (AXTree) | ~200–400 tokens | instant | ✅ Deterministic refs | **Ours**, Playwright MCP, browser-use 2.x, Stagehand |
| Screenshot + Vision | ~3,000–5,000 tokens | 3–8s | ❌ Pixel drift | Anthropic Computer Use, OpenAI CUA (deprecated) |
| Full DOM | ~5,000–20,000 tokens | fast | ❌ Noise-heavy | Legacy systems |

**2026 production pattern**: AXTree primary + screenshot-on-demand for visual edge cases (canvas, WebGL, custom UIs).

### Our Position (Phase 2.0C)

We use CDP `Accessibility.getFullAXTree` — same convergence as industry. This is correct. The gap is:
- No **screenshot-on-demand** hybrid fallback
- No **paint order** sorting (CDP AXTree order, not visual order)
- No **backendNodeId** persistence for cross-refresh stability

---

## 2. Agent Loop Architecture: 5 Approaches

| Dimension | **Ours (L2)** | **browser-use 2.x** | **Playwright MCP** | **Anthropic Computer Use** | **OpenAI CUA** |
|---|---|---|---|---|---|
| Perception | CDP AXTree | DOM/AXTree (compact) | Accessibility Snapshot | Screenshot | Screenshot |
| Execution | CDP mouse/key events | CDP events via Watchdog | Playwright API | Mouse/key events | Virtual mouse/keyboard |
| Orchestration | LangGraph subgraph | Agent class (self-loop) | MCP protocol (tool layer) | Screenshot-action loop | Perception-reason-action |
| LLM calls/step | 2 (decide + assert) | 1 (action implies done) | 1 per tool call | 1 per screenshot | 1 per step |
| Token efficiency | High (AXTree) | High (AXTree) | High (~200–400 tokens) | Very low (~350K/screenshot) | Low |
| State model | `dict` | `AgentState` Pydantic | MCP context | Screenshot history | Conversation history |
| Multi-step planning | L1 test plan (read-only) | Dynamic PlanItem[] | N/A (stateless tool) | Chain-of-thought | Chain-of-thought |
| Loop detection | None | `ActionLoopDetector` | N/A | None | Limited |
| CAPTCHA handling | None | Detect + wait | N/A | None | Limited |

### Key Gaps vs browser-use 2.x (previously identified, still relevant)

- No structured `ActionResult` return type → LLM can't reliably judge success
- No semantic history compression (deletes old messages, losing context)
- No loop detection (can waste tokens on repetitive actions)
- No `backendNodeId` persistence (element refs reset every observe)
- No multi-strategy element location fallback

---

## 3. 2026 Project Landscape

| Project | Category | Perception | Stars/Reach | Benchmark |
|---|---|---|---|---|
| **browser-use** (open-source) | Agent framework | DOM/AXTree | 77K+ GitHub | 89.1% WebVoyager, BU 2.0 model |
| **Playwright MCP** (Microsoft) | Tool layer (MCP) | Accessibility Snapshot | 31K+ GitHub (mcp) | ~200–400 tokens/snapshot |
| **Stagehand** (Browserbase) | SDK (TS) | AXTree (default) | Open-source | Developer-friendly |
| **Yutori n1** | Dedicated model | Vision + structure | API | 91% Navi-Bench, $0.75/M tokens |
| **OpenAGI Lux** | Dedicated model | Vision | API | 83.6% Online-Mind2Web |
| **OpenCUA-72B** (xlang) | Open-source model | Vision | Academic | 45.0% OSWorld (open SOTA) |
| **Anthropic Computer Use** | Desktop agent | Screenshot | API | N/A (demo product) |
| **Our project** | Testing platform | CDP AXTree | Internal | **No benchmark scores** |

### Benchmark Scores Reference

| Benchmark | What it measures | Top Score | Our Score |
|---|---|---|---|
| WebVoyager | Real web task completion | 89.1% (browser-use) | **None** |
| Navi-Bench | Multi-site navigation (100 tasks) | 91% (n1) | **None** |
| OSWorld-Verified | Full computer use (desktop apps) | 45.0% (OpenCUA-72B) | **None** |
| Online-Mind2Web | Web agent (300 tasks, 136 sites) | 83.6% (Lux) | **None** |

---

## 4. Industry Best Practices (2026)

### 4.1 Perception: Accessibility Tree First

Per [perea.ai Research (May 2026)](https://www.perea.ai/research/accessibility-tree-vs-screenshot-perception):
- 7.5x–12.5x token cost gap (AXTree vs screenshot)
- 30–80x latency gap
- [ref=eN] handle convention for deterministic element refs
- **Stagehand defaults to Chrome Accessibility Tree**
- **Playwright MCP uses accessibility snapshot** (v1.59+ `snapshotForAI` API)

### 4.2 Token Optimization

Per [Manus production data](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus):
- Tool responses = **67.6%** of total tokens; system prompt = only 3.4%
- **KV-cache hit rate** is the #1 metric: cached = $0.30/M tokens, uncached = $3.00/M (10x difference)
- Never dynamically add/remove tools mid-iteration (invalidates cache)
- Use logit masking to control tool availability, preserving prefix cache
- **todo.md** files to "recite objectives into the end of context" (combats lost-in-the-middle)
- **Keep failed actions visible** — don't erase failure evidence

### 4.3 Tool Design (Anthropic's Guidance)

From [Anthropic's tool design guide](https://www.anthropic.com/engineering/writing-tools-for-agents):
- **Few thoughtful tools, not a giant catalog**
- "If a human engineer can't definitively say which tool to use, an AI agent can't either"
- Build task-oriented tools (e.g., `schedule_event` instead of `list_users` + `list_events` + `create_event`)
- Tools return error strings, not exceptions
- Object dispatch (`Object.fromEntries(tools.map(t => [t.name, t]))`), not if/else chains

### 4.4 Architecture: Single-Agent Loop Wins

Per Anthropic's Claude Code architecture analysis:
- A simple, single-threaded master loop with disciplined tools and planning **outperforms complex multi-agent swarms** for most browser tasks
- Priority: debuggability > transparency > complex orchestration
- Sub-agents with fresh context windows tackle sub-tasks, return condensed summaries

### 4.5 MCP vs CLI Token Economics

Per [TestQuality 2026 analysis](https://testquality.com/playwright-test-agents-mcp-architecture-2026):
- Playwright MCP: ~114K tokens per full agent test run
- Playwright CLI: ~27K tokens per full agent test run (~4x reduction)
- CLI saves snapshots to disk instead of streaming into LLM context
- **Use CLI when agent has filesystem access, MCP when it doesn't**

### 4.6 Browser-Use v2.0 Specific

- BU 2.0 model: +12% accuracy over BU 1.0, ~200 tasks per dollar on WebVoyager
- Custom Chromium fork for optimized CDP control
- Cloud offering with stealth browsers and proxy rotation
- **DOM accessibility tree, not screenshots** (4x cheaper per step vs vision-only)

---

## 5. Our Project: Gap Analysis & Priority Ranking

### Where We're Strong

| Aspect | Status |
|---|---|
| CDP AXTree perception | ✅ Industry standard |
| CDP mouse/key event execution | ✅ Correct (lower level than Playwright API) |
| LangGraph orchestration | ✅ Solid state machine |
| Chinese prompts | ✅ (appropriate for our model stack) |
| Phase separation (L1 plan → L2 execute) | ✅ Unusual but valuable for test automation |
| Multi-model strategy (qwen/kimi/deepseek/glm) | ✅ Appropriate tiering |

### Where We Need to Close Gaps

| Priority | Gap | Effort | Impact |
|---|---|---|---|
| **P0** | No benchmark scores (can't measure regressions) | 2 days | 🔴 Critical |
| **P0** | No structured `ActionResult` return type | 1 day | 🔴 Critical |
| **P0** | No history compression (deletes = loses info) | 1 day | 🔴 Critical |
| **P1** | No loop detection | 0.5 day | 🟡 High |
| **P1** | No screenshot-on-demand hybrid | 1 day | 🟡 High |
| **P1** | No `backendNodeId` persistence | 1 day | 🟡 High |
| **P1** | KV-cache not optimized (dynamic tool registry) | 0.5 day | 🟡 High |
| **P2** | No CAPTCHA handling | 1 day | 🔵 Medium |
| **P2** | Element locator: no multi-strategy fallback | 1 day | 🔵 Medium |
| **P3** | No URL whitelist | 0.5 day | ⚪ Low |
| **P3** | No runtime plan updates | 2 days | ⚪ Low |

### Where We Can't (or Shouldn't) Compete

- **Dedicated browser-use model** (BU 2.0, n1, etc.) — we use general models via API; fine-tuning is Phase 3+
- **Cloud stealth infrastructure** (proxy rotation, anti-bot) — not in scope
- **Desktop/OS automation** (Computer Use, UFO) — web-only by design
- **MCP server for third-party agents** — our product is the agent, not the tool layer

---

## 6. Recommendations

1. **Immediate (P0, 2 days):** Add structured `ToolResult`, semantic history compression, and a benchmark suite (WebVoyager subset — 10 representative tasks)
2. **Short-term (P1, 3 days):** Loop detection, screenshot-on-demand hybrid, `backendNodeId` persistence, KV-cache-aware tool registration
3. **Medium-term (P2, 2 days):** CAPTCHA detection/handling, multi-strategy element location, URL whitelist
4. **Long-term (Phase 3):** Explore fine-tuning a dedicated model for Chinese web testing (leverage our unique dataset advantage)

### Key Insight

The industry has converged on **our architectural direction** (AXTree + CDP input dispatch). The gaps are not architectural — they are **production-hardening** features: structured returns, history compression, loop detection, and benchmark validation. These are all implementable within the current Phase 2.0C architecture.

---

## 7. Related Documents

- **架构深度对比**：[`DEEP_DIVE_L2_VS_BROWSERUSE.md`](DEEP_DIVE_L2_VS_BROWSERUSE.md) — L2 vs browser-use v2.x 的逐模块深度对比（执行流、DOM 建模、动作精度、上下文管理、避障机制），含 10 项 L2 独特优势总结和优先级 P0–P3 学习路线
- **2026 行业基准**：WebVoyager (89.1% top), Navi-Bench (91% top), OSWorld (45% open SOTA), Online-Mind2Web (83.6% top)
- **核心代码参考**：
  - `agents/ui/execution_graph.py` — LangGraph 5 节点 + 2 条件边 + 三层防护
  - `core/cdp_client.py` — CDP AXTree 提取 + 坐标点击
  - `agents/ui/prompts.py` line 371-384 — Failure Memory 注入位置
  - `core/page_semantic.py` — 2.0C 起的 CDP 优先路径
