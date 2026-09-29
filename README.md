# Lyra Hub

Lyra Hub is the application hub for the Lyra AI platform.

It provides a unified workspace, application registry, plugin runtime, page configuration, permissions and shared capability access for independently deployable AI applications such as Narrative, Printing and Hospital AI.

## Platform boundary

- **Lyra Hub** manages applications, workspace navigation, app/plugin registration and unified configuration.
- **Lyra Agent OS** manages agents, skills, tools, workflows, memory and execution governance.
- **Lyra Gateway** manages model providers, routing, quota, cost and model access.
- **Business applications** own their own business logic, pages, data and deployment lifecycle.

> Applications remain independently runnable and deployable. Hub integration is an additional mode, not a replacement for standalone operation.

Development work is performed on the `dev` branch before promotion to `main`.
