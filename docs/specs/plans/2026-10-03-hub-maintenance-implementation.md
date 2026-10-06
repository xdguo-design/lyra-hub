# Hub 租户与自动维护实施计划

> **给代理执行者：** 依任务顺序按 TDD 完成。每个行为先新增最小测试并实际运行至 RED，再实现至 GREEN。保留工作区现有未提交变更；只编辑本计划列出的相关文件，不提交、不重置已有改动。

**目标：** 在 Hub 提供基于 Agents 权威租户/身份的管理入口，以及持久化巡检、告警和管理员确认修复页面。

**架构要点：** Hub 维护自己的巡检计划、运行摘要、告警、维护审计和平台公告；Agents 用户身份经 Hub 后端转发，平台管理服务凭据独立保存。Worker 通过数据库租约避免重复执行，任何写配置的维护操作都要二次确认、revision 检查、幂等保护和审计。

**技术栈：** FastAPI、SQLAlchemy、SQLite（遵循已有 Hub Database）、React/TypeScript、Vitest；后端 `cd D:\WorkSpace\lyra-hub\backend; python -m pytest`、`python -m ruff check .`；前端 `cd D:\WorkSpace\lyra-hub\frontend; npm test`、`npm run build`。

**关联设计文档：** `docs/specs/2026-10-03-hub-maintenance-agents-multitenancy-design.md`

**分支：** Hub 当前在 `dev`，维持该分支；不切换分支，不提交。

---

## 文件与职责

- 新建 `backend/app/infrastructure/maintenance.py`：巡检、告警、租约与确认修复的数据仓储/服务。
- 新建 `backend/app/api/routes/maintenance.py`：版本化的维护 API、状态授权与错误响应。
- 修改 `backend/app/infrastructure/database.py`：增加 Hub 维护表，保留既有 schema 和连接配置表。
- 新建 `backend/app/workers/maintenance.py`：到期巡检 Worker 与单次 `run_once` 入口。
- 修改 `backend/app/main.py`：依赖注入及路由注册，不在 API 进程自动启动多份调度器。
- 修改 `backend/pyproject.toml`：注册 `lyra-hub-maintenance` 独立 Worker 命令。
- 修改 `backend/app/infrastructure/platforms.py`：为 Gateway/Agents 与应用 Manifest 增加只读检查适配，不自动发起生成/打印。
- 新建 `frontend/src/MaintenancePage.tsx`、`frontend/src/TenantsPage.tsx`；修改 `App.tsx`、`api.ts`、`types.ts`、`styles.css` 加导航和状态。
- 新建对应的 `backend/tests/test_maintenance*.py` 与 `frontend/src/*.test.tsx`，测试公开行为。

## 任务 1：维护结果、告警和操作持久化

**涉及文件：** `backend/app/infrastructure/database.py`、新建 `backend/app/infrastructure/maintenance.py`、`backend/tests/test_maintenance_store.py`。

- [ ] **步骤 1：写 RED 测试**：验证新数据库建表后可写/读巡检记录、同一告警指纹更新原告警而不重复插入、操作审计按时间排序、租约过期后可以再领取。
- [ ] **步骤 2：运行测试**：`python -m pytest tests/test_maintenance_store.py -q`；预期因维护仓储/记录未实现而失败。
- [ ] **步骤 3：最小实现**：添加 schedule/check/alert/repair audit/worker lease SQLAlchemy 模型；实现参数化查询、事务边界、唯一告警指纹和基于时间的租约领取；注册独立 Worker 命令供容器/运维进程启动。
- [ ] **步骤 4：验证 GREEN**：同一命令通过；再运行 `python -m pytest tests/test_applications.py tests/test_shared_files.py -q`，确保既有数据库行为不回归。

## 任务 2：五个服务的只读巡检与持久化调度

**涉及文件：** `backend/app/infrastructure/platforms.py`、新建 `backend/app/workers/maintenance.py`、`backend/tests/test_maintenance_checks.py`、`backend/tests/test_maintenance_worker.py`。

