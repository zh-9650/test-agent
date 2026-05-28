# 🎯 测试智能体架构评估与定制化方案

> **用户需求**: 企业智能体测试平台
> - 输入: 接口文档/线上地址/PRD/规则约束等
> - 输出: 测试报告 + Bug记录（禅道API）+ 执行记录
> - 时间: 2026年5月22日

---

## 📊 架构评估

### ✅ 优势分析

#### 1. **架构设计成熟度 - 9/10** 🌟

**强点**:
- ✨ **三层分离清晰**: Agent → MCP → Backend，职责划分明确
- ✨ **模块化设计**: Skills 架构，每个能力独立开发迭代
- ✨ **可扩展性强**: 新增测试类型只需开发新 Agent + Skills
- ✨ **标准化通信**: MCP 协议避免工具紧耦合

**缺点**:
- ❌ **缺少持久化层**: 没有明确的数据库设计用于存储执行记录
- ❌ **报告生成不完整**: 看不到测试报告的生成模块
- ❌ **缺少外部系统集成**: 没有提及与第三方系统（禅道/JIRA）的集成方案

#### 2. **功能覆盖度 - 8.5/10** 📋

**现有功能**:
- ✅ API 测试 (OpenAPI/Swagger/GraphQL) → 完整
- ✅ UI 自动化 (Web/H5) → 完整
- ✅ 性能测试 → 完整
- ✅ 用例生成 (从需求) → 完整
- ✅ 自动修复能力 → 5种策略

**缺失功能**:
- ❌ **对企业第三方系统的集成** (禅道/JIRA/钉钉等)
- ❌ **执行记录的持久化和查询** 
- ❌ **测试报告的可视化和对标**
- ❌ **测试历史对比** (版本/基线管理)
- ❌ **批量任务管理** (分布式调度)

#### 3. **生产就绪度 - 7/10** 🚀

**已就绪**:
- ✅ Agent 编排层 (LangGraph)
- ✅ 测试代码生成
- ✅ 自动修复流程

**需补完整**:
- 🔄 数据持久化层
- 🔄 第三方系统集成
- 🔄 报告生成和存储
- 🔄 执行状态追踪
- 🔄 错误处理和回滚

---

## 📍 用户需求 vs 架构匹配度

### 需求分析矩阵

| 需求 | 原架构 | 缺陷 | 优先级 | 方案 |
|------|-------|------|-------|------|
| **输入多种格式** | ✅ | 线上地址支持不完整 | 高 | 增强 Fetcher 模块 |
| **输出测试报告** | 🔄 | 无报告生成模块 | 高 | 新增 Reporter 模块 |
| **禅道 Bug 记录** | ❌ | 完全缺失 | 高 | 新增 IssueTracker 模块 |
| **执行记录保存** | 🔄 | 无持久化层 | 高 | 新增 ExecutionLogger 模块 |
| **规则约束执行** | 🔄 | 未明确支持 | 中 | 增强 Validator 模块 |

---

## 🛠️ 定制化实现方案

### 方案概览

```
┌─────────────────────────────────────────────────────┐
│           企业智能体测试平台 (定制版)                  │
└────────┬────────────────────────────────────┬────────┘
         │                                    │
    ┌────▼─────────────────┐         ┌───────▼──────┐
    │   输入处理层          │         │  核心执行层   │
    ├─────────────────────┤         ├──────────────┤
    │• API Fetcher        │         │• LangGraph   │
    │• Doc Parser (PDF)   │  ────→  │• 4大Agent    │
    │• Rule Validator     │         │• MCP Tools   │
    │• PRD Analyzer       │         │• Skills 库   │
    └─────────────────────┘         └───────┬──────┘
                                            │
                ┌───────────────────────────┼───────────────────────────┐
                │                           │                           │
           ┌────▼─────────┐         ┌──────▼──────┐          ┌─────────▼──┐
           │  输出生成层   │         │ 集成层       │          │ 持久化层   │
           ├──────────────┤         ├─────────────┤          ├───────────┤
           │• 报告生成    │         │• 禅道 API   │          │• 执行记录  │
           │• 图表导出    │  ◄──────┤• 钉钉通知   │          │• 结果存储  │
           │• 邮件分发    │         │• JIRA 对接  │          │• 版本管理  │
           └──────────────┘         └─────────────┘          └────────────┘
```

