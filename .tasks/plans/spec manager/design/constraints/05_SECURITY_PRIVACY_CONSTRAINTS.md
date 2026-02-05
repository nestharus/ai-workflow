# Security / Privacy Constraints

- CON-SEC-0001  Evidence layer may contain secrets; default outputs must support redaction overlays without losing original evidence
- CON-SEC-0002  Redaction is a projection (L2); original evidence remains in L0 with access controls
- CON-SEC-0003  Agents receive least-necessary context bundles (bounded by evidence selection)
- CON-SEC-0004  All agent outputs are treated as untrusted until validated
