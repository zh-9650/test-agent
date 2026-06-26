from core.interfaces import (
    BusinessFlow,
    BusinessModule,
    CandidateTestCase,
    CoverageBlueprint,
    ModuleDependency,
    TestAssetPackage as AssetPackage,
)
from core.skills.execution_selector import select_execution_cases


def _case(index: int, **updates) -> CandidateTestCase:
    values = {
        "id": f"TC-{index:03d}",
        "title": f"case {index}",
        "goal": f"goal {index}",
        "trace_references": [f"COV-{index:03d}"],
    }
    values.update(updates)
    return CandidateTestCase(**values)


def test_full_selects_complete_auto_executable_pool_and_defers_unsupported_cases():
    package = AssetPackage(
        candidate_cases=[
            _case(2, goal="打开开发者工具查看 network panel"),
            _case(1),
        ]
    )
    selection = select_execution_cases(package, "full")
    assert selection.selected_case_ids == ["TC-001"]
    assert selection.deferred_case_ids == ["TC-002"]
    assert selection.selection_reasons["TC-002"] == [
        "requires_browser_devtools",
        "requires_network_panel_inspection",
    ]


def test_smoke_never_exceeds_thirty():
    package = AssetPackage(
        candidate_cases=[
            _case(index, priority="high", branch_type="positive")
            for index in range(1, 45)
        ]
    )
    selection = select_execution_cases(package, "smoke", 20)
    assert selection.selected_count <= 30


def test_smoke_respects_target_count_when_optional_pool_is_large():
    package = AssetPackage(
        candidate_cases=[_case(index) for index in range(1, 26)]
    )

    selection = select_execution_cases(package, "smoke", 8)

    assert selection.selected_count == 8
    assert selection.selected_case_ids == [f"TC-{index:03d}" for index in range(1, 9)]


def test_balanced_keeps_mandatory_skeleton_over_target_and_is_stable():
    blueprint = CoverageBlueprint(
        modules=[BusinessModule(id="MOD-1", name="核心", is_core=True)],
        business_flows=[BusinessFlow(id="FLOW-1", name="主流程", is_core=True)],
        dependencies=[
            ModuleDependency(
                id="DEP-1",
                source_module_id="MOD-1",
                target_module_id="MOD-2",
                risk_tier="P0",
            )
        ],
    )
    package = AssetPackage(
        coverage_blueprint=blueprint,
        candidate_cases=[
            _case(1, business_flow_ids=["FLOW-1"], branch_type="e2e"),
            _case(2, dependency_ids=["DEP-1"], branch_type="positive"),
            _case(3, dependency_ids=["DEP-1"], branch_type="recovery"),
            _case(4, module_ids=["MOD-1"], branch_type="positive"),
        ],
    )
    first = select_execution_cases(package, "balanced", 2)
    second = select_execution_cases(package, "balanced", 2)
    assert first.selected_count == 4
    assert first.selected_case_ids == second.selected_case_ids