### 📁 项目结构设计

```
smart-test-agent/
├── core/                           # 核心引擎
│   ├── agent_orchestrator.py       # LangGraph 编排
│   ├── skills_registry.py          # Skills 注册表
│   └── mcp_manager.py              # MCP 管理
│
├── input/                          # 输入处理层 ⭐ 新增
│   ├── api_fetcher.py              # API文档拉取
│   ├── doc_parser.py               # PDF/文档解析
│   ├── url_handler.py              # 线上地址处理
│   └── rule_validator.py           # 规则校验
│
├── agents/                         # 智能体
│   ├── api/                        # API测试Agent
│   ├── perf/                       # 性能测试Agent
│   ├── ui/                         # UI自动化Agent
│   └── testcase/                   # 测试用例Agent
│
├── output/                         # 输出生成层 ⭐ 新增
│   ├── report_generator.py         # 报告生成
│   ├── report_templates/           # 报告模板
│   ├── chart_builder.py            # 图表生成
│   └── exporters.py                # 多格式导出
│
├── integrations/                   # 第三方集成 ⭐ 新增
│   ├── zentao_api.py               # 禅道集成
│   ├── jira_api.py                 # JIRA集成
│   ├── dingtalk_notifier.py        # 钉钉通知
│   └── webhook_sender.py           # 通用Webhook
│
├── persistence/                    # 持久化层 ⭐ 新增
│   ├── execution_logger.py         # 执行日志
│   ├── result_store.py             # 结果存储
│   ├── models.py                   # ORM模型
│   └── database.py                 # 数据库初始化
│
└── config/                         # 配置
    ├── zentao_config.py            # 禅道配置
    ├── app_config.py               # 应用配置
    └── env.example                 # 环境变量示例
```

---

## 🔑 关键模块详设

### 1️⃣ **输入处理层** (Input Layer)

#### URL/接口文档处理

```python
class APIDocumentFetcher:
    """支持多种文档源"""
    
    async def fetch(self, source):
        """
        source 可以是:
        - HTTP URL: https://api.example.com/openapi.json
        - Swagger URL: https://api.example.com/swagger-ui.html
        - 本地文件: /path/to/openapi.yaml
        - 数据库查询: "select openapi from api_specs where id=123"
        """
        
    async def parse_openapi_url(self, url):
        # 下载并解析 OpenAPI 文档
        
    async def parse_swagger_html(self, url):
        # 从 Swagger UI 中提取 spec
        
    async def fetch_from_database(self, query):
        # 从公司数据库获取接口定义
```

#### 规则验证器 (Rule Validator)

```python
class RuleValidator:
    """
    验证测试执行过程中的规则
    """
    
    def validate_contract(self, request, response):
        # 验证契约：请求/响应格式
        
    def validate_sla(self, metrics):
        # 验证 SLA：响应时间、错误率等
        
    def validate_security_rules(self, payload):
        # 验证安全规则：认证、授权、加密等
        
    def validate_business_rules(self, data):
        # 验证业务规则：金额、库存等
```

---

### 2️⃣ **输出生成层** (Output Layer)

#### 测试报告生成

