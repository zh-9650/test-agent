# 🏗️ 智能测试平台 - 整体架构设计

> **关键数据**: 相比传统测试模式，效果至少提升 40%+

---

## 📋 系统架构全景图

```
                          用户端/入口
                         (用户输入)
                             ↓
                    ┌─────────────────┐
                    │ LangGraph 导控 │
                    │ LangGraph Agent │
                    └────────┬────────┘
                             ↓
        ┌────────────────────────────────────────┐
        │         多智能体协调层                   │
    ────┴────────────┬─────────────────┬──────────┴────
    │               │                 │               │
    ▼               ▼                 ▼               ▼
┌──────────┐  ┌────────────┐  ┌──────────────┐  ┌──────────┐
│LLM模型   │  │文件系统    │  │技能库        │  │动态Prompt│
│(DeepSeek)│  │(VirtualFS) │  │(SkillsMgmt)  │  │(Templating)
└──────────┘  └────────────┘  └──────────────┘  └──────────┘
```

---

## 🎯 核心设计原则（三柱架构）

### 1️⃣ **技能化架构 (Skills-Based Architecture)**

每个智能体由多个可复用技能组成：

```
api/
├── agent_skills/
│   ├── skills/
│   │   ├── planner/          # 测试规划技能
│   │   │   └── SKILL.md
│   │   ├── generator/        # 代码生成技能
│   │   │   └── SKILL.md
│   │   └── healer/           # 测试修复技能
│   │       └── SKILL.md
```

**优势**:
- 模块化、可复用
- 技能独立迭代
- 降低耦合度

---

### 2️⃣ **MCP 协议集成 (Model Context Protocol)**

使用 MCP 实现工具与智能体的标准化通信：

```javascript
// MCP 客户端配置
client = MultiServerMCPClient({
  "ui": {
    "transport": "stdio",
    "command": "npx",
    "args": ["playwright"]
  },
  "perf": {
    "transport": "stdio",
    "command": "node",
    "args": ["./artillery-mcp-server.js"]
  }
})
```

**支持的 MCP 服务**:
- Playwright MCP Server (UI自动化)
- Artillery MCP Server (性能测试)
- TypeScript (代码工具)
- npm/yarn (依赖管理)

---

### 3️⃣ **虚拟文件系统后端 (VirtualFS)**

使用 FilesystemBackend 实现工作空间隔离：

```python
workspace_backend = FilesystemBackend(
    root_dir=workspace_root,
    virtual_mode=True  # 虚拟模式，直接操作文件体系
)
```

**功能**:
- 隔离工作空间
- 模拟真实文件系统
- 支持动态读写

---

## 🤖 四大核心智能体

### 1. **API 测试智能体** (backend/app/agents/api/agent.py)

**工作流**:

```
OpenAPI/Swagger/GraphQL SDL
        ↓
    [Planner] 测试规划
        ├→ Schema 分析
        ├→ 覆盖设计
        └→ 样本数据生成
        ↓
    [Generator] 代码生成
        ├→ Playwright脚本
        ├→ Jest测试套件
        └→ Postman Collection
        ↓
    [Healer] 测试修复
        ├→ 自动诊断
        ├→ 5种修复策略
        └→ 智能回退
```

**三大核心技能**:

**Planner - API 测试规划**
- 输入: OpenAPI 3.0 / Swagger 2.0 / GraphQL SDL / 本地文件路径或程序 URL
- 输出:
  - 功能测试场景
  - 安全测试场景
  - 边界测试场景
  - 真实测试样本数据
  - 可选的端点验证结果

**Generator - 代码生成**
- 功能: 从 Schema 自动生成完整测试代码
- 生成内容:
  - Playwright UI 测试脚本
  - Jest 单元测试
  - Postman 集合

**Healer - 测试修复**
- 功能: 智能诊断并修复失败的测试
- 修复策略:
  - 自动诊断故障原因
  - 5种预定义修复策略
  - 智能降级回退

---

### 2. **性能测试智能体**

```
Artillery 配置 → [性能分析] → [报告生成]
                     ↓
                性能基线管理
```

- 支持框架: **Artillery.io**
- 测试维度: 吞吐量、延迟、错误率、P95/P99

---

### 3. **UI 自动化智能体**

```
页面/场景描述 → [元素定位] → [交互执行] → [验证]
                     ↓
                Playwright API
```

- 支持框架: **Playwright**
- 功能: 元素定位、交互执行、断言验证

---

### 4. **测试用例生成智能体**

```
需求文档 → [需求分析] → [用例设计] → [CSV导出]
              ↓
            脑图分析
```

- 输入: PRD、原型、API文档
- 输出: 11列 CSV 自动化用例
- 支持入库: test-automation-workflow

---

## 🔄 Schema 类型识别与转换

```
Schema 输入
   ↓
[Schema 类型判别]
   ├→ OpenAPI (左侧路径)
   │   └→ 解析端点
   │
   └→ GraphQL SDL (右侧路径)
       └→ SDL → Introspection 转换
           └→ 生成 schema.json
               ↓
       [智能样本数据生成]
```

**关键能力**:
- 50+ 字段模式匹配
- 上下文感知数据生成
- 端点自动验证
- 真实 API 调用测试

---

## 📊 API 测试流程 (详细版)

```
                    [50+ 字段模式匹配]
                           ↓
                  [上下文感知数据]
                    firstName: John
                    email: john.doe@example.com
                           ↓
                  [可选: 端点验证]
                           ↓
                    [真实 API 调用]
                           ↓
                    [验证报告]
                   ✅ 成功 / ❌ 失败
                           ↓
                    [测试计划输出]
```

---

## 🛠️ 技术栈详细清单

