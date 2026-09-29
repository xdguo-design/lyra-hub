# Lyra Hub PRD v0.1

Status: Baseline for review and implementation  
Date: 2026-09-29  
Product name: Lyra Hub  
Chinese positioning: AI 应用中枢

## 1. Product definition

Lyra Hub is the unified application hub for the Lyra AI product family. It connects independently deployed business AI applications into one workspace without forcing them into one monolith.

The initial business applications are:

1. Lyra Narrative — novel and content creation.
2. Lyra Print — printing platform.
3. Hospital AI — hospital-oriented AI applications.
4. Future AI business applications.

Lyra Hub is not the model gateway and is not the Agent runtime.

- Gateway owns model/provider access, routing, quota, cost and usage.
- Agent OS owns Agents, Skills, Tools, Workflows, Memory, evaluation and execution governance.
- Lyra Hub owns application registration, app launch, unified workspace, plugin contribution, page configuration and application-level governance.
- Business applications own their domain behavior, pages and data.

## 2. Core principles

### 2.1 Independent applications first

Every business application MUST preserve:

- independent frontend
- independent backend
- independent route system
- independent database or data boundary
- independent deployment
- independent version lifecycle
- independent standalone entry URL

Hub integration is an additional runtime mode.

### 2.2 Unified entrance, not duplicated pages

Lyra Hub MUST NOT require a second copy of Narrative, Printing or Hospital AI pages.

The same business application can be entered from its own URL or from Lyra Hub.

### 2.3 Capabilities are shared through contracts

Applications MUST NOT depend on internal source code of Gateway or Agent OS.

Shared access uses a capability contract such as:

- model.generate
- agent.run
- workflow.run
- knowledge.search
- file.read
- file.write
- image.generate
- event.publish
- notification.send

### 2.4 Two levels of extension

Level 1: Hub installs and manages Applications.  
Level 2: An Application can expose or consume Plugins / Widgets / Page contributions.

## 3. Goals

MVP goals:

- unified workspace for all installed business AI applications
- application registry
- install / enable / disable / configure application
- application detail page
- application launch in standalone or Hub-integrated mode
- App Manifest v1
- unified navigation configuration
- unified page / menu visibility configuration
- plugin / widget contribution registry
- role and permission mapping
- shared capability registry
- Gateway and Agent OS connection status
- audit log for application/configuration changes
- shared design tokens and shell
- application health and version overview

## 4. Non-goals for MVP

The following are explicitly deferred:

- public third-party plugin marketplace
- arbitrary untrusted plugin execution
- runtime installation of unsigned code
- full low-code page builder
- moving business databases into Hub
- replacing each application's own authentication immediately
- forcing all applications to use one frontend framework
- forcing all applications into one repository

## 5. User roles

### Platform Administrator

Can register applications, configure application entry, manage permissions, page visibility, capability access and platform settings.

### Application Administrator

Can manage one application's Hub-facing configuration, navigation, plugin enablement and role mapping.

### Developer

Can validate manifests, integration adapters, capability calls and application health.

### Business User

Can access permitted applications and application pages from the unified workspace.

## 6. Information architecture

Primary navigation:

- Overview
- Applications
- Plugins
- Page Configuration
- Capabilities
- Users & Permissions
- Operations
- Settings

Overview contains:

- My Applications
- Recent Applications
- Application health
- Gateway status
- Agent OS status
- Alerts / actions requiring attention

Applications contains:

- All
- Installed
- Available
- Disabled
- Search / category / status filtering

Application Detail contains:

- Overview
- Entry & Runtime
- Pages
- Plugins
- Permissions
- Capabilities
- Health & Logs
- Basic Settings

## 7. Application model

An Application is a complete business product.

Required conceptual fields:

- id
- name
- version
- description
- icon
- owner
- category
- standalone entry
- workspace entry
- integration type
- health endpoint
- permissions
- capabilities consumed
- capabilities provided
- page contributions
- plugin contributions

## 8. Application runtime modes

### Standalone mode

The user enters the application's own URL. The application runs without Lyra Hub.

### Hub integrated mode

The user enters from Lyra Hub. The application can receive Hub context through the integration adapter.

MVP supported integration types:

1. external — open the standalone app while preserving Hub registry and deep-link context.
2. iframe — compatible embedded mode for independent applications with cross-origin bridge rules.
3. remote — reserved contract for future micro-frontend/native remote loading; not required for MVP acceptance.

The integration type is declared in App Manifest.

## 9. Hub integration adapter

An application may provide a thin Hub adapter. It is responsible only for platform integration:

- current user / tenant context
- theme and locale
- navigation/deep-link context
- capability client
- Hub events
- page title / breadcrumb contribution
- permission checks
- telemetry correlation id

Business logic remains inside the application.

## 10. Page configuration

