### 4. Span Lifecycle States

Span computability is a *claim*, not a guarantee. The system may decide a span is "computable enough to attempt" based on the current partial graph / current covering node set. The only authoritative test is the **reconstruction attempt** itself.

The span lifecycle includes three states:
- `ATTEMPTABLE` - we think we have enough coverage to try reconstruction
- `PROVEN` - reconstruction succeeds; no uncovered words/phrases remain. **This means we have sufficient facts to reconstruct the text**, not that we have extracted every possible fact from it. PROVEN status indicates the reconstruction threshold has been met.
- `FAILED` - reconstruction fails; uncovered words/phrases remain

No design assumes that "computable" implies success. A span can be attempted and still fail; failure is a normal outcome that drives additional search (or escalation to Clarification Questions).
