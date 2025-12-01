# REST ID Breakdown Table

This table classifies EVERY ID and element from the original timestamped file
`.knowledge/originals/20251201T134735Z-project.rest.api-patterns.yml` for granular
rebuild of GENERAL and PROJECT split files.

## Classification Legend

* **GENERAL**: Pure REST/HTTP protocol rules (no lang/framework/app references)
* **PROJECT**: Concrete wiring with app/* paths, FastAPI/Pydantic specifics
* **MIXED→split**: Original text contains both; split into GENERAL rule + PROJECT wiring
* **PARK**: Content belongs in another module (e.g., general.python for Pydantic)

---

### Section 1: url-structure-versioning

| ID | Summary | Class | Rationale | Target |
|----|---------|-------|-----------|--------|
| url.prefix | /api/{version} via create_app | MIXED | Generic prefix vs. app wiring | Both |
| url.health.liveness | GET /health unversioned | MIXED | Abstract vs. include_in_schema | Both |
| url.health.readiness | GET /api/{v}/health versioned | MIXED | Generic concept vs. routing | Both |
| url.resource-naming | Plural kebab-case | GENERAL | URL convention | GENERAL |
| url.path-params | {user_id} not {id} | GENERAL | URL convention | GENERAL |
| url.trailing-slashes | No trailing slash | MIXED | Convention vs. FastAPI | Both |

### Section 2: http-methods-and-status-codes

| ID | Summary | Class | Rationale | Target |
|----|---------|-------|-----------|--------|
| http_method_defaults | 6 methods with statuses | GENERAL | HTTP semantics | GENERAL |
| http.status.named-constants | Use fastapi.status | PROJECT | Framework-specific | PROJECT |
| http.validation.use-400 | 400 for validation | MIXED | Principle vs. override | Both |
| http.validation.error-model | AppError envelope | PROJECT | App-specific | PROJECT |
| http.validation.handler-registration | Handler in create_app | PROJECT | App wiring | PROJECT |
| http.validation.route-responses | VALIDATION_ERROR_RESPONSE | PROJECT | App const | PROJECT |

### Section 3: request-response-modeling

| ID | Summary | Class | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| sample_code | Pydantic models | PARK | Python | N/A |
| modeling.pydantic-extra-forbid | ConfigDict forbid | PROJECT | Pydantic | PROJECT |
| modeling.json-snake-case | snake_case JSON | MIXED | Convention vs impl | Both |
| modeling.response-model | response_model req | PROJECT | FastAPI | PROJECT |
| modeling.describe-side-effects | Side effect notes | GENERAL | Doc principle | GENERAL |

### Section 4: response-shape-and-pagination

| ID | Summary | Class | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| pagination_fields | items/total/page | GENERAL | Standard | GENERAL |
| pagination_type_hints | Type hints | PARK | Python | N/A |
| responses.no-generic-envelopes | No wrapper | GENERAL | REST | GENERAL |
| pagination.standard-fields | Paginated[T] | MIXED | Convention vs impl | Both |
| errors.app-error-envelope | AppError | PROJECT | App-specific | PROJECT |
| errors.validation-error | AppError for 400 | PROJECT | App | PROJECT |
| errors.domain-errors | ErrorCode enum | PROJECT | App | PROJECT |
| errors.decorator-usage | VALIDATION_ERROR | PROJECT | App const | PROJECT |
| errors.paginated-model | TODO Paginated[T] | PROJECT | App | PROJECT |

### Section 5: content-negotiation

| ID | Summary | Class | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| content.json-default | JSON default | GENERAL | HTTP | GENERAL |
| content.serializer-orjson | ORJSONResponse | PROJECT | FastAPI | PROJECT |
| content.compression-gzip | gzip middleware | GENERAL | HTTP | GENERAL |

### Section 6: versioning-and-deprecation

| ID | Summary | Class | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| versioning.path-based | /api/v1, v2 | GENERAL | REST | GENERAL |
| versioning.compatibility | Additive-only | GENERAL | Compatibility | GENERAL |
| versioning.no-breaking | No breaking | GENERAL | Compatibility | GENERAL |
| deprecation.header-deprecation | Deprecation: true header | GENERAL | HTTP deprecation header | GENERAL |
| deprecation.header-sunset | Sunset header with RFC 1123 date | GENERAL | HTTP sunset header | GENERAL |
| deprecation.changelog | Changelog with migration guidance | GENERAL | Documentation principle | GENERAL |
| deprecation.flag-endpoints | deprecated=True | MIXED | Principle vs impl | Both |

### Section 7: anti-patterns

| ID | Summary | Class | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| anti-patterns.business-logic-in-routes | Logic in handlers vs services | GENERAL | Architectural principle | GENERAL |
| anti-patterns.orm-models | ORM vs Pydantic | MIXED | Principle vs impl | Both |
| anti-patterns.error-shapes | Inconsistent errors | GENERAL | Consistency | GENERAL |
| anti-patterns.response-model | Omit response_model | MIXED | Principle vs impl | Both |
| anti-patterns.broad-except | Broad except hiding errors | GENERAL | Python/error handling principle | GENERAL |
| anti-patterns.openapi-docs | Missing OpenAPI docs | GENERAL | Documentation | GENERAL |

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