Hub page configuration manages shared workspace presentation, not internal business page implementation.

Configurable items:

- application name override
- icon
- navigation group
- navigation order
- page visibility
- default route
- role visibility
- badge
- theme token override within allowed scope
- slot/widget order
- default launch mode

Application-internal pages can be declared by manifest for discovery and deep-linking but remain application-owned.

## 11. Plugin and slot model

A plugin may contribute:

- widget
- action
- navigation item
- page
- slot content
- capability adapter

Initial standard slots:

- workspace.home.hero.after
- workspace.home.apps.after
- workspace.home.sidebar
- app.detail.actions
- app.detail.sidebar
- app.page.header.after

Plugins are disabled by default when required permissions are not granted.

## 12. App Manifest v1

Manifest v1 is the source of truth for Hub-facing application metadata.

The contract is stored at contracts/app-manifest.schema.json.

Manifest validation is a release gate for Hub integration.

## 13. Capability registry

Hub exposes one logical capability registry to applications.

Initial capability namespaces:

- model.*
- agent.*
- workflow.*
- knowledge.*
- file.*
- event.*
- notification.*
- audit.*

Implementations may be backed by Gateway, Agent OS, Hub services or an approved external service.

Applications consume a capability by contract rather than by importing another project's internal modules.

## 14. Identity and permissions

MVP permission model:

- Hub roles map to application permissions.
- Application still owns final authorization for business actions.
- Hub does not silently elevate application permissions.
- Launch context contains only the minimum approved identity and tenant metadata.
- Secrets are never exposed through page configuration or manifest payloads.

The final SSO provider is intentionally not locked in v0.1. The integration contract must support signed short-lived launch/session tokens and standard OIDC-compatible identity in a later phase.

## 15. Security baseline

- explicit allowlist for iframe origins
- Content-Security-Policy defined for production
- signed integration context
- no provider credentials in browser
- no application secrets in App Manifest
- permission check on backend for configuration mutations
- audit all install/enable/disable/configuration/permission changes
- plugin permission declaration required
- untrusted remote code execution is out of MVP scope

## 16. Observability

Each registered application has:

- health status
- version
- last successful health check
- last launch
- error rate summary when available
- deployment / entry URL metadata
- integration mode
- capability dependency status

Hub itself exposes /health and /ready.

## 17. Technical baseline

Frontend:

- Node.js >= 22.12
- TypeScript 5.9.x
- React 19.1.x
- Vite 7.1.x
- Ant Design 5.x
- pnpm 10.17.x

Backend:

- Python >= 3.11
- FastAPI
- Pydantic Settings
- SQLAlchemy 2.x
- Alembic
- httpx
- pytest / Ruff

Detailed pinned baseline is in docs/architecture/stack-baseline.md.

## 18. MVP pages

P0:

- Workspace Overview
- Application Center
- Application Detail
- Page Configuration
- Capabilities
- Users & Permissions
- Operations / Health
- Settings

P1:

- Plugin Center
- Audit log detail
- manifest import/validation UI
- widget/slot configuration

## 19. First integration targets

The architecture is considered validated only after these three applications are registered:

1. Lyra Narrative
2. Lyra Print
3. Hospital AI

At least two different frontend technology stacks SHOULD be represented to prove Hub is not coupled to one application framework.

## 20. MVP acceptance criteria

MVP is acceptable when:

- an application can run without Hub
- the same application can be registered in Hub by Manifest
- Hub can enable/disable the application without modifying application source
- navigation is generated from registry/configuration
- role visibility works
- application detail shows runtime/version/health metadata
- page configuration can reorder/hide application navigation
- Hub can call at least one Gateway capability through a platform adapter
- Hub can call at least one Agent OS capability through a platform adapter
- all configuration mutations are audited
- a disabled application cannot be launched from Hub
- invalid manifests fail validation with actionable errors
- Narrative, Printing and Hospital AI manifests all pass validation

## 21. Delivery order

Phase 0 — contracts and prototype baseline  
Phase 1 — Hub shell + registry + config storage  
Phase 2 — application launch + manifest validation  
Phase 3 — permissions + capability adapters  
Phase 4 — page/plugin contributions  
Phase 5 — first three application integrations  
Phase 6 — regression, security hardening and release

## 22. Locked decisions in v0.1

Locked:

- project name: Lyra Hub
- business applications stay independently runnable
- Hub, Agent OS and Gateway are separate responsibility layers
- frontend language: TypeScript
- Hub frontend framework: React
- backend language: Python
- backend framework: FastAPI
- active development branch: dev
- manifest-driven application registry
- unified page configuration does not replace business app page implementation
- MVP avoids arbitrary untrusted remote code execution

Not yet locked:

- production identity provider
- production relational database choice
- remote micro-frontend implementation
- commercial plugin marketplace model
