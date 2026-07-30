# test_agent v2 用例生成内核实施规格

状态：工作草案
范围：从原始输入接入到测试用例资产包产出
不包含：Runtime 改造、测试执行、执行 Memory、共享 Skill 切换

## 1. 目标

在不修改 v1 默认路线的前提下，为 `test_agent` 增加一条独立、可审计、可盲测的 v2
用例生成路线。v2 必须解决三个问题：

1. 原始资料不能再被压成不可追踪的字符串。
2. 测试覆盖必须来自正式模型和明确分母，而不是 Technique 标签。
3. 用例必须是覆盖义务的可验证投影，而不是一次性文本生成结果。

首个固定验证切片是阿勒泰绩效任务全生命周期：

`自评 → 上级评分 → 确认 → 退回 → 重新评分 → 完成 → 申诉/撤销`

## 2. 与 v1 的关系

v1 保持现状：

```text
RequirementFact
→ RequirementAssertion
→ TestCondition
→ TestDesignTechnique
→ CoverageItem
→ CandidateTestCase
```

v2 使用独立入口：

```text
SourceArtifact
→ ParsedArtifact
→ EvidenceClaim
→ BusinessBaseline
→ ModelPortfolio
→ CoverageObligation
→ AtomicTestSpec
→ ChainSuite
→ DesignPackage
```

在盲测通过前：

- 不删除或改写 `core/skills/l2_pipeline.py`。
- 不让 v2 产物进入默认执行路线。
- 不把 v2 逻辑实现为共享 Skill。
- v1 与 v2 使用同一份冻结原始资料进行对照。

## 3. 总体架构

```text
Frontend / API / Local Import
              |
              v
       DesignSessionService
              |
   +----------+-----------+
   |                      |
   v                      v
Source Intake       Session State Store
   |
   v
Parser Registry
   |
   v
Parse Fidelity Gate
   |
   v
Evidence Extractor + Evidence Verifier
   |
   v
Business Baseline Builder
   |
   v
Baseline Review
   |
   v
Model Portfolio Builder + Model Validators
   |
   v
Coverage Compiler Registry
   |
   v
Case Projector + Chain Builder
   |
   v
Design Quality Gates
   |
   v
Versioned DesignPackage
```

`DesignSessionService` 是 v2 生命周期的唯一编排者。LLM 可以参与证据提取、模型候选和
步骤表述，但不能决定阶段是否通过，也不能绕过任何确定性门禁。

## 4. 代码模块

建议新增：

```text
core/design_studio/
├── contracts/
│   ├── source.py
│   ├── evidence.py
│   ├── baseline.py
│   ├── models.py
│   ├── coverage.py
│   ├── cases.py
│   └── session.py
├── ingestion/
│   ├── service.py
│   ├── manifest.py
│   └── artifact_store.py
├── parsing/
│   ├── base.py
│   ├── registry.py
│   ├── markdown_parser.py
│   ├── docx_parser.py
│   ├── openapi_parser.py
│   ├── html_prototype_parser.py
│   ├── image_parser.py
│   ├── source_tree_parser.py
│   └── fidelity_gate.py
├── evidence/
│   ├── extractor.py
│   ├── verifier.py
│   └── conflict_detector.py
├── baseline/
│   ├── builder.py
│   └── validator.py
├── models/
│   ├── portfolio_builder.py
│   ├── state_model.py
│   ├── decision_model.py
│   ├── permission_model.py
│   ├── process_model.py
│   ├── data_domain_model.py
│   ├── combination_model.py
│   ├── relation_oracle_model.py
│   └── validators.py
├── coverage/
│   ├── registry.py
│   ├── state_compiler.py
│   ├── decision_compiler.py
│   ├── permission_compiler.py
│   ├── process_compiler.py
│   ├── data_domain_compiler.py
│   ├── combination_compiler.py
│   └── relation_oracle_compiler.py
├── projection/
│   ├── case_projector.py
│   ├── chain_builder.py
│   └── validators.py
├── invalidation.py
├── gates.py
└── service.py
```

v2 不继续向 `core/skills/l2_pipeline.py` 增加分支。

## 5. DesignSession 状态机

