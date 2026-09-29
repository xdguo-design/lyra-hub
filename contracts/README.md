# Lyra Hub Contracts

Contracts are versioned independently from application UI implementations.

Current v1 contracts:

- app-manifest.schema.json — application registration and Hub integration metadata
- capability.schema.json — shared capability metadata
- permission.schema.json — permission definition format
- event-envelope.schema.json — cross-application and platform event envelope

## Naming rules

Capability IDs, permission IDs and event types use lowercase dot-separated names.

Examples:

- model.generate
- agent.run
- apps.manage
- pages.configure
- application.registered
- workflow.completed

## Security rules

- Contracts never contain credentials or provider secrets.
- Browser clients never receive model-provider credentials.
- Event envelopes carry references and minimal metadata by default, not domain records.
- Sensitive domain payloads, especially hospital/patient data, stay inside the owning application unless an explicitly approved integration contract says otherwise.
