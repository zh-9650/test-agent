# 仓颉知道测试资产包

本目录是从 `C:\Users\17381\Desktop\cangjie` 反向整理出的被测系统输入资产，用于当前 `test_agent` 项目测试 `http://localhost:3001/`。

## 资产说明

- `reverse-prd.md`: 面向测试的反向 PRD，覆盖登录、智能体广场、知识库管理、技能管理。
- `api-contract.md`: 当前前端实际调用的接口契约摘要。
- `test-data.md`: 可复用测试账号、测试数据命名、正负向数据和清理策略。
- `task-payload.json`: 可直接提交给 `POST /api/tasks` 的任务 payload。
- `task-payload-inline.json`: 将 PRD、接口和测试数据正文内联后的任务 payload，推荐用于当前 `test_agent` 自动分析链路。
- `task-payload-login-regression.json`: 聚焦登录页、一键填值、真实管理员登录的回归 payload，用于验证 `test_agent` 执行器对登录场景的定位、断言和误判控制能力。
- `task-payload-platform-selftest.json`: 聚焦 `test_agent` 自身任务创建、资产生成、执行 run 和报告生成的 D4 闭环验证，只覆盖登录与只读搜索路径，避免业务写操作。
- `task-payload-agent-crud.json`: 聚焦智能体广场新增、搜索、非法 URL 校验和清理的写操作 payload，用于推进 CJ-P1-004 到 D2。
- `task-payload-dataset-crud.json`: 聚焦知识库管理新增、搜索、空名称校验和清理的写操作 payload，用于推进 CJ-P1-005 到 D2。
- `task-payload-skill-scaffold.json`: 聚焦技能管理快速初始化脚手架、在线修编元数据、核心文件树和重复 `SKILL.md` 阻断的写操作 payload，用于推进 CJ-P1-006 到 D2/D3。

## 使用提示

当前 `test_agent` 后端会抓取配置字段中的 URL，但不会自动展开 `data/...` 这类本地相对路径。若直接提交只写“见某某文件”的 payload，分析阶段可能缺少足够事实并失败。自动建任务时优先提交 `task-payload-inline.json`；`task-payload.json` 仅作为人读索引或对照样本。

若只想回归登录链路和测试执行器稳定性，优先提交 `task-payload-login-regression.json`。该 payload 比完整业务资产更窄，适合在修复定位、条件分析、断言生成、终态判断后快速验证。

若要验证 `test_agent` 是否已经能从反向资产完成“创建任务 -> 生成 analysis_package -> 执行 UI 用例 -> 生成 report”的完整闭环，优先提交 `task-payload-platform-selftest.json`。该 payload 是 CJ-P2-007 的 D4 收敛版，会禁用历史 memory context，只做登录和只读搜索，不受 FastGPT 新建知识库 502 的产品侧阻塞影响。

若要推进智能体写操作，先用运行记录里的助手清理旧测试数据，再提交 `task-payload-agent-crud.json`。清理助手只会处理名称、描述或 URL 中包含 `TA-20260704` 的智能体：

```powershell
python data\test-runs\cangjie-20260704-acceptance\setup\cangjie_agent_api_helper.py --keyword TA-20260704 --action cleanup
```

若要推进知识库写操作，先用知识库助手清理旧测试数据，再提交 `task-payload-dataset-crud.json`。清理助手只会处理名称、描述或 datasetId 中包含 `TA-20260704` 且未绑定智能体的知识库：

```powershell
python data\test-runs\cangjie-20260704-acceptance\setup\cangjie_dataset_api_helper.py --keyword TA-20260704 --action cleanup
```

若要推进技能管理写操作，先用技能助手清理旧测试数据，再提交 `task-payload-skill-scaffold.json`。清理助手只会处理名称、描述、作者或 skillId 中包含 `TA-20260704` 的技能：

```powershell
python data\test-runs\cangjie-20260704-acceptance\setup\cangjie_skill_api_helper.py --keyword TA-20260704 --action cleanup
```

## 证据来源

- `C:\Users\17381\Desktop\cangjie\cangcloud\仓颉知道3.0 需求规格说明书.md`
- `C:\Users\17381\Desktop\cangjie\cangcloud\《仓颉知道》平台标准化功能清单.md`
- `C:\Users\17381\Desktop\cangjie\cangcloud\api-documentation-agent.md`
- `C:\Users\17381\Desktop\cangjie\cangcloud\api-documentation.md`
- `C:\Users\17381\Desktop\cangjie\cangcloud\integration-test-report.md`
- `C:\Users\17381\Desktop\cangjie\cangcloud\agent-integration-test-report.md`
- `C:\Users\17381\Desktop\cangjie\本地启动全流程.md`
- `C:\Users\17381\Desktop\cangjie\cangjie-zhidao3.0\src\api\index.ts`
- `C:\Users\17381\Desktop\cangjie\cangjie-zhidao3.0\src\App.tsx`
- `C:\Users\17381\Desktop\cangjie\cangjie-zhidao3.0\src\components\LoginView.tsx`

## 当前校准点

- 真实本地登录账号: `admin / admin123`。
- 登录页“一键填值体验”仍填入 `admin / cangjie*2026`，该密码经网关验证已失败。测试时不要把一键填值作为成功登录前置。
- 目标前端端口: `3001`。
- 网关端口: `8080`。
- 当前测试平台后端端口: `8002`。
- 隔离验证后端端口: `8003`，用于在不打断 `8002` 现有任务的前提下验证测试平台修复。