```text
collecting
  → parsing
      → input_blocked
      → extracting
          → baseline_review
              → collecting
              → modeling
                  → model_blocked
                  → compiling
                      → coverage_blocked
                      → projecting
                          → design_review
                              → modeling
                              → completed
```

状态含义：

- `collecting`：接收、版本化并登记原始资料。
- `parsing`：执行格式专用解析器。
- `input_blocked`：必要资料存在失败、部分解析或不支持结构。
- `extracting`：从已通过解析门禁的块中提取证据声明。
- `baseline_review`：人工只确认业务语义、冲突裁决和范围，不修复解析缺失。
- `modeling`：生成模型组合并执行模型验证。
- `model_blocked`：模型存在不可计算结构、悬空来源或未解决冲突。
- `compiling`：确定性编译覆盖义务。
- `coverage_blocked`：覆盖分母不完整或存在无理由豁免。
- `projecting`：把覆盖义务投影为原子用例和链路套件。
- `design_review`：确认设计取舍、豁免和链路组织。
- `completed`：形成冻结、可版本化的 `DesignPackage`。

所有 `blocked` 状态必须带机器可读错误码、关联产物 ID 和恢复动作。

## 6. 输入与解析合同

### 6.1 SourceArtifact

```text
source_id
session_id
source_kind
media_type
original_name
origin_uri
authority: normative | observed | technical | historical
required: bool
sha256
byte_size
source_version
captured_at
secret_refs
```

规则：

- 原件不可被解析结果覆盖。
- 账号密码只保存 Secret 引用，不进入资料文件和设计产物。
- 相同 hash 可去重，但不能合并不同来源身份。
- 来源角色必须明确；真实系统观察不能自动覆盖规范来源。

### 6.2 ParsedBlock

```text
block_id
source_id
source_hash
parser_name
parser_version
block_type
text_content
structured_content
parent_block_id
order
locator
asset_refs
```

`locator` 按格式保存页码、标题路径、表格/行列、接口路径、HTML 文件与选择器、源码
文件行号或图片区域。

### 6.3 ParseFidelityReport

```text
report_id
source_id
status: complete | partial | failed | unsupported
detected_inventory
parsed_inventory
unsupported_features
warnings
errors
gate_decision
parser_version
```

`complete` 必须同时满足：

1. 原始 hash 可复核。
2. 输入格式和版本受当前解析合同支持。
3. 检测到的受支持结构全部进入解析结果。
4. 所有解析块的定位都能回查原件。
5. 未支持结构已显式列出；必要资料存在未支持结构时不得 complete。

人工不能把 `partial` 或 `failed` 直接批准为 `complete`。恢复方式只能是修复解析器、
转换资料格式，或将该来源显式移出必要资料集合并记录风险。

## 7. 首版输入支持矩阵

| 输入 | 首版解析结果 | complete 的关键条件 |
|---|---|---|
| Markdown / TXT | 标题、段落、表格、代码块、链接 | 结构计数一致，编码无损 |
| DOCX | 标题、段落、表格、合并单元格、图片、页眉页脚 | 检测到的受支持 OOXML 结构全部有块 |
| OpenAPI JSON/YAML | path、method、参数、请求、响应、schema、enum、ref | 引用可解析，operation/schema 数量一致 |
| HTML 原型目录或 ZIP | 页面清单、可见文本、表单、字段、按钮、导航、资源引用 | 所有目标 HTML 文件有页面模型，资源缺失显式报告 |
| 原型源码目录或 ZIP | 文件树、路由、组件、表单、接口调用和忽略项 | 纳入/忽略文件均有清单，不执行不可信源码 |
| PNG/JPG | 原图、OCR 块、视觉区域和分析状态 | 图片未损坏，OCR/视觉失败显式报告 |
| 真实系统描述 | URL、角色、环境、权限和现有 `SystemMapEvid` 引用 | 只消费现有观察证据；本里程碑不新增 Runtime 能力 |

XLSX、XMind、扫描 PDF 等未进入首版 complete 矩阵时必须返回 `unsupported`，不能退化为
空文本或伪成功。后续通过新增解析器扩展，不改变上层合同。

大型原型目录不把全部 SVG、JS、CSS 文本塞入 LLM。解析器先建立完整文件和引用清单，
再把页面、交互和目标业务相关块交给语义阶段；未送入模型的资源仍保留处置记录。

