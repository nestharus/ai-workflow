# Structured Diagnostics

Every operational decision that involves skipping, defaulting, coercing,
degrading, or falling back must emit a structured diagnostic record. The
diagnostic must include: what was skipped/defaulted, why (the trigger
condition), and what the downstream impact is (degraded confidence, missing
data, approximate result).

Silent degradation is the failure mode. A system that continues past an
error without recording it has lost the error — it cannot be found,
investigated, or corrected later. The error still affects downstream
results, but now invisibly.

This is distinct from C03 (Error Amplification), which focuses on catching
errors early and not absorbing them. This constraint addresses the case
where continuation IS the correct behavior — the system should keep going —
but the fact that something went wrong must be recorded in a
machine-readable, queryable form.
