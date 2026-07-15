"""Small API helper for Cangjie dataset/knowledge-base test data.

Only records containing the supplied keyword are listed or deleted. This keeps
UI write tests auditable without touching normal business data.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CLIENT_ID = "e5cd7e4891bf95d1d19206ce24a7b32e"


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    payload = None
    headers = {"clientid": CLIENT_ID}
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=payload, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw else {}
            if isinstance(parsed, dict):
                parsed["_http_status"] = resp.status
            return parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw}
        parsed["_http_status"] = exc.code
        return parsed


def _login_result(base_url: str, username: str, password: str) -> dict[str, Any]:
    return _request(
        base_url,
        "POST",
        "/auth/login",
        body={
            "username": username,
            "password": password,
            "grantType": "password",
            "tenantId": "000000",
            "clientId": CLIENT_ID,
        },
    )


def _login(base_url: str, username: str, password: str) -> str:
    result = _login_result(base_url, username, password)
    token = (result.get("data") or {}).get("access_token") or result.get("access_token")
    if result.get("code") != 200 or not token:
        raise SystemExit(f"login failed: {json.dumps(result, ensure_ascii=False)}")
    return str(token)


def _rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    rows = result.get("rows")
    if isinstance(rows, list):
        return [item for item in rows if isinstance(item, dict)]
    return []


def _dataset_id(dataset: dict[str, Any]) -> str:
    value = dataset.get("datasetId") or dataset.get("id") or ""
    return str(value)


def _list_datasets(base_url: str, token: str, keyword: str) -> dict[str, Any]:
    result = _request(
        base_url,
        "GET",
        "/fastgpt/dataset/list",
        token=token,
        query={"keyword": keyword},
    )
    rows = _rows(result)
    matched = [
        row
        for row in rows
        if keyword in str(row.get("datasetName", ""))
        or keyword in str(row.get("datasetIntro", ""))
        or keyword in str(row.get("datasetId", ""))
    ]
    return {
        "raw_code": result.get("code"),
        "raw_msg": result.get("msg"),
        "total_rows": len(rows),
        "matched_count": len(matched),
        "matched": matched,
    }


def _cleanup_datasets(base_url: str, token: str, keyword: str) -> dict[str, Any]:
    before = _list_datasets(base_url, token, keyword)
    deleted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for dataset in before["matched"]:
        dataset_id = _dataset_id(dataset)
        if not dataset_id:
            skipped.append({"dataset": dataset, "reason": "missing datasetId"})
            continue
        if dataset.get("agentId") is not None:
            skipped.append({
                "datasetId": dataset_id,
                "datasetName": dataset.get("datasetName"),
                "reason": "bound_to_agent",
                "agentId": dataset.get("agentId"),
            })
            continue
        delete_result = _request(
            base_url,
            "DELETE",
            f"/fastgpt/dataset/{urllib.parse.quote(dataset_id, safe='')}",
            token=token,
        )
        if delete_result.get("code") == 200:
            deleted.append({
                "datasetId": dataset_id,
                "datasetName": dataset.get("datasetName"),
            })
        else:
            skipped.append({
                "datasetId": dataset_id,
                "datasetName": dataset.get("datasetName"),
                "result": delete_result,
            })
    after = _list_datasets(base_url, token, keyword)
    return {"before": before, "deleted": deleted, "skipped": skipped, "after": after}


def _response_without_http_marker(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "_http_status"}


def _create_dataset_probe(
    base_url: str,
    token: str,
    *,
    keyword: str,
    name: str,
    intro: str,
) -> dict[str, Any]:
    request_body = {"name": name, "intro": intro, "type": "dataset"}
    create_response = _request(
        base_url,
        "POST",
        "/fastgpt/dataset",
        token=token,
        body=request_body,
    )
    list_after_create = _list_datasets(base_url, token, keyword)
    cleanup = _cleanup_datasets(base_url, token, keyword)
    return {
        "request": request_body,
        "create_http_status": create_response.get("_http_status"),
        "create_response": _response_without_http_marker(create_response),
        "list_after_create": list_after_create,
        "matched_after_create": list_after_create["matched"],
        "cleanup": cleanup,
        "list_after_cleanup": cleanup["after"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--keyword", required=True)
    parser.add_argument(
        "--action",
        choices=["list", "cleanup", "create-check"],
        default="list",
    )
    parser.add_argument("--dataset-name", default="")
    parser.add_argument("--intro", default="test_agent dataset dependency probe")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    login_result = _login_result(args.base_url, args.username, args.password)
    token = (login_result.get("data") or {}).get("access_token") or login_result.get("access_token")
    if login_result.get("code") != 200 or not token:
        raise SystemExit(f"login failed: {json.dumps(login_result, ensure_ascii=False)}")
    if args.action == "cleanup":
        result = _cleanup_datasets(args.base_url, token, args.keyword)
    elif args.action == "create-check":
        name = args.dataset_name or f"测试知识库-{args.keyword}"
        result = _create_dataset_probe(
            args.base_url,
            token,
            keyword=args.keyword,
            name=name,
            intro=args.intro,
        )
    else:
        result = _list_datasets(args.base_url, token, args.keyword)

    payload = {
        "action": args.action,
        "base_url": args.base_url,
        "keyword": args.keyword,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "login_code": login_result.get("code"),
        "login_http_status": login_result.get("_http_status"),
        "result": result,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
