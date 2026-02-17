# Explicit Serialization Contracts

Every type that crosses a module boundary — whether for persistence,
inter-stage communication, or external output — must define explicit,
bidirectional serialization methods. The serialization format is part of the
public contract.

Serialization must be deterministic: the same object must always produce the
same serialized form. Deserialization must validate: malformed input is
rejected with structured diagnostics, not silently coerced. The round-trip
property must hold: `from_dict(x.to_dict()) == x` for all valid instances.

Types that cross boundaries without explicit serialization contracts create
invisible coupling — consumers depend on the internal field layout, which
can change without warning. Types with non-deterministic serialization (dict
ordering, floating-point formatting) create phantom diffs and cache misses.