## 8. 解析质量保证

解析保证由程序和回归数据实现，不由 LLM 自报完成。

### 8.1 格式专用结构盘点

每个解析器先盘点原文件，再解析。例如 DOCX 先从 OOXML 统计标题、段落、表格、单元格、
图片关系和未支持对象；OpenAPI 先统计 operation、schema、enum 和 ref。

### 8.2 前后核对

`fidelity_gate.py` 对 `detected_inventory` 和 `parsed_inventory` 做确定性核对。任何必要
结构未被解释，都生成稳定错误码并进入 `input_blocked`。

### 8.3 黄金输入集

首个黄金输入集直接使用阿勒泰绩效切片的冻结副本，至少包含：

- 绩效需求规格书 DOCX。
- 绩效相关接口文档。
- 考核管理、我的绩效、绩效统计相关原型页面和资源清单。
- 绩效思维图图片。
- 脱敏后的真实系统观察证据。

黄金断言分为两层：

- 解析断言：结构、数量、定位和不支持项没有回归。
- 语义断言：关键角色、状态、迁移、退回、确认、申诉和跨模块影响没有遗漏。

关键解析结构和关键业务事实的黄金样本召回必须是 100%；无来源声明必须是 0。

### 8.4 故障注入

必须验证以下情况会被阻断：

- DOCX 表格被解析器静默忽略。
- OpenAPI ref 无法解析。
- HTML 引用了不存在的资源。
- 大文件被截断。
- 图片 OCR 或视觉处理失败。
- 源文件改变但下游仍被当作有效。

## 9. 证据与业务基线

### 9.1 EvidenceClaim

```text
claim_id
claim_kind
modality: normative | observed
subject
predicate
object
qualifiers
source_block_ids
extractor_version
review_status
```

硬规则：

- 每条声明至少引用一个 `ParsedBlock`。
- 规范声明和系统观察分开保存。
- Memory、历史经验和模型猜测不能成为规范声明来源。
- 无法定位、存在冲突或依赖推断的声明必须进入待处理列表。

### 9.2 EvidenceVerifier

独立执行：

- 来源块存在性检查。
- 引用内容是否支持声明。
- 重复声明合并建议。
- 规范与观察冲突识别。
- 角色、状态、条件、公式、权限、异常和 Oracle 遗漏扫描。

它不能静默改写声明，只能产生 finding。

### 9.3 BusinessBaseline

人工确认的是：

- 测试范围与排除项。
- 业务对象和角色。
- 状态、流程和业务规则。
- 字段、约束和计算口径。
- 跨模块关系与正确结果判定。
- 冲突裁决。
- 未解决问题及其阻断级别。

确认结果产生不可变 `baseline_version`。任何被引用来源 hash 变化都会使该版本 stale。

## 10. 正式模型组合

`ModelPortfolioBuilder` 根据已确认基线提出所需模型，但模型是否有效由确定性验证器判断。
每个模型只能表达一种主要测试关系。

### 10.1 通用模型信封

```text
model_id
model_type
model_version
scope
source_claim_ids
criterion_defaults
validation_status
```

### 10.2 首个切片启用的模型

首个阿勒泰切片必须启用：

1. `StateTransitionModel`
   - 状态、动作、角色、guard、合法迁移、非法迁移、结果和副作用。
2. `DecisionModel`
   - 有无确认节点、是否可申诉、输入边界等条件组合。
3. `PermissionModel`
   - 角色 × 动作 × 业务状态 × 允许/拒绝。
4. `RelationOracleModel`
   - 任务状态对消息、我的绩效和统计结果的传播与一致性约束。

`ProcessModel`、`DataDomainModel`、`CombinationModel` 保留合同，但在首个切片证明需要前
不强行启用。

### 10.3 模型验证

至少检查：

- 所有模型元素有来源声明。
- 状态机有起点、终态和可达路径。
- 迁移引用的状态、角色和动作存在。
- decision rule 无空洞、冲突或无法计算条件。
- permission cell 的允许/拒绝语义明确。
- Oracle 有观测对象、比较方式和判定条件。
- 未解决业务问题不能被模型擅自补全。

