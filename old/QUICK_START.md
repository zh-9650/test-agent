# 📋 企业测试智能体快速参考

> **项目**: 基于 Agent+MCP+Skills 的企业智能体测试平台
> **输入**: OpenAPI/Swagger/GraphQL/PRD/线上地址  
> **输出**: 测试报告 + Bug记录(禅道) + 执行记录  
> **状态**: ✅ 完整方案设计

---

## 📂 文档导航

| 文档 | 内容 | 用途 |
|------|------|------|
| **ARCHITECTURE.md** | 原始框架架构分析 | 📖 理解整体设计 |
| **CUSTOMIZATION_PLAN.md** | 企业定制化方案 | 🛠️ 实现路线图 |
| **ZENTAO_INTEGRATION.md** | 禅道集成详解 | 🔗 Bug自动上报 |
| **本文档** | 快速参考指南 | ⚡ 快速上手 |

---

## 🎯 架构评分

| 维度 | 评分 | 说明 |
|------|------|------|
| **成熟度** | 9/10 | 三层分离清晰，模块化设计优秀 |
| **功能** | 8.5/10 | 缺少第三方系统集成和执行记录 |
| **生产就绪** | 7/10 | 需补完 DB/报告/集成层 |
| **总体** | **8/10** | ✅ 强烈推荐，需定制化补完 |

---

## 🚀 三阶段实现计划

### Phase 1: 核心功能 (2-3周)

```
✓ 保留原架构 (Agent+MCP+Skills)
✓ 新增输入处理 (API Fetcher, Rule Validator)
✓ 新增报告生成 (HTML/PDF/JSON/Excel)
✓ 新增数据持久化 (执行日志系统)
```

### Phase 2: 禅道集成 (2-3周)

```
✓ ZentaoBugReporter 实现
✓ 自动 Bug 创建流程
✓ 测试用例关联
✓ 钉钉通知集成
```

### Phase 3: 高级特性 (2-3周)

```
✓ 测试历史对比
✓ 性能基线管理
✓ Web UI 仪表板
✓ 分布式执行支持
```

---

## 📊 核心模块清单

### 输入处理层 (Input Layer)

```python
✓ APIDocumentFetcher    # 支持 URL/文件/数据库
✓ RuleValidator         # 契约/SLA/安全规则验证
✓ DocParser             # PDF/Markdown 解析
✓ URLHandler            # 线上地址处理
```

### 输出生成层 (Output Layer)

```python
✓ ReportGenerator       # HTML/PDF/JSON/Excel 报告
✓ ChartBuilder          # 图表生成
✓ EmailNotifier         # 邮件通知
✓ WebhookSender         # 第三方系统推送
```

### 集成层 (Integration Layer)

```python
✓ ZentaoClient          # 禅道 API 集成 ⭐
✓ JiraClient            # JIRA 集成 (可选)
✓ DingTalkNotifier      # 钉钉推送 ⭐
✓ WebhookSender         # 通用 Webhook
```

### 持久化层 (Persistence Layer)

```python
✓ ExecutionLogger       # 执行日志记录
✓ ResultStore           # 测试结果存储
✓ ReportStore           # 报告存储
✓ BugTracker            # Bug 关联追踪
```

---

## 💻 快速启动

### 1. 项目结构

```bash
smart-test-agent/
├── core/                    # LangGraph + Skills
├── input/                   # ⭐ 新增: 输入处理
├── agents/                  # API/Perf/UI/Testcase
├── output/                  # ⭐ 新增: 报告生成
├── integrations/            # ⭐ 新增: 第三方集成
├── persistence/             # ⭐ 新增: 数据存储
├── config/                  # 配置管理
├── tests/                   # 测试套件
└── docker/                  # Docker支持
```

### 2. 环境配置

```bash
# .env
ZENTAO_URL=http://127.0.0.1:8080
ZENTAO_USERNAME=admin
ZENTAO_PASSWORD=admin123

DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx

DATABASE_URL=postgresql://user:password@localhost/smart_test

DEEPSEEK_API_KEY=xxx
```