```python
class ReportGenerator:
    """
    生成多格式测试报告
    """
    
    def generate_html_report(self, execution_result):
        """
        输出内容:
        - 执行概览 (总数/通过/失败/跳过)
        - 失败详情 (截图/堆栈/建议修复)
        - 性能数据 (响应时间分布/吞吐量)
        - 覆盖率数据 (端点覆盖/测试用例覆盖)
        - 趋势图表 (历史对比)
        """
        
    def generate_pdf_report(self, execution_result):
        # 正式报告 (用于评审和存档)
        
    def generate_json_report(self, execution_result):
        # 机器可读格式 (用于数据驱动分析)
        
    def generate_excel_report(self, execution_result):
        # 电子表格格式 (用于手工分析)
```

#### 报告模板示例

```html
<!-- 测试执行概览 -->
总计用例数: 150
✅ 通过: 135 (90%)
❌ 失败: 10 (6.7%)
⏭️ 跳过: 5 (3.3%)
平均耗时: 2.3s

<!-- 失败详情 -->
[失败用例详表]
ID | 测试点 | 预期 | 实际 | 根因 | 建议

<!-- 自动生成的Bug -->
🐛 新增 Bug (自动上传到禅道)
BUG-2026-001: API返回400错误
BUG-2026-002: 响应时间超过SLA
```

---

### 3️⃣ **集成层** (Integration Layer)

#### 禅道 API 集成

```python
class ZentaoClient:
    """禅道 Bug 自动记录"""
    
    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.session = requests.Session()
        # 登录禅道
        
    async def create_bug(self, bug_data):
        """
        自动创建 Bug
        
        bug_data:
        {
            "title": "API返回400错误",
            "description": "POST /user 端点返回400而不是201",
            "severity": "high",
            "type": "功能缺陷",
            "steps": [
                "1. 调用 POST /user 接口",
                "2. 传入有效的用户数据",
                "3. 期望: 201 Created",
                "4. 实际: 400 Bad Request"
            ],
            "screenshot": "base64_encoded_image",
            "expected_vs_actual": {
                "expected": {"status": 201, "body": {...}},
                "actual": {"status": 400, "body": {...}}
            },
            "test_case_id": "TC-123",
            "test_run_id": "TR-456",
            "reporter": "TestAgent",
            "assigned_to": "dev_team",
        }
        """
        
        # 调用禅道 API 创建 Bug
        response = await self.session.post(
            f"{self.base_url}/index.php?m=bug&f=create",
            data=bug_data
        )
        return response.json()
    
    async def update_test_case_with_result(self, case_id, result):
        """记录测试用例执行结果"""
        
    async def link_bug_to_test_case(self, bug_id, case_id):
        """关联 Bug 和测试用例"""
```

#### 钉钉通知集成

```python
class DingTalkNotifier:
    """
    实时推送测试结果到钉钉
    """
    
    async def send_test_summary(self, execution_result):
        """
        消息格式:
        
        🤖 智能测试执行结果
        ━━━━━━━━━━━━━━━━━━━━━━
        项目: user-service v2.0
        执行时间: 2026-05-22 14:30:00
        总耗时: 5分32秒
        
        📊 统计
        ✅ 通过: 135 个
        ❌ 失败: 10 个
        🆘 Error: 3 个
        
        🐛 新增 Bug: 5 个 (已上传禅道)
        📄 详细报告: [查看链接]
        """
```

---

### 4️⃣ **持久化层** (Persistence Layer)

#### 执行记录存储

```python
class ExecutionLogger:
    """
    存储每次执行的完整记录
    """
    
    async def log_execution_started(self, task_id, config):
        """
        {
            "task_id": "EXEC-2026-001",
            "agent_type": "api",  # api/perf/ui/testcase
            "input_source": "https://api.example.com/openapi.json",
            "config": {...},
            "started_at": "2026-05-22T14:30:00Z",
            "status": "running"
        }
        """
        
    async def log_test_case(self, task_id, test_case):
        """记录单个测试用例"""
        
    async def log_test_result(self, task_id, test_id, result):
        """
        {
            "task_id": "EXEC-2026-001",
            "test_id": "TEST-123",
            "status": "failed",  # passed/failed/skipped/error
            "duration_ms": 1250,
            "assertion_message": "Expected status 200 but got 400",
            "screenshot": "base64_encoded_image",
            "logs": "...",
            "timestamp": "2026-05-22T14:31:00Z"
        }
        """
        
    async def log_execution_completed(self, task_id, summary):
        """记录执行完成"""
        
    async def create_report_from_logs(self, task_id):
        """从日志生成报告"""
```

