# Workspace Context Bridge v1

Status: MVP contract frozen
Version: 1.0

Lyra Hub and an iframe application communicate through browser `postMessage`. The application remains independently runnable and does not import Hub code.

## Handshake

1. Hub appends `lyraHub=1&lyraHubOrigin=<origin>` to the iframe URL.
2. The application validates the configured Hub origin and sends `lyra.app.ready`.
3. Hub validates both `event.source` and the application's Manifest `allowedOrigins`.
4. Hub sends `lyra.workspace.init` with Workspace Context v1.

## Context

The context contains locale, theme, optional identity/tenant information, and only the capability IDs declared by that application.

Identity is intentionally anonymous until the platform identity service is connected. Applications must not infer a user or tenant when `authenticated=false`.

## Capability calls

An embedded application may send:

```json
{
  "type": "lyra.capability.invoke",
  "version": "1.0",
  "requestId": "unique-id",
  "capability": "agent.run",
  "payload": {}
}
```

Hub invokes only capabilities declared in the application's Manifest. Results return as `lyra.capability.result` with the same request ID.

Provider/API credentials never cross the browser bridge.
