# OpenAPI snapshot

The **live** HTTP contract is FastAPI:

- http://localhost:8000/v1/docs
- http://localhost:8000/v1/redoc
- http://localhost:8000/v1/openapi.json

Regenerate the committed snapshot:

```bash
make export-openapi
```

Output: `docs/openapi/openapi.json` and `docs/openapi/openapi.yaml`.

This directory is not an endpoint catalog. Do not add markdown tables of routes.
