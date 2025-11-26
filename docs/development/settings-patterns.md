# Settings and Configuration Patterns

This document defines how runtime configuration is modeled, validated, and
consumed in the AI Workflow system. It standardizes the use of Pydantic v2
and `pydantic-settings` for environment-driven configuration, with a single
`Settings` model as the authoritative source of runtime options.

The primary implementation lives in `app/core/settings.py` as the `Settings`
class, and is exposed to the rest of the application via the `get_settings`
dependency in `app/core/dependencies.py` and the `create_app` factory in
`app/core/factory.py`.

## 1. Pydantic Settings Best Practices

The application uses a single `Settings` class, implemented in
`app/core/settings.py` and subclassing `pydantic-settings.BaseSettings`, as
the canonical representation of configuration. New configuration fields must
be added to this model and follow its conventions rather than introducing
alternative patterns.

The configuration layer is responsible for:

* **Single source of truth:** All runtime options are modeled on the
  `Settings` class; configuration must not be hard-coded across routers,
  services, or infrastructure modules.
* **Environment-first configuration:** Environment variables are the primary
  source of truth, following `BaseSettings` conventions.
* **Fail-fast validation:** Invalid configuration must prevent the
  application from starting; it must never silently fall back to unsafe
  defaults.
* **Secure secrets handling:** Secrets (credentials, tokens, passwords) must
  be masked in logs and schema output and must never be embedded directly in
  source control.
* **Testability:** Settings must be trivial to override in tests via
  dependency injection and explicit `Settings` instances.

`Settings` builds on `BaseSettings`, which automatically reads values that
are not passed explicitly from the environment and applies Pydantic's type
conversion and validation. Default values defined on the model are validated
as well, so misconfigured defaults are caught at startup.

## 2. Settings Structure

The central configuration model is the `Settings` class in
`app/core/settings.py`. It groups related configuration fields into logical
areas:

* **Application identity:** `app_name`, `app_version`, and `debug` describe
  the FastAPI application and control high-level behavior.
* **Routing and prefixes:** `api_prefix` scopes versioned APIs and
  `example_prefix` controls the default example response prefix.
* **Error handling feature flags:** `include_error_body` controls whether
  request bodies are echoed back in validation error responses.
* **SurrealDB connection:** `surrealdb_url`, `surrealdb_namespace`,
  `surrealdb_database`, `surrealdb_user`, `surrealdb_pass`, and
  `surrealdb_pool_size` configure the SurrealDB RPC endpoint and pool
  behavior.
* **Elasticsearch connection:** `elasticsearch_url`,
  `elasticsearch_connections_per_node`, `elasticsearch_request_timeout`,
  `elasticsearch_shards`, and `elasticsearch_replicas` control access to the
  search backend.
* **Embedding configuration:** `embedding_dimension` captures the expected
  dimensionality of embeddings used in the knowledge graph.
* **Middleware toggles:** `enable_gzip`, `enforce_https`, `allowed_hosts`, and
  CORS controls such as `cors_allow_origins`, `cors_allow_methods`,
  `cors_allow_headers`, `cors_expose_headers`, `cors_allow_credentials`, and
  `cors_max_age` gate runtime middleware behavior.

Naming must be descriptive and explicit. For example, prefer
`surrealdb_url` to `db_url`, and `elasticsearch_connections_per_node` to
`connections`. New configuration fields should follow this pattern and be
added to the `Settings` class rather than spread across module-level
constants.

## 3. Environment Variables and .env Files

`Settings` is a subclass of `BaseSettings`, so environment variables are the
authoritative configuration source:

* Each field maps to an environment variable using Pydantic's standard
  naming rules (e.g. `surrealdb_url` reads from `SURREALDB_URL` by default).
* Defaults defined on the model are used when the corresponding environment
  variable is not set.
* For secrets, production deployments must provide values via environment
  variables or a secrets manager; they must not rely on `.env` files
  checked into source control.

Local development may use `.env` files or other tooling to populate
environment variables. When the project standardizes on an `env_file`
pattern (for example via `Settings.model_config` with
`env_file=(".env", ".env.prod")`), this file-based configuration is treated
as a convenience layer over the environment, not as a replacement for it.

Regardless of how values are supplied, the `Settings` initializer always
performs type conversion and validation before the application starts.

## 4. Field Validation Patterns

The `Settings` class uses Pydantic v2 `@field_validator` decorators and
custom exception types to enforce domain-specific rules on configuration
fields.

### 4.1 URL validation

Two dedicated validators enforce URL correctness:

* `_validate_surrealdb_url` ensures that `surrealdb_url` uses one of the
  supported schemes (`ws`, `wss`, `http`, or `https`) and that a host is
  present. On failure, it raises `InvalidSurrealUrlError`.
* `_validate_elasticsearch_url` ensures that `elasticsearch_url` uses
  `http` or `https` and that a host is present. On failure, it raises
  `InvalidElasticsearchUrlError`.

