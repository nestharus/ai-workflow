# Module Definitions

This document serves as the authoritative reference for domain definitions, scope definitions, and
pattern definitions. It is the foundation for semantic classification by the knowledge-analyzer
agent and validation tooling.

> **Note:** Legacy precedence rules removed. Classifier now supports multi-domain tagging per
> chunk. See `docs/development/domain-definitions.yml` for the canonical domain registry.

## Section 1: Domain Descriptions

Domains are independent tags for classification and searching. Content can have multiple domains.

### Domain Registry

| Domain | Description |
|--------|-------------|
| `rest` | HTTP/REST protocol rules, URL structure, status codes, HTTP methods |
| `fastapi` | FastAPI framework patterns, decorators, dependencies |
| `python` | Python language conventions, async/await, type hints |
| `surrealdb` | SurrealDB database patterns, SurrealQL, client usage |
| `elasticsearch` | Elasticsearch patterns, queries, client usage |

> **Canonical Reference:** See `docs/development/domain-definitions.yml` for the authoritative
> domain registry with full descriptions.

---

## Section 2: Multi-Domain Tagging

Domains are independent tags. Content mentioning multiple domains (REST URL + FastAPI mounting)
gets all relevant tags (`['rest', 'fastapi']`). No precedence or single-domain rule. Classifier
outputs represent applied domain tags as a `domains` field containing a list (e.g.,
`"domains": ["rest", "fastapi"]`).

---

## Section 3: Scope Definitions

Every file is either GENERAL (reusable knowledge) or PROJECT (project-specific knowledge).

### GENERAL Scope

**Definition:** Knowledge that applies to any project using the same technology stack.

**Includes:**

* REST/HTTP protocol rules
* FastAPI framework best practices
* Python language conventions
* Database patterns (SurrealDB, Elasticsearch)
* Content that does not reference `app/*` paths (necessary but not sufficient—see note below)

**Excludes:**

* References to `app/*` paths
* Project-specific components (`AppError`, `create_app`, `RepositoryBase`)
* Implementation wiring specific to this project
* Project-specific naming conventions

**Note:** The absence of these exclusions (e.g., no `app/*` references) is necessary for GENERAL scope
but not sufficient. Content must also pass the test question: "Could this rule apply to a different
project using the same stack?"

**Test Question:** "Could this rule apply to a different project using the same stack?"

**Examples - GENERAL:**

```yaml
# general.rest.api-patterns.yml
- id: url-versioning
  content: "Use /api/{version} prefix for API versioning"
  # Applies to any REST API project

# general.fastapi.router-patterns.yml
- id: router-prefix
  content: "Use prefix parameter in APIRouter for route grouping"
  # Applies to any FastAPI project

# general.python.docstrings-guide.yml
- id: google-style
  content: "Use Google-style docstrings for functions"
  # Applies to any Python project
```

### PROJECT Scope

**Definition:** Knowledge specific to this project's implementation.

**Includes:**

* Concrete `app/*` paths (e.g., `app/core/factory.py`)
* Project-specific components (`AppError`, `create_app`, `RepositoryBase`)
* Implementation wiring (how components are connected)
* Project-specific conventions and decisions

**Excludes:**

* Restating GENERAL principles
* Generic framework documentation
* Language tutorials

**Note:** PROJECT content should reference GENERAL principles where applicable rather than restating
them. PROJECT explains where and how general rules are implemented in this codebase.

**Test Question:** "Is this knowledge specific to this project's implementation (files, components, decisions, or conventions)?"

**Examples - PROJECT:**

```yaml
# project.fastapi.factory-patterns.yml
- id: create-app-function
  content: "The create_app function in app/core/factory.py constructs the FastAPI application"
  # References specific file path

# project.python.exception-patterns.yml
- id: app-error-usage
  content: "Use AppError from app/core/errors.py for all application errors"
  # References project-specific component

# project.surrealdb.repository-patterns.yml
- id: repository-base
  content: "All repositories inherit from RepositoryBase in app/repositories/base.py"
  # References project-specific base class
```

**Important:** While `app/*` references are a strong indicator of PROJECT scope, they are not the
only way content can be project-specific. Project-specific decisions, conventions, or rules that
don't happen to mention file paths are still PROJECT scope if they cannot reasonably apply to
another project using the same stack. The flowchart below captures this logic: `app/*` references
immediately classify content as PROJECT, but absence of such references triggers further questions
to determine if the content is project-specific in other ways.

### Scope Decision Flowchart

```plaintext
Is there a reference to app/* paths?
├── Yes → PROJECT
└── No
    └── Does it reference a project-specific component?
        ├── Yes → PROJECT
        └── No
            └── Could this apply to another project?
                ├── Yes → GENERAL
                └── No → PROJECT
```

---

## Section 4: Pattern Definitions

Each pattern type has a specific purpose, inclusions, exclusions, and a test question.

### api-patterns

**Purpose:** Rules for **creating and designing APIs** (not documenting existing APIs).

**Includes:**

* URL structure and versioning
* Request/response modeling
* OpenAPI documentation standards
* Deprecation metadata
* Query parameter conventions
* Path parameter conventions

