# 仓颉知道测试数据

## 1. 账号

| 角色 | 用户名 | 页面展示名 | 密码 | 来源 | 用途 |
|---|---|---|---|---|---|
| 管理员 | `admin` | `zhanghong` | `admin123` | 本地启动文档、网关实测和 UI 登录后页面 | 正常登录、业务 CRUD |
| 历史快捷填值 | `admin` | 不应进入登录后页面 | `cangjie*2026` | 登录页代码和历史 PRD | 负向验证，当前应登录失败 |

说明: `admin` 是登录用户名，登录后首页右上角/用户区域当前展示昵称 `zhanghong`。UI 断言应接受 `admin` 对应的展示名，不应把“未显示 admin 文本”单独判定为登录失败。

## 2. 命名约定

本轮自动化数据统一使用后缀:

```text
TA-20260704
```

建议命名:

- 智能体: `测试智能体-TA-20260704`
- 知识库: `测试知识库-TA-20260704`
- 技能: `测试技能-TA-20260704`
- 文本语料: `测试语料-TA-20260704.md`

## 3. 正向数据

### 新增智能体

```json
{
  "agentName": "测试智能体-TA-20260704",
  "agentDesc": "由 test_agent 自动化验收创建",
  "gatewayUrl": "https://agent-gateway.cangjie.ai/v1/ta-20260704",
  "accessToken": "",
  "knowledgeBaseId": ""
}
```

### 新增知识库

```json
{
  "name": "测试知识库-TA-20260704",
  "intro": "由 test_agent 自动化验收创建"
}
```

### 上传文本语料

```json
{
  "name": "测试语料-TA-20260704.md",
  "text": "## 测试语料\n\n这是由 test_agent 创建的验收语料，用于验证文本集合创建和列表刷新。"
}
```

### 创建技能脚手架

```json
{
  "name": "测试技能-TA-20260704-AUTO",
  "author": "test_agent",
  "description": "由 test_agent 自动化验收创建，可安全清理 TA-20260704"
}
```

## 4. 负向数据

| 场景 | 输入 | 期望 |
|---|---|---|
| 登录密码错误 | `admin / cangjie*2026` | 登录失败，保留在登录页并展示错误提示 |
| 新增智能体名称为空 | `agentName=""` | 前端 required 或后端校验阻断 |
| 新增智能体 URL 非法 | `gatewayUrl="not-url"` | 前端 type=url 或后端校验阻断 |
| 已绑定智能体删除 | 绑定知识库后删除智能体 | 返回业务冲突或前端提示先解绑 |
| 已绑定知识库删除 | 绑定智能体后删除知识库 | 返回业务冲突或前端提示先解绑 |
| 重复创建 `SKILL.md` | 对已有技能创建 `SKILL.md` | 返回 403 或前端阻断 |

## 5. 清理策略

- 智能体: 通过列表搜索 `TA-20260704`，如未绑定则调用 `DELETE /system/agent/{id}`。
- 知识库: 通过列表搜索 `TA-20260704`，如已绑定先 `PUT /fastgpt/dataset/bind` 解绑，再删除。
- 技能: 通过技能列表搜索 `TA-20260704`，调用 `DELETE /system/skill/{skillId}`。
- 若 UI 自动化无法完成清理，保留记录 ID 并在 ledger 中标记 `cleanup_result=retained-for-manual-cleanup`。
