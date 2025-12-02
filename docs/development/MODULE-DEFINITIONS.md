# Module Definitions

This document serves as the authoritative reference for module hierarchy, precedence rules, scope definitions, and pattern definitions. It is the foundation for semantic classification by the knowledge-analyzer agent and validation tooling.

## Section 1: Module Hierarchy

Modules have parent-child relationships that determine precedence. A child module inherits context from its parent but addresses more specific concerns.

```
root
├── rest                    # HTTP/REST protocol (parent of web frameworks)
│   └── fastapi             # FastAPI framework (implements REST via Python)
├── python                  # Python language (parent of Python-based tools)
│   ├── fastapi             # FastAPI framework (built on Python)
│   ├── surrealdb           # SurrealDB Python client
│   └── elasticsearch       # Elasticsearch Python client
├── surrealdb               # SurrealDB database patterns
└── elasticsearch           # Elasticsearch patterns
```

### Module Definitions

| Module | Description | Parent(s) |
|--------|-------------|-----------|
| `rest` | HTTP/REST protocol rules, URL structure, status codes, HTTP methods | - |
| `fastapi` | FastAPI framework patterns, decorators, dependencies | `rest`, `python` |
| `python` | Python language conventions, async/await, type hints | - |
| `surrealdb` | SurrealDB database patterns, SurrealQL, client usage | `python` |
| `elasticsearch` | Elasticsearch patterns, queries, client usage | `python` |

### Dual Parentage

`fastapi` has two parents:
- **rest**: FastAPI implements REST protocol conventions
- **python**: FastAPI is a Python framework

This dual parentage affects precedence (see Section 2).

---

## Section 2: Precedence Rules

When content fits multiple modules, apply these precedence rules in order:

### Rule 1: Protocol Takes Precedence Over Framework

Content about HTTP/REST protocol belongs in `rest`, not in framework modules.

| Content | Correct Module | Incorrect Module | Reason |
|---------|----------------|------------------|--------|
| URL structure `/api/{version}` | `rest` | `fastapi` | REST protocol convention |
| HTTP methods (GET, POST, PUT, DELETE) | `rest` | `fastapi` | HTTP protocol |
| Status codes (200, 404, 500) | `rest` | `fastapi` | HTTP protocol |
| Content-Type headers | `rest` | `fastapi` | HTTP protocol |
| RESTful resource naming | `rest` | `fastapi` | REST convention |

**Example - Correct Classification:**
```yaml
# general.rest.api-patterns.yml
- id: url-versioning
  content: "Use /api/{version} prefix for API versioning (e.g., /api/v1/users)"
```

**Example - Incorrect Classification:**
```yaml
# general.fastapi.api-patterns.yml (WRONG - this is REST, not FastAPI)
- id: url-versioning
  content: "Use /api/{version} prefix for API versioning"
```

### Handling Existing Violations in Protocol Modules

The precedence rules apply bidirectionally. Just as framework content should not appear in protocol modules, **protocol modules must not contain framework- or library-specific details**. When REST documentation includes implementation-specific references—such as `fastapi.status` constants, Pydantic validation rules, or framework-specific response handling—these constitute **precedence violations** that require migration.

**Current known violations in `general.rest.api-patterns.yml`:**
- References to `fastapi.status` constants → should migrate to `general.fastapi.api-patterns.yml`
- Pydantic model validation rules → should migrate to `general.python.validation-patterns.yml` or `general.fastapi.api-patterns.yml`
- Framework-specific response modeling → should migrate to the appropriate `fastapi` module

These items are expected to be migrated to their correct modules in future cleanup phases. **MODULE-DEFINITIONS.md is the normative source** for determining where content ultimately belongs. Until migration occurs, the presence of such items in protocol modules should be treated as technical debt, not as precedent for adding similar content.

### Rule 2: Framework Takes Precedence Over Language

Content about framework-specific features belongs in the framework module, not the language module.

| Content | Correct Module | Incorrect Module | Reason |
|---------|----------------|------------------|--------|
| `response_model` | `fastapi` | `python` | FastAPI decorator parameter |
| `APIRouter` | `fastapi` | `python` | FastAPI class |
| `Depends()` | `fastapi` | `python` | FastAPI dependency injection |
| `@app.get()` decorators | `fastapi` | `python` | FastAPI route decorators |
| `BackgroundTasks` | `fastapi` | `python` | FastAPI background tasks |

**Example - Correct Classification:**
```yaml
# general.fastapi.dependency-patterns.yml
- id: depends-usage
  content: "Use Depends() for dependency injection in route functions"
```

### Rule 3: Language Takes Precedence Over Database

Content about language features belongs in the language module, even when used with databases.

