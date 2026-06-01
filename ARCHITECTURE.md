# Smart Test Agent V2.0 架构白皮书

> **设计哲学**：从“依赖大模型主观猜测”全面升级为“基于事实证据和状态流转的智能断言网络”。

## 架构全景流水线

```text
[Layer 1: Cognitive Initialization (认知初始化)]
  ├── Document Parser (文本纯化)
  ├── Knowledge Extraction (事实/规则/约束提取)
  └── System Modeling (轻量状态机与实体构建)

[Layer 2: Goal-Driven Execution (目标驱动执行)]
  ├── Goal Generator (提取高优探索目标)
  └── UI Explorer Agent (带目标、防幻觉的页面穿透)

[Layer 3: Evidence-Based Assertion (证据链断言)]
  ├── Collector (程序收集：UI/Network/State/Rule 铁证)
  ├── Fusion Engine (多维证据融合)
  └── LLM Judge (大模型总结与归因解释)

[Layer 4: Continuous Learning (长期记忆反思)]
  └── Memory Reflection (失败经验沉淀入库)
```

---

## 第一层：输入与认知层 (Layer 1)

**核心原则：事实(Facts) > 摘要(Summary)，状态(State) > 步骤(Steps)。**

### 1. 结构化知识提取 (Knowledge Extraction)
废弃单一的“大模型总结 (Summary)”方式，采用强类型的知识提纯。
- **输入**：上限 1万字的纯文本 PRD / Swagger
- **输出**：不丢失细节的事实库
```json
{
  "business_rules": ["金额>5000需要总监审批"],
  "roles": ["申请人", "总监"],
  "entities": ["采购申请"],
  "constraints": ["金额阈值5000"],
  "raw_facts": [...]
}
```

### 2. 系统建模与轻量状态机 (System Modeling)
业务模型不再是扁平的文本步骤，而是强制采用 **轻量级状态机 (Lightweight State Machine)**。这是测试系统特有的敏感度要求——测试最关心的是状态跳变。
```json
{
  "flows": [
    {
      "name": "采购审批",
      "nodes": ["草稿", "待经理审批", "已通过"],
      "transitions": [
        {"from": "草稿", "action": "提交", "to": "待经理审批"}
      ]
    }
  ]
}
```

---

## 第二层：探索引擎 (Layer 2)

**核心原则：业务目标(Business Goal) > 页面动作(Action Goal)。**

### 1. 目标生成器 (Goal Generator)
基于 SystemModel，生成高级业务目标供 Explorer 使用，**Explorer 不再直接阅读 PRD**，从根源上斩断信息过载。
- ❌ 错误目标：`点击订单创建按钮` (过度指令化，限制探索范围)
- ✅ 正确目标：`找到订单创建能力` (给予充分的业务探索自由度)

### 2. 导航防火墙 (Navigate Firewall)
在探索阶段严禁 LLM 凭空伪造跳转路由。跳转目标必须存在于页面的实际 DOM 元素（href）或系统模型的已知边界内，极大降低幻觉造成的死循环。

---

## 第三层：证据链断言层 (Layer 3)

**核心原则：LLM 不负责判断事实，只负责解释事实。程序负责收集多维铁证。**

这是与市面普通 AI 测试工具拉开本质差距的核心层。采用**四层证据链 (Evidence Chain)**，对每一次页面操作进行终极判决。

### 证据收集阶段 (Evidence Collection)
在执行动作（如点击提交）后，系统触发等待策略（`wait_for_network_idle`, `wait_for_state_change`），收集以下四维证据：

1. **UI Evidence (视觉/DOM证据)**：页面 DOM 变化、弹出了 Toast（如“提交成功”）、按钮变灰。
2. **Network Evidence (网络证据)**：Playwright 拦截底层的网络请求，确认后端的真实响应状态（如 `POST /submit` 返回 `200` 且业务 code 为 `0`）。
3. **State Evidence (状态铁证)**：主动重新获取核心状态字段，验证状态是否按照状态机流转（如从 `草稿` 变为了 `待经理审批`）。
4. **Business Rule Evidence (规则契约)**：对照第一层提取的 `business_rules` 事实库，确认此次变更是合法的。

