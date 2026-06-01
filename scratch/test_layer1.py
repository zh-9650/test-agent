import asyncio
import argparse
import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.skills.knowledge_extractor import extract_knowledge
from core.skills.use_case_modeler import generate_use_case_model
from core.skills.use_case_coverage import check_use_case_coverage
from core.skills.system_modeler import generate_system_model
from core.skills.goal_extractor import extract_goals


DEFAULT_PRD = """\
# 采购审批系统 PRD
1. 任何员工都可以提交采购申请。
2. 采购金额如果超过 5000 元，需要部门经理审批。
3. 采购金额如果超过 10000 元，需要总监审批。
4. 审批通过后，进入待付款状态，由财务进行打款确认。
5. 核心流转：草稿 -> 待审批 -> 审批通过(待付款) -> 已完成。也可以被"驳回"回到草稿。
"""

DEFAULT_API = """\
POST /api/orders/create
POST /api/orders/approve
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Layer 1 端到端管线验证")
    p.add_argument("--prd", help="PRD 文件路径（默认用内置 mock）")
    p.add_argument("--api-doc", help="Swagger / OpenAPI 文件路径")
    p.add_argument("--changelog", help="Changelog 文件路径")
    p.add_argument("--quiet", action="store_true", help="只打印 done 后的最终 JSON")
    return p.parse_args()


def load_text(path: str | None) -> str:
    if not path:
        return ""
    if not os.path.isfile(path):
        print(f"[WARN] file not found: {path}")
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


async def test_layer1_pipeline(prd: str, api_doc: str, changelog: str, quiet: bool = False):
    def log(msg: str) -> None:
        if not quiet:
            print(msg)

    log("=" * 50)
    log("🚀 启动 Layer 1: 认知初始化重构管线验证")
    log("=" * 50)

    log("\n[Node 1] 正在运行知识提取器 (Knowledge Extractor)...")
    knowledge = await extract_knowledge(prd_content=prd, api_doc_content=api_doc, changelog_content=changelog)
    log("✅ 提取完成！知识事实库 (KnowledgeBase):")
    log(json.dumps(knowledge.model_dump(), indent=2, ensure_ascii=False))

    log("\n[Node 1.5] 正在运行用例脚手架建模 (Use Case Modeler)...")
    use_case_model = await generate_use_case_model(knowledge)
    log("✅ 建模完成！角色用例模型 (UseCaseModel):")
    log(json.dumps(use_case_model.model_dump(), indent=2, ensure_ascii=False))

    log("\n[Node 1.7] 正在运行覆盖率自检 (Coverage Check)...")
    use_case_model, coverage_report = await check_use_case_coverage(knowledge, use_case_model)
    log(
        f"✅ 覆盖自检完成！覆盖 {len(coverage_report.covered_rules)} 条规则，"
        f"遗漏 {len(coverage_report.missing_rules)} 条，"
        f"补全/修改 {len(coverage_report.added_use_cases)} 个用例。"
    )
    log(json.dumps(coverage_report.model_dump(), indent=2, ensure_ascii=False))

    log("\n[Node 2] 正在运行业务状态机建模 (System Modeler)...")
    system_model = await generate_system_model(knowledge, use_case_model)
    log("✅ 建模完成！轻量级状态机 (SystemModel):")
    log(json.dumps(system_model.model_dump(), indent=2, ensure_ascii=False))

    log("\n[Node 3] 正在运行探索目标生成器 (Goal Extractor)...")
    goals = await extract_goals(use_case_model.model_dump(), mode="direct")
    log("✅ 目标生成完成！探索目标列表:")
    for i, goal in enumerate(goals):
        log(f"  {i+1}. [{goal.priority}] {goal.goal}")

    log("\n🎉 Layer 1 验证完毕！")
    return {
        "knowledge_base": knowledge.model_dump(),
        "use_case_model": use_case_model.model_dump(),
        "coverage_report": coverage_report.model_dump(),
        "system_model": system_model.model_dump(),
        "goals": [g.model_dump() for g in goals],
    }


if __name__ == "__main__":
    args = parse_args()
    prd_text = load_text(args.prd) or DEFAULT_PRD
    api_text = load_text(args.api_doc) or DEFAULT_API
    changelog_text = load_text(args.changelog)
    asyncio.run(test_layer1_pipeline(prd_text, api_text, changelog_text, quiet=args.quiet))
