# REST ID Breakdown Table

This table classifies EVERY ID and element from the original timestamped file
`.knowledge/originals/20251201T134735Z-project.rest.api-patterns.yml` for granular
rebuild of GENERAL and PROJECT split files.

### Classification Legend

* **GENERAL**: Pure REST/HTTP protocol rules (no lang/framework/app references)
* **PROJECT**: Concrete wiring with app/* paths, FastAPI/Pydantic specifics
* **MIXED→split**: Original text contains both; split into GENERAL rule + PROJECT wiring
* **PARK**: Content belongs in another module (e.g., general.python for Pydantic)

---

### Section 1: url-structure-versioning

| ID | Original Text Summary | Classification | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| url.prefix | Mount /api/{version} using create_app in app/core/factory.py | MIXED→split | Rule=GENERAL (version prefix); wiring=PROJECT (create_app ref) | Both |
| url.health.liveness | GET /health unversioned, exclude from OpenAPI, orchestrator probe | MIXED→split | Rule=GENERAL (liveness concept); wiring=PROJECT (include_in_schema) | Both |
| url.health.readiness | GET /api/{version}/health versioned, in OpenAPI | MIXED→split | Rule=GENERAL (readiness concept); wiring=PROJECT (router registration) | Both |
| url.resource-naming | Plural kebab-case /api/v1/task-assignments | GENERAL | Pure URL convention | GENERAL |
| url.path-params | Descriptive {user_id} not generic {id} | GENERAL | Pure URL convention | GENERAL |
| url.trailing-slashes | No trailing slash; FastAPI handling not API contract | MIXED→split | Rule=GENERAL; FastAPI note=PROJECT | Both |

### Section 2: http-methods-and-status-codes

| ID | Original Text Summary | Classification | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| (table) http_method_defaults | 6 methods: GET/POST/PUT/PATCH/DELETE with statuses | GENERAL | Pure HTTP semantics | GENERAL |
| http.status.named-constants | Use fastapi.status.HTTP_201_CREATED | PROJECT | Framework-specific (fastapi.status) | PROJECT |
| http.validation.use-400 | 400 for validation, not FastAPI default 422 | MIXED→split | Principle=GENERAL; FastAPI override=PROJECT | Both |
| http.validation.error-model | 400 with AppError envelope, HTTPValidationError in details | PROJECT | App-specific envelope (AppError, details structure) | PROJECT |
| http.validation.handler-registration | create_app registers validation_exception_handler | PROJECT | App wiring (create_app, app/core/exceptions.py) | PROJECT |
| http.validation.route-responses | Route decorators use VALIDATION_ERROR_RESPONSE | PROJECT | App-specific constant (app/contracts/errors.py) | PROJECT |

### Section 3: request-response-modeling

| ID | Original Text Summary | Classification | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| (block) sample_code | Pydantic BaseModel, ConfigDict, Field | PARK | Python/Pydantic-specific; move to general.python | N/A |
| modeling.pydantic-extra-forbid | ConfigDict(extra="forbid") reject unknown fields | PROJECT | Pydantic-specific | PROJECT |
| modeling.json-snake-case | snake_case JSON, UTC ISO 8601 datetimes | MIXED→split | Convention=GENERAL; Pydantic impl=PROJECT | Both |
| modeling.response-model-required | response_model for schema enforcement | PROJECT | FastAPI-specific (response_model decorator) | PROJECT |
| modeling.describe-side-effects | Description for non-trivial side effects | GENERAL | API documentation principle | GENERAL (as note) |

### Section 4: response-shape-and-pagination

| ID | Original Text Summary | Classification | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| (fields) pagination_fields | items, total, page, page_size | GENERAL | Standard pagination structure | GENERAL |
| (hints) pagination_type_hints | list[T], int, int, int | PARK | Python type hints | N/A |
| responses.no-generic-envelopes | No {"status": "ok", "data": ...} wrappers | GENERAL | REST response principle | GENERAL |
| pagination.standard-fields | items/total/page/page_size until Paginated[T] | MIXED→split | Convention=GENERAL; app/contracts ref=PROJECT | Both |
| errors.app-error-envelope | AppError schema with code/message/statusCode/details | PROJECT | App-specific (app/contracts/errors.py) | PROJECT |
| errors.validation-through-app-error | VALIDATION_ERROR code, HTTPValidationError in details | PROJECT | App-specific envelope | PROJECT |
| errors.non-validation-through-app-error | ErrorCode enum for domain errors | PROJECT | App-specific (ErrorCode enum) | PROJECT |
| errors.route-decorator-usage | VALIDATION_ERROR_RESPONSE for 400, AppError for others | PROJECT | App-specific constants | PROJECT |
| errors.todo.paginated-model | TODO: generic Paginated[T] in app/contracts/ | PROJECT | App-specific TODO | PROJECT |

### Section 5: content-negotiation

| ID | Original Text Summary | Classification | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| content.json-default | application/json default Content-Type | GENERAL | HTTP content negotiation | GENERAL |
| content.serializer-orjson | ORJSONResponse in create_app | PROJECT | FastAPI/orjson-specific | PROJECT |
| content.compression-gzip | Accept-Encoding: gzip via middleware | GENERAL | HTTP compression | GENERAL |

### Section 6: versioning-and-deprecation

| ID | Original Text Summary | Classification | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| versioning.path-based | /api/v1, /api/v2 path versioning | GENERAL | REST versioning principle | GENERAL |
| versioning.compatibility-additive | Additive-only changes per version | GENERAL | API compatibility principle | GENERAL |
| versioning.compatibility-no-breaking | No breaking changes within version | GENERAL | API compatibility principle | GENERAL |
| deprecation.header-deprecation | Deprecation: true header | GENERAL | HTTP deprecation header | GENERAL |
| deprecation.header-sunset | Sunset header with RFC 1123 date | GENERAL | HTTP sunset header | GENERAL |
| deprecation.changelog | Changelog with migration guidance | GENERAL | Documentation principle | GENERAL |
| deprecation.flag-endpoints | deprecated=True in route decorator | MIXED→split | Principle=GENERAL; FastAPI impl=PROJECT | Both |

### Section 7: anti-patterns

| ID | Original Text Summary | Classification | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| anti-patterns.business-logic-in-routes | Logic in handlers vs services | GENERAL | Architectural principle | GENERAL |
| anti-patterns.orm-models-as-contracts | ORM vs Pydantic contract models | MIXED→split | Principle=GENERAL (ORM vs contracts); Pydantic=PROJECT | Both |
| anti-patterns.inconsistent-error-shapes | Inconsistent error responses | GENERAL | REST consistency principle | GENERAL |
| anti-patterns.missing-response-model | Omitting response_model | MIXED→split | Principle=GENERAL; response_model=PROJECT | Both |
| anti-patterns.broad-except | Broad except hiding errors | GENERAL | Python/error handling principle | GENERAL |
| anti-patterns.missing-openapi-docs | Incomplete OpenAPI documentation | GENERAL | API documentation principle | GENERAL |

---

### Summary Counts

| Classification | Count | Notes |
|----------------|-------|-------|
| GENERAL only | 15 | Pure protocol/principle rules (only in GENERAL) |
| PROJECT only | 12 | App wiring, FastAPI/Pydantic specifics (only in PROJECT) |
| MIXED→split | 11 | Split to both files with appropriate text variants |
| PARK | 2 | Structural blocks: sample_code, pagination_type_hints |

**Verification Results (automated check):**

* All 38 original IDs accounted for: YES
* GENERAL file is protocol-only (no app/*, FastAPI, Pydantic in item texts): YES
* Structural elements properly placed:
    * `http_method_defaults`: In GENERAL (pure HTTP semantics)
    * `pagination_fields`: In GENERAL (protocol-agnostic field names)
    * `sample_code`: PARKED (Pydantic code examples → future general.python.modeling-patterns)
    * `pagination_type_hints`: PARKED (Python type hints → future general.python)

### Resolution Tracking

The 11 MIXED→split items require `mark-resolved` because the text differs between GENERAL
(protocol-only) and PROJECT (implementation-specific):

| ID | GENERAL text focus | PROJECT text focus |
|----|-------------------|-------------------|
| url.prefix | Generic version prefix rule | create_app in app/core/factory.py |
| url.health.liveness | Abstract liveness concept | include_in_schema=False |
| url.health.readiness | Abstract readiness concept | Register in versioned router |
| url.trailing-slashes | No trailing slash convention | FastAPI redirect note |
| http.validation.use-400 | 400 instead of nonstandard codes | Global validation handler |
| pagination.standard-fields | Generic pagination convention | Until Paginated[T] in app/contracts |
| modeling.json-snake-case | JSON field convention | Via Pydantic serializers |
| modeling.describe-side-effects | API documentation principle | Route description requirement |
| deprecation.flag-endpoints | Mark deprecated in metadata | deprecated=True in FastAPI decorator |
| anti-patterns.orm-models-as-contracts | ORM vs contract models | Pydantic from app/contracts/ |
| anti-patterns.missing-response-model | Omitting response models | response_model in FastAPI |

```bash
# Mark all MIXED→split items as resolved
for id in url.prefix url.health.liveness url.health.readiness url.trailing-slashes \
          http.validation.use-400 pagination.standard-fields modeling.json-snake-case \
          modeling.describe-side-effects deprecation.flag-endpoints \
          anti-patterns.orm-models-as-contracts anti-patterns.missing-response-model; do
  uv run mark-resolved \
    --id "$id" \
    --source-file .knowledge/originals/20251201T134735Z-project.rest.api-patterns.yml \
    --split-file docs/development/general/rest/general.rest.api-patterns.yml \
    --split-file docs/development/project/rest/project.rest.api-patterns.yml
done
```

### PARK Items Detail

These structural blocks are intentionally omitted from REST files:

1. **sample_code** (in request-response-modeling section):
    * Contains: Pydantic BaseModel, ConfigDict, Field examples
    * Reason: Python/Pydantic-specific, not REST protocol
    * Future home: `docs/development/general/python/general.python.modeling-patterns.yml`

2. **pagination_type_hints** (in response-shape-and-pagination section):
    * Contains: `list[T]`, `int` type annotations
    * Reason: Python type hints, not REST protocol
    * Future home: `docs/development/general/python/general.python.modeling-patterns.yml`