### 3. 安装依赖

```bash
pip install -r requirements.txt

# 关键包
pip install fastapi uvicorn sqlalchemy httpx langchain langgraph pydantic pdfplumber
```

### 4. 初始化数据库

```bash
# 创建表
python -m alembic upgrade head

# 或者
python database/init.py
```

### 5. 启动服务

```bash
python main.py

# 或使用 Docker
docker-compose up -d
```

---

## 🔄 典型工作流

### 场景：用户上传 OpenAPI，自动测试并报告 Bug

```
1️⃣ 用户输入
   └─ 上传 OpenAPI 或提供 URL
   └─ 可选: 上传 PRD 文档
   └─ 可选: 定义规则约束

2️⃣ 输入处理
   └─ [APIFetcher] 下载/解析文档
   └─ [RuleValidator] 验证规则
   └─ [Parser] 提取测试信息

3️⃣ 测试执行
   └─ [Planner] 生成测试计划
   └─ [Generator] 生成测试代码
   └─ [MCP Tools] 执行真实 API
   └─ [Healer] 自动修复失败

4️⃣ 结果处理
   ├─ [ExecutionLogger] 记录每个测试结果
   ├─ [BugReporter] 失败案例创建禅道 Bug
   ├─ [ReportGenerator] 生成 HTML/PDF 报告
   └─ [Notifier] 推送钉钉/邮件通知

5️⃣ 输出
   ├─ 📊 测试报告 (可访问的 URL)
   ├─ 🐛 禅道链接 (已创建的 Bug)
   ├─ 📝 执行记录 (完整日志)
   └─ 📈 性能数据 (历史对比)
```

---

## 🐛 禅道集成代码片段

### 创建 Bug 最小示例

```python
from integrations.zentao_api import ZentaoBugReporter, BugModel

# 初始化
reporter = ZentaoBugReporter(
    zentao_url="http://127.0.0.1:8080",
    username="admin",
    password="admin123"
)

# 登录
await reporter.login()

# 创建 Bug
bug = BugModel(
    title="POST /user 返回400而不是201",
    description="创建用户时的状态码错误",
    severity="2",
    steps="1. 调用 POST /user\n2. 传入有效数据",
    expected="返回 201 Created",
    actual="返回 400 Bad Request",
    test_run_id="RUN-2026-001",
    assigned_to="developer@example.com"
)

result = await reporter.create_bug(bug)
print(f"✅ Bug 创建成功: {result['bug_url']}")
```

---

## 📝 执行记录查询

### 查看执行历史

```python
from persistence.execution_logger import ExecutionLogger

logger = ExecutionLogger(session)

# 获取最近10次执行
tasks = await logger.get_execution_history(agent_type="api", limit=10)

for task in tasks:
    print(f"{task.task_id}: {task.status} ({task.total_tests} 个测试)")
```

### 生成数据报告

```python
# 过去7天的成功率
analytics = TestAnalytics(session)
success_rates = await analytics.get_test_success_rate_by_day(days=7)

# 最常失败的端点
failing_endpoints = await analytics.get_top_failing_endpoints(limit=10)

# Bug 统计
bug_stats = await analytics.get_bug_statistics()
```

---

## 🔧 常见集成点

### 集成 1: 从禅道拉取测试用例

```python
class ZentaoTestCaseImporter:
    async def import_test_cases(self, project_id):
        """从禅道导入测试用例作为智能体输入"""
        # 调用禅道 API
        # 转换为统一格式
        # 提交给测试 Agent
```

### 集成 2: 钉钉实时通知

```python
class DingTalkReporter:
    async def send_summary(self, task_id):
        """执行完成后推送钉钉"""
        # 查询数据库获取结果摘要
        # 生成 Markdown 卡片
        # 推送钉钉群
```

### 集成 3: Jenkins 流水线

