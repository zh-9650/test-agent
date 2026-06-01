"""core/skills/risk_analyzer.py — Risk Analyzer (Phase 1.5).

L1 Pipeline Position:
  上游: planning_graph.explore_explore 收集的 page_elements + task_config.prd/swagger
  下游: planning_graph.generate_plan_node (用 risk_points 引导 Planner 生成边界/安全用例)
  本节点职责: 识别高风险元素,输出 risk_points 用于引导 Planner 生成更高价值用例
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.llm_client import safe_structured_invoke


class RiskPoint(BaseModel):
    element: str = Field(description="对应交互元素列表中的 id 或特征描述")
    risk_type: str = Field(description="为什么认为它是高风险点(如 '涉及金额计算')")
    severity: str = Field(description="'high' | 'medium' | 'low'")
    suggestions: list[str] = Field(default_factory=list, description="建议的测试场景列表(如 ['输入负数', '输入超大金额', '输入特殊字符'])")


class RiskAnalysisOutput(BaseModel):
    risk_points: list[RiskPoint] = Field(default_factory=list, description="提取出的风险点列表")


GOOD_EXAMPLE = """
INPUT (excerpt):
- e_42: input - "采购金额"
- e_43: button - "提交订单"
- e_44: select - "收货地址"

EXPECTED OUTPUT:
{
  "risk_points": [
    {
      "element": "e_42: 采购金额 (input)",
      "risk_type": "涉及金额计算,可能存在数值边界与符号注入",
      "severity": "high",
      "suggestions": ["输入负数", "输入 0", "输入超长数字", "输入浮点数 0.001", "输入科学计数法 1e10"]
    },
    {
      "element": "e_43: 提交订单 (button)",
      "risk_type": "不可逆操作,触发后端交易",
      "severity": "high",
      "suggestions": ["连续点击 3 次", "在未填必填项时点击", "在网络断开时点击"]
    }
  ]
}
"""

BAD_EXAMPLE = """
INPUT (excerpt):
- e_99: link - "关于我们"
- e_100: heading - "页脚版权"

WRONG OUTPUT (anti-pattern): 把所有元素都标为 high severity。
RIGHT OUTPUT:
{
  "risk_points": []
}
Reason: 静态展示型元素没有交互风险,不应被识别为 risk_point。
"""


async def analyze_risks(
    page_elements: list[dict[str, Any]],
    swagger: str = "",
    prd: str = "",
) -> list[dict[str, Any]]:
    """识别高风险元素并输出结构化风险点。

    流水线位置: 探索完毕 → 规划生成用例前。
    接收页面元素 + 文档上下文,输出风险点列表,引导 Planner 生成
    更高价值的边界值/安全测试用例。

    Args:
        page_elements: 探索阶段收集的所有交互元素列表
        swagger: Swagger/API 文档文本(可选)
        prd: PRD 文档文本(可选)

    Returns:
        风险点列表,每项包含 element, risk_type, severity, suggestions。
        返回空列表 = "没发现需要重点测的高风险点",不是错误。
    """
    if not page_elements:
        return []

    elements_text = ""
    for el in page_elements[:40]:
        el_type = el.get("type", "")
        label = el.get("label", "") or el.get("text", "") or el.get("placeholder", "")
        el_id = el.get("id", "")
        elements_text += f"  - {el_id}: {el_type} - {label}\n"

    doc_context = ""
    if prd:
        doc_context += f"\n## PRD 摘要\n{prd[:2000]}\n"
    if swagger:
        doc_context += f"\n## 接口文档摘要\n{swagger[:2000]}\n"

    prompt = f"""<role>
你是一个资深安全与质量保证专家。你的唯一职责是从 UI 元素中识别"高风险交互点",并给出具体可执行的测试场景建议。
</role>

<context>
你在测试平台的"规划阶段"流水线中。
- 上游: 探索阶段收集的 page_elements(最多 40 个) + 可选 PRD/Swagger 文档
- 下游: generate_plan_node 会把你的 risk_points 注入 Planner 的 prompt,引导它**优先**为这些元素生成边界值/安全/不可逆测试用例
- 你的成功定义: 下游 Planner 能直接消费 risk_points,零回填,产出的测试用例覆盖了高风险交互
</context>

<task>
分析以下页面元素 + 文档,识别出"高风险"交互元素,给出 severity 评级与具体测试场景建议。
</task>

<rules>
1. **什么算高风险** (重要, 不是"看起来重要"):
   - 涉及金额/价格/库存/数量计算的元素
   - 不可逆操作(删除/注销/提交订单/转账/退款)
   - 接受自由文本输入且会写入数据库的元素(SQL 注入/XSS 风险)
   - 涉及权限变更/角色切换的元素
   - 复杂校验逻辑(密码强度、手机号格式、邮箱格式)
2. **什么不算高风险** (反例):
   - 纯展示型元素(标题、段落、图片、Logo、关于我们)
   - 导航链接(可逆,失败回退)
   - 装饰性按钮(返回、关闭弹窗)
3. **severity 判定标准**:
   - `high`: 涉及金钱损失/数据丢失/安全漏洞/不可逆状态变更
   - `medium`: 涉及数据完整性但可恢复(修改资料、修改密码)
   - `low`: 涉及业务但影响有限(筛选、排序、分页)
4. **suggestions 必须是具体可执行步骤**: "输入负数" / "输入超长字符串 1000 字符" / "在未选必填项时点击提交"。**禁止**"测试边界"、"验证异常"这类空话。
5. **没有就返回空**: 没识别到高风险点时,返回 `{{"risk_points": []}}`,**不要**为了凑数把低风险元素标 high。
6. **最多 8 个**: 一个页面真正的高风险点很少,超过 8 个说明你没在筛。
</rules>

<examples>
<example title="good: 有金额 + 不可逆按钮">
{GOOD_EXAMPLE}
</example>
<example title="bad-to-good: 静态元素不应被误标">
{BAD_EXAMPLE}
</example>
</examples>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "risk_points": [
    {{
      "element": str,            // 元素描述,引用 input 列表中的 id(如 "e_42")或特征
      "risk_type": str,           // 一句话说明高风险原因
      "severity": "high" | "medium" | "low",
      "suggestions": [str]        // 2-5 条具体测试场景
    }}
  ]
}}

字段约束:
- `severity` ∈ {{"high", "medium", "low"}}
- `suggestions` 长度 2-5,不能为空数组(除非 risk_points 整体为空)
- `risk_points` 长度 0-8
- 未知/无风险时 `risk_points` 填 `[]`
</output_contract>

{doc_context}

## 页面元素列表
{elements_text}
"""
    try:
        response = await safe_structured_invoke(prompt, RiskAnalysisOutput, model_type="haiku")

        if response and response.risk_points:
            risk_points = [rp.model_dump() for rp in response.risk_points]
            print(f"[RiskAnalyzer] Identified {len(risk_points)} risk points")
            return risk_points
        print("[RiskAnalyzer] No risk points identified")
        return []
    except Exception as e:
        print(f"[RiskAnalyzer] Failed: {e}")
        return []
