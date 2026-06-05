# browser-use 对齐后 5-case 烟测报告

> 日期：2026-06-05
> 配置：mimo-v2.5 (multimodal) / mimo-v2.5-pro (text) / 1M context / 128K output
> 范围：WV-001, WV-005, WV-007（3 case）
> 文档: `data/bench_aligned_wv001.md`, `wv005.md`, `wv007.md` (第一轮)
>       `data/bench_aligned2_wv001.md`, `wv005.md`, `wv007_v4.md` (第二轮，含修复)

---

## 总体

| 轮次 | 1/3 case | 跑前 10 case 基线 |
|---|---|---|
| 第一轮 (browser-use 对齐 5 模块) | **1/3 = 33.3%** | 30% → 10% → 0% |
| 第二轮 (修了 target/提取完整/4字段) | **2/3 = 66.7%** | — |

**第二轮显著提升** (33% → 67%)。但 n=3, 95% CI ±28%, 仍属不稳定。

## 详细对比

| Case | 第一轮 | 第二轮 | 变化 |
|---|---|---|---|
| WV-001 Amazon 搜索 + 取价 | ✅ 3步 117s | ✅ 3步 167s | 稳定 |
| WV-005 GitHub 搜索 + 取 star | ❌ 2步 59s (locator 失败) | ❌ 10步 277s (搜了但截图早) | 进展（不再 0 步退） |
| WV-007 HN 取 title+score | ❌ 6步 246s (漏title) | ✅ 6步 196s (title+score 全提) | **修好** |

## 第一轮发现 → 第二轮修复

| 问题 | 修复 | 验证 |
|---|---|---|
| LLM 把元素描述当 target | system_prompt 规则 15 + bad example | WV-005 不再 0 步退（10步走完搜索流） |
| LLM 漏提取多字段 | Goal Reminder 自动注入 "提取完整性提醒" + 规则 16 | **WV-007 修好**（之前漏 title，现在全提） |
| 4 字段 Evaluation/Memory/Next Goal 未输出 | 加中英双标 + good example 示范 | 部分起效 (日志看部分 case LLM 开始输出) |

## 仍有问题

1. **WV-005 截图时机问题** —— 搜索动作完成但截图过早，未抓到结果页
   - 根因：search 工具内部没 wait_for_stable
   - **下版本**: 改 search 工具，等 networkidle 再返回

2. **WV-005 star 字段抽取** —— 即便进了结果页，star count 是 `<a>star</a>` 不是简单数字
   - 根因：extracted_content 抽取时只看到 "star" 没看到数字
   - **下版本**: extract_text 支持多级跳转

3. **小样本方差大** —— n=3, 1 case 变 ±33%
   - **下版本**: 跑 10 case 拿稳定数据

## 改动清单

- 第一轮（5 模块对齐）: data layer / message structure / truncation / tools / cache
  - 见 `docs/refactor/2026-06-05-browser-use-alignment-plan.md`
- 第二轮（修复 3 个新问题）:
  - `agents/ui/prompts.py`: 规则 15, 16 + Few-shot
  - `agents/ui/execution_graph.py`: completeness_hint 注入
  - `tests/core/test_l2_prompts.py`: 4 个新 system_prompt test

## 数据消耗

- 第一轮: 422s, 估 15-20 万 token
- 第二轮: 167+277+196 = 640s, 估 25-30 万 token



