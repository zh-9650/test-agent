# 仓颉知道接口契约摘要

## 1. 通用约定

- 前端入口: `http://localhost:3001/`
- 网关入口: `http://127.0.0.1:8080`
- 前端 API 前缀: `/dev-api`
- 认证方式: `Authorization: Bearer {access_token}` + `clientid`
- 固定 clientid: `e5cd7e4891bf95d1d19206ce24a7b32e`
- 登录租户: `tenantId=000000`

统一响应:

```json
{
  "code": 200,
  "msg": "操作成功",
  "data": {}
}
```

分页/特殊列表响应可能为:

```json
{
  "code": 200,
  "msg": "查询成功",
  "rows": [],
  "total": 0
}
```

## 2. 登录与健康

| 功能 | 方法 | 路径 | 请求 | 期望 |
|---|---|---|---|---|
| 登录 | POST | `/auth/login` | `username,password,grantType,tenantId,clientId` | `code=200` 且返回 `access_token` |
| 验证码/登录配置 | GET | `/auth/code` | 无 | `captchaEnabled=false` |
| 网关健康 | GET | `/api/health` | 登录态下由前端调用 | 返回健康状态 |

登录 payload:

```json
{
  "username": "admin",
  "password": "admin123",
  "grantType": "password",
  "tenantId": "000000",
  "clientId": "e5cd7e4891bf95d1d19206ce24a7b32e"
}
```

## 3. 智能体广场

基础路径: `/system/agent`

| 功能 | 方法 | 路径 | 关键入参 | 业务规则 |
|---|---|---|---|---|
| 新增智能体 | POST | `/system/agent` | `agentName,gatewayUrl,agentDesc,accessToken,knowledgeBaseId` | 名称必填，网关 URL 必须 http/https，Token 可自动生成 |
| 编辑智能体 | PUT | `/system/agent` | `id,agentName,gatewayUrl,...` | Token 为空时保持原值 |
| 删除智能体 | DELETE | `/system/agent/{id}` | `id` | 已绑定知识库时禁止删除 |
| 查询列表 | GET | `/system/agent/list` | `keyword?` | 模糊匹配名称/描述/URL，Token 脱敏 |
| 免登跳转 | GET | `/system/agent/{id}/redirect` | `id` | 返回 `redirectUrl` |

新增示例:

```json
{
  "agentName": "测试智能体-TA-20260704",
  "agentDesc": "由 test_agent 自动化验收创建",
  "gatewayUrl": "https://agent-gateway.cangjie.ai/v1/ta-20260704",
  "accessToken": "",
  "knowledgeBaseId": ""
}
```

## 4. 知识库管理

基础路径: `/fastgpt/dataset`

| 功能 | 方法 | 路径 | 关键入参 | 业务规则 |
|---|---|---|---|---|
| 创建知识库 | POST | `/fastgpt/dataset` | `name,intro,type?` | 返回 `datasetId` |
| 查询列表 | GET | `/fastgpt/dataset/list` | `keyword?` | 返回集合数和绑定状态 |
| 查询详情 | GET | `/fastgpt/dataset/{datasetId}` | `datasetId` | 返回本地和 FastGPT 状态 |
| 删除知识库 | DELETE | `/fastgpt/dataset/{datasetId}` | `datasetId` | 已绑定智能体时禁止删除 |
| 创建文本集合 | POST | `/fastgpt/dataset/collection/text` | `datasetId,name,text` | 返回 `collectionId,insertLen` |
| 上传文件集合 | POST | `/fastgpt/dataset/collection/file` | multipart `file,bo` | `bo` 含 `datasetId,trainingType,chunkSettingMode` |
| 数据推送 | POST | `/fastgpt/dataset/data/push` | `collectionId,data[]` | 返回 `insertLen` |
| 语义搜索 | POST | `/fastgpt/dataset/search` | `datasetId,text,limit,similarity,searchMode` | 返回搜索结果数组 |
| 绑定/解绑 | PUT | `/fastgpt/dataset/bind` | `datasetId,agentId|null` | 一对一绑定 |

创建知识库示例:

```json
{
  "name": "测试知识库-TA-20260704",
  "intro": "由 test_agent 自动化验收创建"
}
```

## 5. 技能管理

前端实际调用路径: `/system/skill/**`

| 功能 | 方法 | 路径 | 关键入参 | 业务规则 |
|---|---|---|---|---|
| 分页搜索 | POST | `/system/skill/page` | `keyword,status,pageNum,pageSize` | 返回 `rows,total` |
| 创建脚手架 | POST | `/system/skill/scaffold` | `name,author,description` | 生成 `SKILL.md` 和 `index.js` |
| 上传 ZIP | POST | `/system/skill/upload` | multipart `file` | 仅允许 zip |
| 状态切换 | PUT | `/system/skill/{skillId}/status` | `status=0|1` | skillId 必须存在 |
| 删除技能 | DELETE | `/system/skill/{skillId}` | `skillId` | 逻辑删除并级联文件 |
| 导出 ZIP | GET | `/system/skill/{skillId}/export` | `skillId` | 返回 zip 文件流 |
| 查询详情 | GET | `/system/skill/{skillId}` | `skillId` | 返回技能元数据 |
| 文件树 | GET | `/system/skill/{skillId}/files` | `skillId` | 文件夹优先排序 |
| 新建文件/目录 | POST | `/system/skill/{skillId}/file` | `filePath,content,type` | 禁止重复路径和重复 `SKILL.md` |
| 更新文件 | PUT | `/system/skill/{skillId}/file` | `filePath,content` | 更新 `SKILL.md` 同步元数据 |
| 删除文件/目录 | DELETE | `/system/skill/{skillId}/file` | `filePath,type` | 禁止删除核心 `SKILL.md` |
| 更新元数据 | PUT | `/system/skill/{skillId}/metadata` | `name,version,author,description` | 回写 `SKILL.md` |
| 一键保存 | PUT | `/system/skill/{skillId}/save` | `metadata,files[]` | 批量保存 |

脚手架示例:

```json
{
  "name": "测试技能-TA-20260704",
  "author": "test_agent",
  "description": "自动化验收脚手架"
}
```

## 6. 需要重点观测的契约风险

- 登录页一键填值密码与真实可用密码不一致。
- 业务接口路径经前端 `/dev-api` 代理后是否正确落到网关。
- 技能接口文档中基础路径写为 `/skill`，但前端实际调用 `/system/skill`。
- 删除/绑定类操作有真实数据副作用，测试数据必须使用唯一前缀并清理。
- 列表接口 200 不代表业务数据可用，需要检查 `data` 或 `rows/total`。