#### 数据库模型设计

```python
# models.py

class ExecutionTask(Base):
    """执行任务"""
    __tablename__ = "execution_tasks"
    
    id = Column(Integer, primary_key=True)
    task_id = Column(String, unique=True)  # EXEC-2026-001
    agent_type = Column(String)            # api/perf/ui/testcase
    input_source = Column(String)          # URL或文件路径
    input_content = Column(JSON)           # 原始输入
    status = Column(String)                # running/completed/failed
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    total_duration_ms = Column(Integer)
    
    # 关系
    test_cases = relationship("TestCase")
    test_results = relationship("TestResult")
    report = relationship("TestReport", uselist=False)

class TestResult(Base):
    """单个测试结果"""
    __tablename__ = "test_results"
    
    id = Column(Integer, primary_key=True)
    execution_task_id = Column(String, ForeignKey("execution_tasks.task_id"))
    test_case_id = Column(String)
    status = Column(String)                # passed/failed/skipped/error
    expected_value = Column(JSON)
    actual_value = Column(JSON)
    assertion_message = Column(Text)
    duration_ms = Column(Integer)
    screenshot_data = Column(LargeBinary, nullable=True)
    logs = Column(Text)
    created_at = Column(DateTime)
    
    # 关联的 Bug
    bug_id = Column(String, nullable=True)  # 禅道 BUG-xxx

class TestReport(Base):
    """测试报告"""
    __tablename__ = "test_reports"
    
    id = Column(Integer, primary_key=True)
    execution_task_id = Column(String, ForeignKey("execution_tasks.task_id"))
    report_html = Column(Text)
    report_json = Column(JSON)
    summary_stats = Column(JSON)
    generated_at = Column(DateTime)
    report_url = Column(String)
```

---

## 🔄 完整工作流示例

### 场景：用户上传 OpenAPI 文档进行 API 测试

```
1️⃣ 用户输入阶段
┌──────────────────────────────────┐
│ 输入信息                          │
├──────────────────────────────────┤
│ 📄 API 文档: https://...         │
│ 📋 PRD 文档: xxx_prd.pdf         │
│ 🔐 认证信息: Bearer token=xxx   │
│ 📌 规则约束: {"timeout": 5000}  │
└──────────────────────────────────┘
         ↓
    [ApiDocumentFetcher]
    [RuleValidator]
         ↓

2️⃣ 测试生成和执行阶段
┌──────────────────────────────────┐
│ LangGraph 编排                     │
├──────────────────────────────────┤
│ ① Planner: 分析 Schema            │
│    输出: 测试计划 + 样本数据     │
│                                  │
│ ② Generator: 生成测试脚本         │
│    输出: Playwright/Jest/Postman │
│                                  │
│ ③ MCP Tools: 调用实际 API        │
│    输出: 真实响应 + 性能数据    │
│                                  │
│ ④ Healer: 失败处理和修复          │
│    输出: 修复建议 + 根因分析    │
└──────────────────────────────────┘
         ↓
    [ExecutionLogger] 实时记录

3️⃣ 结果处理阶段
┌──────────────────────────────────┐
│ 多渠道输出                        │
├──────────────────────────────────┤
│ 📊 测试报告生成                    │
│    ├─ HTML: 人类可读             │
│    ├─ PDF: 正式存档              │
│    ├─ JSON: 数据驱动             │
│    └─ Excel: 手工分析            │
│                                  │
│ 🐛 Bug 自动记录                   │
│    ├─ 失败用例 → 禅道            │
│    ├─ 性能问题 → 禅道            │
│    └─ 错误堆栈 → 禅道            │
│                                  │
│ 📢 结果通知                       │
│    ├─ 钉钉群                     │
│    ├─ 邮件                       │
│    └─ WebHook                    │
│                                  │
│ 💾 持久化存储                     │
│    ├─ 执行日志                   │
│    ├─ 测试结果                   │
│    ├─ 报告文件                   │
│    └─ Bug 链接                   │
└──────────────────────────────────┘
```

