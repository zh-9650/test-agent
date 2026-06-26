"""L1 阶段输入输出收集脚本

直接调用 generate_exploration_goals() 收集 L1 阶段的完整输入输出。
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TEST_DATA_DIR = Path(r"C:\Users\17381\Desktop\项目文件\人力资源\人才盘点一期功能需求清单文档")
OUTPUT_DIR = PROJECT_ROOT / "tests" / "l1_output"


def load_allRequirements() -> str:
    """读取所有需求文档，合并为一个 PRD 内容"""
    md_files = sorted(TEST_DATA_DIR.glob("*.md"))
    parts = []
    for f in md_files:
        content = f.read_text(encoding="utf-8")
        parts.append(f"\n\n{'='*60}\n## 文件: {f.name}\n{'='*60}\n\n{content}")
    return "\n".join(parts)


async def run_l1_collection():
    """执行 L1 阶段并收集完整输入输出"""
    from core.skills.l2_pipeline import generate_exploration_goals

    # 1. 准备输入
    prd_content = load_allRequirements()

    md_files = sorted(TEST_DATA_DIR.glob("*.md"))
    print(f"[L1 Collection] PRD 内容加载完成: {len(md_files)} 个文件, 总长度 {len(prd_content)} 字符")
    print(f"[L1 Collection] 文件列表:")
    for f in md_files:
        print(f"  - {f.name} ({len(f.read_text(encoding='utf-8'))} chars)")

    # 2. 调用 L1 管道
    print(f"\n[L1 Collection] 开始调用 generate_exploration_goals()...")
    start_time = datetime.now()

    goals, review_items, facts, assertions = await generate_exploration_goals(
        prd_content=prd_content,
        api_doc_content="",
        changelog_content="",
        prototype_notes="",
        architecture_notes="",
        rules="",
    )

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"[L1 Collection] L1 管道执行完成, 耗时 {elapsed:.1f}s")

    # 3. 收集输出
    output = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": elapsed,
            "prd_file_count": len(list(TEST_DATA_DIR.glob("*.md"))),
            "prd_content_length": len(prd_content),
            "input_params": {
                "prd_content_length": len(prd_content),
                "api_doc_content": "",
                "changelog_content": "",
                "prototype_notes": "",
                "architecture_notes": "",
                "rules": "",
            },
        },
        "input_prd_preview": prd_content[:2000] + "..." if len(prd_content) > 2000 else prd_content,
        "output": {
            "facts_count": len(facts),
            "assertions_count": len(assertions),
            "goals_count": len(goals),
            "review_items_count": len(review_items),
            "facts": [f.model_dump() for f in facts],
            "assertions": [a.model_dump() for a in assertions],
            "goals": [g.model_dump() for g in goals],
            "review_items": review_items,
        },
    }

    # 4. 保存输出
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"l1_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as fp:
        json.dump(output, fp, ensure_ascii=False, indent=2, default=str)
    print(f"\n[L1 Collection] 输出已保存到: {output_file}")

    # 5. 打印摘要
    print(f"\n{'='*60}")
    print(f"L1 阶段输出摘要")
    print(f"{'='*60}")
    print(f"  Facts (需求事实): {len(facts)}")
    print(f"  Assertions (断言): {len(assertions)}")
    print(f"  Goals (探索目标): {len(goals)}")
    print(f"  Review Items (人工审核项): {len(review_items)}")

    if facts:
        print(f"\n--- Facts 样例 (前5条) ---")
        for i, f in enumerate(facts[:5]):
            print(f"  [{i+1}] {f.id}: {f.subject} / {f.action} / {f.object}")
            print(f"      来源: {f.source_reference}")

    if assertions:
        print(f"\n--- Assertions 样例 (前5条) ---")
        for i, a in enumerate(assertions[:5]):
            print(f"  [{i+1}] {a.id}: {a.assertion_text[:120]}")
            print(f"      类型: {a.assertion_type}, 风险: {a.risk_level}, 来源事实: {a.fact_ids}")

    if goals:
        print(f"\n--- Goals 样例 (前5条) ---")
        for i, g in enumerate(goals[:5]):
            print(f"  [{i+1}] {g.goal}: 优先级={g.priority}")

    if review_items:
        print(f"\n--- Review Items (人工审核项) ---")
        for i, item in enumerate(review_items):
            print(f"  [{i+1}] {item[:150]}")

    return output


if __name__ == "__main__":
    asyncio.run(run_l1_collection())
