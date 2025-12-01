# REST ID Breakdown Table

This table classifies EVERY ID and element from the original timestamped file
`.knowledge/originals/20251201T143104Z-project.rest.api-patterns.yml` for granular
rebuild of GENERAL and PROJECT split files.

## Classification Legend

* **GENERAL**: Any content not specific to this app (REST/HTTP protocol rules + FastAPI/Pydantic best practices without app/* references)
* **PROJECT-rest**: Concrete wiring in project.rest.api-patterns.yml referencing app/contracts/ paths
* **PROJECT-other**: Content covered by other PROJECT files (factory-patterns, exception-patterns, fastapi.api-patterns)
* **MIXED→split**: Original text contains both general principle AND app/* wiring; split into separate text variants
* **PARK**: Content belongs in another module (e.g., general.python for Pydantic samples, type hints)

---

### Section 1: url-structure-versioning

| ID | Summary | Class | Rationale | Target |
|----|---------|-------|-----------|--------|
| url.prefix | /api/{version} prefix | GENERAL + PROJECT-other | Convention in GENERAL; wiring in factory-patterns `router.version-prefix` | GENERAL only in rest |
| url.health.liveness | GET /health unversioned | GENERAL + PROJECT-other | Concept in GENERAL; wiring in factory-patterns `router.internal-endpoints` | GENERAL only in rest |
| url.health.readiness | GET /api/{v}/health versioned | GENERAL + PROJECT-other | Concept in GENERAL; wiring in fastapi.api-patterns `registration.health-versioned` | GENERAL only in rest |
| url.resource-naming | Plural kebab-case | GENERAL | Pure URL convention, no framework refs | GENERAL |
| url.path-params | {user_id} not {id} | GENERAL | Pure URL convention, no framework refs | GENERAL |
| url.trailing-slashes | No trailing slash | GENERAL | Pure URL convention; FastAPI behavior is implementation-specific | GENERAL |

### Section 2: http-methods-and-status-codes

| ID | Summary | Class | Rationale | Target |
|----|---------|-------|-----------|--------|
| http_method_defaults | 6 methods with statuses | GENERAL | Pure HTTP semantics, no framework refs | GENERAL |
| http.status.named-constants | Use fastapi.status | GENERAL | FastAPI best practice, no app/* refs | GENERAL |
| http.validation.use-400 | 400 for validation | GENERAL + PROJECT-other | Principle in GENERAL; wiring in exception-patterns | GENERAL only in rest |
| http.validation.error-model | AppError envelope | PROJECT-other | Covered by exception-patterns `structure.validation-failures` | exception-patterns |
| http.validation.handler-registration | Handler in create_app | PROJECT-other | Covered by exception-patterns `handlers.validation-handler` | exception-patterns |
| http.validation.route-responses | VALIDATION_ERROR_RESPONSE | PROJECT-other | Covered by exception-patterns `openapi.use-validation-constant` | exception-patterns |

### Section 3: request-response-modeling

| ID | Summary | Class | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| sample_code | Pydantic models | PARK | Python code examples → general.python | N/A |
| modeling.contracts-location | app/contracts/ location | PROJECT-rest | Unique to rest.api-patterns; about contract file locations | PROJECT rest |
| modeling.error-contracts-location | app/contracts/errors.py | PROJECT-rest | Unique to rest.api-patterns; about error contract location | PROJECT rest |
| modeling.pydantic-extra-forbid | ConfigDict forbid | GENERAL | Pydantic best practice, no app/* refs | GENERAL |
| modeling.json-snake-case | snake_case JSON + Pydantic | GENERAL | JSON convention + Pydantic, no app/* refs | GENERAL |
| modeling.response-model-required | response_model required | GENERAL | FastAPI best practice, no app/* refs | GENERAL |
| modeling.describe-side-effects | Side effect notes | GENERAL | Documentation principle, no app/* refs | GENERAL |

### Section 4: response-shape-and-pagination

| ID | Summary | Class | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| pagination_fields | items/total/page | GENERAL | Standard pagination fields, no framework refs | GENERAL |
| pagination_type_hints | Type hints | PARK | Python type hints → general.python | N/A |
| responses.no-generic-envelopes | No wrapper | GENERAL | REST principle, no framework refs | GENERAL |
| pagination.paginated-model | Paginated[T] from app/contracts/pagination.py | PROJECT-rest | Canonical pagination model exists; unique to rest.api-patterns | PROJECT rest |
| errors.app-error-envelope | AppError envelope | PROJECT-other | Covered by exception-patterns `apperror.canonical-envelope` | exception-patterns |
| errors.validation-through-app-error | AppError for validation | PROJECT-other | Covered by exception-patterns `structure.validation-failures` | exception-patterns |
| errors.non-validation-through-app-error | AppError for domain errors | PROJECT-other | Covered by exception-patterns `structure.domain-infrastructure` | exception-patterns |
| errors.route-decorator-usage | VALIDATION_ERROR_RESPONSE | PROJECT-other | Covered by exception-patterns `openapi.use-validation-constant` | exception-patterns |

### Section 5: content-negotiation

| ID | Summary | Class | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| content.json-default | JSON default | GENERAL | HTTP content negotiation, no framework refs | GENERAL |
| content.serializer-orjson | ORJSONResponse | PROJECT-other | Covered by factory-patterns `factory.fastapi-construction` | factory-patterns |
| content.compression-gzip | gzip middleware | GENERAL | HTTP compression, no framework refs | GENERAL |

### Section 6: versioning-and-deprecation

| ID | Summary | Class | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| versioning.path-based | /api/v1, v2 | GENERAL | REST versioning principle, no framework refs | GENERAL |
| versioning.compatibility-additive | Additive-only changes | GENERAL | API compatibility principle | GENERAL |
| versioning.compatibility-no-breaking | No breaking changes | GENERAL | API compatibility principle | GENERAL |
| deprecation.header-deprecation | Deprecation: true header | GENERAL | HTTP deprecation header standard | GENERAL |
| deprecation.header-sunset | Sunset header with RFC 1123 date | GENERAL | HTTP sunset header standard | GENERAL |
| deprecation.changelog | Changelog with migration guidance | GENERAL | Documentation principle | GENERAL |
| deprecation.flag-endpoints | deprecated=True | GENERAL | FastAPI decorator feature, no app/* refs | GENERAL |

### Section 7: anti-patterns

| ID | Summary | Class | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| anti-patterns.business-logic-in-routes | Logic in handlers vs services | GENERAL | Architectural principle, no framework refs | GENERAL |
| anti-patterns.orm-models-as-contracts | ORM vs contract models | MIXED→split | GENERAL has principle; PROJECT has app/contracts/ ref | Both |
| anti-patterns.inconsistent-error-shapes | Inconsistent errors | GENERAL | Consistency principle, no framework refs | GENERAL |
| anti-patterns.missing-response-model | Omit response_model | GENERAL | FastAPI best practice, no app/* refs | GENERAL |
| anti-patterns.broad-except | Broad except hiding errors | GENERAL | Error handling principle | GENERAL |
| anti-patterns.missing-openapi-docs | Missing OpenAPI docs | GENERAL | Documentation principle | GENERAL |

---

### Summary Counts (for rest.api-patterns files only)

| Classification | Count | Notes |
|----------------|-------|-------|
| GENERAL only | 26 | Protocol/principle rules + FastAPI/Pydantic practices (no app/* refs) |
| PROJECT-rest only | 4 | Contract location rules unique to rest.api-patterns |
| MIXED→split | 1 | Split to GENERAL + PROJECT rest (anti-patterns.orm-models-as-contracts) |
| PROJECT-other | 8 | Covered by factory-patterns, exception-patterns, or fastapi.api-patterns |
| PARK | 2 | Structural blocks: sample_code, pagination_type_hints → future general.python |

**Total: 41 items (39 IDs + 2 structural blocks)** - TODO item removed after Paginated[T] implementation

### PROJECT rest.api-patterns Contents (Final)

The PROJECT rest.api-patterns file contains 4 items unique to REST contract locations:

1. **modeling.contracts-location** - Where to put request/response contracts (app/contracts/)
2. **modeling.error-contracts-location** - Where error contracts live (app/contracts/errors.py)
3. **pagination.paginated-model** - Use Paginated[T] from app/contracts/pagination.py for collection endpoints
4. **anti-patterns.orm-models-as-contracts** - Use app/contracts/ not ORM models

All other PROJECT content (exception handling, router registration, factory wiring) is covered by:
- `project.fastapi.factory-patterns.yml` - create_app, router mounting, ORJSONResponse
- `project.fastapi.exception-patterns.yml` - AppError, validation handlers, error responses
- `project.fastapi.api-patterns.yml` - health endpoint registration

### PARK Items Detail

These structural blocks are intentionally omitted from REST files:

1. **sample_code** (in request-response-modeling section):
   * Contains: Pydantic BaseModel, ConfigDict, Field examples
   * Reason: Python/Pydantic-specific code examples, not REST protocol or patterns
   * Future home: `docs/development/general/python/general.python.modeling-patterns.yml`

2. **pagination_type_hints** (in response-shape-and-pagination section):
   * Contains: `list[T]`, `int` type annotations
   * Reason: Python type hints, not REST protocol
   * Future home: `docs/development/general/python/general.python.modeling-patterns.yml`

### Audit Trail

This breakdown was refined on 20251201 with the following changes:

1. **Initial classification** identified items by content type (GENERAL vs PROJECT)
2. **Refinement 1** expanded GENERAL to include FastAPI/Pydantic practices without app/* refs
3. **Refinement 2** audited every PROJECT item against existing files:
   - 9 items found to be duplicates covered by factory-patterns, exception-patterns, or fastapi.api-patterns
   - 13 movements recorded documenting where content is covered
   - PROJECT rest.api-patterns reduced to 5 unique contract-location items
   - 4 items originally MIXED→split now have PROJECT wiring in other files, only GENERAL in rest
4. **Refinement 3** (20251201): Paginated[T] implementation completed
   - `errors.todo.paginated-model` TODO removed (implemented at app/contracts/pagination.py)
   - `pagination.standard-fields` renamed to `pagination.paginated-model` and changed from MIXED→split to PROJECT-rest
   - PROJECT rest.api-patterns reduced to 4 unique items

All movements tracked in `.knowledge/movements/movements.csv` for validation.
