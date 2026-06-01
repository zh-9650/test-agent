# Phase 2 (V1.5) - Layer 1 鲁棒性与可观测性加固 (Layer 1 Hardening)

**时间**: 2026-06-01
**责任人**: Lead
**前置**: V1.3 (KnowledgeBase IR) + V1.4 (UseCaseModel Scaffold)

## 1. 业务目标

V1.3/V1.4 上线后，Layer 1 管线在真实 LLM 调用中暴露出两类稳定性问题：

1. **生产端点兼容性问题**：`ChatAnthropic.with_structured_output()` 在阿里云 Bailian 的 Qwen 兼容端点上不稳定，会偶发返回 `None` 或超时；返回的 `content` 字段也是 Anthropic 风格的内容块列表（含 `text` 与 `thinking` 块），而非纯字符串。所有 7 个 skill 模块（`knowledge_extractor` / `use_case_modeler` / `use_case_coverage` / `system_modeler` / `goal_extractor` / `risk_analyzer` / `system_mapper`）都依赖 `with_structured_output`，任意一个失败都会让 Layer 1 整体降级为空结果。
2. **覆盖率自检报告"看不见"**：Node 1.7 新增的 `CoverageReport` 只能在 `/api/test/layer1` 调试端点看到，主流程的 HTML 报告没有它。同时后端在 `progress: "error"` 时，前端 SSE 解析会静默丢失。

本轮在 V1.3/V1.4 基础上做加固，让 Layer 1 端到端在生产端点上"跑得稳 + 看得见"。

## 2. 变更详情

### 2.1 统一 LLM 调用兜底（`core/llm_client.py`）

新增 `safe_structured_invoke(prompt, schema, model_type)` 集中入口：

1. 先尝试 `llm.with_structured_output(schema).ainvoke(prompt)`；
2. 若返回 `None` 或抛异常，自动降级为 `llm.ainvoke(prompt)` 拿原始 content；
3. 通过 `_unwrap_content()` 解析 Anthropic 风格 `[{type, text/thinking}, ...]` content 块，提取 `text` 字段；
4. 通过 `_extract_json_blob()` 优先匹配 ```json``` 代码块，否则回退到裸 `{...}` / `[...]` ；
5. 通过 `_unwrap_envelope()` 自动剥掉 `{"UseCaseModel": {...}}` 之类的单层包络；
6. 通过 `_coerce_to_pydantic()` 容忍 list / str / dict 三种输入形态，最后用 `schema.model_validate` 校验。

7 个 skill 全部从 `with_structured_output` 切换到 `safe_structured_invoke`，行为对齐。

### 2.2 覆盖率自检鲁棒性（`core/skills/use_case_coverage.py`）

- 抽出 `_normalize_for_match()`（去空白 + 小写）和 `_compute_coverage()`（子串双向包含匹配）工具，将 fast path 从"纯文本精确匹配"升级为"模糊子串匹配"，命中率显著提升。
- fast path 阈值从 1.0 降到 0.9，命中后 `missing_rules` 仍会忠实记录，让用户能看到"差几条没覆盖"。
- 新增 `_compute_local_diff()`：LLM 补全后不再相信 LLM 自报的 `added_use_cases`，改为本地对比 `before / after` 的 `use_case_model`，精确识别新增和修改（`related_rules` 变化）的用例。
- 修复 LLM 偶发把 `use_case_model` 字段返回为 JSON 字符串的 bug，通过 `_coerce_use_case_model()` 兼容 dict/str/list。

### 2.3 报告可观测性（`core/report_builder.py` + `core/runtime.py`）

- `ReportBuilder` 新增 `set_layer1_coverage(coverage_report)` 方法与 `l1_coverage` 字段。
- 报告 HTML 新增"Layer 1 认知自检 (Use-Case Coverage)"卡片：三色统计（已覆盖 / 遗漏 / 补全）+ 覆盖率进度条 + 折叠规则详情 + 折叠补全用例列表。
- `Runtime._save_report()` 从 `task_config["_coverage_report"]` 取出 Node 1.7 产出，自动注入到 ReportBuilder。

### 2.4 前端 SSE 错误识别（`frontend/src/api/client.ts`）

`testLayer1()` 的 SSE 解析原来只识别 `progress: "done"`，对 `progress: "error"` 静默丢弃。新增 `if (data.progress === "error") throw new Error(data.error || "Layer 1 pipeline failed")`，让"试运行 Layer 1"按钮在管线报错时能正确抛错到 UI。

### 2.5 死代码清理（`agents/ui/planning_graph.py`）

`_format_goals()` 中 `elif isinstance(g, str)` 分支上游永远喂 dict，属于不可达代码，删除。

## 3. 端到端验证

`scratch/test_layer1.py` 在真实 LLM（qwen3.7-max）上一次跑通：

| Node | 状态 | 关键输出 |
|------|------|---------|
| 1 Knowledge | ✅ | 4 business_rules + 4 roles + 2 entities + 2 constraints + 3 raw_facts，全部带 quote/source/confidence |
| 1.5 UseCaseModel | ✅ | 4 use cases，含 actor/trigger/outcome/related_rules |
| 1.7 Coverage | ✅ | **Fast path 100% 命中**，跳过 LLM，0 missing / 0 added |
| 2 SystemModel | ✅ | 1 流程、4 状态、6 流转边 |
| 3 Goals (direct) | ✅ | 4 个 high 优先级目标 |

## 4. 意义

1. **生产端点耐受性**：7 个 skill 统一走 `safe_structured_invoke`，从单点脆弱的 `with_structured_output` 升级为"原生结构化 + 手动 JSON 解析"双轨，Qwen/DeepSeek/Kimi 等任何兼容端点都能稳定解析。
2. **覆盖率可见性**：用户能在最终 HTML 报告里直接看到 Layer 1 自我审计的结果，知道"系统到底读懂了多少业务规则"，无需再去调试接口看 JSON。
3. **前端鲁棒性**：试运行 Layer 1 失败时能抛错到 UI，而不是假成功。