---

## 🚀 实现优先级

### Phase 1: 核心功能 (1-2周)
- [x] 架构框架搭建
- [x] API 测试 Agent 完善
- [ ] **输入处理** (API Fetcher, Rule Validator) ⭐
- [ ] **报告生成** (HTML 报告模板) ⭐
- [ ] **数据持久化** (执行日志) ⭐

### Phase 2: 第三方集成 (1-2周)
- [ ] **禅道 API** 集成 (Bug 自动创建) ⭐
- [ ] 钉钉通知集成
- [ ] 基础 Web UI (报告查看)

### Phase 3: 高级特性 (2-3周)
- [ ] 测试历史对比
- [ ] 性能基线管理
- [ ] 分布式执行
- [ ] 高级图表和分析

### Phase 4: 运维和优化 (持续)
- [ ] 监控和告警
- [ ] 日志聚合
- [ ] 成本优化

---

## 💻 快速启动代码框架

### 核心编排框架

```python
# main.py

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph
from pydantic import BaseModel, Field
from typing import Dict, Any, List

# 1️⃣ 定义状态
class TestExecutionState(BaseModel):
    """测试执行的全局状态"""
    
    # 输入
    input_source: str
    api_doc: Dict[str, Any]
    rules: Dict[str, Any]
    
    # 中间
    test_plan: List[Dict]
    generated_code: str
    
    # 输出
    test_results: List[Dict]
    bugs: List[Dict]
    report: Dict
    
    # 元信息
    task_id: str
    execution_log: List[str]


# 2️⃣ 定义节点

async def fetch_input(state: TestExecutionState):
    """获取输入文档"""
    fetcher = APIDocumentFetcher()
    api_doc = await fetcher.fetch(state.input_source)
    return {"api_doc": api_doc}


async def validate_rules(state: TestExecutionState):
    """验证规则"""
    validator = RuleValidator()
    validated = await validator.validate_all(state.rules)
    return {"rules_validated": validated}


async def run_planner(state: TestExecutionState):
    """运行 Planner Agent"""
    agent = APITestPlannerAgent()
    plan = await agent.plan(state.api_doc, state.rules)
    return {"test_plan": plan}


async def run_generator(state: TestExecutionState):
    """运行 Generator Agent"""
    agent = APITestGeneratorAgent()
    code = await agent.generate(state.test_plan)
    return {"generated_code": code}


async def run_tests(state: TestExecutionState):
    """执行测试"""
    executor = TestExecutor()
    results = await executor.execute(state.generated_code)
    return {"test_results": results}


async def run_healer(state: TestExecutionState):
    """运行 Healer Agent（修复失败）"""
    agent = APITestHealerAgent()
    healed_results = await agent.heal(
        state.test_results, 
        state.generated_code
    )
    return {"test_results": healed_results}


async def create_bugs(state: TestExecutionState):
    """在禅道中创建 Bug"""
    zentao = ZentaoClient()
    bugs = []
    for result in state.test_results:
        if result['status'] == 'failed':
            bug = await zentao.create_bug({
                'title': f"API 测试失败: {result['test_id']}",
                'description': result['error_message'],
                'severity': 'high',
                'test_run_id': state.task_id,
            })
            bugs.append(bug)
    return {"bugs": bugs}


async def generate_report(state: TestExecutionState):
    """生成测试报告"""
    reporter = ReportGenerator()
    report = reporter.generate_html_report({
        'test_results': state.test_results,
        'bugs': state.bugs,
        'task_id': state.task_id,
    })
    
    # 保存执行日志和报告
    logger = ExecutionLogger()
    await logger.log_execution_completed(state.task_id, {
        'test_results': state.test_results,
        'bugs': state.bugs,
        'report': report,
    })
    
    return {"report": report}


# 3️⃣ 构建图

def create_test_workflow():
    """构建测试工作流"""
    
    workflow = StateGraph(TestExecutionState)
    
    # 添加节点
    workflow.add_node("fetch_input", fetch_input)
    workflow.add_node("validate_rules", validate_rules)
    workflow.add_node("run_planner", run_planner)
    workflow.add_node("run_generator", run_generator)
    workflow.add_node("run_tests", run_tests)
    workflow.add_node("run_healer", run_healer)
    workflow.add_node("create_bugs", create_bugs)
    workflow.add_node("generate_report", generate_report)
    
    # 定义边（流程）
    workflow.add_edge("START", "fetch_input")
    workflow.add_edge("fetch_input", "validate_rules")
    workflow.add_edge("validate_rules", "run_planner")
    workflow.add_edge("run_planner", "run_generator")
    workflow.add_edge("run_generator", "run_tests")
    
    # 条件边：如果有失败，运行 Healer
    def should_heal(state):
        return any(r['status'] == 'failed' for r in state.test_results)
    
    workflow.add_conditional_edges(
        "run_tests",
        should_heal,
        {
            True: "run_healer",
            False: "create_bugs"
        }
    )
    
    workflow.add_edge("run_healer", "create_bugs")
    workflow.add_edge("create_bugs", "generate_report")
    workflow.add_edge("generate_report", "END")
    
    return workflow.compile()


# 4️⃣ 执行测试

async def main():
    workflow = create_test_workflow()
    
    initial_state = TestExecutionState(
        task_id="EXEC-2026-001",
        input_source="https://api.example.com/openapi.json",
        api_doc={},
        rules={"timeout": 5000, "sla": 0.99},
        test_plan=[],
        generated_code="",
        test_results=[],
        bugs=[],
        report={},
        execution_log=[]
    )
    
    result = await workflow.ainvoke(initial_state)
    
    print(f"✅ 测试执行完成!")
    print(f"📊 报告: {result['report']['url']}")
    print(f"🐛 发现Bug: {len(result['bugs'])} 个")
    print(f"📌 禅道链接: {[b['url'] for b in result['bugs']]}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

---

## 📋 禅道 API 集成详例

```python
# integrations/zentao_api.py

