# Automation Exercise - 产品需求文档

> 测试目标: https://automationexercise.com/
> 测试账号: 见 `accounts` 配置 (测试时使用唯一时间戳邮箱注册后登录)
> 接口文档: data/fixtures/swagger_automation_exercise.yaml
> 发版日志: data/fixtures/changelog_automation_exercise.md

## 1. 产品概述

Automation Exercise 是一个面向自动化测试工程师的"全栈"练习网站，提供 UI 测试场景和 API 测试场景两套入口。
- **UI 部分**: 一个完整的电商 Demo，包含产品浏览、购物车、注册/登录、下单（带 mock 支付）等核心电商流程。
- **API 部分**: 14 个 RESTful 接口覆盖产品/品牌/账户三大资源。

> 关键定位: 网站不追求真实交易，重点是提供**确定性、可重放**的测试场景。所有 test case 编号 1-26 都有官方文档支持。

## 2. 角色定义

| 角色 | 权限 | 备注 |
|------|------|------|
| 未登录访客 (Guest) | 浏览首页/产品/分类/品牌/测试用例页; 加入购物车; 提交 Contact Us 表单; 订阅邮件 | 不可登录后操作 |
| 已注册用户 (Customer) | 上述全部 + 登录/登出/账户管理/下单/查看历史订单/写产品评价 | 标准测试账号 |
| 已删除用户 (Deleted) | 任何操作均拒绝 | TC-1, TC-2, TC-14, TC-15, TC-16, TC-23, TC-24 末尾清理 |

## 3. 业务规则 (硬约束)

1. **邮箱唯一性**: 注册时邮箱必须全局唯一; 重复注册时表单提交后显示 `Email Address already exist!`。
2. **密码强度**: 注册时密码字段必填且至少 6 位; 登录密码必须完全匹配。
3. **必填字段**: 账户注册第 2 步 (ENTER ACCOUNT INFORMATION) 必填: Title / Name / Email / Password / DOB (三段) / First name / Last name / Company / Address / Country / State / City / Zipcode / Mobile Number; Address2 和 Newsletter 复选框可选。
4. **账户创建结果**: 注册成功后显示 `ACCOUNT CREATED!`, 点击 Continue 后跳回首页且头部显示 `Logged in as <username>`。
5. **登录失败错误**: 邮箱或密码错误时显示 `Your email or password is incorrect!` (不区分两者, 防枚举)。
6. **登出**: 点击 Logout 后清空 session 并跳转到登录页, 头部 `Logged in as` 文案消失。
7. **购物车持久化**: 商品加入购物车后, 即便未登录也会保留在浏览器 storage 中; 登录后可看到相同商品 (TC-20 验证)。
8. **购物车价格锁定**: 加入购物车时商品价格被锁定; 后续商品列表降价不影响已加入购物车的条目。
9. **订阅 (Subscription)**: 邮箱订阅是匿名操作, 不需要登录; 订阅成功显示 `You have been successfully subscribed!`。
10. **Contact Us 表单**: 必填 Name / Email / Subject / Message; 可选上传文件; 提交后弹原生 `OK` 确认框, 确认后显示 `Success! Your details have been submitted successfully.`。
11. **产品搜索**: 在 `/products` 页搜索框输入关键词后点击搜索按钮; 关键词为空时不应提交, 但页面无错误 (前端拦截); URL 上关键词通过 query string `?search=` 可见。
12. **分类导航**: 左侧栏 `Women` / `Men` / `Kids` 三个一级分类可展开; 点击子分类跳转 `/category_products/<id>` (例如 `/category_products/1` 是 Women > Dress)。
13. **品牌过滤**: `/products` 页左侧 `Brands` 列表展示所有品牌; 点击品牌跳转 `/brand_products/<brand_name>`。
14. **产品详情**: 详情页(`/product_details/<id>`) 必须展示 product name / category / price / availability / condition / brand 6 个字段。
15. **产品评价 (Review)**: 详情页底部 `Write Your Review` 表单提交后, 页面显示 `Thank you for your review.`, 不需要登录。
16. **数量调整**: 详情页 `Quantity` 输入框默认 1, 可手动改为 2/3/...; 加入购物车时数量被锁定。
17. **推荐位 (Recommended Items)**: 首页底部 `recommended items` 横向滚动列表, 来自独立接口; 至少 4 个产品; 加入购物车后弹窗 `View Cart` / `Continue Shopping`。
18. **滚动功能**: 首页右下角浮动 `↑` 按钮, 滚动到底部后点击滚动到顶部; 滚动后页面应看到 `Full-Fledged practice website for Automation Engineers` 文案。
19. **下单流程 (mock)**: 进入 Checkout 后, 即使填写真实卡号也不会真的扣款; 提交后显示 `Your order has been placed successfully!`, 可下载 Invoice 文本文件。
20. **地址继承**: 已登录用户在 Checkout 页的 Delivery Address 和 Billing Address 必须与注册时填写的完全一致 (TC-23 验证)。

