"""scratch/debug_n2_fallback.py — 临时调试脚本: 在 4 fixture 上跑 N2 SystemModel, 抓 LLM 原始输出。

目的: 确认 V1.7 报告点名的 "N2 SystemModel 是 fallback 触发最多的节点 (3/4 fixture)" 的根因。

输出: 每个 fixture 的
  - safe_structured_invoke 是否返回 None (触发 fallback)
  - 第一次返回的 raw text (前 500 字)
  - 第一次返回的 SystemModel 字段 (json 化)
  - use_case.name 集合 (供对照)
  - 触发 fallback 时, raw fallback 路径的 text

用法: $env:L1_LIVE=1; python scratch/debug_n2_fallback.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

# 强制 UTF-8
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")

# 项目根
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 加载 .env
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

from core.interfaces import KnowledgeBase, KnowledgeItem, UseCaseModel, UseCase
from core.skills import knowledge_extractor, use_case_modeler, use_case_coverage, system_modeler
from core.llm_client import get_llm_client, _unwrap_content, _extract_json_blob

FIXTURES = ["prd_aitalk", "prd_purchase", "prd_minimal", "prd_adversarial"]


async def run_one(fixture_name: str) -> dict:
    """跑单 fixture, 返回诊断 dict。"""
    from core.llm_client import safe_structured_invoke

    fixtures_dir = ROOT / "data" / "fixtures"
    prd_path = fixtures_dir / f"{fixture_name}.md"
    prd = prd_path.read_text(encoding="utf-8") if prd_path.exists() else ""
    api_doc = ""
    changelog = ""
    if fixture_name == "prd_aitalk":
        api_doc = (fixtures_dir / "swagger_aitalk.yaml").read_text(encoding="utf-8")
        changelog = (fixtures_dir / "changelog_aitalk.md").read_text(encoding="utf-8")

    # 跑 N1 -> N1.5 -> N1.7 (与正式 L1 pipeline 一致)
    kb = await knowledge_extractor.extract_knowledge(
        prd_content=prd, api_doc_content=api_doc, changelog_content=changelog,
    )
    ucm = await use_case_modeler.generate_use_case_model(kb)
    ucm_refined, cov = await use_case_coverage.check_use_case_coverage(kb, ucm)
    ucm_names = [uc.name for uc in ucm_refined.use_cases]

    # 现在调 N2 system_modeler.generate_system_model 复现
    # 同时记录 raw text 用作诊断
    llm = get_llm_client("default")
    from core.skills.system_modeler import generate_system_model

    # 1. 跑正常路径, 看是否 fallback
    sm = await generate_system_model(kb, ucm_refined)
    sm_dump = sm.model_dump()
    flows_summary = [
        {
            "name": f.get("name"),
            "nodes": f.get("nodes"),
            "transitions_count": len(f.get("transitions", [])),
            "transitions_actions": [t.get("action") for t in f.get("transitions", [])],
        }
        for f in sm_dump.get("flows", [])
    ]
    fallback_triggered = (len(sm.flows) == 0)

    # 2. 直接调 safe_structured_invoke, 拿 raw text 用作诊断
    from core.skills.system_modeler import SystemModel as _SM  # type: ignore
    from core.interfaces import SystemModel, UseCaseModel as _UCM  # type: ignore
    from core.llm_client import safe_structured_invoke

    # 重写一遍 prompt 取 raw output
    prompt = f"""<role>
你是一个顶级系统架构师。
</role>

<context>
基于 UseCaseModel 构建状态机。
</context>

<task>
构建状态机 JSON。
</task>

<rules>
1. nodes 2-6 个汉字, 禁止前缀后缀标点英文数字
2. transitions[].action 必须精确等于某 use_case.name
3. 每个 use_case 至少一条 transition
4. flow 按业务域分 modules
5. 继承 N1 字段
</rules>

<output_contract>
Return ONLY JSON, no markdown fences.

{{
  "system_name": str,
  "modules": [str],
  "entities": [str],
  "roles": [str],
  "flows": [
    {{
      "name": str,
      "nodes": [str],
      "transitions": [
        {{"from_state": str, "action": str, "to_state": str}}
      ]
    }}
  ]
}}
</output_contract>

### UseCaseModel
```json
{ucm_refined.model_dump_json(indent=2)}
```

### KnowledgeBase
```json
{kb.model_dump_json(indent=2)}
```
"""
    # 先 with_structured_output 路径
    raw_structured = None
    raw_text = None
    try:
        raw_structured = await llm.with_structured_output(SystemModel).ainvoke(prompt)
    except Exception as e:
        raw_structured = f"EXCEPTION: {e}"

    # 再 raw 路径拿 text
    try:
        raw_msg = await llm.ainvoke(prompt)
        raw_text = _unwrap_content(raw_msg.content)[:1500]
    except Exception as e:
        raw_text = f"EXCEPTION: {e}"

    return {
        "fixture": fixture_name,
        "ucm_count": len(ucm_refined.use_cases),
        "ucm_names": ucm_names,
        "kb_business_rules_count": len(kb.business_rules),
        "sm_dump": sm_dump,
        "flows_summary": flows_summary,
        "fallback_triggered": fallback_triggered,
        "raw_structured_ok": raw_structured is not None and not isinstance(raw_structured, str),
        "raw_structured_dump": (
            raw_structured.model_dump() if hasattr(raw_structured, "model_dump")
            else str(raw_structured)[:800] if raw_structured is not None
            else None
        ),
        "raw_text_first_1500": raw_text,
    }


async def main() -> None:
    if not os.getenv("ANTHROPIC_AUTH_TOKEN"):
        print("ERROR: ANTHROPIC_AUTH_TOKEN not set, run with .env loaded or set env")
        return

    print("=" * 80)
    print("N2 SystemModel Fallback Debug")
    print("=" * 80)

    results = []
    for fx in FIXTURES:
        print(f"\n--- Fixture: {fx} ---")
        try:
            r = await run_one(fx)
            results.append(r)
            print(f"ucm_count={r['ucm_count']} | rules={r['kb_business_rules_count']} | "
                  f"fallback_triggered={r['fallback_triggered']} | "
                  f"raw_structured_ok={r['raw_structured_ok']}")
            print(f"sm.modules={r['sm_dump'].get('modules')} | "
                  f"sm.flows_count={len(r['sm_dump'].get('flows', []))}")
            for f in r["flows_summary"]:
                print(f"  flow '{f['name']}': nodes={f['nodes']} "
                      f"transitions={f['transitions_actions']}")
            print(f"\nraw_text (first 800 chars):\n{r['raw_text_first_1500'][:800]}")
            print("-" * 60)
        except Exception as e:
            traceback.print_exc()
            print(f"ERROR on {fx}: {e}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    fallback_count = sum(1 for r in results if r["fallback_triggered"])
    raw_ok_count = sum(1 for r in results if r["raw_structured_ok"])
    print(f"Fallback triggered: {fallback_count}/{len(results)} fixtures")
    print(f"Raw structured_output ok: {raw_ok_count}/{len(results)} fixtures")
    print(f"Per fixture fallback: {[(r['fixture'], r['fallback_triggered']) for r in results]}")

    out_path = ROOT / "data" / "n2_fallback_debug.json"
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nFull debug dump saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
