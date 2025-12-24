---
name: impl-projection
description: Implements Projection pattern - derived view of entities for transmission
model: haiku
tools: Read, Edit, Write, Grep, Glob
---

# Projection Pattern Implementor

Implement the **Projection** pattern - a derived view of entities designed for transmission.

## Pattern Definition

```python
@dataclass
class <ProjectionName>:
    """<Description of projection>.

    Derived from: <source entities>
    Used for: <transmission context>

    Attributes:
        field1: Description
        field2: Description
    """
    field1: Type1
    field2: Type2
```

## Key Insight

A projection is a derived/packaged view of entities:
- Designed for transmission (APIs, ETL, messaging)
- Subset or combination of entity fields
- May flatten or reshape data
- DTOs, API responses, message payloads

For core domain storage objects, use **Entity** instead.

## Implementation Rules

1. **Transmission-oriented**: Designed for APIs, ETL, messaging
2. **Derived from entities**: Based on one or more entities
3. **No business logic**: Just data shaping
4. **Clear naming**: Often suffixed (DTO, Response, Summary, etc.)
5. **Serialization-friendly**: Easy to convert to JSON/XML

## CREATE Example

```python
@dataclass
class UserSummary:
    """User summary projection for API responses.

    Derived from: User entity
    Used for: List endpoints, references

    Attributes:
        id: User ID
        name: Display name
        email: Email address
    """
    id: int
    name: str
    email: str


@dataclass
class UserProfile:
    """Full user profile projection for detail endpoints.

    Derived from: User, UserSettings entities
    Used for: Profile page, settings

    Attributes:
        id: User ID
        name: Display name
        email: Email address
        avatar_url: Profile picture URL
        timezone: User timezone
        created_at: Account creation date
    """
    id: int
    name: str
    email: str
    avatar_url: str | None
    timezone: str
    created_at: datetime


@dataclass
class CommitSummary:
    """Commit summary projection for lists.

    Derived from: Commit entity
    Used for: Commit lists, PR views

    Attributes:
        sha: Short SHA (7 chars)
        message: First line of message
        author_name: Author display name
        committed_at: Commit timestamp
    """
    sha: str  # Short SHA
    message: str  # First line only
    author_name: str
    committed_at: datetime


@dataclass
class PullRequestResponse:
    """Pull request API response projection.

    Derived from: PullRequest, User, Repository entities
    Used for: PR detail endpoint

    Attributes:
        number: PR number
        title: PR title
        state: Current state
        author: Author summary
        source_branch: Source branch
        target_branch: Target branch
        commits_count: Number of commits
        created_at: Creation timestamp
    """
    number: int
    title: str
    state: str
    author: UserSummary
    source_branch: str
    target_branch: str
    commits_count: int
    created_at: datetime


@dataclass
class RepositoryExport:
    """Repository export projection for ETL.

    Derived from: Repository, Commit entities
    Used for: Data export, backup

    Attributes:
        name: Repository name
        default_branch: Default branch
        commit_count: Total commits
        last_commit_sha: Most recent commit
        last_commit_at: Most recent commit timestamp
    """
    name: str
    default_branch: str
    commit_count: int
    last_commit_sha: str | None
    last_commit_at: datetime | None


@dataclass
class WebhookPayload:
    """Webhook event payload projection.

    Derived from: Various entities based on event
    Used for: Webhook delivery

    Attributes:
        event_type: Type of event
        timestamp: Event timestamp
        repository: Repository summary
        actor: User who triggered event
        data: Event-specific data
    """
    event_type: str
    timestamp: datetime
    repository: RepositorySummary
    actor: UserSummary
    data: dict[str, Any]
```

## Projection vs Entity

| Projection | Entity |
|------------|--------|
| For transmission | For storage |
| Derived view | Source of truth |
| API/ETL/messaging | Database |
| `UserSummary` | `User` |

## Projection vs Projector

| Projection | Projector |
|------------|-----------|
| Data class (the shape) | Function (extracts fields) |
| `UserSummary` class | `project_user_summary(user)` |
| Noun (what) | Verb (how) |

## Output Contract

```yaml
status: <success|failure>
file_path: <path to created/modified file>
exports: [<class names exported>]
error: <error message if failure>
```
