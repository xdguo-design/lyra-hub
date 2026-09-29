# Contracts

This directory contains versioned contracts shared between Lyra Hub and independently deployed applications.

Current contracts:

- app-manifest.schema.json — App Manifest v1 JSON Schema

Rules:

- contracts are backward compatible within a major version
- breaking changes require a new major version
- manifests must not contain secrets
- applications remain authoritative for business authorization
