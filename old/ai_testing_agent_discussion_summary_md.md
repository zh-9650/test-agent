# AI 测试智能体平台讨论整理

# 一、项目定位

本项目目标是构建一个：

```text
AI Native Testing Platform（AI 原生测试平台）
```

而不是传统的：

```text
自动化测试平台 + AI
```

核心思想：

```text
Agent负责理解与决策
Skill负责执行能力
Runtime负责状态与流程
```

系统最终能够实现：

```text
输入：
- 网站地址
- Swagger/OpenAPI
- PRD文档
- 测试规则
- 测试账号
- 业务说明

输出：
- UI测试结果
- API测试结果
- 探索式测试结果
- 执行日志
- 截图
- 测试报告
- AI分析总结
```

---

# 二、核心设计理念

# 1. Agent 不是脚本生成器

本系统不是：

```text
AI 自动生成 Playwright 脚本
```

而是：

```text
AI 自主完成测试任务
```

区别：

传统自动化：

```text
脚本驱动
```

AI 测试智能体：

```text
目标驱动
任务驱动
状态驱动
```

---

# 2. Agent 不直接操作底层工具

LLM 不应该直接生成：

```python
page.locator().click()
```

而应该输出：

```json
{
  "action": "click",
  "target": "登录按钮"
}
```

真正执行由 Skill 完成。

---

# 3. 页面需要“语义层”

禁止直接将完整 DOM 输入 LLM。

正确做法：

```json
{
  "page_type": "login",
  "buttons": ["登录"],
  "inputs": ["用户名", "密码"]
}
```

这样可以：

```text
降低Token消耗
提高稳定性
减少上下文污染
```

---

# 三、系统总体架构

```text
┌──────────────────────┐
│      Frontend        │
│ React + Ant Design   │
└──────────────────────┘
           ↓
┌──────────────────────┐
│      FastAPI         │
└──────────────────────┘
           ↓
┌──────────────────────┐
│    Agent Runtime     │
│      LangGraph       │
└──────────────────────┘
           ↓
┌──────────────────────┐
│       Agents         │
│ Planner / UI / API   │
└──────────────────────┘
           ↓
┌──────────────────────┐
│       Skills         │
└──────────────────────┘
           ↓
┌──────────────────────┐
│       Tools          │
│ Playwright / HTTPX   │
└──────────────────────┘
```

---

# 四、技术栈

# 前端

```text
React
Ant Design
Zustand
Axios
WebSocket
```

---

# 后端

```text
Python
FastAPI
LangChain
LangGraph
```

---

# UI 自动化

```text
Playwright
```

原因：

```text
自动等待
Trace支持好
适合AI场景
DOM能力强
```

---

# API 自动化

```text
HTTPX
Pytest
```

---

# 数据库

推荐：

```text
PostgreSQL
```

可选：

```text
MySQL
```

后期支持：

```text
pgvector
```

---

# 缓存与队列

```text
Redis
Celery
```

---

# 五、Agent Runtime 设计

# Runtime 核心职责

```text
状态管理
任务管理
上下文管理
Skill调度
Agent调度
错误恢复
```

---

# Runtime State

```python
class RuntimeState:
    task_id: str
    current_page: str
    current_step: int
    screenshots: list
    logs: list
    observations: list
    action_history: list
    testcases: list
    assertion_results: list
    errors: list
```

---

# Runtime 执行流程

```text
INIT
↓
LOAD_CONTEXT
↓
OBSERVE_PAGE
↓
ANALYZE_PAGE
↓
PLAN_ACTION
↓
RULE_CHECK
↓
EXECUTE_ACTION
↓
OBSERVE_RESULT
↓
ASSERT_RESULT
↓
GENERATE_REPORT
↓
FINISH
```

---

# 六、Agent 设计

# 1. Planner Agent

职责：

```text
理解测试目标
拆分任务
规划执行链路
调度其他Agent
```

---

# 2. UI Testing Agent

职责：

```text
页面理解
元素识别
UI操作
页面探索
UI断言
```

支持：

```text
登录
菜单遍历
表单测试
搜索测试
分页测试
上传测试
```

---

# 3. API Testing Agent

职责：

```text
Swagger解析
接口测试
参数生成
异常测试
```

支持：

```text
正常流
边界值
空值
鉴权
超长字符串
SQL注入
XSS
```

---

# 4. Explorer Agent

职责：

```text
探索式测试
风险发现
随机探索
异常发现
```

探索方式：

```text
菜单遍历
按钮遍历
随机输入
重复点击
搜索测试
```

---

# 5. Assertion Agent

职责：

```text
页面断言
接口断言
数据库断言
日志断言
```

---

# 6. Report Agent

职责：

```text
测试结果聚合
失败原因分析
AI总结生成
报告生成
```

---

# 七、Skill 体系设计

# Skill 设计原则

```text
原子化
可复用
可扩展
可组合
```

---

# 核心 Skill

# browser_observe_skill

职责：

```text
获取页面结构
获取元素摘要
获取截图
```

---

# action_execute_skill

职责：

```text
click
input
hover
scroll
upload
```

---

# page_analyze_skill

职责：

```text
识别页面类型
识别业务区域
识别页面功能
```

---

# testcase_generate_skill

职责：

```text
生成测试点
生成测试步骤
生成断言
```

---

# assertion_skill

职责：

```text
执行断言
判断成功失败
分析异常
```

---

# report_generate_skill

职责：