## 11. 覆盖编译

覆盖义务只能由模型专用编译器确定性生成。

### 11.1 CoverageObligation

```text
obligation_id
model_id
model_version
criterion_id
subject_refs
precondition
stimulus
expected_relation
oracle_requirement
priority
status: required | waived | deferred
waiver_reason
source_claim_ids
```

`obligation_id` 基于模型版本、覆盖准则和被覆盖元素内容寻址生成；同一模型重复编译应
产生相同 ID。

### 11.2 编译器职责

- 状态模型：状态覆盖、合法迁移、关键非法迁移、guard 正反例、起点到终态路径、
  返回和循环路径。
- 决策模型：每条规则、默认分支、条件真/假、规则空洞和冲突。
- 权限模型：范围内每个允许格和拒绝格，结合关键业务状态。
- 关系 Oracle 模型：传播、隔离、聚合、一致性和时序义务。
- 数据域模型：有效类、无效类、边界值、空值和格式。
- 组合模型：由因素、取值、约束和强度生成 covering array。

覆盖分母是 `required + waived + deferred` 的完整集合。任何义务没有状态都阻断。

## 12. 用例投影

### 12.1 AtomicTestSpec

```text
case_id
title
purpose
obligation_ids
source_claim_ids
actors
semantic_preconditions
test_data_requirements
actions
checkpoints
oracles
cleanup_intent
dependency_ids
```

原子用例必须：

- 至少覆盖一个 obligation。
- 每个 obligation 在用例中有可识别 checkpoint。
- Oracle 可独立判断，不使用“结果正确”等空描述。
- 不包含 CSS selector、坐标或维护型浏览器脚本。
- 不把多个无法独立归因的失败点合成一个大用例。

LLM 可以把义务表述成业务步骤，但 `projection/validators.py` 必须验证 obligation、
checkpoint、Oracle 和来源没有丢失。

### 12.2 ChainSuite

`ChainSuite` 不是重新生成的大用例，而是对原子用例的有向编排：

```text
suite_id
atomic_case_ids
dependency_edges
shared_fixture
state_checkpoints
stop_policy
cleanup_policy
```

首个切片的主链套件可以组织：

`自评 → 评分 → 无附件确认被拒 → 退回 → 重新评分 → 有附件确认 → 完成 → 申诉 → 撤销`

每个节点仍保留自己的 obligation、checkpoint 和 verdict。

## 13. 质量门

| Gate | 阶段 | 硬失败条件 |
|---|---|---|
| G0 Input Fidelity | parsing | 必要来源非 complete、定位不可回查、静默丢结构 |
| G1 Evidence | extracting | 无来源声明、未处理冲突、关键黄金事实遗漏 |
| G2 Baseline | baseline_review | 未批准、阻断问题未解决、来源已变化 |
| G3 Model | modeling | 模型不可计算、元素无来源、状态/规则不闭合 |
| G4 Coverage | compiling | 覆盖分母不完整、义务无状态、无理由豁免 |
| G5 Projection | projecting | 义务无用例、checkpoint/Oracle 缺失、追溯断裂 |
| G6 Design Package | design_review | 产物 stale、版本不一致、审查未完成 |

门禁输出使用稳定错误码，例如：

```text
input.unsupported_structure
input.inventory_mismatch
input.truncated
evidence.unanchored_claim
evidence.unresolved_conflict
baseline.stale_source
model.unreachable_state
model.unresolved_reference
coverage.unassigned_obligation
coverage.unjustified_waiver
projection.missing_checkpoint
projection.unjudgeable_oracle
```

## 14. 版本与失效重算

依赖图：

```text
Source hash
→ ParsedArtifact version
→ EvidenceClaim version
→ BusinessBaseline version
→ Model version
→ CoverageObligation version
→ AtomicTestSpec / ChainSuite version
```

任一上游变化：

1. 直接依赖产物标记 `stale`。
2. 递归失效下游产物。
3. 保留旧版本用于审计和 v1/v2 对比。
4. 只允许从最后一个有效 checkpoint 重新计算。
5. 人工批准不会跨版本自动继承。

## 15. 持久化设计

大型原件不存入任务 JSONB。首版使用文件制品仓库和轻量会话记录：