import httpx
from typing import Dict, Any

class ZentaoClient:
    """禅道客户端"""
    
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.session = httpx.AsyncClient()
        self.token = None
        
    async def login(self):
        """登录禅道"""
        response = await self.session.post(
            f"{self.base_url}/index.php?m=user&f=login",
            data={
                "account": self.username,
                "password": self.password,
            }
        )
        self.token = response.json().get("token")
        
    async def create_bug(self, bug_data: Dict[str, Any]) -> Dict:
        """创建Bug"""
        
        bug_payload = {
            "product": bug_data.get("product_id", 1),
            "module": bug_data.get("module_id", 1),
            "title": bug_data["title"],
            "description": bug_data["description"],
            "severity": bug_data.get("severity", "3"),  # 3=一般, 2=严重, 1=致命
            "type": bug_data.get("type", "功能缺陷"),
            "assigned_to": bug_data.get("assigned_to", ""),
            "found_build": bug_data.get("found_build", ""),
            "steps": bug_data.get("steps", ""),
            "expected": bug_data.get("expected", ""),
            "actual": bug_data.get("actual", ""),
        }
        
        # 附加信息
        if "test_case_id" in bug_data:
            bug_payload["case_id"] = bug_data["test_case_id"]
            
        if "screenshot_url" in bug_data:
            bug_payload["screenshot"] = bug_data["screenshot_url"]
        
        response = await self.session.post(
            f"{self.base_url}/index.php?m=bug&f=create",
            data=bug_payload,
            headers={"Authorization": f"Bearer {self.token}"}
        )
        
        result = response.json()
        return {
            "bug_id": result.get("id"),
            "bug_url": f"{self.base_url}/index.php?m=bug&f=view&bugID={result.get('id')}",
            "success": result.get("success", False)
        }
    
    async def link_bug_to_test_case(self, bug_id: str, case_id: str):
        """关联Bug和测试用例"""
        
        response = await self.session.post(
            f"{self.base_url}/index.php?m=testcase&f=linkBug",
            data={
                "case_id": case_id,
                "bug_id": bug_id,
            },
            headers={"Authorization": f"Bearer {self.token}"}
        )
        return response.json()
    
    async def update_test_case_result(self, case_id: str, run_id: str, result: str):
        """更新测试用例执行结果"""
        
        response = await self.session.post(
            f"{self.base_url}/index.php?m=testcase&f=recordResult",
            data={
                "case_id": case_id,
                "run_id": run_id,
                "result": result,  # pass/fail/skip/block
                "notes": "自动化测试执行结果",
            },
            headers={"Authorization": f"Bearer {self.token}"}
        )
        return response.json()


