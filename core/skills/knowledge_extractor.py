"""core/skills/knowledge_extractor.py — Node 1: Knowledge Extraction.

L1 Pipeline Position:
  上游: 用户输入的 PRD / Swagger / Changelog 文本
  下游: N1.5 UseCaseModeler、N2 SystemModeler、Layer 3 规则断言
  本节点职责: 把零散文档提纯为带溯源指针的结构化 KnowledgeBase
"""
from pydantic import BaseModel
from core.llm_client import safe_structured_invoke
from core.interfaces import KnowledgeBase


GOOD_EXAMPLE = """
INPUT (excerpt):
"采购金额超过 5000 元需要部门经理审批。"

EXPECTED OUTPUT:
{
  "business_rules": [
    {
      "text": "采购金额超过 5000 元需要部门经理审批",
      "source": "prd",
      "quote": "采购金额超过 5000 元需要部门经理审批",
      "confidence": 1.0
    }
  ],
  "roles": [{"text": "部门经理", "source": "prd", "quote": "采购金额超过 5000 元需要部门经理审批", "confidence": 1.0}],
  "entities": [],
  "constraints": [{"text": "采购金额阈值：5000 元", "source": "prd", "quote": "采购金额超过 5000 元需要部门经理审批", "confidence": 1.0}],
  "raw_facts": []
}
"""

BAD_EXAMPLE = """
INPUT (excerpt):
"系统通过审批工作流保证合规。"

WRONG OUTPUT (anti-pattern): summarize into one vague fact.
RIGHT OUTPUT:
{
  "business_rules": [],
  "roles": [],
  "entities": [],
  "constraints": [],
  "raw_facts": [
    {
      "text": "系统通过审批工作流保证合规",
      "source": "prd",
      "quote": "系统通过审批工作流保证合规",
      "confidence": 0.7
    }
  ]
}
Reason: 这是"描述性陈述"而非"业务规则/实体/角色/约束"，按定义应放 raw_facts，
       且因无具体阈值或角色，confidence 给 0.7（信息量不足）。
"""


async def extract_knowledge(prd_content: str, api_doc_content: str, changelog_content: str) -> KnowledgeBase:
    """Node 1: Knowledge Extraction. Extracts hard facts, business rules, entities,
    roles, and constraints with traceable source quotes. No summarization allowed.
    """
    prompt = f"""<role>
你是一个极其严谨的"可追溯知识提取器"。你的唯一职责是从输入文档中**精确**提取结构化事实，每条事实必须能通过原文引用追溯。
</role>

<context>
你在 L1 认知初始化流水线的最上游。
- 下游 N1.5 会读你的 roles / entities / business_rules 来推导 UseCase；
- 下游 N2 会读 entities / roles 命名空间来建状态机；
- Layer 3 规则断言会用你的 business_rules 作为"业务契约铁证"。
- 本节点的成功定义 = 下游能直接消费你的输出，零回填。
</context>

<task>
从以下三份系统文档中提取出所有可追溯的结构化知识。
</task>

<rules>
1. **不要做摘要**！逐条提取具体事实，禁止把多条规则合并成"概括性陈述"。
2. **冲突处理**：当 PRD 与 Swagger 存在冲突时，**绝对以 PRD 为准**；冲突时 confidence 降至 ≤ 0.7。
3. **不可追溯 fallback**（重要）：当某条事实找不到精确原文引用时，`quote` 写 `"N/A"`，且 `confidence ≤ 0.5`，`source` 写 `"inferred"`。**禁止编造 quote**。
4. **每个 KnowledgeItem 必须有 4 字段**：
   - `text` (string): 事实描述
   - `source` (enum: `prd` | `swagger` | `changelog` | `inferred`)
   - `quote` (string): 原文引用，**必须能 Ctrl+F 找到**；不可追溯时填 "N/A"
   - `confidence` (number 0.0-1.0)
5. **不要无中生有**：如果某类信息不存在，保留空数组。
6. **5 类信息的边界**：
   - `business_rules`: 业务逻辑规则（"金额>5000 需要 X 审批"）
   - `roles`: 系统用户角色（"员工" / "部门经理"）
   - `entities`: 核心业务实体（"采购单" / "订单"）
   - `constraints`: 阈值与硬性约束（"金额阈值 5000"）
   - `raw_facts`: 上面 4 类装不下、但明显是客观事实的陈述
</rules>

<examples>
<example title="good: 有明确原文支撑">
{GOOD_EXAMPLE}
</example>
<example title="bad-to-good: 不可追溯时正确降级">
{BAD_EXAMPLE}
</example>
</examples>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "business_rules": [{{"text": str, "source": enum, "quote": str, "confidence": number}}],
  "roles":           [{{"text": str, "source": enum, "quote": str, "confidence": number}}],
  "entities":        [{{"text": str, "source": enum, "quote": str, "confidence": number}}],
  "constraints":     [{{"text": str, "source": enum, "quote": str, "confidence": number}}],
  "raw_facts":       [{{"text": str, "source": enum, "quote": str, "confidence": number}}]
}}

字段约束：
- `source` ∈ {{"prd", "swagger", "changelog", "inferred"}}
- `confidence` ∈ [0.0, 1.0]
- 未知值用空数组 `[]`，**不编造**
</output_contract>

### 产品需求文档 (PRD)
{prd_content or "未提供"}

### 接口文档 / Swagger
{api_doc_content or "未提供"}

### 变更日志 (Changelog)
{changelog_content or "未提供"}
"""
    empty = KnowledgeBase(business_rules=[], roles=[], entities=[], constraints=[], raw_facts=[])
    result = await safe_structured_invoke(prompt, KnowledgeBase, model_type="default")
    if result is None:
        print("[KnowledgeExtractor] LLM returned no usable knowledge, using empty KnowledgeBase")
        return empty
    return result