Both validators rely on `urllib.parse.urlsplit` to inspect the URL.
Constructing `Settings` with an invalid URL causes a `ValueError` with a
clear, domain-specific message, preventing the application from starting with
an unusable endpoint.

### 4.2 Numeric field validation

Numeric configuration values that represent counts, sizes, or timeouts must
never be zero or negative unless explicitly modeled as such. The
`Settings` class applies this rule consistently:

* `_validate_positive` validates fields such as `surrealdb_pool_size`,
  `elasticsearch_connections_per_node`, `elasticsearch_request_timeout`,
  `elasticsearch_shards`, and `embedding_dimension`. If any of these are
  less than or equal to zero, the validator raises
  `PositiveIntegerValidationError`, embedding the offending field name in the
  error message.
* `_validate_non_negative` validates `elasticsearch_replicas` to ensure it is
  zero or positive, raising `NonNegativeElasticsearchReplicasError` when
  violated.

These validators are declared on the `Settings` class and operate at startup
time. Misconfigured numeric values cause startup to fail fast with clear
messages, rather than producing subtle runtime behavior (such as an empty
connection pool or disabled indexing).

### 4.3 Validation of defaults

Because `Settings` inherits from `BaseSettings`, default values are validated
by default. This means that changes to default pool sizes, shard counts, or
timeouts must continue to satisfy the validators; an invalid default will
surface as an error during application startup rather than in production
traffic.

## 5. Credential Security and Complexity

The `Settings` class includes credential fields for SurrealDB:

* `surrealdb_user`
* `surrealdb_pass`

Both fields are defined using `pydantic.Field` with strong security
constraints:

* **Minimum length:** Credentials must be at least 12 characters long.
* **Complexity pattern:** Both fields use a deliberate
  `CREDENTIAL_COMPLEXITY_PATTERN` regex that enforces the presence of
  uppercase letters, lowercase letters, digits, and special characters.
  Because Pydantic's underlying regex engine does not support lookahead
  assertions, this pattern enumerates valid permutations instead of relying
  on lookaheads.

The credential complexity rules enforce the following requirements:
* Must contain at least one uppercase letter (A-Z)
* Must contain at least one lowercase letter (a-z)
* Must contain at least one digit (0-9)
* Must contain at least one special character (non-alphanumeric)
* Must be at least 12 characters in total length
* **Secret representation:** `repr=False` prevents credential values from
  appearing in model `repr` output or logs derived from it.
* **OpenAPI schema hints:** `json_schema_extra={"format": "password"}` marks
  these fields as password-like in generated schemas so tooling can treat
  them as secrets.

When constructing `Settings`, invalid credentials (too short or not matching
the complexity pattern) produce validation errors and prevent startup.

Tests in `tests/unit/test_validation_errors.py` demonstrate how to generate
safe test credentials using helpers like `_generate_test_credential` and the
`_build_settings` factory. This pattern should be followed whenever tests
need to instantiate `Settings` with real credential values.

## 6. Environment-Specific Behavior

The `Settings` model supports multiple environments (development, staging,
production, test) via different environment variable values rather than
environment-specific subclasses.

Key fields for environment-specific behavior include:

* `debug`: Enables development diagnostics such as more verbose logging and
  more permissive error responses when combined with other flags.
* `include_error_body`: Controls whether request bodies are echoed back in
  validation error responses, primarily for debugging and non-production
  environments.

Typical patterns:

* **Development:** `DEBUG=true` and `INCLUDE_ERROR_BODY=true` to maximize
  observability while working locally.
* **Staging:** `DEBUG=false` but `INCLUDE_ERROR_BODY` may be enabled for
  limited troubleshooting in non-public environments.
* **Production:** `DEBUG=false` and `INCLUDE_ERROR_BODY=false` to avoid
  leaking request payloads in error responses.

Environment selection is an operational concern; no branching logic based on
"environment name" should live in the `Settings` model. Instead, use
different environment variable values for each environment.

## 7. Accessing Settings at Runtime

There are two primary ways application code obtains configuration:

1. **Application factory:** `create_app` in `app/core/factory.py` accepts a
   `Settings` instance and attaches it to `app.state.settings` during
   application construction. This is the canonical entry point used by tests
   and startup scripts.
2. **Dependency injection:** `get_settings` in `app/core/dependencies.py`
   returns a cached `Settings` instance using `functools.lru_cache`. Routers
   or other dependencies can declare `settings: Settings = Depends(get_settings)`
   to obtain configuration without reconstructing the model.

The patterns for using settings are:

* **Routers:** Accept `Settings` as a dependency and pass it into services or
  infrastructure factories as needed; routers must not construct `Settings`
  directly.
* **Services:** Receive `Settings` via constructor injection (see
  `docs/development/service-patterns.toon`) and use it for configuration-dependent
  behaviour, such as timeouts or feature flags.
* **Infrastructure:** Connection factories such as `create_surrealdb_pool`
  and `create_elasticsearch_wrapper` receive `Settings` instances and read
  only the fields they need.

