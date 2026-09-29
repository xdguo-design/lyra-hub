# Lyra Hub Architecture v0.1

## Layer model

Business Applications
- Lyra Narrative
- Lyra Print
- Hospital AI
- future applications

Application Hub
- Workspace Shell
- App Registry
- Plugin Registry
- Page Configuration
- Permission Mapping
- Capability Registry
- Operations / Audit

AI Runtime
- Lyra Agent OS
- Agents
- Skills
- Tools
- Workflows
- Memory
- Evaluation

AI Infrastructure
- Lyra Gateway
- Models
- Providers
- Routing
- Quota
- Cost
- Usage

Cross-cutting platform services
- identity context
- tenant context
- secrets boundary
- files
- events
- notifications
- audit
- telemetry
- design tokens

## Hard boundaries

1. Hub does not own business domain data.
2. Hub does not call model providers directly when Gateway is available.
3. Hub does not execute Agent logic that belongs to Agent OS.
4. Business apps do not import Gateway or Agent OS internals.
5. Hub integration must not become a startup dependency for standalone application mode.
6. App manifests contain metadata and permissions, never secrets.
7. The browser never receives provider credentials.

## Runtime interaction

User -> Lyra Hub -> Business Application -> Capability Client -> Gateway / Agent OS / approved platform service.

Standalone path remains valid:

User -> Business Application -> its own backend -> approved shared platform capability.

## Application integration modes

external:
- safest first integration
- Hub controls discovery, permissions and launch
- application owns full browser shell

iframe:
- compatible embedded experience
- strict origin allowlist
- postMessage bridge is versioned
- application remains independently deployed

remote:
- future native micro-frontend mode
- reserved by contract
- not required for MVP

## Why external + iframe first

The current application portfolio is heterogeneous. Some apps are Vue, some are React, and some server-render their pages. The MVP therefore integrates at protocol boundaries instead of forcing a frontend rewrite.

## Data ownership

Hub database stores only Hub-owned entities such as:

- application registry
- application installation/configuration
- page/navigation configuration
- role mappings
- plugin registry/configuration
- audit records
- health snapshots
- capability registration metadata

Business records stay in the business application.

## Suggested backend modules

app/
- api/
- domain/
  - applications/
  - plugins/
  - pages/
  - permissions/
  - capabilities/
  - operations/
- integrations/
  - gateway/
  - agent_os/
- infrastructure/
  - db/
  - security/
  - audit/
- main.py

## Suggested frontend modules

src/
- app/
- pages/
- features/
  - applications/
  - plugins/
  - page-config/
  - capabilities/
  - permissions/
  - operations/
  - settings/
- platform/
  - api/
  - auth/
  - events/
  - theme/
- components/
- styles/
