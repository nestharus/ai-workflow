# Generating OpenAPI Schema

Generates the OpenAPI 3.1 schema JSON file from the FastAPI application code.

* **Usage**: `uv run app.api.generate`
* **Output**: Saves to `openapi/openapi.json`
* **Note**: This script must be run before `lint` or security scans to ensure the schema
  is up-to-date
* **Timeout guidance**: Allow up to 2 hours for this command; do not stop it early when
  invoked via `uv run`
