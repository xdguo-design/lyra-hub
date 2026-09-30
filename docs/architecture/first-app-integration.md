# First real application integration

Status: active on `dev`
Date: 2026-09-29

## Applications

### Lyra Narrative

Repository: `xdguo-design/lyra-narrative` (`dev` integration branch)

Current Hub development contract:

- standalone UI/API: `http://127.0.0.1:8000`
- health: `http://127.0.0.1:8000/api/health`
- Hub mode: iframe
- allowed origin: `http://127.0.0.1:8000`
- application remains independently runnable

Narrative serves its own browser UI and API from the same FastAPI process, so Hub embedding does not require browser cross-origin API access for the initial MVP.

### Lyra Print

Repository: `xdguo-design/lyra-print`

Current Hub development contract:

- React console: `http://127.0.0.1:5174`
- backend: `http://127.0.0.1:8080`
- health: `http://127.0.0.1:8080/health`
- Hub mode: iframe
- allowed origin: `http://127.0.0.1:5174`
- application remains independently runnable

The Vite development server proxies `/api` and `/actuator` to the Print backend. Production must preserve the same-origin/reverse-proxy contract or configure the frontend API base explicitly.

## Cross-repository acceptance

`.github/workflows/app-integration.yml` checks out the real Narrative and Print repositories, starts their services, builds the Print React console, verifies health endpoints and confirms the UI responses do not opt out of iframe embedding.

This workflow is a Hub integration gate, not a replacement for each application's own CI.
