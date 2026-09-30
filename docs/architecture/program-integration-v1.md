# Program Integration v1

Status: implementation on `feature/program-integration-v1`
Version: 1.0
Date: 2026-09-30

Lyra Hub supports more than one integration shape. A business program stays independently runnable and adopts only the transports it needs.

## Integration matrix

| Need | Transport | Status |
| --- | --- | --- |
| Embed an application's UI inside Hub | Workspace Bridge v1 over browser `postMessage` | implemented |
| Call Hub capabilities from another backend/service | REST + OpenAPI + per-application Bearer token | implemented |
| Expose tools/resources to AI hosts | MCP adapter | planned |
| Coordinate an independent remote AI agent | A2A adapter | planned |
| Publish asynchronous cross-application events | CloudEvents-compatible webhook/event bus | planned |

Do not require every application to implement MCP or A2A. Normal business services should use REST/OpenAPI. AI-specific protocols should be adapters at the Hub boundary.

## REST service-to-service contract

Discovery:

- `GET /api/v1/integration`
- `GET /api/v1/integration/apps/{app_id}`
- `GET /openapi.json`

Invocation:

`POST /api/v1/integration/apps/{app_id}/capabilities/{capability}/invoke`

Request:

```json
{
  "payload": {
    "prompt": "example"
  }
}
```

Authentication:

```http
Authorization: Bearer <application-token>
```

Tokens are configured only in the Hub backend through `LYRA_APP_TOKENS_JSON` or an injected token registry. They MUST NOT be placed in App Manifests, frontend source, Workspace Context, or the browser bridge.

The Hub validates, in order:

1. the application exists;
2. an external integration credential is configured;
3. the caller is authenticated as that application;
4. the application is enabled;
5. the requested capability is declared in the application's `capabilities.consumes`;
6. the capability exists in the Hub capability catalog;
7. the Hub invokes the backing platform service.

Successful calls are audited without storing the request payload.

## Workspace Bridge

UI embedding continues to use Workspace Context Bridge v1. The browser bridge is intentionally separate from server-to-server authentication.

The child application validates the Hub origin and parent window. The Hub validates the child window and the Manifest's `allowedOrigins`. Provider and platform credentials never cross this bridge.

## Capability ownership

There are three categories:

- Platform capabilities: owned by Lyra Gateway or Agent OS and routed by Hub. Existing examples include `model.generate`, `agent.run`, and `workflow.compile`.
- Application-provided capabilities: declared by an application such as `print.execute`. These need an application adapter/endpoint registry and are the next implementation slice.
- Shared data capabilities: examples include `file.read` and knowledge access. These should be backed by a dedicated storage/knowledge service instead of direct filesystem access from arbitrary applications.

A Manifest declaration is permission intent, not proof that the capability is currently routable. `/api/v1/capability-dependencies` remains the runtime availability view.

## Next adapters

### CloudEvents-compatible events

Use the existing `event-envelope.schema.json` as the Lyra domain envelope and map it to CloudEvents fields for webhook or broker delivery. Initial delivery should support:

- event publish endpoint;
- subscription registration;
- signed webhook delivery;
- idempotency by event ID;
- retry with bounded exponential backoff;
- dead-letter storage;
- correlation and causation IDs.

Payloads should carry references and minimal metadata by default.

### MCP

Add an MCP server adapter when AI hosts need Lyra tools/resources. Map approved Hub capabilities to MCP tools and resource discovery. Do not expose provider credentials or unrestricted internal HTTP endpoints.

### A2A

Add A2A only for independently deployed agents that need task-oriented collaboration. Keep Agent OS as the execution/governance owner and let Hub advertise or route approved agents.

## Production hardening

The v1 per-application static token is suitable for the current local/integration baseline. Before public multi-tenant deployment:

- move tokens to a managed secret store and support rotation;
- prefer OAuth 2.0/OIDC client credentials or mTLS for service identities;
- add scopes derived from Manifest capabilities and permissions;
- add rate limits and quotas by application;
- propagate correlation IDs through Hub, Gateway, Agent OS, and application calls;
- sign outbound webhooks and protect against replay;
- restrict CORS separately from server-to-server authorization.
