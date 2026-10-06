# Hub 本机登录与平台配对实施计划

> **给代理执行者：** 按任务顺序逐项勾选；保留当前工作树中的既有更改，不重置或覆盖它们。Gateway/Agents 服务端配对 API 是跨仓库依赖，完成前不要启用 Hub 配对按钮。

**目标：** 用本机 Hub 管理员会话和 Gateway/Agents 配对授权替代浏览器里的共享管理员令牌输入。

**非目标（Out of Scope）：** 本计划不改造 Gateway 模型路由、Agents 租户授权模型，也不自动创建供应商账号或同意第三方条款。

**架构要点：** Hub 本地首次初始化创建管理员账号；登录后使用 HttpOnly 会话 Cookie 和 CSRF 校验。Gateway、Agents 分别签发 Hub 专属、最小权限、可撤销的服务身份；一次性配对码由目标平台管理员在其管理页批准。服务凭据进入 Hub 后端的系统凭据库，浏览器不接触凭据。

**技术栈/运行方式：** FastAPI/SQLAlchemy/pytest；React/TypeScript/Vitest。后端验证：`cd backend; python -m pytest`。前端验证：`cd frontend; pnpm test` 与 `pnpm build`。

**关联设计文档：** `docs/specs/2026-10-04-hub-app-store-installation-design.md`

---

## 文件变更清单

- 新建：
  - `backend/app/domain/identity/models.py`（本机管理员与会话模型）
  - `backend/app/api/routes/identity.py`（初始化、登录、登出和会话端点）
  - `backend/app/infrastructure/credential_store.py`（系统凭据库抽象）
  - `backend/tests/test_identity.py`（初始化、密码、Cookie 和 CSRF 测试）
  - `backend/tests/test_platform_pairing.py`（配对状态、scope 与撤销测试）
- 修改：
  - `backend/app/main.py`、`backend/app/infrastructure/database.py`（身份路由和迁移）
  - `backend/app/api/routes/platform_connections.py`、`backend/app/infrastructure/platform_connections.py`（以会话授权替换管理令牌并调用配对 API）
  - `frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`（初始化、登录、会话和配对 API）
  - `frontend/src/PlatformPage.tsx`、`frontend/src/AdminTokenControl.tsx`（删除共享令牌操作，呈现服务配对状态）
  - `frontend/src/PlatformPage.test.tsx`、`frontend/src/api.auth.test.ts`（会话与配对交互）

## 任务列表

### 任务 1：本机管理员初始化和会话

**涉及文件：** 新建 `backend/app/domain/identity/models.py`、`backend/app/api/routes/identity.py`、`backend/tests/test_identity.py`；修改 `backend/app/main.py`、`backend/app/infrastructure/database.py`。

- [ ] **步骤 1：写失败测试**：首次初始化只允许一次；密码不明文存储；登录成功返回 HttpOnly/SameSite Cookie；登出撤销会话；缺少 CSRF Token 的状态变更返回 `403`。
- [ ] **步骤 2：运行**：`cd backend; python -m pytest tests/test_identity.py -q`；预期新端点测试失败。
- [ ] **步骤 3：实现最小身份契约**：使用带随机 salt 的 scrypt 密码哈希、数据库会话记录、HttpOnly Cookie、CSRF nonce；初始向导只对回环地址开放。
- [ ] **步骤 4：复跑**：同上；预期所有身份测试通过，测试输出不包含密码或 Cookie 值。

### 任务 2：系统凭据库抽象与平台配对 API

**涉及文件：** 新建 `backend/app/infrastructure/credential_store.py`、`backend/tests/test_platform_pairing.py`；修改 `backend/app/infrastructure/platform_connections.py`、`backend/app/api/routes/platform_connections.py`。

- [ ] **步骤 1：写失败测试**：测试 Gateway 和 Agents 配对创建/批准、最小 scope 限制、凭据只存系统凭据库、撤销后拒绝目录读取、失效后要求重新配对。
- [ ] **步骤 2：运行**：`cd backend; python -m pytest tests/test_platform_pairing.py -q`；预期当前连接模型不支持配对而失败。
- [ ] **步骤 3：实现 Hub 侧契约**：每个平台单独保存 credential reference；Hub 不接受 scope 扩展、不把服务凭据返回给浏览器；外部配对 API 尚未部署时明确显示“平台未支持配对”。
- [ ] **步骤 4：复跑**：同上；预期撤销、scope 和密钥保密测试通过。

### 任务 3：前端移除共享令牌输入并呈现配对

**涉及文件：** 修改 `frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`、`frontend/src/PlatformPage.tsx`、`frontend/src/AdminTokenControl.tsx`；新增或修改前端测试文件。

- [ ] **步骤 1：写失败测试**：匿名打开时显示本机初始化/登录页；登录后平台配置请求自动带 Cookie 与 CSRF；Gateway/Agents 卡片只显示“未连接/等待批准/已连接/需重连”，不存在共享令牌输入框。
- [ ] **步骤 2：运行**：`cd frontend; pnpm test -- PlatformPage.test.tsx api.auth.test.ts`；预期因现有令牌表单仍显示而失败。
- [ ] **步骤 3：实现 UI 流程**：删除 sessionStorage 管理令牌；添加初始化、登录、登出和配对弹窗；配对码只展示一次且有明确过期倒计时。
- [ ] **步骤 4：复跑与构建**：`cd frontend; pnpm test -- PlatformPage.test.tsx api.auth.test.ts; pnpm build`；预期测试与构建通过。

## 跨仓库依赖门控

- Gateway 仓库必须提供登录管理员批准 Hub 配对、签发可撤销最小 scope 凭据、管理 Provider 连接以及撤销接口。
- Agents 仓库必须提供登录管理员批准 Hub 配对、签发可撤销最小 scope 凭据、读取 Agent 目录以及撤销接口。
- 用户须提供 Gateway 和 Agents 的 GitHub 仓库链接或本机工作区路径，才能把配对服务端契约落实到相应仓库。对应 API 未实现并验收前，Hub 不显示可执行的“连接成功”状态。

## 验收

- Hub 管理操作不再要求用户手工输入 `LYRA_HUB_ADMIN_TOKEN`。
- 未登录状态无法执行平台配置变更；本机首次管理员初始化只能成功一次。
- Gateway/Agents 凭据经各自管理员批准配对后保存至系统凭据库，权限可查、可撤销、可重新配对。