In all cases, configuration should flow from a single `Settings` instance
created at startup; additional instances should only be created explicitly in
tests. For additional patterns on services that consume settings, see
`docs/development/service-patterns.toon`.

## 8. Settings in Tests

Tests must be able to construct reproducible `Settings` instances with safe
defaults and override only the fields relevant to each scenario.

Patterns in this codebase include:

* `tests/conftest.py` defines a `test_settings` fixture that returns a
  `Settings` instance with default values, used for integration tests via the
  `test_app` and `async_client` fixtures.
* The `client_include_error_body` fixture in `tests/conftest.py` demonstrates
  how to enable `include_error_body` for specific tests by calling
  `test_settings.model_copy(update={"include_error_body": True})` before
  constructing the app.
* `tests/unit/test_validation_errors.py` defines a `_build_settings` helper
  that constructs `Settings` with generated credentials satisfying the
  complexity pattern while toggling `include_error_body` as needed.

When tests need custom configuration, they should:

1. Start from a known-safe `Settings` instance (either via fixtures or
   `_build_settings`).
2. Use `model_copy(update={...})` or direct constructor arguments to override
   specific fields.
3. Pass the resulting `Settings` instance into `create_app` or override
   `get_settings` using FastAPI's `app.dependency_overrides`, rather than
   mutating global state.

## 9. Database and Search Settings

The following fields configure the database and search backends:

* **SurrealDB:**
  * `surrealdb_url`
  * `surrealdb_namespace`
  * `surrealdb_database`
  * `surrealdb_user`
  * `surrealdb_pass`
  * `surrealdb_pool_size`
* **Elasticsearch:**
  * `elasticsearch_url`
  * `elasticsearch_connections_per_node`
  * `elasticsearch_request_timeout`
  * `elasticsearch_shards`
  * `elasticsearch_replicas`
* **Embeddings:**
  * `embedding_dimension`

Validators enforce that pool sizes, timeouts, shard counts, and embedding
dimensions are positive and that Elasticsearch replicas are non-negative.
Connection lifecycle and pooling strategies are handled by
`app/infrastructure/db_connections.py` and are documented in
`connection-pooling-patterns.md`; this document focuses on how settings
define the expected configuration for those components.

## 10. Feature Flags

Settings can act as lightweight feature flags. The primary examples today
are:

* `debug`: Governs high-level debug behavior, logging verbosity, and other
  non-sensitive diagnostics.
* `include_error_body`: Controls whether the validation exception handler
  echoes request bodies in error responses.

The validation exception handler in `app/core/exceptions.py` reads
`request.app.state.settings` and, when `include_error_body` is `True`, builds
an `HTTPValidationError` from `app/contracts/errors.py` that includes a
`body` field mirroring the request payload. When the flag is `False`, the
`body` field is omitted and only the `detail` field is returned.

New feature flags should:

* Be added as boolean fields on `Settings`.
* Be consumed in routers, middleware, or services via dependency-injected
  `Settings` or `app.state.settings`.
* Default to the safest behaviour for production; more permissive behavior
  should require explicit opt-in via environment variables.

For complex or frequently changing flags, integrating with a dedicated
feature flag service is possible, but that is outside the scope of this
document.

## 11. Settings Documentation and Naming

All `Settings` fields should be self-documenting through descriptive names
and type hints. Additionally:

* Document every `Settings` field in `app/core/settings.py` using docstrings
  or field-level comments that state its purpose, default value, valid
  range, and the corresponding environment variable name (for example,
  `SURREALDB_URL`, `SURREALDB_USER`).
* Keep environment variable names aligned with field names using
  `BaseSettings` conventions (for example, `surrealdb_url` → `SURREALDB_URL`,
  `surrealdb_user` → `SURREALDB_USER`).
* Ensure defaults and valid ranges are consistent with operational
  expectations; for example, default pool sizes suitable for local
  development, not production maximums.

Configuration that is not modeled on `Settings` is effectively undocumented
and should be refactored into the settings model.

## 12. Anti-Patterns to Avoid

The following practices are explicitly discouraged:

* **Hardcoding configuration values:** Do not embed URLs, credentials, or
  environment-specific constants directly in routers, services, or
  infrastructure modules.
* **Global mutable configuration:** Do not use module-level globals or
  ad-hoc singletons for configuration; always use `Settings` instances.
* **Bypassing validation:** Do not construct partial configuration objects or
  skip validators when adding new fields; always rely on `Settings`
  initialization to enforce invariants.
* **Leaking secrets:** Never log credential values or include them in error
  messages; rely on `repr=False` and avoid string interpolation of secret
  fields.
* **Divergent patterns:** Do not introduce alternative configuration models
  or patterns in new modules. All configuration must ultimately be routed
  through `Settings` and its associated helpers.

By following these patterns, configuration remains centralized, validated,
and secure, making the system easier to operate and evolve over time.