| Content | Correct Module | Incorrect Module | Reason |
|---------|----------------|------------------|--------|
| `async/await` patterns | `python` | `surrealdb` | Python language feature |
| Type hints (`List[User]`) | `python` | `elasticsearch` | Python language feature |
| Context managers (`async with`) | `python` | `surrealdb` | Python language feature |
| Pydantic models | `python` | `surrealdb` | Python library |

**Example - Correct Classification:**
```yaml
# general.python.async-patterns.yml
- id: async-context-manager
  content: "Use async with for database connections"
```

### Rule 4: Most Specific Module Wins

When precedence rules don't apply, use the most specific module.

| Content | Correct Module | Reason |
|---------|----------------|--------|
| SurrealQL query syntax | `surrealdb` | SurrealDB-specific |
| Elasticsearch DSL | `elasticsearch` | Elasticsearch-specific |
| FastAPI lifespan events | `fastapi` | FastAPI-specific |

---

## Section 3: Scope Definitions

Every file is either GENERAL (reusable knowledge) or PROJECT (project-specific knowledge).

### GENERAL Scope

**Definition:** Knowledge that applies to any project using the same technology stack.

**Includes:**
- REST/HTTP protocol rules
- FastAPI framework best practices
- Python language conventions
- Database patterns (SurrealDB, Elasticsearch)
- All content described without `app/*` references

**Excludes:**
- References to `app/*` paths
- Project-specific components (`AppError`, `create_app`, `RepositoryBase`)
- Implementation wiring specific to this project
- Project-specific naming conventions

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
- Concrete `app/*` paths (e.g., `app/core/factory.py`)
- Project-specific components (`AppError`, `create_app`, `RepositoryBase`)
- Implementation wiring (how components are connected)
- Project-specific conventions and decisions

**Excludes:**
- Restating GENERAL principles
- Generic framework documentation
- Language tutorials

**Test Question:** "Does this reference a specific file, function, or component in this project?"

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

### Scope Decision Flowchart

