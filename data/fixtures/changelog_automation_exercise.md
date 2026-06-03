# Automation Exercise 发版日志

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [v1.2.0] — 2026-05-15

### Added (新功能)
- 首页底部新增 "Recommended Items" 横向滚动区, 数据来自独立 `recommended` 列表接口 (≥4 个产品)。
- 产品详情页 (`/product_details/<id>`) 新增 "Write Your Review" 表单, 允许访客提交评价; 提交成功显示 `Thank you for your review.`。
- 登录页新增 "Forgot Password" 占位链接 (实际不实现重置流程)。
- 引入滚动到顶部浮动 `↑` 按钮 (右下角, 仅在首页 / 列表页生效)。

### Changed (变更)
- 顶部主导航新增 "Test Cases" 入口, 跳转 `/test_cases` 显示 26 个文档化测试用例。
- 顶部主导航新增 "API Testing" 入口, 跳转 `/api_list` 显示 14 个文档化 API。
- 购物车页 `/view_cart` 加入 "Proceed To Checkout" 按钮, 未登录时点击会跳 `/login` 并提示 Register/Login。
- 产品列表页 `/products` 搜索行为改为 URL query string `?search=<keyword>` 反映当前关键词。

### Fixed (修复)
- 修复了登录失败时偶发不显示 `Your email or password is incorrect!` 错误提示的 bug (服务端 200 但前端未渲染)。
- 修复了用户登出后 `Logged in as <username>` 文案未立即消失的延迟问题 (依赖 localStorage 清理, 现改为 state 同步)。
- 修复了 Contact Us 表单提交后偶发不弹原生 OK 确认框的 bug (现改用 `window.confirm` 强制同步等待)。
- 修复了首页 Recommended Items 在 Chrome 100% 缩放下, 第一屏看不到前 2 个产品的滚动条遮盖问题 (z-index 调整)。

### Removed (移除)
- 移除登录页 "Sign in with Google/Facebook" 占位按钮 (与 PRD 不符, 站点不做 OAuth)。

---

## [v1.1.0] — 2026-03-01

### Added
- Contact Us 表单文件上传字段, 接受 `.txt` / `.png` / `.jpg`。
- 邮件订阅表单空邮箱前端拦截 (避免无效请求)。

### Fixed
- 修复了 Product Detail 页在低分辨率下图片错位的 CSS bug。

---

## [v1.0.0] — 2026-01-10

### Added
- 初始版本: 注册 / 登录 / 登出 / 浏览产品 / 加入购物车 / 模拟支付 / 下载发票。
- 14 个公开 API 接口 (含 7 个 GET / 5 个 POST / 1 个 PUT / 1 个 DELETE)。