### 证据融合与大模型归因 (Fusion & LLM Judge)
系统程序将上述四种铁证融合打包，交给大模型。大模型失去主观猜测权，只能基于铁证出具归因报告：
```json
{
  "result": "pass",
  "reason": "状态已从草稿流转到待经理审批，且接口调用成功，符合业务规则阈值约束。"
}
```

---

## 架构演进建议

* **数据防污染 (State Pollution)**：后续在探索阶段（Planning）引入账号隔离或读写权限分级，防止探索期的盲目点击摧毁执行期的依赖数据。

---

## 附录：第一层 (Layer 1) 详细重构与开发指导设计

为了将上述第一层的“知识提取 -> 状态机建模”流水线在代码层面落地，以下是指导核心研发 (Core-Dev) 的具体设计契约。

### 1. 核心 Schema 契约定义 (`core/interfaces.py`)
所有模块间传递的数据必须使用以下强类型的 Pydantic 模型作为中间产物 (IR)：

```python
class KnowledgeBase(BaseModel):
    """节点 1 输出：结构化提取的业务事实与规则"""
    business_rules: list[str] = Field(description="核心业务规则，如：金额>5000需总监审批")
    roles: list[str] = Field(description="系统识别出的角色集合")
    entities: list[str] = Field(description="核心业务实体，如：采购申请、订单")
    constraints: list[str] = Field(description="阈值与硬性约束条件")
    raw_facts: list[str] = Field(description="不包含主观总结的原始客观事实条目")

class StateTransition(BaseModel):
    """状态机流转边"""
    from_state: str = Field(description="触发前的起始状态")
    action: str = Field(description="触发流转的动作")
    to_state: str = Field(description="流转后的目标状态")

class BusinessFlow(BaseModel):
    """轻量级状态机节点"""
    name: str = Field(description="流程名称，如：采购审批流")
    nodes: list[str] = Field(description="该流程涉及的所有状态枚举")
    transitions: list[StateTransition] = Field(description="状态之间的合法流转路径")

class SystemModel(BaseModel):
    """节点 2 输出：全系统骨架 (基于状态机)"""
    system_name: str = Field(default="Test System")
    modules: list[str]
    entities: list[str]
    roles: list[str]
    flows: list[BusinessFlow]

class ExplorationGoal(BaseModel):
    """节点 3 输出：探索目标"""
    goal: str = Field(description="业务级能力探索目标，如：'找到订单创建能力'")
    priority: str = Field(description="高/中/低优先级")
```

### 2. Node 1：知识提取 (`core/skills/knowledge_extractor.py`)
- **定位**：取代粗放的“读文档”，做无损事实提取。
- **输入**：`prd_content`, `api_doc_content`, `changelog_content`
- **输出**：`KnowledgeBase` 实例
- **Prompt 策略**：禁止归纳总结（Summary）。1:1 提取原文中关于规则、实体、角色的陈述。冲突时强制以 PRD 为准。

### 3. Node 2：业务状态机建模 (`core/skills/system_modeler.py`)
- **定位**：摒弃阅读长文档的压力，专心对着提纯后的事实块建图。
- **输入**：上一步输出的 `KnowledgeBase`
- **输出**：`SystemModel` 实例
- **Prompt 策略**：要求输出轻量级状态机 (Lightweight State Machine)，明确每个 `BusinessFlow` 里的 `from_state` -> `action` -> `to_state`。

### 4. Node 3：探索目标生成 (`core/skills/goal_extractor.py`)
- **定位**：断绝 Explorer Agent 读取原始文档的途径。
- **输入**：上一步输出的 `SystemModel`
- **输出**：`list[ExplorationGoal]`
- **Prompt 策略**：禁止输出 UI 级指令（如“点击审批按钮”），保持在业务能力层级（如“找到审批流转入口”）。

### 5. 流水线组装 (`api/app.py`)
在后台启动任务阶段（`_run_test_session`），将这三个动作串联为前置预处理：
```python
# 1. 解析链接拿到 raw_docs
enriched_config = await parse_and_fetch_links(config)

# 2. Node 1: 知识提纯
knowledge = await extract_knowledge(prd, api_doc, changelog)
enriched_config["_knowledge_base"] = knowledge.model_dump()

# 3. Node 2: 状态机建模
system_model = await generate_system_model(knowledge)
enriched_config["_system_model"] = system_model.model_dump()
```
