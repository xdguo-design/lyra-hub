# 本地多项目联调

此联调拓扑把 Hub、Gateway、Agents、Narrative 和 Print 放在同一台开发机上运行。各项目数据库使用独立的本地集成库，不会覆盖仓库已有业务数据。

## 服务地址

| 服务 | 地址 | 用途 |
| --- | --- | --- |
| Hub API / 页面 | `http://127.0.0.1:8000` / `http://127.0.0.1:5173` | 平台总览、项目连接、租户管理、自动巡检 |
| Gateway API / 管理页 | `http://127.0.0.1:8765` / `http://127.0.0.1:8765/admin/` | 模型路由、租户应用与模型调用 |
| Agents API / 页面 | `http://127.0.0.1:8770` / `http://127.0.0.1:5175` | Agent 治理、多租户和运行管理 |
| Narrative API / 页面 | `http://127.0.0.1:8001` | 小说创作应用 |
| Print API / 页面 | `http://127.0.0.1:8080` / `http://127.0.0.1:5174` | 打印平台和管理控制台 |

Hub 后端默认将 Narrative 指向 `8001`。Agents 与 Print 的 Vite 代理地址、端口与表格一致；Agents 后端代理目标可用 `VITE_AGENTS_API_PROXY_TARGET` 覆盖。

## 启动

在每个项目根目录分别启动 API：

```powershell
# Gateway
$env:FREELLM_GATEWAY_DB = 'data/lyra-local-integration.sqlite3'
python -m freellm_gateway run --skip-web-build --host 127.0.0.1 --port 8765

# Agents（需设置安全配置中的三个必填密钥）
$env:LYRA_DATABASE_URL = 'sqlite:///./data/lyra-local-integration.db'
python -m uvicorn lyra_agents.main:app --host 127.0.0.1 --port 8770

# Narrative（将新数据与现有小说库分开）
$env:NOVEL_DB_PATH = "$env:LOCALAPPDATA/LyraHubIntegration/narrative-integration.db"
make run PORT=8001

# Print（在 backend/print-platform-python 目录中）
$env:PRINT_DATABASE_URL = 'sqlite:///./data/print-local-integration.db'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Hub 后端需要设置 `LYRA_HUB_ADMIN_TOKEN` 和稳定的 `LYRA_HUB_SECRET_KEY`；Gateway 需要配置 API/Admin token。凭据与加密密钥应由本机 secret store 管理，不要提交到仓库或写入前端环境变量。Hub 的 Gateway / Agents 地址和凭据可在“平台连接”页面保存；保存后 Hub 会执行连通性检查。Agents 的 Gateway 凭据按租户单独配置。

## 验收

依次请求 Hub、Gateway、Agents、Narrative、Print 的健康端点：

```text
GET http://127.0.0.1:8000/health
GET http://127.0.0.1:8765/health
GET http://127.0.0.1:8770/health
GET http://127.0.0.1:8001/api/health
GET http://127.0.0.1:8080/health
```

进入 Hub 的“自动维护”页面手动运行巡检。巡检只读探测健康状态和已授权目录，不会触发模型生成、Agent 执行或打印任务；修复动作仍需管理员确认。