# 使用示例
async def handle_failed_test(test_result: Dict):
    """处理失败的测试"""
    
    zentao = ZentaoClient(
        base_url="https://zentao.example.com",
        username="admin",
        password="admin123"
    )
    
    await zentao.login()
    
    # 1. 创建Bug
    bug = await zentao.create_bug({
        "product_id": 1,
        "module_id": 1,
        "title": f"API测试失败: {test_result['endpoint']}",
        "description": test_result['error_message'],
        "severity": "2",  # 严重
        "type": "功能缺陷",
        "assigned_to": "developer@example.com",
        "steps": f"1. 调用端点: {test_result['endpoint']}\n2. 传入数据: {test_result['request_body']}",
        "expected": f"响应状态: {test_result['expected_status']}\n响应体: {test_result['expected_body']}",
        "actual": f"响应状态: {test_result['actual_status']}\n响应体: {test_result['actual_body']}",
        "screenshot_url": test_result.get('screenshot_url'),
        "test_case_id": test_result['test_case_id'],
    })
    
    print(f"✅ Bug已创建: {bug['bug_url']}")
    
    # 2. 关联到测试用例
    await zentao.link_bug_to_test_case(bug['bug_id'], test_result['test_case_id'])
    
    # 3. 记录测试结果
    await zentao.update_test_case_result(
        case_id=test_result['test_case_id'],
        run_id=test_result['run_id'],
        result='fail'
    )
```

---

## 🎯 总结建议

### ✅ 架构评分：8/10

**优点**:
- 整体设计成熟，三层分离清晰
- 模块化和可扩展性强
- 自动修复和故障诊断能力优秀

**改进方向**:
1. **增加持久化层** - 执行记录和报告存储
2. **实现第三方集成** - 禅道/JIRA/钉钉
3. **完善报告生成** - 多格式输出和可视化
4. **补全输入处理** - 支持更多文档类型
5. **添加监控告警** - 执行状态追踪

### 🚀 建议方案

**不重新设计，在现有架构上扩展**：
- 保留现有的 Agent + MCP + Skills 三层架构
- 新增 4 个关键模块（见上文项目结构）
- 重点开发禅道集成和持久化层
- 采用分阶段实现策略

**预期工作量**: 
- Phase 1 (核心): 2-3周
- Phase 2 (集成): 2-3周
- Phase 3+ (优化): 持续迭代

---

**下一步**: 您想深入其中哪个模块的设计？禅道集成、报告生成、还是执行日志系统？
