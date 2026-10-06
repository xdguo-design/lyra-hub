# Hub GitHub 应用包安装器实施计划

> **给代理执行者：** 按任务顺序逐项勾选；保留当前工作树中的既有更改，不重置或覆盖它们。安装目录、Docker runtime、目录发布者信任根都按已批准的设计执行。

**目标：** 从已验证的 GitHub Release 安装 Lyra OCI 应用，并提供隔离启动、健康检查、升级回滚和保留数据的卸载。

**非目标（Out of Scope）：** 不执行下载包内的任意安装脚本；不允许任意第三方上传；不安装 Docker Engine；不下载模型权重。

**架构要点：** 官方签名目录列出 GitHub Release 附件中的 OCI/Docker image archive、固定资产 URL、SHA-256 和镜像 digest；Hub 只用内置 Docker adapter 校验归档并加载镜像，不执行包内脚本，OCI 容器遵循最小权限配置。应用数据存于每个应用独立的主机目录，更新前停止容器并复制、校验文件级快照；健康检查失败时恢复快照并启动旧镜像。

**技术栈/运行方式：** FastAPI/SQLAlchemy/cryptography/pytest；React/TypeScript/Vitest。后端验证：`cd backend; python -m pytest`。前端验证：`cd frontend; pnpm test` 与 `pnpm build`。Docker 集成测试需 Docker Engine；无 Docker 时运行 Mock adapter 单元测试。

**关联设计文档：** `docs/specs/2026-10-04-hub-app-store-installation-design.md`

---

## 文件变更清单

- 新建：
  - `backend/app/domain/installer/models.py`（安装状态、运行状态和版本记录）
  - `backend/app/domain/installer/service.py`（签名校验、下载、安装、升级、回滚和卸载流程）
  - `backend/app/infrastructure/oci_runtime.py`（加载 OCI archive 并生成受限 Docker Compose 配置）
  - `backend/app/infrastructure/artifact_downloader.py`（只允许目录声明的 HTTPS GitHub Release 资产）
  - `backend/tests/test_installer.py`（包校验、权限、失败回滚和状态机）
  - `backend/tests/test_oci_runtime.py`（容器隔离配置）
- 修改：
  - `backend/app/api/routes/catalog.py`（受管理员会话保护的安装、更新、卸载操作）
  - `backend/app/main.py`、`backend/app/infrastructure/database.py`（路由、安装记录和数据迁移）
  - `frontend/src/MarketplacePage.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`（安装状态和操作）
  - `frontend/src/MarketplacePage.test.tsx`（安装状态、失败提示和回滚交互）

## 任务列表

### 任务 1：受限下载器与 Release 资产验证

**涉及文件：** 新建 `backend/app/infrastructure/artifact_downloader.py`、`backend/tests/test_installer.py`。

- [ ] **步骤 1：写失败测试**：拒绝非 HTTPS、非目录白名单 GitHub host、未声明资产 URL、签名目录校验失败、SHA-256 不符、超过 Manifest 大小上限的资产；验证连接中断时临时文件清理。
- [ ] **步骤 2：运行**：`cd backend; python -m pytest tests/test_installer.py -q`；预期下载器相关测试失败。
- [ ] **步骤 3：实现下载器**：只用 `httpx` 流式下载；每个重定向目标重新校验 host；校验文件长度与 SHA-256；写入临时目录后原子改名。
- [ ] **步骤 4：复跑**：同上；预期所有无网络 Mock 测试通过。

### 任务 2：安全 OCI 适配器

**涉及文件：** 新建 `backend/app/infrastructure/oci_runtime.py`、`backend/tests/test_oci_runtime.py`。

- [ ] **步骤 1：写失败测试**：确保生成配置包含 non-root、read-only rootfs、cap-drop ALL、无特权、无 host 网络/PID/IPC、无设备映射、无 Docker socket、独立数据目录、仅声明端口。
- [ ] **步骤 2：运行**：`cd backend; python -m pytest tests/test_oci_runtime.py -q`；预期当前无 OCI 适配器而失败。
- [ ] **步骤 3：实现固定 Compose 配置**：将已校验的 OCI archive 加载到 Docker Engine，检查加载后的镜像 digest 与目录一致；服务只在 Hub 内部网络启动；管理员确认前不增加任何可选权限；拒绝主机路径挂载和特权模式。
- [ ] **步骤 4：复跑**：同上；预期安全配置断言通过，Docker 不可用时返回明确 `runtime_unavailable` 状态。

### 任务 3：安装状态机与可回滚数据更新

**涉及文件：** 新建 `backend/app/domain/installer/models.py`、`backend/app/domain/installer/service.py`；修改 `backend/app/infrastructure/database.py`、`backend/app/main.py`、`backend/app/api/routes/catalog.py`、`backend/tests/test_installer.py`。

- [ ] **步骤 1：写失败测试**：覆盖 `available → downloading → verifying → installing → health_check → installed`；坏签名不写安装记录；空间不足拒绝更新；迁移/健康检查失败时恢复校验通过的快照和旧镜像；卸载不删除数据目录。
- [ ] **步骤 2：运行**：`cd backend; python -m pytest tests/test_installer.py -q`；预期状态机测试失败。
- [ ] **步骤 3：实现服务**：按签名目录的类型调用下载器和 OCI 适配器；维护每应用版本记录；执行更新前停机、空间检查、目录副本与 SHA-256 校验；失败时停止新容器并恢复快照；卸载只移除镜像与 Hub 登记。
- [ ] **步骤 4：复跑**：同上；预期各状态、回滚与数据保留断言通过。

### 任务 4：商店 UI 安装操作和端到端检查

**涉及文件：** 修改 `frontend/src/MarketplacePage.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`、`frontend/src/MarketplacePage.test.tsx`；新增 `frontend/e2e/marketplace.spec.ts` 和对应 Playwright 配置。

- [ ] **步骤 1：写失败测试**：测试安装进度、Docker 缺失说明、签名错误提示、健康检查成功后的“打开”、失败升级后的旧版本状态和保留数据提示。
- [ ] **步骤 2：运行**：`cd frontend; pnpm test -- MarketplacePage.test.tsx`；预期新交互测试失败。
- [ ] **步骤 3：实现 UI**：安装、更新和卸载均要求有效 Hub 管理员会话；显示进度、版本和错误状态；卸载只标注“保留数据”且不触发数据删除。
- [ ] **步骤 4：复跑**：`cd frontend; pnpm test -- MarketplacePage.test.tsx; pnpm build`；预期通过。
- [ ] **步骤 5：浏览器验收**：配置 Playwright 只运行 `frontend/e2e/marketplace.spec.ts`；执行 `cd frontend; pnpm exec playwright test e2e/marketplace.spec.ts`；预期临时测试目录安装后列表状态变为“已安装”，坏签名测试包不安装。

## 用户输入门控

- 每个正式安装条目需有用户提供的 GitHub 仓库、固定 Release 资产 URL、资产类型、支持系统、OCI image digest、发布者公钥和 SHA-256。信息未齐时只运行测试夹具，不发布可安装条目。
- 安装第一次官方 OCI 包前需在本机确认 Docker Engine 已安装并可访问；计划不自动安装或修改 Docker 权限。

## 验收

- 安装仅接受有效签名目录中的固定 GitHub Release 资产、摘要匹配和受支持包类型。
- 默认容器无特权、无主机敏感资源访问，模型 Provider Key 不进入容器。
- 健康检查成功才登记为已安装；安装/升级失败不覆盖既有数据；卸载保留数据。