```text
data/design-sessions/<session-id>/
├── manifest.json
├── raw/
├── parsed/
├── fidelity-reports/
├── evidence/
├── baseline/
├── models/
├── coverage/
├── cases/
└── package/
```

数据库新增 `DesignSession` 记录会话状态、当前版本、产物 URI、阻断错误和时间戳。后续切换
对象存储时保持 URI 合同不变。

原始密码、token、cookie 不进入上述目录；只保存外部 Secret 引用。

## 16. API 与前端

建议新增独立 API：

```text
POST /api/design-sessions
POST /api/design-sessions/{id}/sources
POST /api/design-sessions/{id}/parse
GET  /api/design-sessions/{id}/sources
GET  /api/design-sessions/{id}/fidelity-reports
GET  /api/design-sessions/{id}/baseline
POST /api/design-sessions/{id}/baseline-decision
POST /api/design-sessions/{id}/generate
GET  /api/design-sessions/{id}/package
```

前端首版需要四个区域：

1. 多来源上传和目录/ZIP 接入。
2. 解析状态与丢失结构报告。
3. 业务基线确认和冲突裁决。
4. 模型、覆盖分母、原子用例和链路套件查看。

现有 `TaskCreate` 和任务执行页面保持 v1 行为；v2 页面只负责设计会话。

## 17. v1/v2 盲测

### 17.1 输入冻结

- 使用同一份脱敏、hash 固定的阿勒泰原始资料。
- v1 通过现有入口消费可支持的文本。
- v2 消费完整 SourceArtifact 集。
- 记录 v1 无法消费的资料，作为输入能力差异，不隐藏。

### 17.2 输出匿名

把两套用例统一转成审查格式，隐藏生成器和内部模型名称，由不了解来源的审查者评分。

### 17.3 评分维度

- 关键业务风险召回。
- 状态、权限、决策和跨模块覆盖完整度。
- 错误或无来源业务假设。
- 覆盖分母是否明确。
- Oracle 是否可独立判断。
- 用例冗余和不可执行前置。
- 证据到用例的追溯完整度。

### 17.4 通过条件

v2 至少满足：

- 关键黄金业务事实与关键覆盖义务召回 100%。
- 无来源业务声明为 0。
- 所有 required obligation 均被用例覆盖。
- 所有 waived/deferred obligation 都有明确理由。
- 所有用例有可判断 Oracle。
- 相比 v1 多发现的风险能回溯到正式模型和原始来源。

达到上述条件只证明 v2 用例生成里程碑通过，不等于 Runtime 或生产验收通过。

## 18. 实施顺序

### T0：合同与黄金输入

- 落地核心 Pydantic 合同。
- 冻结阿勒泰首个输入集及 hash。
- 标注解析黄金结构和关键业务事实。

### T1：输入与解析

- SourceArtifact 仓库、manifest、parser registry。
- Markdown、DOCX、OpenAPI、HTML 原型、源码树和图片解析器。
- ParseFidelityReport 和 G0。

### T2：证据与基线

- EvidenceClaim 提取、来源校验和冲突检测。
- BusinessBaseline 构建、版本化和批准接口。
- G1、G2。

### T3：首个模型组合

- 状态、决策、权限和关系 Oracle 模型合同。
- 模型组合构建和确定性验证。
- G3。

### T4：覆盖编译

- 四类首批编译器。
- obligation 稳定 ID、状态和追溯。
- G4。

### T5：用例投影

- AtomicTestSpec 投影。
- ChainSuite 依赖编排。
- G5、G6。

### T6：独立 API 与前端

- DesignSession API。
- 上传、解析报告、基线审查和设计资产页面。

### T7：盲测

- v1/v2 双跑。
- 匿名审查。
- 记录差异、失败归因和是否进入下一模型类型。

## 19. 明确不做

- 不在本里程碑切换默认 `TaskLifecycleService`。
- 不修改浏览器执行策略和工具权限。
- 不生成维护型 Playwright/Selenium 脚本。
- 不让一次成功运行自动修改业务基线或共享 Skill。
- 不追求首版支持所有文件格式。
- 不以人工确认替代解析完整性。
- 不以 LLM 自评替代模型、覆盖和投影门禁。