```text
生成HTML报告
生成Markdown报告
生成PDF报告
```

---

# 八、输入上下文设计

# 最低输入

系统最低支持：

```text
URL
```

即可开始测试。

---

# 增强输入

支持：

```text
PRD
Swagger
测试规则
测试重点
账号密码
数据库结构
历史缺陷
```

用于增强 AI 理解能力。

---

# Context Builder

职责：

```text
整理所有输入信息
压缩上下文
构建结构化上下文
```

输出：

```json
{
  "core_business": [],
  "high_risk_modules": [],
  "forbidden_actions": []
}
```

---

# 九、规则约束系统

# 规则目标

防止 Agent 执行危险行为。

---

# 支持规则

```text
禁止删除数据
禁止真实支付
禁止发送短信
禁止修改生产数据
禁止调用危险接口
```

---

# 执行流程

```text
Agent生成Action
↓
Rule Engine校验
↓
允许执行 / 阻止执行
```

---

# 十、页面语义层设计

# 页面摘要结构

```json
{
  "page_type": "login",
  "buttons": ["登录"],
  "inputs": ["用户名", "密码"],
  "forms": [],
  "tables": []
}
```

---

# 元素定位优先级

```text
text
role
placeholder
aria-label
data-testid
xpath
```

禁止默认使用 XPath。

---

# 十一、UI 测试流程

```text
输入URL
↓
页面观察
↓
页面分析
↓
生成测试点
↓
生成Action
↓
规则校验
↓
执行Action
↓
观察结果
↓
断言
↓
记录日志
↓
继续探索
↓
生成报告
```

---

# 十二、API 测试流程

```text
解析Swagger
↓
提取接口
↓
生成Case
↓
生成参数
↓
执行接口
↓
断言结果
↓
生成报告
```

---

# 十三、前端页面设计

# 1. 任务创建页面

支持输入：

```text
URL
账号密码
PRD
Swagger
测试规则
```

---

# 2. 执行监控页面

显示：

```text
Agent状态
当前步骤
AI思考过程
执行日志
实时截图
```

类似：

```text
Cursor Agent 执行面板
```

---

# 3. 报告页面

显示：

```text
测试结果
风险问题
执行日志
截图
AI总结
```

---

# 十四、测试报告设计

# 报告内容

# 基础信息

```text
任务ID
测试时间
测试目标
执行时长
```

---

# 测试覆盖

```text
已测试页面
已测试接口
已测试模块
```

---

# 执行结果

```text
总步骤
成功步骤
失败步骤
成功率
```

---

# 风险问题

```text
页面异常
接口异常
性能风险
安全风险
```

---

# 执行日志

```text
每一步执行过程
```

---

# 截图

```text
步骤截图
失败截图
```

---

# AI总结

```text
整体质量分析
风险总结
建议修复点
```

---

# 十五、数据库设计

# task 表

```sql
CREATE TABLE task (
    id BIGINT PRIMARY KEY,
    task_name VARCHAR(255),
    target_url TEXT,
    status VARCHAR(50),
    created_at TIMESTAMP
);
```

---

# task_step 表

```sql
CREATE TABLE task_step (
    id BIGINT PRIMARY KEY,
    task_id BIGINT,
    step_index INT,
    action_type VARCHAR(50),
    action_target TEXT,
    result TEXT,
    screenshot TEXT,
    created_at TIMESTAMP
);
```

---

# report 表

```sql
CREATE TABLE report (
    id BIGINT PRIMARY KEY,
    task_id BIGINT,
    report_path TEXT,
    summary TEXT,
    created_at TIMESTAMP
);
```

---

# 十六、MVP 功能范围

# MVP 必须实现

## UI测试

```text
登录
菜单点击
页面跳转
表单输入
搜索
分页
按钮点击
```

---

## API测试

```text
Swagger解析
接口执行
基础断言
异常参数测试
```

---

## 探索式测试

```text
菜单探索
页面探索
按钮探索
表单探索
```

---

## 测试报告

```text
HTML报告
步骤日志
截图
AI总结
```

---

## 前端页面

```text
任务创建
执行监控
报告查看
```

---

# 十七、完整版本目标

# 企业级能力

## 多Agent协作

```text
Planner Agent
UI Agent
API Agent
Report Agent
```

---

## MCP 集成

```text
Jira
GitLab
Redis
MySQL
K8S
```

---

## 数据库断言

```text
SQL校验
数据一致性校验
```

---

## 日志分析

```text
错误日志
异常分析
链路分析
```

---

## 性能测试

```text
并发测试
压测
接口性能分析
```

---

## 历史学习能力

```text
历史case学习
历史bug学习
风险预测
```

---

# 十八、开发阶段规划

# Phase1

```text
Runtime + UI测试闭环
```

目标：

```text
URL → AI探索 → Playwright执行 → HTML报告
```

---

# Phase2

```text
页面理解增强
测试点生成
```

---

# Phase3

```text
Swagger → 自动接口测试
```

---

# Phase4

```text
探索式测试
主动风险发现
```

---

# Phase5

```text
多Agent
MCP
企业级扩展
```

---

# 十九、最终目标

最终系统定位：

```text
AI Native Testing Operating System
```

核心能力：

```text
AI自主理解系统
AI自主执行测试
AI自主分析风险
AI自主生成报告
```

最终实现：

```text
任务驱动
Agent驱动
Skill驱动
上下文驱动
```

而不是：

```text
脚本驱动
```

