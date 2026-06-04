"""WebVoyager benchmark smoke test - verify task loading and structure only."""
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.benchmarks.webvoyager_subset.runner import load_tasks, generate_report

tasks = load_tasks()
print(f"Loaded {len(tasks)} tasks")
assert len(tasks) == 10, f"Expected 10 tasks, got {len(tasks)}"

required_fields = ["id", "site", "url", "instruction", "success_criteria", "category", "max_steps"]
for t in tasks:
    for f in required_fields:
        assert f in t, f"Task {t.get('id', '?')} missing field {f}"
    assert t["max_steps"] > 0
    assert t["url"].startswith("http")

print("All 10 tasks have required fields and valid structure")

# Test report generation
fake_results = [
    {"task_id": "WV-001", "status": "success", "success": True, "reason": "ok", "steps": 5, "duration_s": 12.3},
    {"task_id": "WV-002", "status": "fail", "success": False, "reason": "no match", "steps": 10, "duration_s": 25.1},
]
report = generate_report(fake_results)
assert "Success rate: 1/2" in report
assert "WV-001" in report
assert "WV-002" in report
print("Report generation OK")
print("\nSmoke test PASSED")
