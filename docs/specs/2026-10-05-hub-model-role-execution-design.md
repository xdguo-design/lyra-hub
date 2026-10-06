# Hub model connections and role execution

**Status:** Draft for review  
**Date:** 2026-10-05

## Goal

Complete a Hub workflow that connects to the configured model platform, creates a reusable work role, and runs a user task through an Agent that uses that role and a model.

## Current behavior

- Hub already has Gateway and Agents connection pages, with revision checks, connection checks, redacted saved credentials, and model/Agent catalog reads.
- The Hub role view only previews application navigation for a comma-separated role string. It does not create an executable role or authorize an Agent run.
- Agents already exposes tenant-scoped governance-role creation/version/publish APIs and a tenant-scoped Agent run API. An Agent version resolves its published role/persona/skill when run.
- Gateway already owns provider configuration, model routes, and model inference. Hub exposes a model-generation smoke check, but not the whole configured-role run flow.

## Proposed user flow

1. In Hub Settings, check the Gateway and Agents service connections and show model/Agent catalog readiness.
2. In a new **工作角色与任务测试** view, create a role with name, responsibilities, constraints, and a version; publish the version.
3. Create or select a runnable Agent version that references the published role and a model already registered in Gateway. Provide a concise task input and run it.
4. Show run status, output, selected Agent/version, model/usage metadata when available, and a safe error message. Retain the run ID for inspection and idempotent retry behavior.

## Integration boundaries

- Gateway remains the only owner of provider API keys and model routing. Hub should only list configured Gateway models and invoke generation through Gateway/Agents; it should not copy provider keys into Hub page configuration.
- Agents remains the owner of governance roles, Agent versions, tenant identity, and execution records. Hub should call its documented APIs rather than store a second role registry.
- Model/provider keys shown in the supplied screenshots were exposed in plaintext in the conversation. They must be rotated and are excluded from all live tests. A live test requires newly rotated credentials to be configured locally in Gateway.
- Hub-to-Agents requests must use an authenticated tenant principal with `agents:run`; do not treat `X-Lyra-Roles` or a user-supplied role string as authorization. If the current Hub connection cannot provide that principal safely, surface the missing setup instead of bypassing Agents authorization.

## UI and behavior

- Replace role visibility preview as the primary role function with an executable-role workspace; retain navigation preview only as a small permission preview if still useful.
- Provide role list, create, version/publish, Agent binding, task input, run, and result history/detail.
- Make connection readiness explicit: Gateway reachable/model available; Agents reachable/tenant authorized; Agent published and runnable.
- Do not put admin tokens in URL, logs, rendered result, or persistent browser storage. Keep upstream credentials write-only/redacted.
- Prevent duplicate submissions while running; send a unique `Idempotency-Key`; handle 401/403, 404, 409, 422, timeout/unknown outcome, and upstream unavailable with actionable messages.

## Acceptance checks

- API and UI tests cover role creation/version publishing, binding to a published role, and successful Agent run using a mocked Gateway response.
- Negative tests cover missing tenant authorization/run scope, unpublished role or Agent, disconnected Gateway, invalid model, and duplicate idempotency key.
- Browser-level flow verifies the settings readiness indicators, creates a sample novel-writing role, runs a short task, and renders returned output.
- Live provider verification is reported separately from deterministic tests and is only run after rotated credentials are configured in Gateway.

## Open decision

Confirm whether “用户角色” means an executable work role for an Agent (the interpretation used above) or an account permission role for Hub login. These are distinct systems and must not be conflated.
