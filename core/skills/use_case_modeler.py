"""core/skills/use_case_modeler.py — Node 1.5: Use Case Modeling.

L1 Pipeline Position:
  上游: N1 输出的 KnowledgeBase
  下游: N1.7 自检 + N3 直接映射 goals
  本节点职责: 把零散事实聚合成带 trigger/outcome 的原子级 UseCase,作为状态机的脚手架
"""
from core.llm_client import safe_structured_invoke, get_last_raw
from core.interfaces import KnowledgeBase, UseCaseModel
from core.diag_logger import get_diag_auto


async def generate_use_case_model(knowledge: KnowledgeBase) -> UseCaseModel:
    """Node 1.5: Use Case Modeling.
    Acts as a cognitive scaffold bridging the flat KnowledgeBase to the SystemModel state machine.
    """
    prompt = f"""<role>
你是一个专业的系统分析师。你的唯一职责是把零散的事实聚合成"用例 (UseCase)",作为状态机的脚手架。
</role>

<context>
你在 L1 流水线的中间。
- 上游: N1 输出的 KnowledgeBase (含 roles / entities / business_rules)
- 下游: N1.7 用你的 use_cases 跟 N1.business_rules 做覆盖自检;N3 直接把每个 use_case.name 映射成探索目标
- 你的成功定义: 下游 N1.7 + N3 能零成本消费你的输出
</context>

<task>
阅读以下 KnowledgeBase,推导并输出该系统所有的业务用例。
</task>

<rules>
1. **actor 字段硬约束** (重要): `actor` 的值**必须**在 `knowledge.roles[].text` 列表中存在。
   - 找不到对应角色时填 `"unknown_actor:<原始输入>"`(便于下游发现幻觉)
   - 禁止凭空发明角色名(如模型默认"User"/"Admin")
2. **related_rules 覆盖率目标 ≥ 85%**: 每条 `business_rule` 应至少被一个 `use_case.related_rules` 文本字面或语义引用。
   - N1.7 会做严格校验,缺失的规则会触发 LLM 补全
3. **粒度反向约束**: 用例是粗粒度业务操作(提交采购申请、审批采购申请),**禁止**精细到"点击某个按钮"。
4. **覆盖所有核心流转**: 把所有"主动作 + 状态变更"配对都建模出来,不要遗漏。
5. **trigger / outcome 用业务语言**: 不要写"点击 submit 按钮后 form 提交",要写"申请单处于草稿状态" → "申请单状态变为待审批"。
</rules>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "use_cases": [
    {{
      "name": str,
      "actor": str,         // MUST be in knowledge.roles[].text
      "trigger": str,
      "outcome": str,
      "related_rules": [str]   // 文本可在 knowledge.business_rules[].text 找到(字面包含或语义同)
    }}
  ]
}}

字段约束:
- `use_cases` 长度 ≥ 1
- `actor` ∈ knowledge.roles[].text ∪ {{"unknown_actor:*"}}
- 未知/缺失时 `related_rules` 用空数组 `[]`
</output_contract>

### 输入:KnowledgeBase
```json
{knowledge.model_dump_json(indent=2)}
```
"""
    result = await safe_structured_invoke(prompt, UseCaseModel, model_type="default")
    if result is None or not result.use_cases:
        print("[UseCaseModeler] LLM returned no usable use cases, falling back to empty UseCaseModel")
        get_diag_auto().dump("02_l1_use_case", node="N15_use_case_modeler", output=UseCaseModel(use_cases=[]), status="empty_fallback", raw_content=get_last_raw())
        return UseCaseModel(use_cases=[])
    get_diag_auto().dump("02_l1_use_case", node="N15_use_case_modeler", output=result, status="ok",
                          use_cases_count=len(result.use_cases), raw_content=get_last_raw())
    return result
