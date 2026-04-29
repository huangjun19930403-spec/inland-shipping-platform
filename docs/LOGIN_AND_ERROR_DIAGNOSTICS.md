# 登录与错误诊断说明

## 1. 登录链路

当前登录主链路：

1. `POST /api/v1/auth/login`
2. `GET /api/v1/auth/me`
3. `GET /api/v1/auth/me/menus`

前端在登录成功后会继续调用 `/auth/me` 与 `/auth/me/menus` 完成用户上下文初始化。

## 2. 常见失败场景

- 账号或密码错误（`/auth/login` 返回认证失败）
- token 失效或被清理（`/auth/me` / `/auth/me/menus` 返回 401）
- 用户状态不可登录（如 `DISABLED/INACTIVE/LOCKED/DELETED`）
- 角色/菜单 seed 异常导致 `/auth/me/menus` 失败
- 后端未捕获异常导致 500

## 3. 排查方式

### 3.1 先看前端错误提示

登录页会显示后端错误消息，并尽量附带 `request_id`。

### 3.2 对齐 Network 与后端日志

1. 在浏览器 Network 查看失败请求
2. 获取请求/响应头中的 `X-Request-ID`
3. 在后端日志中按 `request_id` 检索

### 3.3 定位失败发生在哪一步

- `/auth/login` 失败：优先排查账号状态、密码、登录日志
- `/auth/me` 失败：优先排查 token、用户状态
- `/auth/me/menus` 失败：优先排查角色-菜单关系与 seed 初始化

## 4. 后端诊断能力（阶段 4A）

- 每个请求会透传或生成 `request_id`
- 所有响应头回写 `X-Request-ID`
- `AppException` / `422` / `500` 响应体包含 `request_id`
- 未捕获异常统一由全局异常处理记录 `logger.exception` 堆栈
- 日志不打印密码、token、密钥明文

## 5. E2E 验收

Playwright 登录 smoke：

- `tests/e2e/auth-login.spec.ts`
  - 正确账号密码可登录并进入 `/dashboard`
  - 错误账号密码时页面可见错误提示

执行：

```bash
npm run e2e
```
