from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = (
    ROOT
    / "data"
    / "test-runs"
    / "cangjie-20260704-acceptance"
    / "setup"
    / "cangjie_dataset_api_helper.py"
)


def _load_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cangjie_dataset_api_helper", HELPER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_create_probe_records_fastgpt_502_without_dirty_data() -> None:
    helper = _load_helper()

    def fake_request(
        base_url: str,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if path == "/auth/login":
            return {"_http_status": 200, "code": 200, "data": {"access_token": "tok"}}
        if path == "/fastgpt/dataset" and method == "POST":
            return {
                "_http_status": 200,
                "code": 502,
                "msg": "FastGPT服务异常",
                "data": None,
            }
        if path == "/fastgpt/dataset/list":
            return {"_http_status": 200, "code": 200, "msg": "操作成功", "data": []}
        raise AssertionError(f"unexpected request: {method} {path}")

    helper._request = fake_request
    token = helper._login("http://target", "admin", "admin123")
    result = helper._create_dataset_probe(
        "http://target",
        token,
        keyword="TA-HELPER-502",
        name="测试知识库-TA-HELPER-502",
        intro="probe",
    )

    assert result["create_http_status"] == 200
    assert result["create_response"]["code"] == 502
    assert result["matched_after_create"] == []
    assert result["cleanup"]["deleted"] == []
    assert result["list_after_cleanup"]["matched_count"] == 0


def test_create_probe_cleans_created_unbound_dataset() -> None:
    helper = _load_helper()
    state = {"created": False}

    def fake_request(
        base_url: str,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if path == "/auth/login":
            return {"_http_status": 200, "code": 200, "data": {"access_token": "tok"}}
        if path == "/fastgpt/dataset" and method == "POST":
            state["created"] = True
            return {"_http_status": 200, "code": 200, "data": {"datasetId": "ds-1"}}
        if path == "/fastgpt/dataset/list":
            if state["created"]:
                return {
                    "_http_status": 200,
                    "code": 200,
                    "msg": "操作成功",
                    "data": [
                        {
                            "datasetId": "ds-1",
                            "datasetName": "测试知识库-TA-HELPER-SUCCESS",
                            "datasetIntro": "probe",
                            "agentId": None,
                        }
                    ],
                }
            return {"_http_status": 200, "code": 200, "msg": "操作成功", "data": []}
        if path == "/fastgpt/dataset/ds-1" and method == "DELETE":
            state["created"] = False
            return {"_http_status": 200, "code": 200, "msg": "操作成功"}
        raise AssertionError(f"unexpected request: {method} {path}")

    helper._request = fake_request
    token = helper._login("http://target", "admin", "admin123")
    result = helper._create_dataset_probe(
        "http://target",
        token,
        keyword="TA-HELPER-SUCCESS",
        name="测试知识库-TA-HELPER-SUCCESS",
        intro="probe",
    )

    assert result["create_http_status"] == 200
    assert result["create_response"]["code"] == 200
    assert result["matched_after_create"][0]["datasetId"] == "ds-1"
    assert result["cleanup"]["deleted"] == [
        {"datasetId": "ds-1", "datasetName": "测试知识库-TA-HELPER-SUCCESS"}
    ]
    assert result["list_after_cleanup"]["matched_count"] == 0


if __name__ == "__main__":
    test_create_probe_records_fastgpt_502_without_dirty_data()
    test_create_probe_cleans_created_unbound_dataset()
    print("cangjie dataset helper regression checks passed")
