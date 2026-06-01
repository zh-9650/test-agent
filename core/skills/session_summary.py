"""core/skills/session_summary.py — Session Summary (Phase 1.5).

L1 Pipeline Position:
  上游: 单个 TestCase 的执行 steps + status
  下游: 下一个 TestCase 的 SystemMessage 顶部注入(让 LLM 记住"之前已经做了什么")
  本节点职责: 把单个 case 的执行过程压缩成 < 100 字的摘要 + key_findings
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.llm_client import safe_structured_invoke


class CaseSummary(BaseModel):
    case_id: str = Field(description="用例 ID")
    status: str = Field(description="pass / fail / skipped / incomplete")
    summary: str = Field(description="一句话描述做了什么和结果,<= 100 字")
    key_findings: list[str] = Field(default_factory=list, description="关键发现,0-3 条")


GOOD_EXAMPLE = """
INPUT (excerpt):
用例: TC-001 - 登录成功
状态: pass
执行步骤:
  - navigate(/login) → 导航成功 []
  - input_text(username=test_c) → 输入成功 []
  - input_text(password=***) → 输入成功 []
  - click(登录按钮) → 跳转首页 [pass]
访问过的页面: /login, /

EXPECTED OUTPUT:
{
  "case_id": "TC-001",
  "status": "pass",
  "summary": "用 test_c/123456 在 /login 登录,3 步内成功跳转到首页,无异常。",
  "key_findings": ["登录后正确跳转到 /,未跳到 dashboard", "无验证码校验"]
}
"""

BAD_EXAMPLE = """
INPUT (excerpt):
用例: TC-002 - 登录失败
状态: pass (断言为"错误提示出现",通过)
执行步骤:
  - input_text(wrong_password) → 输入成功 []
  - click(登录按钮) → 页面显示错误提示 [pass]
访问过的页面: /login

WRONG OUTPUT (anti-pattern): summary 写成"测试通过",丢失了"验证了错误提示"这个关键信息。
RIGHT OUTPUT:
{
  "case_id": "TC-002",
  "status": "pass",
  "summary": "用错误密码登录,验证到红色错误提示'用户名或密码错误'正常出现。",
  "key_findings": ["错误提示文案是'用户名或密码错误',非通用'登录失败'", "未触发账号锁定(连续失败 3 次才锁)"]
}
Reason: summary 必须保留"测了什么 + 验证到什么"两个要素,不能只说"通过"。
"""


async def generate_case_summary(
    test_case_id: str,
    test_case_title: str,
    status: str,
    steps: list,
    page_urls: list[str] | None = None,
) -> dict[str, Any]:
    """调用 LLM 将 Case 执行结果压缩为简短摘要。

    流水线位置: 每个 TestCase 结束后 → 下一个 TestCase 开始前的 SystemMessage 顶部注入。
    摘要必须保留"测了什么 + 验证到什么",不能只说"通过"。

    Args:
        test_case_id: 用例 ID
        test_case_title: 用例标题
        status: 执行状态 (pass/fail/skipped/incomplete)
        steps: 步骤结果列表
        page_urls: 访问过的页面 URL 列表(可选)

    Returns:
        dict {case_id, status, summary, key_findings}
    """
    steps_text = ""
    for s in steps[:10]:
        action = getattr(s, "action_type", "") or ""
        target = getattr(s, "action_target", "") or ""
        result = getattr(s, "result", "") or ""
        assertion_status = ""
        if hasattr(s, "assertion") and s.assertion:
            assertion_status = s.assertion.status
        steps_text += f"  - {action}({target}) → {result[:80]} [{assertion_status}]\n"

    prompt = f"""<role>
你是一个测试记录压缩器。你的唯一职责是把单个测试用例的执行过程压缩成 100 字内的"对下一个 case 有用"的记忆点。
</role>

<context>
你在测试平台的"执行阶段"流水线中。
- 上游: 刚执行完一个 TestCase,获得 steps + status
- 下游: 这个摘要会被注入到下一个 TestCase 的 SystemMessage 顶部,让 LLM 记住"上一个 case 做了什么"
- 你的成功定义: 下一个 case 的 LLM 看 summary 后能直接接着上次的进度(例如"已登录,直接测业务"),不会重复登录或重复已发现的页面
</context>

<task>
将以下测试用例的执行过程压缩为简短摘要。
</task>

<rules>
1. **summary 必须保留两个要素**: (a) 测了什么动作 (b) 验证到什么结果。**禁止**只说"通过"或"失败"。
   - 好: "用 test_c 登录后跳转到首页,验证无验证码"
   - 坏: "登录测试通过"(下一个 case 不知道"无验证码"这个事实)
2. **summary 长度 ≤ 100 字**,中文。
3. **status 透传**: `status` 字段必须与输入完全一致,不要改写。
4. **key_findings 0-3 条**: 只记录对未来 case 有用的事实(已登录状态、发现的文案、发现的入口、失败的根因)。
   - 不要写"用例通过"这种废话
   - 不要写"步骤 1 成功"这种步骤重放
5. **失败时的 key_findings 必填**: 如果 status 是 fail/incomplete,key_findings 至少 1 条说明根因或失败位置。
6. **CoT 引导**: 在生成 JSON 前,内部先想清楚"下一个 case 看到这个摘要,最需要知道什么"。
</rules>

<examples>
<example title="good: 保留两个要素 + key_findings 有价值">
{GOOD_EXAMPLE}
</example>
<example title="bad-to-good: 失败用例也要保留验证信息">
{BAD_EXAMPLE}
</example>
</examples>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "case_id": str,
  "status": str,                  // 透传输入的 status
  "summary": str,                 // <= 100 字中文,保留"测了什么 + 验证到什么"
  "key_findings": [str]            // 0-3 条
}}

字段约束:
- `case_id` == 输入
- `status` == 输入
- `summary` 长度 ≤ 100 字
- `key_findings` 长度 0-3
</output_contract>

### 用例
- ID: {test_case_id}
- 标题: {test_case_title}
- 状态: {status}

### 执行步骤
{steps_text}

### 访问过的页面
{', '.join(page_urls[:5]) if page_urls else '未知'}
"""
    try:
        response = await safe_structured_invoke(prompt, CaseSummary, model_type="haiku")

        if response is None:
            print(f"[SessionSummary] LLM returned None for {test_case_id}, using fallback")
            return _fallback_summary(test_case_id, test_case_title, status)

        result = response.model_dump()
        print(f"[SessionSummary] Case {test_case_id}: {result.get('summary', '')}")
        return result
    except Exception as e:
        print(f"[SessionSummary] Failed for {test_case_id}: {e}")
        return _fallback_summary(test_case_id, test_case_title, status)


def _fallback_summary(test_case_id: str, test_case_title: str, status: str) -> dict[str, Any]:
    return {
        "case_id": test_case_id,
        "status": status,
        "summary": f"{test_case_title} - {status}",
        "key_findings": [],
    }