```bash
# Jenkinsfile
pipeline {
    stages {
        stage('测试') {
            steps {
                sh 'python -m pytest api_tests/'
                sh 'python api.py execute --input https://api.example.com'
            }
        }
        stage('报告') {
            steps {
                publishHTML([
                    reportDir: 'reports',
                    reportFiles: 'index.html',
                    reportName: '测试报告'
                ])
            }
        }
    }
}
```

---

## 📊 数据库 Schema 核心表

### 执行任务表

```sql
CREATE TABLE execution_tasks (
    task_id VARCHAR(50) PRIMARY KEY,
    agent_type VARCHAR(20),
    status VARCHAR(20),
    total_tests INT,
    passed_tests INT,
    failed_tests INT,
    error_rate DECIMAL(5,2),
    started_at DATETIME,
    completed_at DATETIME
);
```

### 测试结果表

```sql
CREATE TABLE test_results (
    id INT PRIMARY KEY AUTO_INCREMENT,
    task_id VARCHAR(50),
    test_id VARCHAR(100),
    status VARCHAR(20),
    endpoint VARCHAR(255),
    response_status INT,
    error_message TEXT,
    bug_id VARCHAR(50),
    FOREIGN KEY (task_id) REFERENCES execution_tasks(task_id)
);
```

---

## 📈 性能指标

### 预期性能

| 指标 | 预期值 |
|------|--------|
| 单个 API 测试执行时间 | < 2s |
| 报告生成时间 | < 5s |
| 禅道 Bug 创建时间 | < 1s |
| 钉钉通知时间 | < 2s |
| 数据库查询 (100万条记录) | < 500ms |

---

## ⚠️ 风险与应对

| 风险 | 影响 | 应对方案 |
|------|------|--------|
| 禅道 API 超时 | ⭐⭐⭐ | 重试机制 + 异步队列 |
| 大量 Bug 创建 | ⭐⭐⭐ | 去重 + 批量提交 |
| 数据库瓶颈 | ⭐⭐ | 分表 + 异步写入 |
| LLM 成本高 | ⭐⭐ | 缓存 + 采样执行 |

---

## 🎓 学习资源

### 推荐阅读

1. **原架构文档**: `ARCHITECTURE.md`
   - 了解 Agent + MCP + Skills 设计

2. **定制化方案**: `CUSTOMIZATION_PLAN.md`
   - 完整的模块设计和实现路线图

3. **禅道集成**: `ZENTAO_INTEGRATION.md`
   - 禅道 API 详解和完整代码示例

### 相关链接

- [LangGraph 官方文档](https://python.langchain.com/docs/langgraph)
- [MCP 协议规范](https://modelcontextprotocol.io/)
- [禅道 API 文档](https://www.zentao.net/book/zentaopms.html)
- [Playwright 文档](https://playwright.dev/)

---

## ✅ 检查清单

### 开发准备

- [ ] 理解原架构 (ARCHITECTURE.md)
- [ ] 审视定制方案 (CUSTOMIZATION_PLAN.md)
- [ ] 配置禅道账户和 Token
- [ ] 准备数据库 (PostgreSQL 或 MySQL)
- [ ] 申请 DeepSeek API Key

### Phase 1 实现

- [ ] 搭建项目框架
- [ ] 实现 APIFetcher 和 RuleValidator
- [ ] 实现 ReportGenerator
- [ ] 实现 ExecutionLogger
- [ ] 编写单元测试

### Phase 2 集成

- [ ] 实现 ZentaoBugReporter
- [ ] 集成钉钉通知
- [ ] 联调禅道 API
- [ ] 测试完整流程

### Phase 3 优化

- [ ] 性能优化
- [ ] 监控告警
- [ ] 文档完善
- [ ] 上线部署

---

## 🚀 下一步

1. **立即开始**: 克隆项目，运行 Phase 1 核心模块
2. **测试驱动**: 为 Fetcher → Logger → Reporter 编写测试
3. **逐步集成**: 联调禅道，验证 Bug 创建流程
4. **上线运维**: 监控、日志、告警体系建设

---

**祝您开发顺利！** 🎉  
有问题可参考详细文档或查看代码注释。
