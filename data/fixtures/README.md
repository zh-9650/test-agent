# Layer 1 测试数据 Fixtures

> 用于 `scratch/test_layer1.py`、前端"试运行 Layer 1"按钮和 Node 1 端到端验证的样本数据。
> 路径全部用 `data/fixtures/*.md|yaml|txt` 引用，相对项目根。

## 文件清单

| 文件 | 用途 | 验证目标 |
|------|------|---------|
| `prd_aitalk.md` | 主目标系统的 PRD | Node 1 → Node 1.5 → Node 1.7 完整管线，规则数 12 条 |
| `swagger_aitalk.yaml` | 主目标系统的 OpenAPI | OpenAPI 3.0 解析，约束/API 路径提取 |
| `changelog_aitalk.md` | 主目标系统的更新日志 | 跨版本变更检测，source=changelog 标注 |
| `prd_purchase.md` | 简单 5 条规则 | 经典 fast path 100% 命中场景 |
| `swagger_purchase.txt` | 简单 4 个接口 | 极简 Swagger 解析 |
| `prd_adversarial.md` | 故意模糊/矛盾 | 验证 KnowledgeExtractor 标 `inferred` + use_case_coverage 鲁棒性 |
| `prd_minimal.md` | 1 条规则 | 极小输入下 Node 1 不崩 |
| `prd_automation_exercise.md` | 公开 e-commerce 测试站 PRD | 26 个官方 TC + 20 条业务规则 + 完整状态机 + 8 业务场景 |
| `swagger_automation_exercise.yaml` | 公开 e-commerce 测试站 OpenAPI | 14 个 API 端点 (products/brands/accounts/search) |
| `changelog_automation_exercise.md` | 公开 e-commerce 测试站发版日志 | v1.2.0 新增 Recommended Items / Write Your Review / 滚动按钮 |

## 用法

### 命令行

```bash
# 主目标系统完整套
python scratch/test_layer1.py \
  --prd data/fixtures/prd_aitalk.md \
  --api-doc data/fixtures/swagger_aitalk.yaml \
  --changelog data/fixtures/changelog_aitalk.md

# 极简 fast path
python scratch/test_layer1.py \
  --prd data/fixtures/prd_minimal.md

# 鲁棒性
python scratch/test_layer1.py \
  --prd data/fixtures/prd_adversarial.md
```

### 通过前端

进入 TaskCreate 页 → 上传对应文件 → 点"试运行 Layer 1"。

### 通过 API

```bash
curl -X POST http://localhost:8002/api/test/layer1 \
  -H "Content-Type: application/json" \
  -d "{
    \"prd\": $(jq -Rs . data/fixtures/prd_aitalk.md),
    \"api_doc\": $(jq -Rs . data/fixtures/swagger_aitalk.yaml),
    \"changelog\": $(jq -Rs . data/fixtures/changelog_aitalk.md)
  }"
```

## 添加新 fixture 的规范

1. 命名：`prd_<system>.md` / `swagger_<system>.yaml|json|txt` / `changelog_<system>.md`
2. PRD 用一级标题写产品名，开头用 `> 测试目标: URL` 注明真实地址（若有）
3. Swagger 优先用 OpenAPI 3.0 完整 YAML；纯接口列表退化为 `.txt`
4. Changelog 遵循 Keep a Changelog 格式
5. 在本 README 表格里加一行

## 注意事项

- PRD 内必须保留足够上下文（角色、状态机、关键数字），否则 L1 fast path 命中率会下降
- Adversarial fixture 是故意的低质量样本，**不要在 production 跑它**——仅用于验证 L1 自我审计能力
- AITalk fixture 与真实 192.168.31.155 系统**不保证 1:1 一致**（无访问权限），如有差异以真实系统为准
