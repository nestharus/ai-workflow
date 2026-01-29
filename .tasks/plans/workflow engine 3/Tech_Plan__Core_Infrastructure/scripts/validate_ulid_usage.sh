#!/usr/bin/env bash
# Validate ULID usage patterns in implementation code
# Exit code 0 = no violations, 1 = violations found

set -euo pipefail

VIOLATIONS=0

echo "Checking for ULID ordering anti-patterns..."

# Check for ULID sorting
if rg -n 'sorted.*ulid|\.sort.*ulid' app/ scripts/ 2>/dev/null; then
    echo "❌ Found ULID sorting (may violate cross-process ordering constraint)"
    VIOLATIONS=1
fi

# Check for ULID comparison
if rg -n 'if.*_id\s*[<>].*_id' app/ scripts/ 2>/dev/null; then
    echo "❌ Found ULID comparison for ordering"
    VIOLATIONS=1
fi

# Check for lexicographic ordering mentions
if rg -n 'lexicographic.*ulid|ulid.*lexicographic' app/ scripts/ 2>/dev/null; then
    echo "❌ Found lexicographic ULID ordering references"
    VIOLATIONS=1
fi

if [ $VIOLATIONS -eq 0 ]; then
    echo "✅ No ULID ordering violations found"
fi

exit $VIOLATIONS
