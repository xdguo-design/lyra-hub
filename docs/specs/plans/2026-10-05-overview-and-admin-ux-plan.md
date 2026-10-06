# 总览与管理页面体验修复实施计划

> **给代理执行者：** 在当前会话中按勾选逐步执行。任务使用 `- [ ]` 勾选跟踪。

**目标：** 改善 Hub 总览加载、Gateway 凭据表单排版和租户权限错误态。

**架构要点：** 前端继续使用现有 REST API 和 React 页面结构。总览并发读取 Registry 与平台状态，但不相互阻塞；租户页面只有成功读取租户后开放写操作。

**技术栈：** React 19、TypeScript、Vitest、Vite。验证命令：`pnpm test`、`pnpm build`；后端回归命令：`python -m pytest`。

**关联设计文档：** `docs/specs/2026-10-05-overview-and-admin-ux-design.md`

---

## 文件与职责

- 修改 `frontend/src/App.tsx`：拆分核心总览刷新与平台状态刷新。
- 修改 `frontend/src/App.navigation.test.tsx`：覆盖平台状态延迟时总览仍显示应用。
- 修改 `frontend/src/PlatformPage.tsx`、`frontend/src/styles.css`：将凭据移除选项与说明排在同一操作组。
- 修改 `frontend/src/TenantsPage.tsx`：追踪租户读取授权状态并门控写操作。
- 修改 `frontend/src/TenantsPage.test.tsx`：覆盖未授权时不呈现写操作，以及授权后保留操作。

## 任务 1：总览与平台状态解耦

- [ ] 在 `frontend/src/App.navigation.test.tsx` 添加一个延迟 `/api/v1/platform/status` 的测试。完成应用和导航响应后，断言“小说工作台”已显示、页面状态不是持续等待；随后放开平台状态请求并清理组件。
- [ ] 运行 `pnpm exec vitest run src/App.navigation.test.tsx`，确认测试因当前 `refreshCore` 等待平台状态而失败。
- [ ] 修改 `App.refreshCore`：让应用、导航和 Hub 健康请求决定总览核心完成时点；将 `getPlatformStatus()` 的结果独立写入状态，并单独处理其失败。
- [ ] 再运行 `pnpm exec vitest run src/App.navigation.test.tsx`，确认全部导航测试通过。

## 任务 2：Gateway 凭据选项排版

- [ ] 在 `PlatformPage.tsx` 将清除凭据复选框包进具有明确类名的操作容器，并给说明文本加 label 文案。
- [ ] 在 `styles.css` 为该容器定义横向对齐、间距、最大宽度和窄屏换行规则；不改变现有输入和保存逻辑。
- [ ] 运行 `pnpm build`，确认 TypeScript 与 Vite 构建成功。
- [ ] 在浏览器观察 Gateway 页面，确认复选框和说明视觉上相邻、窄屏可完整阅读。

## 任务 3：租户权限错误态门控

- [ ] 在 `TenantsPage.test.tsx` 添加读取 403 时的行为测试：显示权限提示，不显示创建表单或租户停用、邀请按钮。
- [ ] 运行 `pnpm exec vitest run src/TenantsPage.test.tsx`，确认新测试因当前未授权错误态仍显示创建表单而失败。
- [ ] 在 `TenantsPage.tsx` 仅在租户读取成功后启用写操作；读取 401/403 时保留 `AdminTokenControl` 和清楚的权限说明，隐藏租户创建和行内写操作；授权保存后重新读取。
- [ ] 再运行 `pnpm exec vitest run src/TenantsPage.test.tsx`，确认授权成功时原有创建、停用和邀请测试仍通过。

## 收尾验证

- [ ] 运行 `pnpm test` 和 `pnpm build`，确认全部前端测试及生产构建通过。
- [ ] 在隔离数据库和临时 `LYRA_HUB_SECRET_KEY` 下运行 `python -m pytest`，确认后端回归测试通过。
- [ ] 在本地浏览器复查总览、Gateway 和 Agents 租户页的实际呈现，并检查 `git diff --check`。
