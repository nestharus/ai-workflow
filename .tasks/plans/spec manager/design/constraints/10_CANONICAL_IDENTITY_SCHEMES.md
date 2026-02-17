# Canonical Identity Schemes

Every persistent entity must be addressable by a stable, typed identifier.
The identifier must: use a prefix that identifies the entity type (e.g.,
`PIN-`, `VS-`, `E-`, `R-`), be allocated by a single authoritative
allocator (no ad-hoc ID generation), and be validated at ingestion
boundaries (reject malformed IDs immediately).

Human-readable names are labels, not identifiers. Names change, are
ambiguous, and vary across contexts. IDs are stable, unique, and
machine-parseable. Cross-artifact references use IDs. Display uses names.
Search may use either.
