---
status: accepted
date: 2026-07-30
---

# 用确定性保真解析和 G0 门禁接收 v2 输入

## 背景

v1 `api/utils.py` 和文档解析链会把不同格式压成字符串。例如 DOCX 只读取段落会静默
丢失表格、单元格和图片；HTML、源码目录和图片即使无法理解动态或视觉语义，也可能被
上层误当作“已经阅读”。在这种输入上增加人工确认，只会让人确认一份已经缺失的结果。

## 决策

v2 从 `core/design_studio` 的独立入口接收原始资料，不修改
`core/skills/l2_pipeline.py`。正式公共入口是：

- `InputParsingService.parse(SourceInput) -> ParsedArtifact`
- `ParseFidelityGate.evaluate(Iterable[ParsedArtifact]) -> FidelityGateDecision`

每个格式解析器必须先盘点结构，再产生带来源 hash 和 locator 的 `ParsedBlock`，最后由
公共核对程序生成 `ParseFidelityReport`。解析器不能靠提示词或自身声明绕过以下检查：

- detected/parsed inventory 必须一致。
- 块的 `source_id`、`source_hash` 和 locator 必须可回查原件。
- block ID 包含来源 hash、解析器版本、locator 和块内容；来源或内容变化会换 ID。
- 未支持结构必须列入 `unsupported_features`，不能退化为空文本成功。
- 损坏输入、悬空 OpenAPI `$ref`、HTML 缺失本地资源和来源不可读返回 `failed`。
- 没有注册解析器的格式返回 `unsupported`。

G0 默认规则为：必要来源只有 `complete` 可以通过；可选来源允许降级并产生 finding。
人工确认不能把 `partial`、`failed` 或 `unsupported` 改写成 `complete`。

## 原件冻结

`FilesystemArtifactStore` 可在解析前把文件或目录冻结到内容寻址目录，并在复用时重新
校验 payload。正式会话必须使用
`InputParsingService.default(artifact_root=...)`；不传 `artifact_root` 的入口只适合
本地评估和只读探测，不能宣称已持久化原件。

Secret 只保存引用；manifest 不保存密码、token 或 cookie。

## 首版格式结论

| 输入 | 当前结论 | 原因 |
|---|---|---|
| DOCX | 可 `complete` | OOXML 段落、表格、行列、drawing、媒体、链接和页眉页脚均盘点并定位；未支持对象会降级 |
| Markdown/TXT | 可 `complete` | 保留标题路径、段落、表格、代码块和链接 |
| JSON/YAML/OpenAPI | 可 `complete` | 普通结构保留 JSON Pointer；OpenAPI 单独保留 operation、参数、请求、响应、schema、enum 和 ref |
| HTML 原型目录/ZIP | 通常 `partial` | 静态文件、文字、控件和资源闭包可验证；JS 状态、自定义交互和渲染可见性未证明 |
| 原型源码目录/ZIP | `partial` | 文件/忽略清单及静态路由、组件、表单、接口调用可定位；不执行不可信源码 |
| PNG/JPG | `partial` | 二进制、hash、尺寸和格式可验证；OCR 和视觉区域语义适配器尚未实现 |

XLSX、XMind、扫描 PDF 等未注册格式必须显式 `unsupported`。

## 真实黄金集验证

阿勒泰资料当前得到：

- 主 PRD DOCX：`complete`；773 段、15 表、120 行、558 单元格、31 drawing、
  31 媒体全部核对一致。
- API Markdown：`complete`；147 标题、291 段、234 表、1,092 表格行、
  50 代码块、22 链接全部核对一致。
- 八页 HTML 原型：`partial`；10,117 可见文本块、508 原生控件、272 script、
  7,028 inline SVG；0 个本地缺失引用。
- 思维图 PNG：`partial`；原图和 `2706×1272` 元数据保留，OCR/视觉语义未实现。

HTML 的直接 `src/href` 黄金闭包仍是 74 文件和
`B1EA4A1A5882E8D5CA1FF0E225D91312364AFEF965C9E64E0D90484747940485`。
正式解析器继续追踪 CSS `url(...)`，因此传递闭包是 77 文件和
`D3A7CF16EFC0966B6D9ED50CFE1A697A72E914848FC7F019DB0CCA3661CC9302`；
新增的 3 个资源会在 manifest 中逐项保存，不修改直接闭包黄金断言。

## 后果与边界

- 输入缺失会在业务理解之前暴露，不再让人工确认承担解析修复。
- 解析结果可以作为后续 EvidenceClaim 的稳定来源和失效重算起点。
- HTML 动态语义、源码运行时语义和图片语义仍是明确能力缺口；它们不是本决策已完成的
  能力。
- 本决策没有新增 API/前端页面，没有接入 v1 默认路由，也没有改造 Runtime、Memory
  或共享 Skill。
