---
name: api-contract-guard
description: Use whenever backend changes may affect the existing frontend or public API. Preserves routes, parameters, status behavior, and response schemas.
---

# API Contract Guard

## Establish the contract

Before editing:

1. Read the router, request schema, response schema, service, and relevant tests.
2. Search the repository for every caller of the endpoint.
3. When a frontend repository is available, inspect its API client and TypeScript types without modifying them.
4. Record:
   - HTTP method and path;
   - query and path parameters;
   - request body;
   - response fields and nullability;
   - pagination shape;
   - empty-state behavior;
   - expected error statuses.

## Compatibility rules

- Do not change existing paths, methods, parameter names, or required fields.
- Do not remove or rename response fields.
- Do not change field types or nullability.
- Add fields only when optional and backward compatible.
- Preserve pagination and envelope structures.
- Preserve legitimate empty responses.
- External Elasticsearch or database field names must not become API fields directly.
- Normalize external documents into internal models before business or API mapping.
- External-service failures must not expose stack traces, credentials, URLs containing secrets, or raw vendor responses.

## Validation

After editing:

1. Compare the current OpenAPI schema or response model with the pre-change contract.
2. Run focused contract or API tests.
3. Exercise:
   - normal data;
   - empty data;
   - malformed external data;
   - unavailable external service.
4. Confirm the existing frontend can continue using the same request and response types.

Do not ask for a frontend change to compensate for an avoidable backend incompatibility.
