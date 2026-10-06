# Lyra Hub

Lyra Hub is the AI application hub for the Lyra platform.

## Positioning

Lyra Hub is the unified application entrance, registry, configuration center and plugin container for independently deployable business AI applications.

For the local multi-project port map, startup commands, and integration checks, see [本地多项目联调](docs/setup/local-multi-project-integration.md).

Current first-class applications:

- Lyra Narrative — novel / content creation
- Lyra Print — printing platform
- Hospital AI — hospital AI applications
- Future business AI applications

Platform boundaries:

- Lyra Hub manages applications, navigation, app/plugin registration, page configuration, shared identity context and capability access.
- Lyra Agent OS manages Agent, Skill, Tool, Workflow, Memory and execution governance.
- Lyra Gateway manages model/provider access, routing, quota, cost and usage.
- Business applications own their own domain logic, pages, data and deployment lifecycle.

A business application MUST remain independently runnable. Joining Lyra Hub adds a second integrated mode; it MUST NOT make standalone operation depend on Hub.

## Repository layout

- frontend/ — Hub web workspace, React + TypeScript
- backend/ — Hub control plane API, Python + FastAPI
- contracts/ — App Manifest and integration contracts
- examples/ — sample application manifests
- docs/product/ — PRD and product decisions
- docs/architecture/ — architecture and stack decisions
- docs/ux/ — page and prototype specifications
- prototypes/ — reviewable visual prototype assets

## Branching

- main — stable baseline
- dev — active integration branch

Development changes land on dev first and are promoted to main after regression verification.


## Integration modes

- Workspace UI: iframe + Workspace Context Bridge v1 (`postMessage`)
- Program/service integration: REST + OpenAPI + per-application Bearer authentication
- AI tool integration: MCP adapter planned
- Agent-to-agent integration: A2A adapter planned
- Async cross-application integration: persisted event outbox + HMAC-signed webhook delivery

See `docs/architecture/program-integration-v1.md`.

## Platform connection security

Hub's Gateway and Agent OS connection pages allow administrators to check, save, and restore the upstream URL and client credential. Saved credentials are encrypted in Hub's database with Fernet; configure `LYRA_HUB_SECRET_KEY` with a generated Fernet key before saving non-empty credentials. For example:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set `LYRA_HUB_ADMIN_TOKEN` to enable connection changes and billable or side-effecting capability calls. Enter this token in the Gateway or Agents page; the browser keeps it only in the current session. The server never returns saved upstream credential values. A saved database configuration takes precedence over `LYRA_GATEWAY_*` or `LYRA_AGENT_OS_*` environment values for that service; the page's “clear saved configuration” action restores the environment values. Keep both keys in the deployment secret manager and back them up together with the Hub database.

`agent.run` and `workflow.run` remain unavailable through Hub. Agents supports tenant-scoped single-Agent runs through its own API using that tenant's Gateway credentials; Hub does not proxy those runs. Workflow execution remains unavailable until Agents publishes a supported workflow-run contract. Print's `print.execute` uses the dedicated idempotent endpoint and requires an `idempotencyKey` in the capability payload. Enable Print API key RBAC in integrated deployments and grant the Hub key the operator role.
