# Hub GitHub 应用目录实施计划

> **给代理执行者：** 按任务顺序逐项勾选；保留当前工作树中的既有更改，不重置或覆盖它们。

**目标：** 让 Hub 首页展示由签名 GitHub Release 资产目录驱动的可发现应用与连接器。

**非目标（Out of Scope）：** 本计划只交付目录浏览、详情和受校验的下载入口，不执行下载包、不启动应用、不接收供应商凭据。

**架构要点：** 官方目录使用版本化 Manifest，并由 Hub 后端校验签名后提供给前端。每条下载资产固定到 GitHub 仓库、Release 版本和具体资产 URL，并校验 SHA-256；不接受 `main`/`master` 压缩包或 `latest` 别名。目录加载和列表浏览不要求 Hub 管理员手工输入共享令牌。

**技术栈/运行方式：** FastAPI/Pydantic/SQLAlchemy；React/TypeScript/Vitest。后端验证：`cd backend; python -m pytest`。前端验证：`cd frontend; pnpm test` 与 `pnpm build`。

**关联设计文档：** `docs/specs/2026-10-04-hub-app-store-installation-design.md`

---

## 文件变更清单

- 新建：
  - `backend/app/domain/catalog/models.py`（目录条目和 GitHub Release 资产的数据模型）
  - `backend/app/domain/catalog/registry.py`（本地版本化目录载入与校验）
  - `backend/app/api/routes/catalog.py`（只读目录 API）
  - `backend/tests/test_catalog.py`（Manifest、签名、Release URL 和摘要验证）
  - `frontend/src/MarketplacePage.tsx`（发现、已安装、连接器筛选和详情）
  - `frontend/src/MarketplacePage.test.tsx`（目录状态和下载入口交互测试）
- 修改：
  - `backend/app/main.py`（挂载目录 API）
  - `frontend/src/App.tsx`（Hub 默认页接入应用商店入口）
  - `frontend/src/api.ts`（读取目录）
  - `frontend/src/types.ts`（目录条目类型）
  - `frontend/src/styles.css`（商店列表和状态样式）

## 任务列表

### 任务 1：定义并校验目录 Manifest

**涉及文件：** 新建 `backend/app/domain/catalog/models.py`、`backend/app/domain/catalog/registry.py`、`backend/tests/test_catalog.py`。

- [ ] **步骤 1：添加失败测试**：覆盖必填字段、固定 GitHub Release 资产 URL、版本号、SHA-256 格式、目录签名无效拒绝。
- [ ] **步骤 2：运行测试**：`cd backend; python -m pytest tests/test_catalog.py -q`；预期新测试因目录模型/注册表不存在而失败。
- [ ] **步骤 3：实现模型与签名验证**：使用 Pydantic 校验条目结构，用 `cryptography` Ed25519 校验随 Hub 发行包固定的目录根公钥签名；拒绝 latest 别名、分支归档 URL、无摘要资产和撤销的目录根密钥。
- [ ] **步骤 4：复跑测试**：同上；预期目录结构与签名测试通过，未签名或摘要错误数据被拒绝。

### 任务 2：提供只读目录 API

**涉及文件：** 新建 `backend/app/api/routes/catalog.py`、`backend/tests/test_catalog.py`；修改 `backend/app/main.py`。

- [ ] **步骤 1：添加 API 测试**：`GET /api/v1/catalog` 返回已验证的目录版本和条目；目录签名失败返回 `503` 且不返回部分目录。
- [ ] **步骤 2：运行测试**：`cd backend; python -m pytest tests/test_catalog.py -q`；预期因路由未挂载而失败。
- [ ] **步骤 3：挂载路由**：只暴露校验后的目录对象；响应不包含任何供应商 Key 或 Hub 服务凭据。
- [ ] **步骤 4：复跑测试**：同上；预期有效目录返回 `200`，签名错误目录返回 `503`。

### 任务 3：构建 Hub 发现页

**涉及文件：** 新建 `frontend/src/MarketplacePage.tsx`、`frontend/src/MarketplacePage.test.tsx`；修改 `frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`、`frontend/src/styles.css`。

- [ ] **步骤 1：添加 UI 测试**：目录按“应用/连接器/已安装/更新”筛选；每张卡片显示发布者、版本、平台要求和权限；GitHub 下载操作使用已校验的精确资产 URL。
- [ ] **步骤 2：运行测试**：`cd frontend; pnpm test -- MarketplacePage.test.tsx`；预期因页面组件未定义而失败。
- [ ] **步骤 3：实现页面和导航**：默认显示“发现”页；目录服务失败时展示可重试错误状态，不展示未验证的缓存目录。
- [ ] **步骤 4：复跑测试及构建**：`cd frontend; pnpm test -- MarketplacePage.test.tsx; pnpm build`；预期测试通过且 TypeScript/Vite 构建成功。

## 用户输入门控

- 在写入真实目录条目前，用户须提供每个条目的 GitHub 仓库和固定 Release 资产下载 URL，并指出资产类型/平台。仓库主页或 Release 页面可用于查找，但目录最终必须固定到具体版本资产并附 SHA-256。未收到链接前，只能使用测试夹具，不能编造生产下载地址。
- 第一个真实目录条目发布前，用户须在安全渠道交付官方目录签名公钥；私钥由用户保存在 GitHub Actions Secret 或其他本机密钥库，禁止提交至仓库。

## 验收

- Hub 首页展示应用与连接器目录；筛选和详情可用。
- 目录通过签名校验后才显示；伪造目录、分支归档地址和摘要不匹配资产被拒绝。
- 列表与详情的读取不需要用户手工输入 Hub 管理令牌。
- 本计划不下载或执行 Release 资产。
