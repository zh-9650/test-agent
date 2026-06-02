"""core/skills/system_modeler.py — Node 2: Business Extraction / System Modeling.

L1 Pipeline Position:
  上游: N1 KnowledgeBase + N1.5 UseCaseModel (refined by N1.7)
  下游: N3 GoalExtractor (用 modules/entities 命名空间) + Layer 3 (State Evidence)
  本节点职责: 把脚手架升级为轻量级状态机(Lightweight State Machine)

V1.6.1 加固 (2026-06-02):
  - 修 V1.7 报告点名的 fallback 频繁 (3/4 fixture) P0
  - 加 _normalize_system_model() 后处理 (剥后缀 / 对齐 action / 去重 transitions)
  - 加 _derive_minimal_system_model() 兜底 (LLM 完全失败时不再返回空)
  - 加 rule 6 (后缀黑名单 + transitions 去重) 到 prompt
  - 加 _is_node_normalized() 公开校验函数, 与 tests 共享防止漂移
"""
from __future__ import annotations

from core.llm_client import safe_structured_invoke
from core.interfaces import SystemModel, KnowledgeBase, UseCaseModel, BusinessFlow, StateTransition


# 节点名后缀黑名单 (LLM 经常在节点名加这些尾巴, 违反 rule 1)
_NODE_SUFFIX_BLACKLIST: tuple[str, ...] = ("状态", "流程", "页", "中", "期")


# =============================================================================
# V1.6.1: 节点名校验 + 后处理辅助函数
# =============================================================================


def _is_chinese_noun_phrase(s: str) -> bool:
    """2-6 汉字, 纯中文, **无后缀黑名单**。"""
    if not s:
        return False
    s = s.strip()
    if not (2 <= len(s) <= 6):
        return False
    import re
    if not re.match(r"^[\u4e00-\u9fff]+$", s):
        return False
    if any(s.endswith(suf) for suf in _NODE_SUFFIX_BLACKLIST):
        return False
    return True


# 公开别名, 让 tests 共享同一份校验逻辑, 避免漂移
is_node_normalized = _is_chinese_noun_phrase
_is_node_normalized = _is_chinese_noun_phrase


def _strip_node_suffix(node: str) -> str:
    """剥掉节点名常见后缀 (状态/流程/页/中/期), 长度低于 2 则保持原样。

    反复剥, 处理 "审核中状态" → "审核" 这类多层后缀。
    不剥前缀 (LLM 发明前缀是另一类问题, 不应自动掩盖)。
    """
    if not node:
        return node
    s = node
    changed = True
    while changed and len(s) > 2:
        changed = False
        for suf in _NODE_SUFFIX_BLACKLIST:
            if s.endswith(suf) and len(s) - len(suf) >= 2:
                s = s[: -len(suf)]
                changed = True
                break
    return s


def _align_action(action: str, ucm_names: list[str]) -> str:
    """把 transitions[].action 对齐到最接近的 use_case.name。

    策略 (按顺序):
      1. 精确匹配 → 保持
      2. action 是某 ucm_name 的子串 → 用最长的 ucm_name
         (LLM 经常缩写, e.g., "提交" → 应恢复为 "提交采购申请")
      3. 某 ucm_name 是 action 的子串 → 用最长的 ucm_name
         (LLM 经常扩展, e.g., "登录后访问首页" → 应恢复为 "登录")
      4. 仍无匹配 → 保持原样 (test 会失败, 但至少 LLM 有原始数据)
    """
    if not action or not ucm_names:
        return action
    if action in ucm_names:
        return action
    candidates = [n for n in ucm_names if action in n and action != n]
    if candidates:
        return max(candidates, key=len)
    candidates = [n for n in ucm_names if n in action and n != action]
    if candidates:
        return max(candidates, key=len)
    return action


def _normalize_system_model(sm: SystemModel, ucm: UseCaseModel) -> SystemModel:
    """V1.6.1: 后处理 SystemModel, 修三类常见 LLM 违规:
      1. nodes 带 状态/流程/页/中/期 后缀 → 剥掉
      2. transitions[].action 不对齐 use_case.name → 对齐 (substring 策略)
      3. transitions 重复 (同 from_state+action) / 跨节点引用 → 清理
    """
    ucm_names = [uc.name for uc in ucm.use_cases]
    fixed_flows: list[BusinessFlow] = []
    for flow in sm.flows:
        fixed_nodes = [_strip_node_suffix(n) for n in flow.nodes]
        node_set = set(fixed_nodes)
        seen: set[tuple[str, str]] = set()
        fixed_transitions: list[StateTransition] = []
        for t in flow.transitions:
            fs = _strip_node_suffix(t.from_state)
            ts = _strip_node_suffix(t.to_state)
            action = _align_action(t.action, ucm_names)
            if fs not in node_set or ts not in node_set:
                continue
            key = (fs, action)
            if key in seen:
                continue
            seen.add(key)
            fixed_transitions.append(
                StateTransition(from_state=fs, action=action, to_state=ts)
            )
        fixed_flows.append(BusinessFlow(
            name=_strip_node_suffix(flow.name),
            nodes=fixed_nodes,
            transitions=fixed_transitions,
        ))
    return SystemModel(
        system_name=sm.system_name,
        modules=list(sm.modules),
        entities=list(sm.entities),
        roles=list(sm.roles),
        flows=fixed_flows,
    )


