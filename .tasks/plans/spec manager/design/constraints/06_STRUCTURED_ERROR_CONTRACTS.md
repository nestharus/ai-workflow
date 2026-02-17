# Structured Error Contracts

When a component produces a result, the result type must be total — it must
represent both success and failure states as structured data. Components that
communicate failure by throwing exceptions across module boundaries force
callers into catch-based control flow, which is fragile and couples the
caller to the exception type hierarchy.

The contract between producer and consumer is the result type. The result
type must include: a success/failure discriminator, the payload on success,
and structured diagnostic information on failure (error type, severity,
human-readable message, and contextual details). Exceptions are reserved
for invariant violations — programmer errors that indicate a bug, not
operational failures that are expected and recoverable.

This applies at module boundaries and cross-component interfaces. Within a
module, exceptions may be used for local control flow where they are
immediately caught and handled. The constraint is about what crosses
boundaries.
