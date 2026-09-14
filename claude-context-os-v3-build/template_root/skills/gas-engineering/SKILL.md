---
description: Use for Google Apps Script scripts, web apps, triggers, deployments, Sheets integrations, quotas, PropertiesService, clasp, or GAS architecture work.
---
# GAS Engineering

Inspect entry points, manifest, triggers, deployment assumptions, PropertiesService usage, external services, and quota-sensitive loops before changing code. Preserve existing entry points and deployment contracts unless explicitly changing them. Never move secrets into source or documentation.

For web apps, confirm `doGet`/`doPost`, HTML service boundaries, client/server calls, authorization scope, and production URL implications. For triggers, distinguish simple vs installable triggers and preserve ownership/account assumptions. Validate with the smallest available local/static checks plus Apps Script execution evidence when accessible.