def _derive_minimal_system_model(ucm: UseCaseModel) -> SystemModel:
    """V1.6.1: 当 LLM 完全失败 (safe_structured_invoke 返回 None) 时,
    用 UseCaseModel 推导一个最小可用骨架。

    每个 use_case.name 作为 action, trigger 作为 from_state, outcome 作为 to_state。
    保证下游 N3 / Layer 3 永远有数据可用 (不再返回空 SystemModel())。
    """
    flows_by_name: dict[str, list[str]] = {}
    transitions_by_name: dict[str, list[StateTransition]] = {}
    for uc in ucm.use_cases:
        from_state = _strip_node_suffix(uc.trigger) or "初始"
        to_state = _strip_node_suffix(uc.outcome) or "完成"
        flow_name = _derive_flow_name(uc)
        flows_by_name.setdefault(flow_name, [])
        if from_state not in flows_by_name[flow_name]:
            flows_by_name[flow_name].append(from_state)
        if to_state not in flows_by_name[flow_name]:
            flows_by_name[flow_name].append(to_state)
        transitions_by_name.setdefault(flow_name, []).append(
            StateTransition(from_state=from_state, action=uc.name, to_state=to_state)
        )
    flows = [
        BusinessFlow(
            name=flow_name,
            nodes=flows_by_name[flow_name],
            transitions=transitions_by_name[flow_name],
        )
        for flow_name in flows_by_name
    ]
    return SystemModel(
        system_name="Derived System Model (LLM fallback V1.6.1)",
        modules=["核心业务"],
        entities=[],
        roles=[],
        flows=flows,
    )


def _derive_flow_name(uc) -> str:
    """从 use_case 名字粗略分流的兜底, 剥后缀, 截断到 6 字。"""
    if not uc.name:
        return "默认业务流"
    cleaned = _strip_node_suffix(uc.name)
    return cleaned[:6] if len(cleaned) > 6 else (cleaned or "默认业务流")


# =============================================================================
# 主流程
# =============================================================================


async def generate_system_model(knowledge: KnowledgeBase, use_case_model: UseCaseModel) -> SystemModel:
    """Node 2: System Modeling. V1.6.1 加固版。"""
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
   - **禁止**带前缀( "申请单-草稿")、后缀( "草稿状态" "采购流程" "用户页" "审核中" "执行期")、标点、英文、数字
   - **同一节点在不同 flow 中拼写必须完全一致**(去空格+小写后字符串相等)
2. **transitions[].action 硬约束**: 必须**精确等于**某 use_case.name。这是 Layer 2 探索器匹配 action 的关键键。
   - **禁止**改写、缩写( "提交" → "提交采购申请" 是错的, action 应是 use_case.name 全名)
   - **禁止**扩展( "登录" → "登录后访问首页" 是错的)
3. **覆盖 UseCaseModel**: 每个 use_case 至少对应一条 transition(从 trigger 状态到 outcome 状态)。
4. **flow 划分**: 按业务域分 modules,如 "采购审批流"、"用户管理流"。一个 flow 内 nodes 集合是该流的状态空间。
5. **继承**: system_name / modules / entities / roles 应与 N1 KnowledgeBase 对齐,不要发明 N1 没有的实体。
6. **transitions 去重**: 同一个 (from_state, action) 只保留一条。
   - 想表达 approve/reject 两条路径,就用**两个不同的 use_case.name** (比如 "部门经理审批通过" 和 "部门经理审批驳回")
   - 同一 action 配不同 to_state 是错的,下游会重复匹配。
</rules>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble. No trailing comma.

{{
  "system_name": str,
  "modules":      [str],
  "entities":     [str],
  "roles":        [str],
  "flows": [
    {{
      "name": str,
      "nodes": [str],
      "transitions": [
        {{
          "from_state": str,
          "action":      str,
          "to_state":    str
        }}
      ]
    }}
  ]
}}

**自检步骤 (返回前在脑里走一遍)**:
1. 每个 node 是 2-6 汉字, 无 "状态"/"流程"/"页"/"中"/"期" 等后缀
2. 每个 transitions[].action 精确等于某 use_case.name (不扩展不缩写)
3. transitions[].from_state 和 to_state 都出现在本 flow.nodes 中
4. 同一 (from_state, action) 不重复
5. 整体 JSON 语法正确, 无尾逗号
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
        print("[SystemModeler] LLM returned None, falling back to UseCaseModel-derived minimal skeleton (V1.6.1)")
        return _derive_minimal_system_model(use_case_model)
    # V1.6.1: 总是过 normalize (LLM 输出即使 parse 成功, 也常有违规)
    normalized = _normalize_system_model(result, use_case_model)
    return normalized
