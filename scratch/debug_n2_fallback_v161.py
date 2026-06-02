"""scratch/debug_n2_fallback_v161.py — V1.6.1 验证脚本: 跑 4 fixture 验证加固后 fallback 率。

对比 V1.7 报告数据 (3/4 fixture 触发 inner fallback, 部分带"状态"后缀违规)。

V1.6.1 加固:
  - prompt 加 rule 6 (后缀黑名单)
  - _normalize_system_model 自动修 LLM 违规
  - _derive_minimal_system_model 兜底 (不再返回空)

期望:
  - 4 fixture 全过, 节点名无"状态"/"流程"/"页"/"中"/"期"后缀
  - transitions[].action 100% 匹配 use_case.name
  - 无重复 (from_state, action)
  - LLM inner fallback (structured_output -> raw parse) 仍可能触发, 但 final SystemModel 满足 invariant
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

from core.interfaces import SystemModel, UseCaseModel
from core.skills import knowledge_extractor, use_case_modeler, use_case_coverage, system_modeler
from core.skills.system_modeler import _is_chinese_noun_phrase, _normalize_system_model

FIXTURES = ["prd_aitalk", "prd_purchase", "prd_minimal", "prd_adversarial"]


async def run_one(fixture_name: str) -> dict:
    fixtures_dir = ROOT / "data" / "fixtures"
    prd = (fixtures_dir / f"{fixture_name}.md").read_text(encoding="utf-8")
    api_doc = ""
    changelog = ""
    if fixture_name == "prd_aitalk":
        api_doc = (fixtures_dir / "swagger_aitalk.yaml").read_text(encoding="utf-8")
        changelog = (fixtures_dir / "changelog_aitalk.md").read_text(encoding="utf-8")

    kb = await knowledge_extractor.extract_knowledge(
        prd_content=prd, api_doc_content=api_doc, changelog_content=changelog,
    )
    ucm = await use_case_modeler.generate_use_case_model(kb)
    ucm_refined, cov = await use_case_coverage.check_use_case_coverage(kb, ucm)

    sm = await system_modeler.generate_system_model(kb, ucm_refined)
    return {
        "fixture": fixture_name,
        "ucm_count": len(ucm_refined.use_cases),
        "ucm_names": [uc.name for uc in ucm_refined.use_cases],
        "sm_dump": sm.model_dump(),
        "is_minimal_fallback": sm.system_name == "Derived System Model (LLM fallback V1.6.1)",
    }


def check_invariants(result: dict) -> dict:
    """对 V1.6.1 后的 SystemModel 跑 invariant 校验, 返回违规列表。"""
    violations = []
    sm_dump = result["sm_dump"]
    ucm_names = set(result["ucm_names"])
    is_minimal = result["is_minimal_fallback"]

    # 1. nodes 满足 _is_chinese_noun_phrase (无后缀, 2-6 汉字)
    for f in sm_dump.get("flows", []):
        for n in f.get("nodes", []):
            if not _is_chinese_noun_phrase(n):
                violations.append(f"flow '{f.get('name')}' node '{n}' violates _is_chinese_noun_phrase")

    # 2. transitions[].action 在 ucm.names 中
    for f in sm_dump.get("flows", []):
        for t in f.get("transitions", []):
            if t.get("action") not in ucm_names:
                violations.append(
                    f"flow '{f.get('name')}' transition action '{t.get('action')}' not in ucm.names"
                )

    # 3. transitions 无重复 (from_state, action)
    for f in sm_dump.get("flows", []):
        seen = set()
        for t in f.get("transitions", []):
            key = (t.get("from_state"), t.get("action"))
            if key in seen:
                violations.append(
                    f"flow '{f.get('name')}' duplicate transition {key}"
                )
            seen.add(key)

    # 4. transitions[].from_state/to_state 在 flow.nodes 中
    for f in sm_dump.get("flows", []):
        nodes_set = set(f.get("nodes", []))
        for t in f.get("transitions", []):
            if t.get("from_state") not in nodes_set:
                violations.append(
                    f"flow '{f.get('name')}' from_state '{t.get('from_state')}' not in nodes"
                )
            if t.get("to_state") not in nodes_set:
                violations.append(
                    f"flow '{f.get('name')}' to_state '{t.get('to_state')}' not in nodes"
                )

    return {
        "is_minimal_fallback": is_minimal,
        "violation_count": len(violations),
        "violations": violations,
        "flows_count": len(sm_dump.get("flows", [])),
        "transitions_count": sum(len(f.get("transitions", [])) for f in sm_dump.get("flows", [])),
    }


async def main() -> None:
    if not os.getenv("ANTHROPIC_AUTH_TOKEN"):
        print("ERROR: ANTHROPIC_AUTH_TOKEN not set")
        return

    print("=" * 80)
    print("V1.6.1 N2 SystemModel Verification (4 fixture live)")
    print("=" * 80)

    results = []
    for fx in FIXTURES:
        print(f"\n--- Fixture: {fx} ---")
        try:
            r = await run_one(fx)
            check = check_invariants(r)
            r["invariant_check"] = check
            results.append(r)
            print(f"ucm_count={r['ucm_count']} | sm.flows={check['flows_count']} | "
                  f"sm.transitions={check['transitions_count']} | "
                  f"is_minimal_fallback={check['is_minimal_fallback']} | "
                  f"violations={check['violation_count']}")
            if check["violations"]:
                for v in check["violations"][:5]:
                    print(f"  VIOLATION: {v}")
            # 打印实际 transitions
            for f in r["sm_dump"].get("flows", []):
                print(f"  flow '{f.get('name')}': nodes={f.get('nodes')}")
                for t in f.get("transitions", []):
                    print(f"    {t.get('from_state')} --[{t.get('action')}]--> {t.get('to_state')}")
        except Exception as e:
            print(f"ERROR on {fx}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 80)
    print("V1.6.1 SUMMARY")
    print("=" * 80)
    all_pass = all(r["invariant_check"]["violation_count"] == 0 for r in results)
    fallback_count = sum(1 for r in results if r["invariant_check"]["is_minimal_fallback"])
    print(f"4/4 fixtures invariant pass: {all_pass}")
    print(f"Minimal fallback triggered: {fallback_count}/4")
    print(f"\nPer fixture:")
    for r in results:
        chk = r["invariant_check"]
        print(f"  {r['fixture']:20s} | flows={chk['flows_count']:2d} trans={chk['transitions_count']:2d} "
              f"| violations={chk['violation_count']:2d} | minimal_fallback={chk['is_minimal_fallback']}")

    out_path = ROOT / "data" / "n2_v161_live_results.json"
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nFull results saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
