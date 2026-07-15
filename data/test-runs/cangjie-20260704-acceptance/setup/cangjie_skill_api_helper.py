"""Small API helper for Cangjie skill-management test data.

Only records containing the supplied keyword are listed or deleted. This keeps
skill write tests auditable without touching normal business data.
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
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw}
        parsed["_http_status"] = exc.code
        return parsed


def _login(base_url: str, username: str, password: str) -> str:
    result = _request(
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
    token = (result.get("data") or {}).get("access_token") or result.get("access_token")
    if result.get("code") != 200 or not token:
        raise SystemExit(f"login failed: {json.dumps(result, ensure_ascii=False)}")
    return str(token)


def _rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data")
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        return [item for item in data["rows"] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    rows = result.get("rows")
    if isinstance(rows, list):
        return [item for item in rows if isinstance(item, dict)]
    return []


def _skill_id(skill: dict[str, Any]) -> str:
    value = skill.get("skillId") or skill.get("id") or ""
    return str(value)


def _list_skills(base_url: str, token: str, keyword: str) -> dict[str, Any]:
    result = _request(
        base_url,
        "POST",
        "/system/skill/page",
        token=token,
        body={"keyword": keyword, "pageNum": 1, "pageSize": 100},
    )
    rows = _rows(result)
    matched = [
        row
        for row in rows
        if keyword in str(row.get("name", ""))
        or keyword in str(row.get("description", ""))
        or keyword in str(row.get("author", ""))
        or keyword in str(row.get("skillId", ""))
    ]
    return {
        "raw_code": result.get("code"),
        "raw_msg": result.get("msg"),
        "total": result.get("total") or (result.get("data") or {}).get("total"),
        "total_rows": len(rows),
        "matched_count": len(matched),
        "matched": matched,
    }


def _file_tree(base_url: str, token: str, skill_id: str) -> dict[str, Any]:
    result = _request(
        base_url,
        "GET",
        f"/system/skill/{urllib.parse.quote(skill_id, safe='')}/files",
        token=token,
    )
    tree = result.get("data")
    if not isinstance(tree, list):
        tree = []

    flat: list[dict[str, Any]] = []

    def visit(nodes: list[Any]) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            flat.append({
                "path": node.get("path"),
                "name": node.get("name"),
                "type": node.get("type"),
                "isCore": node.get("isCore"),
            })
            children = node.get("children")
            if isinstance(children, list):
                visit(children)

    visit(tree)
    return {
        "raw_code": result.get("code"),
        "raw_msg": result.get("msg"),
        "skillId": skill_id,
        "flat_paths": [str(item.get("path") or "") for item in flat],
        "files": flat,
        "has_skill_md": any(str(item.get("path") or "").lower() == "skill.md" for item in flat),
        "has_index_js": any(str(item.get("path") or "").lower() == "index.js" for item in flat),
    }


def _first_matched_skill_id(base_url: str, token: str, keyword: str) -> str:
    listed = _list_skills(base_url, token, keyword)
    if not listed["matched"]:
        raise SystemExit(f"no skill matched keyword: {keyword}")
    skill_id = _skill_id(listed["matched"][0])
    if not skill_id:
        raise SystemExit(f"matched skill has no skillId: {json.dumps(listed['matched'][0], ensure_ascii=False)}")
    return skill_id


def _duplicate_skill_md(base_url: str, token: str, skill_id: str) -> dict[str, Any]:
    result = _request(
        base_url,
        "POST",
        f"/system/skill/{urllib.parse.quote(skill_id, safe='')}/file",
        token=token,
        body={"filePath": "SKILL.md", "content": "# duplicate", "type": "file"},
    )
    return {
        "skillId": skill_id,
        "raw_code": result.get("code"),
        "raw_msg": result.get("msg"),
        "http_status": result.get("_http_status"),
        "blocked": result.get("code") != 200,
        "result": result,
    }


def _cleanup_skills(base_url: str, token: str, keyword: str) -> dict[str, Any]:
    before = _list_skills(base_url, token, keyword)
    deleted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for skill in before["matched"]:
        skill_id = _skill_id(skill)
        if not skill_id:
            skipped.append({"skill": skill, "reason": "missing skillId"})
            continue
        delete_result = _request(
            base_url,
            "DELETE",
            f"/system/skill/{urllib.parse.quote(skill_id, safe='')}",
            token=token,
        )
        if delete_result.get("code") == 200:
            deleted.append({"skillId": skill_id, "name": skill.get("name")})
        else:
            skipped.append({
                "skillId": skill_id,
                "name": skill.get("name"),
                "result": delete_result,
            })
    after = _list_skills(base_url, token, keyword)
    return {"before": before, "deleted": deleted, "skipped": skipped, "after": after}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--skill-id", default="")
    parser.add_argument(
        "--action",
        choices=["list", "files", "duplicate-skill-md", "cleanup"],
        default="list",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    token = _login(args.base_url, args.username, args.password)
    if args.action == "cleanup":
        result = _cleanup_skills(args.base_url, token, args.keyword)
    elif args.action == "files":
        skill_id = args.skill_id or _first_matched_skill_id(args.base_url, token, args.keyword)
        result = _file_tree(args.base_url, token, skill_id)
    elif args.action == "duplicate-skill-md":
        skill_id = args.skill_id or _first_matched_skill_id(args.base_url, token, args.keyword)
        result = _duplicate_skill_md(args.base_url, token, skill_id)
    else:
        result = _list_skills(args.base_url, token, args.keyword)

    payload = {
        "action": args.action,
        "base_url": args.base_url,
        "keyword": args.keyword,
        "skill_id": args.skill_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