**Excludes:**

* Documentation of existing APIs → `architecture`
* Implementation wiring → `factory-patterns`
* Error response design → `exception-patterns`

**Test Question:** "Is this a rule for how to create an API, or documentation of an existing API?"

**GENERAL Examples:**

* URL structure `/api/{version}` (in `rest` module, not `fastapi`)
* Request body validation rules
* Response model conventions
* OpenAPI schema generation

**PROJECT Examples:**

* Specific endpoint documentation → `architecture` (not api-patterns)
* How endpoints are mounted → `factory-patterns`

### architecture (or architectural-patterns)

**Purpose:** Documentation of **how the system is structured** and **what components exist**.

**Includes:**

* Layer integration (how services, repositories, and routers interact)
* Dependency flow (what depends on what)
* Existing APIs (what endpoints exist and what they do)
* Readiness checks (what dependencies are checked)
* Component inventory
* System boundaries

**Excludes:**

* Rules for creating APIs → `api-patterns`
* Implementation wiring → `factory-patterns`
* How to implement services → `service-patterns`

**Test Question:** "Is this describing the system's structure, or prescribing how to build it?"

**PROJECT Examples:**

* "The `/health` endpoint checks database and cache readiness"
* "The service layer delegates to repositories for data access"
* "Routers depend on services via Depends()"

**Note:** The `/health` endpoint discussion about readiness checks belongs in `architecture`, not
`api-patterns`, because it documents existing system behavior rather than prescribing API design
rules.

### factory-patterns

**Purpose:** Rules for **constructing and configuring** the application.

**Includes:**

* Application construction (`create_app`)
* Middleware registration
* Router mounting
* Default response class configuration
* Lifespan management
* Startup/shutdown hooks

**Excludes:**

* API design rules → `api-patterns`
* System architecture → `architecture`
* Middleware behavior → `middleware-patterns`

**Test Question:** "Is this about how to wire up the application at startup?"

**PROJECT Examples:**

* `create_app` function implementation
* Router mounting to `/api/{version}` (the **implementation**, not the REST convention)
* ORJSONResponse configuration as `default_response_class`
* Lifespan context manager setup

**Clarification:** The `/api/{version}` URL structure is a REST convention (→
`general.rest.api-patterns.yml`), but the code that mounts routers to that path is factory wiring
(→ `project.fastapi.factory-patterns.yml`).

### exception-patterns

**Purpose:** Rules for **handling errors** and exceptions.

**Includes:**

* Error handling strategies
* AppError usage (PROJECT scope)
* Validation error handling
* Exception handlers registration
* Error response formatting

**Excludes:**

* API error response design → `api-patterns`
* Error handling architecture → `architecture`
* HTTP status code conventions → `rest`

**Test Question:** "Is this about how to handle exceptions?"

### router-patterns

**Purpose:** Rules for **organizing and registering routers**.

**Includes:**

* APIRouter usage and configuration
* Route decorators (`@router.get`, `@router.post`)
* Endpoint wiring (connecting handlers to routes)
* Router registration patterns
* Route grouping

**Excludes:**

* API design → `api-patterns`
* Factory wiring (mounting routers) → `factory-patterns`
* Dependency injection → `dependency-patterns`

**Test Question:** "Is this about how to organize routers?"

### service-patterns

**Purpose:** Rules for **implementing the service layer**.

**Includes:**

* Service layer patterns
* Business logic delegation
* Service construction
* Service dependencies
* Transaction boundaries

**Excludes:**

* API layer → `router-patterns`
* Data access → `repository-patterns`
* Dependency injection → `dependency-patterns`

**Test Question:** "Is this about how to implement services?"

### repository-patterns

**Purpose:** Rules for **implementing data access**.

**Includes:**

* Data access patterns
* Query patterns
* Repository construction
* CRUD operations
* Query builders

**Excludes:**

* Service layer → `service-patterns`
* Database pooling → `connection-pooling-patterns`
* Database-specific syntax (belongs in database module)

**Test Question:** "Is this about how to access data?"

**PROJECT Examples:**

* `RepositoryBase` usage
* Query methods (`find_by_id`, `find_all`)
* SurrealDB-specific repository patterns

### middleware-patterns

**Purpose:** Rules for **configuring middleware**.

**Includes:**

* Middleware stack configuration
* Middleware ordering
* Middleware options
* Request/response middleware

**Excludes:**

* Factory wiring (registering middleware) → `factory-patterns`
* Architecture (middleware role) → `architecture`

**Test Question:** "Is this about how to configure middleware?"

### settings-patterns

**Purpose:** Rules for **managing configuration**.

**Includes:**

* Settings model design
* Environment variable binding
* Configuration validation
* Settings access patterns

**Excludes:**

* Factory wiring (loading settings) → `factory-patterns`
* Architecture (settings role) → `architecture`

**Test Question:** "Is this about how to manage configuration?"

### connection-pooling-patterns

**Purpose:** Rules for **managing database connections**.

**Includes:**

* Connection pool configuration
* Client management
* Connection cleanup
* Pool sizing

**Excludes:**

