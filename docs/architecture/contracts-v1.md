# Lyra Hub Integration Contracts v1

Status: frozen for MVP implementation
Date: 2026-09-29

## Contract set

Phase 0 freezes four integration contracts:

1. App Manifest v1
2. Capability Definition v1
3. Permission Definition v1
4. Event Envelope v1

All business applications remain independently runnable. These contracts describe how they join Lyra Hub; they do not move business ownership into Hub.

## Capability boundary

Initial platform capabilities include:

- model.generate, model.list and provider.health.read — Lyra Gateway
- agent.run, workflow.run and knowledge.search — Lyra Agent OS
- file.read and file.write — approved platform/application file boundary
- event.publish — Hub event boundary

Applications consume a capability by stable name and must not import Gateway or Agent OS internals.

## Permission naming

Permissions use resource.action naming. Hub MVP starts with:

- apps.read
- apps.manage
- plugins.read
- plugins.manage
- pages.read
- pages.configure
- capabilities.read
- capabilities.invoke
- permissions.read
- permissions.manage
- operations.read
- settings.manage

Business applications may declare their own namespaces such as narrative.write or printing.operate.

## Event envelope

Cross-application events use Event Envelope v1. Payloads should contain identifiers and state transitions by default, not complete business records.

Initial event types:

- application.registered
- application.enabled
- application.disabled
- application.config.updated
- capability.invoked
- capability.failed
- workflow.completed
- workflow.failed

Hospital/patient information must not be placed on the shared event bus by default.

## Versioning and runtime guarantees

- schemaVersion 1.0 is the MVP contract version.
- Breaking field or semantic changes require a new major version.
- Standalone mode must work without Hub.
- Hub treats Gateway and Agent OS as external platform services.
- Manifests never contain secrets.
- Hub may reject invalid manifests or unapproved capability/permission requests.