## 4. 状态机

### 4.1 账户状态流转

```
[未注册访客] --signup_success--> [已注册未登录] --login_success--> [已登录用户]
                                                                 |
                                                                 +--logout--> [未注册访客]
                                                                 |
                                                                 +--delete_account--> [已删除]
```

### 4.2 购物车状态流转

```
[空购物车] --add_to_cart--> [已加入, 未登录] --login--> [已加入, 已登录]
                       |                            |
                       +--Continue Shopping---------+--> [继续添加 / 移除]
                       +--View Cart----------------->--> [进入 /view_cart 页面]
```

### 4.3 订单状态流转

```
[浏览] --add_to_cart--> [有商品未结账] --proceed_to_checkout--> [地址确认] --place_order--> [支付] --pay_and_confirm--> [已下单]
                                                                                                          |
                                                                                                          +--download_invoice--> [已下载]
```

## 5. 接口约定 (摘要, 详见 swagger_automation_exercise.yaml)

```
GET    /api/productsList                列出所有产品
GET    /api/brandsList                  列出所有品牌
POST   /api/searchProduct               搜索产品 (body: {search_product: "top"})
POST   /api/verifyLogin                 校验登录 (body: {email, password})
POST   /api/createAccount               创建账户 (body: 17 个字段)
PUT    /api/updateAccount               更新账户 (body: 同上)
DELETE /api/deleteAccount               删除账户 (body: {email, password})
GET    /api/getUserDetailByEmail        按邮箱查用户 (query: email)
```

## 6. 关键页面 URL 列表

| 路径 | 名称 | 备注 |
|------|------|------|
| `/` | Home | 含 slider / features items / categories / brands / recommended items |
| `/products` | All Products | 列表 + 搜索框 + 左侧 brand 列表 |
| `/product_details/<id>` | Product Detail | 含 name/category/price/avail/condition/brand + 数量 + Add to cart + Write Your Review |
| `/view_cart` | Cart | 列表 + 删除按钮 + Proceed To Checkout |
| `/login` | Signup / Login | 双区: 左侧 Login to your account, 右侧 New User Signup! |
| `/contact_us` | Contact Us | 表单 + 文件上传 |
| `/test_cases` | Test Cases | 文档化 26 个测试用例 |
| `/api_list` | API Testing | 文档化 14 个 API |
| `/delete_account` | Delete Account | 立即删除当前已登录账户 |
| `/logout` | Logout | 清 session 后回首页 |

## 7. 核心业务流程 (Scenario)

1. **新用户注册 → 浏览 → 加购物车 → 注销** (对应官方 TC-1, TC-12, TC-22, 关键路径)
2. **老用户登录 → 搜索 → 加购物车 → 结账 → 支付** (对应官方 TC-2, TC-9, TC-16, 关键路径)
3. **登录失败 → 错误提示** (对应官方 TC-3, 异常路径)
4. **访客 Contact Us → 提交表单** (对应官方 TC-6, 匿名路径)
5. **产品详情查看 + 评价提交** (对应官方 TC-8, TC-21)
6. **首页订阅邮件** (对应官方 TC-10)
7. **分类 / 品牌导航浏览** (对应官方 TC-18, TC-19)
8. **滚动到顶部 Arrow 按钮** (对应官方 TC-25)

## 8. 不在测试范围 (约束)

- **支付**: 站点 mock 支付, 不需要真实卡号校验; 测试可填假数据 `4111111111111111`。
- **图片上传**: Contact Us 表单的文件上传字段可跳过 (无障碍 + 路径跨平台差异大)。
- **多语言**: 站点仅英文, 不测试 i18n。
- **移动端 UI**: 仅桌面端测试, 不切换 viewport。
- **DELETE 账户**: 测试用账户创建后不再删除, 避免污染他人测试 (用唯一时间戳邮箱)。
- **真实下单**: 不完成支付, 加入购物车 + Checkout 页可见即视为通过。