* Repository patterns → `repository-patterns`
* Factory wiring → `factory-patterns`

**Test Question:** "Is this about how to manage connections?"

### dependency-patterns

**Purpose:** Rules for **dependency injection**.

**Includes:**

* `Depends()` usage
* Factory functions for dependencies
* Injection patterns
* Dependency lifecycle

**Excludes:**

* Factory wiring → `factory-patterns`
* Architecture → `architecture`

**Test Question:** "Is this about how to inject dependencies?"

### docstrings-guide

**Purpose:** Documentation standards (not a pattern, but a guide).

**Includes:**

* Docstring conventions
* Formatting rules
* Documentation structure
* Example formats

**Excludes:**

* Code patterns
* Implementation guidelines

**Test Question:** "Is this about how to write documentation?"

---

## Section 5: Cross-Reference Quality Rules

PROJECT files often reference other files or modules. Follow these rules for quality cross-references:

### Rule 1: Explain the Implementation

Don't just point to a file; explain what it does.

**Bad:**

```yaml
- id: response-serialization
  content: "See project.fastapi.factory-patterns.yml for ORJSONResponse configuration."
```

**Good:**

```yaml
- id: response-serialization
  content: |
    ORJSONResponse is configured as default_response_class in the create_app
    function (app/core/factory.py) via FastAPI(default_response_class=ORJSONResponse).
    This enables automatic orjson serialization for all endpoints without per-route configuration.
```

### Rule 2: Include the File Path

Always include the concrete file path.

**Bad:**

```yaml
- id: error-handling
  content: "Errors are handled centrally."
```

**Good:**

```yaml
- id: error-handling
  content: "Errors are handled centrally in app/core/errors.py."
```

### Rule 3: Include Function, Class, or Field Name

Help readers find the exact location.

**Bad:**

```yaml
- id: app-factory
  content: "See app/core/factory.py for application setup."
```

**Good:**

```yaml
- id: app-factory
  content: "The create_app function in app/core/factory.py sets up the application."
```

### Rule 4: Describe What It Does

Explain the purpose, not just the location.

**Bad:**

```yaml
- id: middleware-setup
  content: "Middleware is configured in app/core/factory.py."
```

**Good:**

```yaml
- id: middleware-setup
  content: |
    Middleware is registered in the create_app function (app/core/factory.py):
    - CORSMiddleware for cross-origin requests
    - RequestLoggingMiddleware for request/response logging
    - ErrorHandlingMiddleware for exception translation
```

### Rule 5: Explain Why It's Relevant

Connect the reference to the current pattern.

**Bad:**

```yaml
- id: router-mounting
  content: "Routers are mounted in create_app."
```

**Good:**

```yaml
- id: router-mounting
  content: |
    Routers are mounted in the create_app function (app/core/factory.py) using
    app.include_router(). This centralizes route registration and ensures
    consistent prefix application (/api/v1).
```

---

## Section 6: Usage Guidelines

Use this document for classification decisions.

### Classification Workflow

1. Identify All Relevant Domains

   Determine which domain(s) the content relates to: `rest`, `fastapi`, `python`, `surrealdb`,
   `elasticsearch`. Content can have multiple domains.

2. Apply All Applicable Domain Tags

   * If content relates to multiple domains, tag it with ALL of them
   * Do not reduce to a single domain—use multi-domain tagging (see Section 2)
   * Example: FastAPI route with URL versioning → `['rest', 'fastapi']`

3. Determine Scope

   Use Section 3 tests:

   * GENERAL: "Could this apply to a different project?"
   * PROJECT: "Does this reference a specific file or component?"

4. Determine Pattern

   * Use Section 4 test questions
   * Match content to the pattern whose test question gets a "yes"

5. Consider Splitting

   * If content spans multiple scopes or patterns, split into separate items
   * Each item should have a single scope and pattern
   * Multi-domain items do NOT need splitting—domains are independent tags

### Example Classification

**Content:** "The `/api/v1` prefix is used for all API routes. Routers are mounted in `create_app` using
`app.include_router(router, prefix='/api/v1')`."

**Analysis:**

1. Domains: `['rest', 'fastapi']` — URL structure relates to REST, router mounting relates to FastAPI
2. Scope: References `create_app` → PROJECT for the mounting part; URL convention → GENERAL
3. Pattern: URL structure → `api-patterns`; mounting → `factory-patterns`

**Decision:** Split by scope (not by domain):

* `general.rest.api-patterns.yml`: URL versioning convention (domains: `['rest']`)
* `project.fastapi.factory-patterns.yml`: Router mounting implementation (domains: `['fastapi']`)

Note: The split is based on scope (GENERAL vs PROJECT), not domain. If both parts were GENERAL,
they could remain together with domains: `['rest', 'fastapi']`.

### Primary Consumer

The knowledge-analyzer agent (`.claude/agents/knowledge-analyzer.md`) is the primary consumer of this
document. The agent should:

1. Use these definitions for semantic classification instead of keyword matching
2. Apply all relevant domain tags to content (no single-domain resolution)
3. Use test questions to validate scope and pattern classifications
4. Reference this document when explaining classification decisions