```
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
- URL structure and versioning
- Request/response modeling
- OpenAPI documentation standards
- Deprecation metadata
- Query parameter conventions
- Path parameter conventions

**Excludes:**
- Documentation of existing APIs → `architecture`
- Implementation wiring → `factory-patterns`
- Error response design → `exception-patterns`

**Test Question:** "Is this a rule for how to create an API, or documentation of an existing API?"

**GENERAL Examples:**
- URL structure `/api/{version}` (in `rest` module, not `fastapi`)
- Request body validation rules
- Response model conventions
- OpenAPI schema generation

**PROJECT Examples:**
- Specific endpoint documentation → `architecture` (not api-patterns)
- How endpoints are mounted → `factory-patterns`

### architecture (or architectural-patterns)

**Purpose:** Documentation of **how the system is structured** and **what components exist**.

**Includes:**
- Layer integration (how services, repositories, and routers interact)
- Dependency flow (what depends on what)
- Existing APIs (what endpoints exist and what they do)
- Readiness checks (what dependencies are checked)
- Component inventory
- System boundaries

**Excludes:**
- Rules for creating APIs → `api-patterns`
- Implementation wiring → `factory-patterns`
- How to implement services → `service-patterns`

**Test Question:** "Is this describing the system's structure, or prescribing how to build it?"

**PROJECT Examples:**
- "The `/health` endpoint checks database and cache readiness"
- "The service layer delegates to repositories for data access"
- "Routers depend on services via Depends()"

**Note:** The `/health` endpoint discussion about readiness checks belongs in `architecture`, not `api-patterns`, because it documents existing system behavior rather than prescribing API design rules.

### factory-patterns

**Purpose:** Rules for **constructing and configuring** the application.

**Includes:**
- Application construction (`create_app`)
- Middleware registration
- Router mounting
- Default response class configuration
- Lifespan management
- Startup/shutdown hooks

**Excludes:**
- API design rules → `api-patterns`
- System architecture → `architecture`
- Middleware behavior → `middleware-patterns`

**Test Question:** "Is this about how to wire up the application at startup?"

**PROJECT Examples:**
- `create_app` function implementation
- Router mounting to `/api/{version}` (the **implementation**, not the REST convention)
- ORJSONResponse configuration as `default_response_class`
- Lifespan context manager setup

**Clarification:** The `/api/{version}` URL structure is a REST convention (→ `general.rest.api-patterns.yml`), but the code that mounts routers to that path is factory wiring (→ `project.fastapi.factory-patterns.yml`).

### exception-patterns

**Purpose:** Rules for **handling errors** and exceptions.

**Includes:**
- Error handling strategies
- AppError usage (PROJECT scope)
- Validation error handling
- Exception handlers registration
- Error response formatting

**Excludes:**
- API error response design → `api-patterns`
- Error handling architecture → `architecture`
- HTTP status code conventions → `rest`

**Test Question:** "Is this about how to handle exceptions?"

### router-patterns

**Purpose:** Rules for **organizing and registering routers**.

**Includes:**
- APIRouter usage and configuration
- Route decorators (`@router.get`, `@router.post`)
- Endpoint wiring (connecting handlers to routes)
- Router registration patterns
- Route grouping

**Excludes:**
- API design → `api-patterns`
- Factory wiring (mounting routers) → `factory-patterns`
- Dependency injection → `dependency-patterns`

**Test Question:** "Is this about how to organize routers?"

### service-patterns

**Purpose:** Rules for **implementing the service layer**.

**Includes:**
- Service layer patterns
- Business logic delegation
- Service construction
- Service dependencies
- Transaction boundaries

**Excludes:**
- API layer → `router-patterns`
- Data access → `repository-patterns`
- Dependency injection → `dependency-patterns`

**Test Question:** "Is this about how to implement services?"

### repository-patterns

**Purpose:** Rules for **implementing data access**.

**Includes:**
- Data access patterns
- Query patterns
- Repository construction
- CRUD operations
- Query builders

**Excludes:**
- Service layer → `service-patterns`
- Database pooling → `connection-pooling-patterns`
- Database-specific syntax (belongs in database module)

**Test Question:** "Is this about how to access data?"

**PROJECT Examples:**
- `RepositoryBase` usage
- Query methods (`find_by_id`, `find_all`)
- SurrealDB-specific repository patterns

### middleware-patterns

**Purpose:** Rules for **configuring middleware**.

**Includes:**
- Middleware stack configuration
- Middleware ordering
- Middleware options
- Request/response middleware

**Excludes:**
- Factory wiring (registering middleware) → `factory-patterns`
- Architecture (middleware role) → `architecture`

**Test Question:** "Is this about how to configure middleware?"

### settings-patterns

**Purpose:** Rules for **managing configuration**.

**Includes:**
- Settings model design
- Environment variable binding
- Configuration validation
- Settings access patterns

**Excludes:**
- Factory wiring (loading settings) → `factory-patterns`
- Architecture (settings role) → `architecture`

**Test Question:** "Is this about how to manage configuration?"

### connection-pooling-patterns

**Purpose:** Rules for **managing database connections**.

**Includes:**
- Connection pool configuration
- Client management
- Connection cleanup
- Pool sizing

**Excludes:**
- Repository patterns → `repository-patterns`
- Factory wiring → `factory-patterns`

**Test Question:** "Is this about how to manage connections?"

### dependency-patterns

**Purpose:** Rules for **dependency injection**.

**Includes:**
- `Depends()` usage
- Factory functions for dependencies
- Injection patterns
- Dependency lifecycle

**Excludes:**
- Factory wiring → `factory-patterns`
- Architecture → `architecture`

**Test Question:** "Is this about how to inject dependencies?"

### docstrings-guide

**Purpose:** Documentation standards (not a pattern, but a guide).

**Includes:**
- Docstring conventions
- Formatting rules
- Documentation structure
- Example formats

**Excludes:**
- Code patterns
- Implementation guidelines

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

1. **Identify the Technology**
   - Determine which module(s) the content relates to: `rest`, `fastapi`, `python`, `surrealdb`, `elasticsearch`

2. **Apply Precedence Rules**
   - If content fits multiple modules, use Section 2 rules
   - Protocol > Framework > Language > Database

3. **Determine Scope**
   - Use Section 3 tests:
     - GENERAL: "Could this apply to a different project?"
     - PROJECT: "Does this reference a specific file or component?"

4. **Determine Pattern**
   - Use Section 4 test questions
   - Match content to the pattern whose test question gets a "yes"

5. **Consider Splitting**
   - If content spans multiple scopes or patterns, split into separate items
   - Each item should have a single scope and pattern

### Example Classification

**Content:** "The `/api/v1` prefix is used for all API routes. Routers are mounted in `create_app` using `app.include_router(router, prefix='/api/v1')`."

**Analysis:**
1. Technology: `rest` (URL structure) + `fastapi` (router mounting)
2. Precedence: URL structure is REST protocol → `rest`; router mounting is FastAPI → `fastapi`
3. Scope: References `create_app` → PROJECT for the mounting part
4. Pattern: URL structure → `api-patterns`; mounting → `factory-patterns`

**Decision:** Split into two items:
- `general.rest.api-patterns.yml`: URL versioning convention
- `project.fastapi.factory-patterns.yml`: Router mounting implementation

### Primary Consumer

The knowledge-analyzer agent (`.claude/agents/knowledge-analyzer.md`) is the primary consumer of this document. The agent should:
1. Use these definitions for semantic classification instead of keyword matching
2. Apply precedence rules to resolve multi-module content
3. Use test questions to validate classifications
4. Reference this document when explaining classification decisions