### 后端技术栈
| 分类 | 技术/框架 | 版本 | 用途 |
|------|---------|------|------|
| Web 框架 | FastAPI | ≥0.109.0 | 高性能异步 Web 框架 |
| Web 框架 | Uvicorn | ≥0.27.0 | ASGI 服务器 |
| 数据验证 | Pydantic | ≥2.5.0 | 数据模型和验证 |
| 数据库 | AsyncPG | ≥0.29.0 | PostgreSQL 异步驱动 |
| 数据库 | Motor | ≥3.3.0 | MongoDB 异步驱动 |
| AI框架 | LangChain | Latest | LLM 应用框架 |
| 图框架 | LangGraph | Latest | 智能体编排 |
| LLM 模型 | DeepSeek | deepseek | 核心推理引擎 |
| MCP 协议 | mcp-adapters | Latest | Model Context Protocol |
| 文件系统 | FilesystemBackend | Custom | 虚拟文件系统 |
| 测试框架 | Playwright | Latest | UI/API 自动化 |
| 性能测试 | Artillery.io | Latest | 性能测试 |
| 测试框架 | Jest | Latest | JavaScript 测试 |
| PDF 解析 | PyPDF2 | ≥3.0.0 | PDF 需求文档解析 |
| HTTP 客户端 | HTTPX | ≥0.26.0 | 异步 HTTP 请求 |

### 前端/Node.js 技术栈
```
Node.js 生态
├── 测试框架
│   ├─ Playwright (UI/API自动化)
│   ├─ Jest (单元/集成测试)
│   └─ Artillery.io (性能测试)
├── MCP 服务端
│   ├─ Playwright MCP Server
│   ├─ Artillery MCP Server
│   └─ TypeScript (工具集成)
└── 辅助工具
    ├─ npm/yarn (包管理)
    └─ TypeScript (类型安全)
```

---

## 🔌 MCP 生态拓展

### 已集成的 MCP 服务

1. **Playwright MCP Server**
   - 功能: 浏览器自动化
   - 调用: `playwright.click()`, `playwright.navigate()` 等

2. **Artillery MCP Server**
   - 功能: 性能测试执行和分析
   - 调用: `artillery.run()`, `artillery.report()` 等

3. **TypeScript/Node.js Tools**
   - 功能: 代码执行和工具调用
   - 支持: 脚本编译、执行、依赖管理

---

## 📦 四大关键特性

### ✨ 1. 全栈覆盖
- API 测试 (功能/安全/边界)
- UI 自动化 (Playwright)
- 性能测试 (Artillery)
- 用例生成 (AI驱动)

### 🧠 2. 智能化
- Schema 自动理解
- 50+ 字段模式识别
- 上下文感知测试数据
- 自动修复失败用例

### 🔧 3. 可扩展
- 技能化架构 (Skills 插件)
- MCP 标准化接口
- 虚拟文件系统隔离
- 支持自定义 Agent

### 📊 4. 可观测
- 详细的测试报告
- 性能基线管理
- 失败诊断和修复日志
- 完整的审计跟踪

---

## 💡 架构亮点

### 🎯 1. **智能体的模块化设计**
- 每个智能体 = 多个 Skills
- Planner → Generator → Healer 的三阶段流程
- 独立开发、独立测试、独立部署

### 🔐 2. **MCP 标准化通信**
- 与工具的通信协议统一
- 低耦合、易扩展
- 支持多种工具集成

### 📁 3. **虚拟文件系统的工作空间隔离**
- 每个任务的工作空间独立
- 避免文件冲突
- 支持并发执行

### 🤝 4. **LangGraph 的智能体编排**
- 多智能体协作
- 自动状态管理
- 高效的执行流程

---

## 🚀 典型使用流程

```
1️⃣ 用户输入 API 文档 (OpenAPI/Swagger/GraphQL)
   ↓
2️⃣ API 测试智能体接管
   ├→ Planner: 分析 Schema → 生成测试计划
   ├→ Generator: 生成 Playwright/Jest/Postman 脚本
   └→ Healer: 执行测试，自动修复失败用例
   ↓
3️⃣ 输出完整的测试套件和报告
   ├→ 测试脚本 (.js/.ts)
   ├→ 测试报告 (HTML/JSON)
   ├→ 性能数据 (if性能测试)
   └→ 修复日志 (if失败修复)
```

---

## 📚 相关文件位置

| 组件 | 位置 | 说明 |
|------|------|------|
| API Agent | `backend/app/agents/api/agent.py` | 主智能体入口 |
| Skills | `backend/app/agents/api/agent_skills/skills/` | 技能实现 |
| Planner | `...skills/planner/SKILL.md` | 规划技能文档 |
| Generator | `...skills/generator/SKILL.md` | 生成技能文档 |
| Healer | `...skills/healer/SKILL.md` | 修复技能文档 |
| MCP Config | 工作空间根目录 | MCP 服务配置 |

---

## 🎓 学习路径建议

1. **理解核心概念**
   - [ ] Agent + MCP + Skills 三层架构
   - [ ] 四大智能体的职责划分
   - [ ] Schema 类型识别流程

2. **深入关键模块**
   - [ ] Planner 的测试规划逻辑
   - [ ] Generator 的代码生成策略
   - [ ] Healer 的故障诊断和修复

3. **动手实践**
   - [ ] 用 API 文档创建第一个测试计划
   - [ ] 生成并运行自动化测试脚本
   - [ ] 观察 Healer 的自动修复过程

4. **高级拓展**
   - [ ] 实现自定义 Skill
   - [ ] 扩展 MCP 工具集
   - [ ] 构建多智能体协作流程

---

**最后更新**: 2026年1月16日 | **版本**: v2.0 | **来源**: 但回智能技术
