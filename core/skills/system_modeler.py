"""core/skills/system_modeler.py — Node 2: Business Extraction / System Modeling.

L1 Pipeline Position:
  上游: N1 KnowledgeBase + N1.5 UseCaseModel (refined by N1.7)
  下游: N3 GoalExtractor (用 modules/entities 命名空间) + Layer 3 (State Evidence)
  本节点职责: 把脚手架升级为轻量级状态机(Lightweight State Machine)
"""
from core.llm_client import safe_structured_invoke
from core.interfaces import SystemModel, KnowledgeBase, UseCaseModel


async def generate_system_model(knowledge: KnowledgeBase, use_case_model: UseCaseModel) -> SystemModel:
    """Node 2: System Modeling. Consumes KnowledgeBase + UseCaseModel to build a
    Lightweight State Machine graph. UseCaseModel is treated as a hard scaffold:
    transitions[].action MUST equal some use_case.name, and node names are
    normalized so Layer 2 graph matching can succeed.
    """
    prompt = f"""<role>
你是一个顶级系统架构师。你的唯一职责是把"用例脚手架 (UseCaseModel)"升级为系统的"轻量级状态机 (Lightweight State Machine)"。
</role>

<context>
你在 L1 流水线的下游。
- 上游: N1 KnowledgeBase + N1.5 UseCaseModel (N1.7 已做过覆盖自检)
- 下游: N3 读 modules/entities 命名空间;Layer 3 用 transitions[] 做 State Evidence 比对
- 你的成功定义: Layer 2 探索器能直接用 transitions[].action 字符串匹配 UseCaseModel.name,从而知道"在哪个 action 后跳到哪个状态"
</context>

<task>
基于 UseCaseModel 的 trigger / outcome,构建状态机 JSON。
</task>

<rules>
1. **nodes 归一化 (重要, 防下游匹配失败)**:
   - 每个 node 必须是**2-6 个汉字**的名词短语(如 "草稿"、"待审批"、"已完成")
   - **禁止**带前缀( "申请单-草稿")、后缀( "草稿状态")、标点( "草稿.")、英文( "draft")、数字( "状态1")
   - **同一节点在不同 flow 中拼写必须完全一致**(去空格+小写后字符串相等)
2. **transitions[].action 硬约束**: 必须**精确等于**某 use_case.name。这是 Layer 2 探索器匹配 action 的关键键。
3. **覆盖 UseCaseModel**: 每个 use_case 至少对应一条 transition(从 trigger 状态到 outcome 状态)。
4. **flow 划分**: 按业务域分 modules,如 "采购审批流"、"用户管理流"。一个 flow 内 nodes 集合是该流的状态空间。
5. **继承**: system_name / modules / entities / roles 应与 N1 KnowledgeBase 对齐,不要发明 N1 没有的实体。
</rules>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "system_name": str,
  "modules":      [str],       // 业务模块名,如 ["采购管理", "审批管理"]
  "entities":     [str],       // 核心实体,继承自 N1
  "roles":        [str],       // 角色,继承自 N1
  "flows": [
    {{
      "name": str,             // 业务流名称
      "nodes": [str],          // 该流涉及的状态节点(2-6 字汉字)
      "transitions": [
        {{
          "from_state": str,   // 必须出现在本 flow.nodes 中
          "action":      str,  // 必须 == 某 use_case.name
          "to_state":    str   // 必须出现在本 flow.nodes 中
        }}
      ]
    }}
  ]
}}

字段约束:
- `transitions[].action` ∈ ∪ use_case.name
- `transitions[].from_state`、`to_state` ∈ 本 flow.nodes
- 同一节点名在所有 flows 中拼写一致
- 节点名长度 2-6 字汉字
</output_contract>

### 输入 1:UseCaseModel (refined, 是脚手架)
```json
{use_case_model.model_dump_json(indent=2)}
```

### 输入 2:KnowledgeBase (补充细节)
```json
{knowledge.model_dump_json(indent=2)}
```
"""
    result = await safe_structured_invoke(prompt, SystemModel, model_type="default")
    if result is None:
        print("[SystemModeler] LLM returned no usable model, using empty SystemModel")
        return SystemModel()
    return result
