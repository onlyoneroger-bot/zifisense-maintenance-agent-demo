# Public interface documentation

## REST OpenAPI

- `specs/纵行科技_智能运维Agent_比赛Demo_API_v1.openapi.yaml`

The OpenAPI file describes the complete intended REST V1 contract. The runtime currently implements the subset documented in the repository root `README.md`.

Runtime behavior and automated tests are authoritative for what is currently implemented.

## MCP Streamable HTTP

- `specs/纵行科技_智能运维Agent_MCP_Tools_v1.md`

The runtime endpoint is `/mcp`. `tools/list` is the machine-readable authority for Tool input and output schemas.
