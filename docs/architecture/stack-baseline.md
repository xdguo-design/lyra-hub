# Technical Stack Baseline

Date: 2026-09-29

The goal is to reuse the language/runtime baseline already present in the Lyra projects instead of introducing another stack.

## Frontend

Locked baseline for Lyra Hub:

- Node.js >= 22.12.0
- package manager: pnpm 10.17.1
- TypeScript ^5.9.2
- React ^19.1.1
- React DOM ^19.1.1
- Vite ^7.1.7
- React Router ^7.9.2
- Ant Design ^5.27.4
- TanStack React Query ^5.90.2
- Zod ^4.1.11
- Vitest 5.0.1
- Playwright ^1.55.0

Reference baseline: the React console already present in lyra-print.

## Backend

Locked language/runtime baseline:

- Python >= 3.11
- FastAPI 0.141.x line
- Uvicorn 0.35.x line
- Pydantic Settings 2.x
- SQLAlchemy 2.0.x
- Alembic 1.x
- httpx 0.28.x
- pytest 8.x
- Ruff 0.13.x line

Python 3.11 is aligned with lyra-print and lyra-agents.

## Why React for Hub

Lyra Hub is a shell/configuration product rather than a business application. The existing lyra-print repository already contains a React + TypeScript management console baseline with the desired modern runtime versions. Using the same baseline allows shared linting, testing, dependency policy and future design-system extraction.

This does not require business applications to use React. Vue and other frontend applications remain valid Hub applications through the integration contract.

## Version policy

- Do not upgrade Hub language/runtime versions independently without checking lyra-print and lyra-agents compatibility.
- Runtime upgrades require CI and integration regression.
- Application integration protocol versioning is independent from UI framework versions.
