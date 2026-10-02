# Lyra Hub

Lyra Hub is the AI application hub for the Lyra platform.

## Positioning

Lyra Hub is the unified application entrance, registry, configuration center and plugin container for independently deployable business AI applications.

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