- [ ] **步骤 1：写 RED 测试**：用 httpx MockTransport 验证 Hub `/health` 与 `/ready`、Gateway 模型目录、Agents Agent 目录、Narrative `/api/health`、Print `/health` 的健康/空目录/401/超时分类；断言请求方法全为 GET 且不调用模型/打印端点。
- [ ] **步骤 2：运行测试**：`python -m pytest tests/test_maintenance_checks.py tests/test_maintenance_worker.py -q`；预期新巡检服务/Worker 缺失而失败。
- [ ] **步骤 3：最小实现**：实现可注入 transport、每服务超时、并发上限、随机抖动、错误分类、5 分钟默认周期、2 次连续失败开告警、成功恢复事件；Worker 只在领取租约后执行到期只读任务。
- [ ] **步骤 4：验证 GREEN**：上述测试通过；重复领取一个租约只能有一个 Worker 成功；Worker 崩溃后租约过期可重试只读巡检。

## 任务 3：维护 API、应急管理与修复确认

**涉及文件：** 新建 `backend/app/api/routes/maintenance.py`、修改 `backend/app/main.py`、`backend/tests/test_maintenance_api.py`、`backend/tests/test_platform_connections.py`。

- [ ] **步骤 1：写 RED 测试**：匿名请求被拒；合法平台管理员可读 overview/alerts、手动触发 GET-only 巡检、确认告警；修复未确认时配置不变；确认恢复 last-good 时 revision 冲突返回 409，成功写审计且重放幂等。
- [ ] **步骤 2：运行测试**：`python -m pytest tests/test_maintenance_api.py -q`；预期维护路由不存在而失败。
- [ ] **步骤 3：最小实现**：实现 `/api/v1/maintenance/overview`、`/alerts`、`/checks`、`/alerts/{id}/acknowledge`、`/repairs/{id}/confirm`；沿用 Hub 平台管理员校验和 break-glass，只允许服务明细中声明的恢复动作，检查 expected revision 和 `Idempotency-Key`，敏感字段不入审计。
- [ ] **步骤 4：验证 GREEN**：API 测试通过；`python -m pytest tests/test_platform_connections.py -q` 回归通过。Agents 不可用时，break-glass 只能查看 Hub 告警并恢复 Hub 连接，不能代理读取 Agents 租户资源。

## 任务 4：租户管理与 Agents 身份代理

**涉及文件：** 新建 `backend/app/api/routes/agent_proxy.py`、`backend/app/infrastructure/agent_proxy.py`、`backend/tests/test_agent_proxy.py`，修改 `main.py` 及前端 `api.ts`/`types.ts`。

- [ ] **步骤 1：写 RED 测试**：验证登录/当前用户与租户 API 通过 Hub 转发到配置的 Agents origin；用户 bearer token 原样转发且不会记录；不允许任意 URL/path 转发；平台管理服务凭据只用于租户管理端点；Agents 不可用映射为可诊断 503。
- [ ] **步骤 2：运行测试**：`python -m pytest tests/test_agent_proxy.py -q`；预期代理模块不存在而失败。
- [ ] **步骤 3：最小实现**：加入严格 allowlist 的 Agents auth/platform-tenant 代理。租户 ID 由 Agents 身份/平台管理 API 管理，Hub 不信任浏览器的 tenant 切换参数；配置密文不回传浏览器。
- [ ] **步骤 4：验证 GREEN**：测试通过；Hub admin/break-glass 不能冒充租户管理员调用 `/runs`。

## 任务 5：Hub 维护中心、租户页面与导航

**涉及文件：** 新建 `frontend/src/MaintenancePage.tsx`、`frontend/src/TenantsPage.tsx` 及相邻 Vitest 测试；修改 `App.tsx`、`api.ts`、`types.ts`、`styles.css`。

- [ ] **步骤 1：写 RED 测试**：按页面行为测试五服务状态/空目录/错误、告警去重和恢复、修复二次确认与 revision 冲突、租户创建/停用状态及 Agents offline/break-glass 状态；确认页面加载本身不触发写操作。
- [ ] **步骤 2：运行测试**：`npm test -- --run`；预期新增页面导入/组件失败。
- [ ] **步骤 3：最小实现**：接维护与 Agents proxy API；增加总览、租户和维护路由；本期无公告编辑页，只展示未来公告存储归属；交互错误、空态、加载态和敏感凭据脱敏均显式呈现。
- [ ] **步骤 4：验证 GREEN**：`npm test -- --run`、`npm run build` 均通过。

## 完成门禁

- [ ] 在 `backend` 执行 `python -m pytest` 与 `python -m ruff check .`。
- [ ] 在 `frontend` 执行 `npm test` 与 `npm run build`。
- [ ] `git diff --check`；复核没有用户输入/密钥进入日志、无未确认修复路径、无本期自动生成或打印。
- [ ] 不执行 git reset、clean、checkout；不提交 Hub 现有或本次修改。
