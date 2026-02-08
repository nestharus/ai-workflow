# Lint Fixer

Fix lint errors provided in the prompt. Only report what you couldn't fix.

## Input Format

You receive lint output and working directory:

```text
<lint output>

Working directory: /path/to/repo
```

## Workflow

1. **Read the error list** from the prompt
2. **For each error**:
   - Read the file containing the error
   - Analyze the issue
   - Apply the appropriate fix
3. **Report** any unfixable items

## Output

Only report unfixable items. Include:

- File and line number
- Error code
- What you tried
- Why it failed

Do not report what was fixed.

## Rules

- **NEVER** modify lint rules, exclusions, ignore patterns, or lint script
  logic
- **NEVER** add `# noqa`, `# type: ignore` without explicit justification
  - this agent must not autonomously add suppressions

## Inline Suppression Policy

**Before considering any inline suppression**, always check
`pyproject.toml` `[tool.ruff.lint.per-file-ignores]` to see if the file or
pattern already has a configured exception.

**Acceptable justification criteria** (suppression may be warranted):

- Documented third-party library or mypy false positive with reference to
  upstream issue or stub limitation
- Known mypy limitation with a tracking issue (e.g., `# type: ignore[arg-type]
  # mypy#12345`)
- Generated code or external constraints that cannot be modified
- Explicit project decision documented in comments or ADRs

**Unacceptable justifications** (suppression NOT allowed):

- Masking a real bug or type error to make CI pass
- Avoiding a refactor that would properly fix the issue
- Convenience or time pressure ("fix later")
- No explanation or generic "doesn't work" comments

**Examples:**

```python
# JUSTIFIED - documented upstream issue
result = third_party_func()  # type: ignore[return-value]
# stubs incorrect, see typeshed#4567

# JUSTIFIED - mypy limitation with reference
callback(handler)  # type: ignore[arg-type]
# mypy#9424 - callable protocol variance

# UNJUSTIFIED - masking real bug
user.name = get_value()  # type: ignore  # just make it work

# UNJUSTIFIED - avoiding proper fix
data: Any = process()  # noqa: ANN401  # too hard to type properly
```

**When suppression seems necessary**, do NOT add it. Instead, report it as
unfixable with:
- What you tried
- Why it failed
- Whether suppression might be appropriate and why

Let the caller decide whether to add per-file ignore in pyproject.toml or
inline suppression.

## Common Fix Patterns

- **E501** (line too long): Wrap line, split string, use parentheses
- **F401** (unused import): Remove the import
- **I001** (unsorted imports): Run `ruff check --fix` or manually reorder
- **TCH003**: Add `TYPE_CHECKING` import guard for type-only imports
- **arg-type/return-value**: Fix the actual type issue, not suppress it
- Docstrings: see `docs/development/python/python.docstrings-guide.yml`
- Markdown: Wrap long lines, align bullet markers (asterisks)

## YAML Formatting

**NEVER** convert block scalars to quoted strings with `\n` escapes.

Use `|` (literal block scalar) for: `code:`, multi-line `description:`,
`text:`, `example:`, `scope:` fields.

```yaml
# WRONG - never do this:
code: "def foo():\n    return bar"

# CORRECT - use block scalar:
code: |
  def foo():
      return bar
```

- Trailing whitespace in block scalars: remove the spaces, do NOT convert
  to quoted string
- Avoid `''` for apostrophes, `\"` or `\n` escapes - use `|` block scalar
  instead
- Single-line values with colons can use quotes: `text: 'Note: this
  works'`
## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

errors:
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/extractors/call_graph.py
    line: 48
    column: 33
    code: SIM201
    message: |
      Use `path.suffix != ".py"` instead of `not path.suffix == ".py"`
    fix_available: true
    fix_message: |
      Replace with `!=` operator
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/extractors/call_graph.py
    line: 144
    column: 12
    code: SIM101
    message: |
      Multiple `isinstance` calls for `parent`, merge into a single call
    fix_available: true
    fix_message: |
      Merge `isinstance` calls for `parent`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/extractors/event_graph.py
    line: 85
    column: 33
    code: SIM201
    message: |
      Use `path.suffix != ".py"` instead of `not path.suffix == ".py"`
    fix_available: true
    fix_message: |
      Replace with `!=` operator
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/extractors/event_graph.py
    line: 157
    column: 12
    code: SIM101
    message: |
      Multiple `isinstance` calls for `parent`, merge into a single call
    fix_available: true
    fix_message: |
      Merge `isinstance` calls for `parent`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/extractors/event_graph.py
    line: 330
    column: 12
    code: SIM101
    message: |
      Multiple `isinstance` calls for `parent`, merge into a single call
    fix_available: true
    fix_message: |
      Merge `isinstance` calls for `parent`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/extractors/store_graph.py
    line: 111
    column: 33
    code: SIM201
    message: |
      Use `path.suffix != ".py"` instead of `not path.suffix == ".py"`
    fix_available: true
    fix_message: |
      Replace with `!=` operator
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/extractors/store_graph.py
    line: 256
    column: 12
    code: SIM101
    message: |
      Multiple `isinstance` calls for `parent`, merge into a single call
    fix_available: true
    fix_message: |
      Merge `isinstance` calls for `parent`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/extractors/store_graph.py
    line: 288
    column: 5
    code: SIM110
    message: |
      Use `return any(hint.lower() in type_name.lower() for hint in STORE_TYPE_HINTS)` instead of `for` loop
    fix_available: true
    fix_message: |
      Replace with `return any(hint.lower() in type_name.lower() for hint in STORE_TYPE_HINTS)`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_cooccurrence.py
    line: 24
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_cooccurrence.py
    line: 157
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_cooccurrence.py
    line: 162
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_cooccurrence.py
    line: 201
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_cooccurrence.py
    line: 202
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_cooccurrence.py
    line: 220
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_cooccurrence.py
    line: 226
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_cooccurrence.py
    line: 227
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_cooccurrence.py
    line: 235
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_cooccurrence.py
    line: 242
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_event_graph.py
    line: 23
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_event_graph.py
    line: 24
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_event_graph.py
    line: 58
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_event_graph.py
    line: 90
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_event_graph.py
    line: 121
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_event_graph.py
    line: 144
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_event_graph.py
    line: 168
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_event_graph.py
    line: 174
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_event_graph.py
    line: 180
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_event_graph.py
    line: 181
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_event_graph.py
    line: 200
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_event_graph.py
    line: 218
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_event_graph.py
    line: 244
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 14
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 15
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 23
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 36
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 52
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 53
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 64
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 76
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 77
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 85
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 91
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 107
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 108
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 120
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 126
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 135
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 141
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 149
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 158
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 166
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 176
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 194
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 206
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 216
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 228
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 241
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 257
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 268
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 300
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 306
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_graph.py
    line: 313
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_store_graph.py
    line: 23
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_store_graph.py
    line: 127
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_store_graph.py
    line: 132
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/branches/analysis.py
    line: 162
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/branches/analysis.py
    line: 333
    column: 15
    code: ANN401
    message: |
      Dynamically typed expressions (typing.Any) are disallowed in `atom`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/branches/atoms.py
    line: 25
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/branches/collapse.py
    line: 159
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/branches/collapse.py
    line: 293
    column: 9
    code: SIM102
    message: |
      Use a single `if` statement instead of nested `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/branches/collapse.py
    line: 395
    column: 9
    code: SIM102
    message: |
      Use a single `if` statement instead of nested `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/branches/downward_flow.py
    line: 99
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/branches/downward_flow.py
    line: 149
    column: 9
    code: SIM108
    message: |
      Use ternary operator `confidence = (1.0 if exact_match else 0.7) if traced_pins else 0.0` instead of `if`-`else`-block
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/branches/manager.py
    line: 48
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/branches/pins.py
    line: 90
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/branches/promotion.py
    line: 107
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/compliance/promotion/pin_coverage.py
    line: 199
    column: 13
    code: SIM102
    message: |
      Use a single `if` statement instead of nested `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/edit_in_place.py
    line: 83
    column: 9
    code: D105
    message: Missing docstring in magic method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/edit_in_place.py
    line: 86
    column: 9
    code: D105
    message: Missing docstring in magic method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/edit_in_place.py
    line: 143
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/edit_in_place.py
    line: 147
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/edit_in_place.py
    line: 151
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/edit_in_place.py
    line: 154
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/edit_in_place.py
    line: 367
    column: 17
    code: SIM102
    message: |
      Use a single `if` statement instead of nested `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/edit_in_place.py
    line: 627
    column: 9
    code: SIM110
    message: |
      Use `return any(start <= line <= end for start, end in func_line_ranges)` instead of `for` loop
    fix_available: true
    fix_message: |
      Replace with `return any(start <= line <= end for start, end in func_line_ranges)`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 41
    column: 1
    code: E402
    message: Module level import not at top of file
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 42
    column: 1
    code: E402
    message: Module level import not at top of file
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 43
    column: 1
    code: E402
    message: Module level import not at top of file
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 695
    column: 36
    code: ANN401
    message: |
      Dynamically typed expressions (typing.Any) are disallowed in `llm_client`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 793
    column: 101
    code: E501
    message: Line too long (113 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 926
    column: 101
    code: E501
    message: Line too long (121 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 965
    column: 101
    code: E501
    message: Line too long (105 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 994
    column: 36
    code: ANN401
    message: |
      Dynamically typed expressions (typing.Any) are disallowed in `llm_client`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 1139
    column: 101
    code: E501
    message: Line too long (106 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 1151
    column: 101
    code: E501
    message: Line too long (103 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 1270
    column: 28
    code: RUF012
    message: |
      Mutable class attributes should be annotated with `typing.ClassVar`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 1384
    column: 101
    code: E501
    message: Line too long (101 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 1427
    column: 101
    code: E501
    message: Line too long (147 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 1470
    column: 101
    code: E501
    message: Line too long (103 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 1581
    column: 101
    code: E501
    message: Line too long (105 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 1612
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 1612
    column: 24
    code: ANN001
    message: |
      Missing type annotation for function argument `llm_client`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 1689
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 1730
    column: 17
    code: B007
    message: |
      Loop control variable `file_part` not used within loop body
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 1800
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 1800
    column: 24
    code: ANN001
    message: |
      Missing type annotation for function argument `llm_client`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2128
    column: 5
    code: ANN001
    message: |
      Missing type annotation for function argument `registry`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2189
    column: 48
    code: ANN001
    message: |
      Missing type annotation for function argument `registry`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2277
    column: 101
    code: E501
    message: Line too long (107 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2360
    column: 48
    code: ANN001
    message: |
      Missing type annotation for function argument `registry`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2387
    column: 101
    code: E501
    message: Line too long (107 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2395
    column: 50
    code: ANN001
    message: |
      Missing type annotation for function argument `registry`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2527
    column: 101
    code: E501
    message: Line too long (101 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2530
    column: 101
    code: E501
    message: Line too long (112 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2549
    column: 101
    code: E501
    message: Line too long (112 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2552
    column: 101
    code: E501
    message: Line too long (116 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2578
    column: 101
    code: E501
    message: Line too long (101 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2580
    column: 101
    code: E501
    message: Line too long (113 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2594
    column: 101
    code: E501
    message: Line too long (113 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2596
    column: 101
    code: E501
    message: Line too long (108 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2635
    column: 101
    code: E501
    message: Line too long (116 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2637
    column: 101
    code: E501
    message: Line too long (126 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2645
    column: 43
    code: ANN001
    message: |
      Missing type annotation for function argument `registry`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2735
    column: 101
    code: E501
    message: Line too long (110 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2737
    column: 101
    code: E501
    message: Line too long (117 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2754
    column: 101
    code: E501
    message: Line too long (133 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2756
    column: 101
    code: E501
    message: Line too long (121 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2767
    column: 13
    code: SIM102
    message: |
      Use a single `if` statement instead of nested `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2784
    column: 101
    code: E501
    message: Line too long (124 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2786
    column: 101
    code: E501
    message: Line too long (103 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2794
    column: 5
    code: D205
    message: 1 blank line required between summary line and description
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/gaps.py
    line: 2836
    column: 19
    code: B007
    message: |
      Loop control variable `section` not used within loop body
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 38
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 39
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 47
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 48
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 55
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 56
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 71
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 85
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 86
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 109
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 121
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 137
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 153
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 169
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 185
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 201
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 224
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 225
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 257
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 280
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 281
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 284
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 287
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 290
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 293
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 296
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 299
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 302
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 305
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 308
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 311
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 314
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 317
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 320
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 323
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 326
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 329
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 332
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 335
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 339
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 340
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 362
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 382
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 397
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 410
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 411
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 421
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 431
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 441
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 451
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 466
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 482
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 483
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 496
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 505
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 528
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 536
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 544
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 552
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 570
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 571
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 604
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 625
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 640
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 661
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 689
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 690
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 710
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 726
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 744
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 772
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 776
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 783
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 793
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 794
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 802
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 813
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 820
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 829
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 830
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 847
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 856
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 857
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py
    line: 880
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place_cli.py
    line: 29
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place_cli.py
    line: 30
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place_cli.py
    line: 52
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place_cli.py
    line: 65
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place_cli.py
    line: 66
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place_cli.py
    line: 88
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place_cli.py
    line: 101
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place_cli.py
    line: 102
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place_cli.py
    line: 117
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place_cli.py
    line: 118
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place_cli.py
    line: 125
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place_cli.py
    line: 136
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/core/tests/test_edit_in_place_cli.py
    line: 137
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/core/bus.py
    line: 34
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/core/worker_pool.py
    line: 21
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/core/worker_pool.py
    line: 28
    column: 16
    code: ANN401
    message: |
      Dynamically typed expressions (typing.Any) are disallowed in `*args`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/core/worker_pool.py
    line: 29
    column: 19
    code: ANN401
    message: |
      Dynamically typed expressions (typing.Any) are disallowed in `**kwargs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/core/worker_pool.py
    line: 30
    column: 10
    code: ANN401
    message: |
      Dynamically typed expressions (typing.Any) are disallowed in `submit`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/core/worker_pool.py
    line: 52
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/engine/executor.py
    line: 23
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/engine/registry.py
    line: 15
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/engine/registry.py
    line: 61
    column: 9
    code: D105
    message: Missing docstring in magic method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/generator/labyrinth_builder.py
    line: 80
    column: 15
    code: S311
    message: Standard pseudo-random generators are not suitable for cryptographic purposes
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/generator/labyrinth_builder.py
    line: 230
    column: 13
    code: S112
    message: |
      `try`-`except`-`continue` detected, consider logging the exception
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/generator/service_factory.py
    line: 16
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/generator/spec_generator.py
    line: 95
    column: 101
    code: E501
    message: Line too long (106 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/generator/spec_generator.py
    line: 175
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/generator/steering_generator.py
    line: 27
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/generator/steering_generator.py
    line: 94
    column: 101
    code: E501
    message: Line too long (105 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/integration/integration_points.py
    line: 60
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/integration/integration_points.py
    line: 102
    column: 9
    code: D105
    message: Missing docstring in magic method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/integration/pipeline.py
    line: 31
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/integration/wiring.py
    line: 42
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 17
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 22
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 43
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_mixed_functions`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 43
    column: 36
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 43
    column: 47
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 68
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_convention_based_detection`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 68
    column: 47
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 68
    column: 58
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 84
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_annotation_based_detection`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 84
    column: 47
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 84
    column: 58
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 100
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_annotation_overrides_private`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 100
    column: 49
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 100
    column: 60
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 115
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_heuristic_requires_docstring`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 115
    column: 49
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 115
    column: 60
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 128
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_heuristic_max_lines`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 128
    column: 40
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 153
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_exclusion_patterns`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 153
    column: 39
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 153
    column: 50
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 164
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_conftest_excluded`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 164
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 164
    column: 38
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 164
    column: 49
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 174
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_syntax_error_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 174
    column: 38
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 174
    column: 49
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 181
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_nonexistent_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 181
    column: 37
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 181
    column: 48
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 191
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_pure_function_is_shape`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 191
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 191
    column: 43
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 191
    column: 54
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 201
    column: 20
    code: RUF015
    message: |
      Prefer `next(c for c in candidates if c.function_name == "add")` over single element slice
    fix_available: true
    fix_message: |
      Replace with `next(c for c in candidates if c.function_name == "add")`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 204
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_global_disqualifies_shape`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 204
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 204
    column: 46
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 204
    column: 57
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 215
    column: 20
    code: RUF015
    message: |
      Prefer `next(...)` over single element slice
    fix_available: true
    fix_message: |
      Replace with `next(...)`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 218
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_io_call_disqualifies_shape`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 218
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 218
    column: 47
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 218
    column: 58
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 227
    column: 20
    code: RUF015
    message: |
      Prefer `next(...)` over single element slice
    fix_available: true
    fix_message: |
      Replace with `next(...)`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 230
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_attribute_mutation_disqualifies_shape`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 230
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 230
    column: 58
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 230
    column: 69
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 240
    column: 20
    code: RUF015
    message: |
      Prefer `next(...)` over single element slice
    fix_available: true
    fix_message: |
      Replace with `next(...)`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 243
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_self_mutation_allowed_for_shape`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 243
    column: 52
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 243
    column: 63
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 262
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_simple_args`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 262
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 262
    column: 32
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 262
    column: 43
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 273
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_typed_args`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 273
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 273
    column: 31
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 273
    column: 42
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 286
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_default_values`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 286
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 286
    column: 35
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 286
    column: 46
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 298
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_kwargs`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 298
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 298
    column: 27
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 298
    column: 38
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 310
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_return_annotation`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 310
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 310
    column: 38
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 310
    column: 49
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 325
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_deterministic_hash`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 325
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 325
    column: 39
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 325
    column: 50
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 347
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_different_bodies_different_hashes`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 347
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 347
    column: 54
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 347
    column: 65
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 377
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_recursive_extraction`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 377
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 377
    column: 41
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 377
    column: 52
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 392
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_non_recursive_extraction`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 392
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 392
    column: 45
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 392
    column: 56
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 411
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detect_db_reference`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 411
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 411
    column: 40
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 411
    column: 51
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 420
    column: 16
    code: RUF015
    message: |
      Prefer `next(...)` over single element slice
    fix_available: true
    fix_message: |
      Replace with `next(...)`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 423
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detect_cache_reference`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 423
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 423
    column: 43
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 423
    column: 54
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 432
    column: 18
    code: RUF015
    message: |
      Prefer `next(...)` over single element slice
    fix_available: true
    fix_message: |
      Replace with `next(...)`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 439
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detect_called_functions`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 439
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 439
    column: 44
    code: ANN001
    message: |
      Missing type annotation for function argument `extractor`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 439
    column: 55
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_ast_extractor.py
    line: 450
    column: 16
    code: RUF015
    message: |
      Prefer `next(...)` over single element slice
    fix_available: true
    fix_message: |
      Replace with `next(...)`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 11
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 12
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_create_with_data`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 12
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 20
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_record`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 20
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 26
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 27
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_create_with_data`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 27
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 39
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 40
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_append_and_retrieve`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 40
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 47
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_filter_by_type`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 47
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 55
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_filter_by_source`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 55
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 62
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_filter_by_topic`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 62
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 68
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_sources_in_order`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 68
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 75
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_clear`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 75
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 81
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_thread_safety`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 87
    column: 13
    code: ANN202
    message: |
      Missing return type annotation for private function `append_entries`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 87
    column: 28
    code: ANN001
    message: |
      Missing type annotation for function argument `n`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 100
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 101
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_subscribe_and_publish`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 101
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 105
    column: 19
    code: ANN202
    message: |
      Missing return type annotation for private function `handler`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 105
    column: 27
    code: ANN001
    message: |
      Missing type annotation for function argument `topic`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 105
    column: 34
    code: ANN001
    message: |
      Missing type annotation for function argument `payload`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 114
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_multiple_subscribers`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 114
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 118
    column: 19
    code: ANN202
    message: |
      Missing return type annotation for private function `handler1`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 118
    column: 28
    code: ANN001
    message: |
      Missing type annotation for function argument `topic`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 118
    column: 35
    code: ANN001
    message: |
      Missing type annotation for function argument `payload`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 121
    column: 19
    code: ANN202
    message: |
      Missing return type annotation for private function `handler2`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 121
    column: 28
    code: ANN001
    message: |
      Missing type annotation for function argument `topic`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 121
    column: 35
    code: ANN001
    message: |
      Missing type annotation for function argument `payload`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 129
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_unsubscribe`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 129
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 133
    column: 19
    code: ANN202
    message: |
      Missing return type annotation for private function `handler`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 133
    column: 27
    code: ANN001
    message: |
      Missing type annotation for function argument `topic`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 133
    column: 34
    code: ANN001
    message: |
      Missing type annotation for function argument `payload`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 141
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_no_subscribers`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 141
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 146
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_topics`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 146
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 149
    column: 19
    code: ANN202
    message: |
      Missing return type annotation for private function `handler`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 149
    column: 27
    code: ANN001
    message: |
      Missing type annotation for function argument `t`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 149
    column: 30
    code: ANN001
    message: |
      Missing type annotation for function argument `p`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 158
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_subscriber_count`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 158
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 161
    column: 19
    code: ANN202
    message: |
      Missing return type annotation for private function `handler`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 161
    column: 27
    code: ANN001
    message: |
      Missing type annotation for function argument `t`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 161
    column: 30
    code: ANN001
    message: |
      Missing type annotation for function argument `p`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 170
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 171
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_submit_sync_function`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 171
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 174
    column: 13
    code: ANN202
    message: |
      Missing return type annotation for private function `add`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 174
    column: 17
    code: ANN001
    message: |
      Missing type annotation for function argument `a`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 174
    column: 20
    code: ANN001
    message: |
      Missing type annotation for function argument `b`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 181
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_max_workers`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_core.py
    line: 181
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 19
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 20
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_eq`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 20
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 25
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_neq`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 25
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 30
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_gt`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 30
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 35
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_in_operator`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 35
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 40
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_contains`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 40
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 44
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_missing_field`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 44
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 49
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 50
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_and_all_true`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 50
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 57
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_and_one_false`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 57
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 64
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_or_one_true`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 64
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 71
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_group`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 71
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 75
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_nested_groups`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 75
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 89
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 90
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_evaluate_matching`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 90
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 102
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_evaluate_no_match`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 102
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 109
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_evaluate_no_transform`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 109
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 115
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 116
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_sequential`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 116
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 125
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_parallel`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 125
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 134
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_conditional_first_match`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 134
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 146
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 147
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_dependency_ordering`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 147
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 158
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 159
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_register_and_get`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 159
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 167
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_by_group`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 167
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 174
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_remove`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_engine.py
    line: 174
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 22
    column: 5
    code: ANN003
    message: |
      Missing type annotation for `**kwargs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 50
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 57
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detect_import_from`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 57
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 57
    column: 39
    code: ANN001
    message: |
      Missing type annotation for function argument `builder`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 57
    column: 48
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 72
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detect_module_import`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 72
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 72
    column: 41
    code: ANN001
    message: |
      Missing type annotation for function argument `builder`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 72
    column: 50
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 84
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detect_aliased_import`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 84
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 84
    column: 42
    code: ANN001
    message: |
      Missing type annotation for function argument `builder`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 84
    column: 51
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 98
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_usage_sites_detected`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 98
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 98
    column: 41
    code: ANN001
    message: |
      Missing type annotation for function argument `builder`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 98
    column: 50
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 115
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_no_algorithmic_import`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 115
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 115
    column: 42
    code: ANN001
    message: |
      Missing type annotation for function argument `builder`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 115
    column: 51
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 127
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_syntax_error_returns_empty`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 127
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 127
    column: 47
    code: ANN001
    message: |
      Missing type annotation for function argument `builder`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 127
    column: 56
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 138
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 141
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_pass_through_direct_call`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 141
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 141
    column: 45
    code: ANN001
    message: |
      Missing type annotation for function argument `builder`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 156
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_wrap_decorated_function`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 156
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 156
    column: 44
    code: ANN001
    message: |
      Missing type annotation for function argument `builder`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 171
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_wrap_partial_application`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 171
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 171
    column: 45
    code: ANN001
    message: |
      Missing type annotation for function argument `builder`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 191
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 194
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detect_smear`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 194
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 194
    column: 33
    code: ANN001
    message: |
      Missing type annotation for function argument `builder`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 221
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_no_smear_single_import`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 221
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 221
    column: 43
    code: ANN001
    message: |
      Missing type annotation for function argument `builder`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 241
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_build_graph_with_matching_functions`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 241
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 241
    column: 56
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 271
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_build_graph_no_matches`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 271
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 271
    column: 43
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 295
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_smear_detection_in_build`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 295
    column: 45
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 333
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_wrapped_function_detection`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 333
    column: 47
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 371
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_introduction_is_absence`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 372
    column: 9
    code: D205
    message: 1 blank line required between summary line and description
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_import_graph.py
    line: 379
    column: 9
    code: F841
    message: |
      Local variable `ref` is assigned to but never used
    fix_available: true
    fix_message: |
      Remove assignment to unused variable `ref`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 80
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_scan_finds_atoms`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 80
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 80
    column: 37
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 97
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_scan_finds_import_edges`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 97
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 97
    column: 44
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 111
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_scan_empty_project`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 111
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 111
    column: 39
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 126
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_diff_detects_modification`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 126
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 126
    column: 46
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 166
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_query_importers`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 166
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 166
    column: 36
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 180
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_query_importers_not_found`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 180
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 180
    column: 46
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 193
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_query_pin_functions_for_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 193
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 193
    column: 49
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 216
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_save_creates_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 216
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 216
    column: 38
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 236
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_saved_registry_can_be_loaded`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 236
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 236
    column: 49
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 255
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_analysis_contains_expected_sections`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 255
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 255
    column: 56
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 271
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_analysis_lists_functions`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 271
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 271
    column: 45
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 286
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_analysis_empty_project`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 286
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_orchestrator.py
    line: 286
    column: 43
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 30
    column: 5
    code: ANN003
    message: |
      Missing type annotation for `**kwargs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 52
    column: 5
    code: ANN003
    message: |
      Missing type annotation for `**kwargs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 80
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_body_modification_detected`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 80
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 93
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_signature_change_detected`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 93
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 112
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_function_added_detected`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 112
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 133
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_function_removed_detected`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 133
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 154
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_no_changes_detected`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 154
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 167
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_pass_through_auto_propagated`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 167
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 192
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_wrap_review_required`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 192
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 209
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_smear_review_required`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 209
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 225
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_signature_change_breaking`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 225
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 244
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_removed_function_breaking`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 244
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 260
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_added_function_no_propagation`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 260
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 275
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_changes_no_propagation`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 275
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 286
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_multiple_edges_for_same_change`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 323
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_conversion_creates_drift_items`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 323
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 349
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_breaking_change_produces_mismatch`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 349
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 373
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_report_produces_no_drift`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 373
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 378
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_review_required_produces_mismatch`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 378
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 407
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 412
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_modified_pass_through`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 412
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 412
    column: 42
    code: ANN001
    message: |
      Missing type annotation for function argument `propagator`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 421
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_modified_wrap`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 421
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 421
    column: 34
    code: ANN001
    message: |
      Missing type annotation for function argument `propagator`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 430
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_modified_smear`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 430
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 430
    column: 35
    code: ANN001
    message: |
      Missing type annotation for function argument `propagator`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 439
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_signature_changed_any`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 439
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 439
    column: 42
    code: ANN001
    message: |
      Missing type annotation for function argument `propagator`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 449
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_removed_any`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 449
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_propagation.py
    line: 449
    column: 32
    code: ANN001
    message: |
      Missing type annotation for function argument `propagator`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 22
    column: 5
    code: ANN003
    message: |
      Missing type annotation for `**kwargs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 47
    column: 5
    code: ANN003
    message: |
      Missing type annotation for `**kwargs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 67
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_basic_creation`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 67
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 76
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_shape_function`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 76
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 80
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_store_touches`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 80
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 84
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_evidence_atom_ids`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 84
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 90
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_default_lists_are_empty`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 90
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 99
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_pass_through`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 99
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 103
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_middleware_wrap`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 103
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 107
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_smear`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 107
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 111
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_introduction`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 111
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 115
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_confidence_bounds`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 115
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 119
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_confidence_lower_bound`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 119
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 120
    column: 14
    code: B017
    message: |
      Do not assert blind exception: `Exception`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 123
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_confidence_upper_bound`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 123
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 124
    column: 14
    code: B017
    message: |
      Do not assert blind exception: `Exception`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 127
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_is_direct_import_default`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 127
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 131
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_inferred_import`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 131
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 139
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_function_level`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 139
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 146
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_line_range`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 146
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 151
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_call_site`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 151
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 163
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 206
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 206
    column: 21
    code: ANN001
    message: |
      Missing type annotation for function argument `sample_registry`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 209
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_importers_found`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 209
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 209
    column: 40
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 213
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_importers_not_found`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 213
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 213
    column: 44
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 217
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_pin_functions_for_arch`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 217
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 217
    column: 47
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 223
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_by_name_found`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 223
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 223
    column: 38
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 228
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_by_name_not_found`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 228
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 228
    column: 42
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 232
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_by_id_found`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 232
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 232
    column: 36
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 237
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_by_id_not_found`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 237
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 237
    column: 40
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 241
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_resolve_micro_address_function_level`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 241
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 241
    column: 57
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 247
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_resolve_micro_address_line_range_valid`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 247
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 247
    column: 59
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 253
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_resolve_micro_address_line_range_invalid`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 253
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 253
    column: 61
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 259
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_resolve_micro_address_line_range_inverted`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 259
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 259
    column: 62
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 264
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_resolve_micro_address_call_site_valid`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 264
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 264
    column: 58
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 272
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_resolve_micro_address_call_site_invalid_composition`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 272
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 272
    column: 72
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 280
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_resolve_micro_address_nonexistent_pin`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 280
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 280
    column: 58
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 285
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_affected_locations`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 285
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 285
    column: 43
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 289
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_affected_locations_multiple`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 289
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 289
    column: 52
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 293
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_affected_locations_no_duplicates`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 293
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 293
    column: 57
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 297
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_affected_locations_empty`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 297
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 297
    column: 49
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 301
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_affected_locations_no_importers`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 301
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 301
    column: 56
    code: ANN001
    message: |
      Missing type annotation for function argument `index`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 309
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_json_round_trip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 309
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 344
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_registry_round_trip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 344
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 357
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_multiple_pin_functions_round_trip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/labyrinth/tests/test_pin_registry.py
    line: 357
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/orchestration/extraction.py
    line: 107
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/orchestration/extraction.py
    line: 242
    column: 38
    code: E741
    message: |
      Ambiguous variable name: `l`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/pin_functions/orchestrator.py
    line: 50
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/builder.py
    line: 80
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/builder.py
    line: 115
    column: 13
    code: B007
    message: |
      Loop control variable `file_path` not used within loop body
    fix_available: true
    fix_message: |
      Rename unused `file_path` to `_file_path`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/builder.py
    line: 169
    column: 9
    code: SIM116
    message: |
      Use a dictionary instead of consecutive `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/builder.py
    line: 207
    column: 33
    code: SIM201
    message: |
      Use `path.suffix != ".py"` instead of `not path.suffix == ".py"`
    fix_available: true
    fix_message: |
      Replace with `!=` operator
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/builder.py
    line: 274
    column: 9
    code: SIM102
    message: |
      Use a single `if` statement instead of nested `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/builder.py
    line: 278
    column: 24
    code: S324
    message: |
      Probable use of insecure hash functions in `hashlib`: `md5`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/data_flow.py
    line: 108
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/import_graph.py
    line: 78
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/test_pin_baseline.py
    line: 268
    column: 17
    code: SIM102
    message: |
      Use a single `if` statement instead of nested `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/test_pin_baseline.py
    line: 272
    column: 32
    code: S324
    message: |
      Probable use of insecure hash functions in `hashlib`: `md5`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/test_pin_baseline.py
    line: 322
    column: 21
    code: SIM102
    message: |
      Use a single `if` statement instead of nested `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/test_pin_baseline.py
    line: 327
    column: 13
    code: SIM102
    message: |
      Use a single `if` statement instead of nested `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/test_pin_discovery.py
    line: 136
    column: 12
    code: SIM101
    message: |
      Multiple `isinstance` calls for `node`, merge into a single call
    fix_available: true
    fix_message: |
      Merge `isinstance` calls for `node`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/test_pin_discovery.py
    line: 150
    column: 17
    code: SIM102
    message: |
      Use a single `if` statement instead of nested `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/test_pin_discovery.py
    line: 162
    column: 9
    code: SIM102
    message: |
      Use a single `if` statement instead of nested `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/test_pin_discovery.py
    line: 163
    column: 13
    code: SIM102
    message: |
      Use a single `if` statement instead of nested `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/test_pin_discovery.py
    line: 192
    column: 5
    code: SIM110
    message: |
      Use `return any(node is func_node for node in tree.body)` instead of `for` loop
    fix_available: true
    fix_message: |
      Replace with `return any(node is func_node for node in tree.body)`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 106
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 107
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_direct_import_classified_as_pass_through`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 121
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_event_handler_classified_as_event_bridge`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 135
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_middleware_classified_as_middleware_wrap`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 148
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_retry_classified_as_retry_decorate`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 162
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_no_matching_atom_skipped`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 174
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_multiple_atoms_in_handler_classified_as_smear`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 203
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_confidence_scoring`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 221
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 222
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_roundtrip_serialization`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 240
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 241
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_compute_known_function`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 253
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_compute_missing_function_returns_none`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 260
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_compute_missing_file_returns_none`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_builder.py
    line: 265
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_signature_changes_alter_hash`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py
    line: 26
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py
    line: 27
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_roundtrip_serialization`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py
    line: 42
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_defaults_are_empty_lists`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py
    line: 51
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py
    line: 52
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_roundtrip_serialization`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py
    line: 72
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py
    line: 73
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_pass_through_preserves_all_signals`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py
    line: 98
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_slice_detects_dropped_signals`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py
    line: 122
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_signals_added_detected`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py
    line: 139
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_compute_flow_returns_none_without_specs`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py
    line: 145
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_store_touch_graph`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py
    line: 170
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_find_signal_loss_returns_only_lossy_hops`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_data_flow.py
    line: 190
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_hop_type_from_lineage_edge`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_drift_detector.py
    line: 49
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_drift_detector.py
    line: 50
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_drift_kind_values`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_drift_detector.py
    line: 59
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_drift_detector.py
    line: 60
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detect_file_moved`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_drift_detector.py
    line: 84
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detect_signature_changed`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_drift_detector.py
    line: 109
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detect_function_removed`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_drift_detector.py
    line: 130
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_no_drift_for_valid_edges`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_drift_detector.py
    line: 154
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_severity_assignment`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_drift_detector.py
    line: 193
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detect_import_drift`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_drift_detector.py
    line: 217
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detect_import_drift_no_drift`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_drift_detector.py
    line: 251
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_unknown_atom_no_file_drift`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_edges.py
    line: 11
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_edges.py
    line: 12
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_projection_type_values`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_edges.py
    line: 23
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_all_eight_types_exist`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_edges.py
    line: 28
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_edges.py
    line: 29
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_edge_roundtrip_serialization`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_edges.py
    line: 53
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_edge_default_confidence`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_edges.py
    line: 62
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_edge_introduction_no_from_unit`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_edges.py
    line: 73
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_edge_to_dict_structure`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_edges.py
    line: 91
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_from_dict_with_missing_optional_fields`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_persistence.py
    line: 18
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_persistence.py
    line: 19
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_lineage_table_persistence_roundtrip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_persistence.py
    line: 51
    column: 27
    code: B905
    message: |
      `zip()` without an explicit `strict=` parameter
    fix_available: true
    fix_message: |
      Add explicit value for parameter `strict=`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_persistence.py
    line: 60
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_persistence.py
    line: 61
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_import_graph_persistence_roundtrip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_persistence.py
    line: 100
    column: 27
    code: B905
    message: |
      `zip()` without an explicit `strict=` parameter
    fix_available: true
    fix_message: |
      Add explicit value for parameter `strict=`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_persistence.py
    line: 106
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_save_creates_parent_directories`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 9
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 45
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_add_edge_indexes_correctly`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 59
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_trace_forward_returns_all_arch_locations`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 69
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_trace_forward_respects_min_confidence`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 78
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_trace_backward_returns_source_atoms`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 85
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_trace_backward_empty_for_unknown`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 91
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_find_orphan_atoms`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 98
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_find_orphan_arch_locations`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 108
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_find_introductions`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 116
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_edges_by_transformation`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 123
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_table_roundtrip_serialization`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 130
    column: 27
    code: B905
    message: |
      `zip()` without an explicit `strict=` parameter
    fix_available: true
    fix_message: |
      Add explicit value for parameter `strict=`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 141
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_remove_edges_for`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 152
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_remove_edges_for_as_to_unit`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_table.py
    line: 161
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_add_edge_returns_edge`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_test_pin_baseline.py
    line: 169
    column: 32
    code: B905
    message: |
      `zip()` without an explicit `strict=` parameter
    fix_available: true
    fix_message: |
      Add explicit value for parameter `strict=`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/lineage/tests/test_test_pin_baseline.py
    line: 326
    column: 18
    code: RUF059
    message: |
      Unpacked variable `changes` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/projection/pin_propagation.py
    line: 58
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/baselines/harness.py
    line: 29
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/baselines/harness.py
    line: 154
    column: 9
    code: F841
    message: |
      Local variable `instance` is assigned to but never used
    fix_available: true
    fix_message: |
      Remove assignment to unused variable `instance`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/logger.py
    line: 96
    column: 17
    code: ANN401
    message: |
      Dynamically typed expressions (typing.Any) are disallowed in `**data`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/phase_evals/alignment_check.py
    line: 35
    column: 9
    code: D105
    message: Missing docstring in magic method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/phase_evals/overview_generation.py
    line: 33
    column: 9
    code: D105
    message: Missing docstring in magic method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/phase_evals/qa_evaluation.py
    line: 33
    column: 9
    code: D105
    message: Missing docstring in magic method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/phase_evals/quality_gates.py
    line: 34
    column: 9
    code: D105
    message: Missing docstring in magic method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/phase_evals/spec_building.py
    line: 40
    column: 9
    code: D105
    message: Missing docstring in magic method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/phase_evals/summarization.py
    line: 38
    column: 9
    code: D105
    message: Missing docstring in magic method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/phase_evals/tasks.py
    line: 40
    column: 9
    code: D105
    message: Missing docstring in magic method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/workflow_integration.py
    line: 311
    column: 25
    code: SIM102
    message: |
      Use a single `if` statement instead of nested `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/workflow_integration.py
    line: 861
    column: 17
    code: SIM105
    message: |
      Use `contextlib.suppress(OSError)` instead of `try`-`except`-`pass`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/workflow_integration.py
    line: 873
    column: 34
    code: ANN401
    message: |
      Dynamically typed expressions (typing.Any) are disallowed in `exc_type`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/workflow_integration.py
    line: 873
    column: 48
    code: ANN401
    message: |
      Dynamically typed expressions (typing.Any) are disallowed in `exc_val`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/evals/workflow_integration.py
    line: 873
    column: 61
    code: ANN401
    message: |
      Dynamically typed expressions (typing.Any) are disallowed in `exc_tb`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/hollowed_spec/adjacency.py
    line: 76
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/hollowed_spec/extractor.py
    line: 252
    column: 9
    code: SIM108
    message: |
      Use ternary operator `body_end = heading_positions[i + 1][0] if i + 1 < len(heading_positions) else len(lines)` instead of `if`-`else`-block
    fix_available: true
    fix_message: |
      Replace `if`-`else`-block with `body_end = heading_positions[i + 1][0] if i + 1 < len(heading_positions) else len(lines)`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/hollowed_spec/searcher.py
    line: 47
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/interactive/signal_exchange.py
    line: 35
    column: 9
    code: D107
    message: |
      Missing docstring in `__init__`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/wrappers/glm_wrapper.py
    line: 217
    column: 36
    code: ANN401
    message: |
      Dynamically typed expressions (typing.Any) are disallowed in `data`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement/wrappers/gpt_wrapper.py
    line: 238
    column: 15
    code: ANN401
    message: |
      Dynamically typed expressions (typing.Any) are disallowed in `data`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement_engine/operations.py
    line: 134
    column: 5
    code: SIM102
    message: |
      Use a single `if` statement instead of nested `if` statements
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/refinement_engine/operations.py
    line: 147
    column: 17
    code: RUF005
    message: |
      Consider `[issue.grouping_unit, *issue.related_units]` instead of concatenation
    fix_available: true
    fix_message: |
      Replace with `[issue.grouping_unit, *issue.related_units]`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/strategies/implementations/translation_entity_resolution.py
    line: 90
    column: 9
    code: SIM110
    message: |
      Use `return any(re.search(pattern, comment_lower) for pattern in _VAGUE_PATTERNS)` instead of `for` loop
    fix_available: true
    fix_message: |
      Replace with `return any(re.search(pattern, comment_lower) for pattern in _VAGUE_PATTERNS)`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/strategies/implementations/translation_entity_resolution.py
    line: 216
    column: 13
    code: S110
    message: |
      `try`-`except`-`pass` detected, consider logging the exception
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/spec_manager/strategies/implementations/translation_entity_resolution.py
    line: 229
    column: 13
    code: S110
    message: |
      `try`-`except`-`pass` detected, consider logging the exception
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 21
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 36
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 66
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 95
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 107
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 113
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 123
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 152
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 173
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 214
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 221
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 246
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 253
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 267
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 284
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 300
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/detection/test_orchestrator.py
    line: 317
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/promotion/test_orchestrator.py
    line: 57
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/promotion/test_orchestrator.py
    line: 58
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/promotion/test_orchestrator.py
    line: 98
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/promotion/test_orchestrator.py
    line: 126
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/promotion/test_orchestrator.py
    line: 156
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/promotion/test_orchestrator.py
    line: 172
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/promotion/test_orchestrator.py
    line: 195
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/promotion/test_orchestrator.py
    line: 223
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/promotion/test_orchestrator.py
    line: 249
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/promotion/test_orchestrator.py
    line: 250
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/compliance/promotion/test_orchestrator.py
    line: 272
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/refinement/hollowed_spec/test_evidence_store_researcher.py
    line: 57
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_research_finds_answer_in_store`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/refinement/hollowed_spec/test_evidence_store_researcher.py
    line: 74
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_research_no_answer_returns_none`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/refinement/hollowed_spec/test_evidence_store_researcher.py
    line: 85
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_flag_as_spec_gap_creates_gap`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/refinement/hollowed_spec/test_evidence_store_researcher.py
    line: 107
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_response_source_is_evidence_store`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/refinement/hollowed_spec/test_evidence_store_researcher.py
    line: 118
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_flag_idempotent`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/refinement/hollowed_spec/test_evidence_store_researcher.py
    line: 133
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_low_score_returns_none`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/workflows/test_evidence_builder.py
    line: 276
    column: 9
    code: F841
    message: |
      Local variable `initial_nodes` is assigned to but never used
    fix_available: true
    fix_message: |
      Remove assignment to unused variable `initial_nodes`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/component/workflows/test_evidence_builder.py
    line: 277
    column: 9
    code: F841
    message: |
      Local variable `initial_edges` is assigned to but never used
    fix_available: true
    fix_message: |
      Remove assignment to unused variable `initial_edges`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_eval_sparse_to_dense.py
    line: 95
    column: 5
    code: F841
    message: |
      Local variable `original_init` is assigned to but never used
    fix_available: true
    fix_message: |
      Remove assignment to unused variable `original_init`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_eval_sparse_to_dense.py
    line: 97
    column: 9
    code: ANN202
    message: |
      Missing return type annotation for private function `fake_init`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_eval_sparse_to_dense.py
    line: 97
    column: 19
    code: ANN001
    message: |
      Missing type annotation for function argument `self`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_eval_sparse_to_dense.py
    line: 97
    column: 25
    code: ANN003
    message: |
      Missing type annotation for `**kwargs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_eval_sparse_to_dense.py
    line: 107
    column: 9
    code: ANN202
    message: |
      Missing return type annotation for private function `fake_run`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_eval_sparse_to_dense.py
    line: 107
    column: 18
    code: ANN001
    message: |
      Missing type annotation for function argument `self`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_eval_sparse_to_dense.py
    line: 107
    column: 24
    code: ANN001
    message: |
      Missing type annotation for function argument `spec_text`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 21
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 26
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 31
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 35
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 39
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 45
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 54
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 72
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 90
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 108
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 109
    column: 14
    code: B017
    message: |
      Do not assert blind exception: `Exception`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 116
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 130
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 144
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 161
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 161
    column: 31
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 167
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 167
    column: 35
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 172
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 172
    column: 33
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 178
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 178
    column: 40
    code: ANN001
    message: |
      Missing type annotation for function argument `mock_run_agent`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 178
    column: 56
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 199
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 199
    column: 42
    code: ANN001
    message: |
      Missing type annotation for function argument `mock_run_agent`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 199
    column: 58
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 226
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 226
    column: 37
    code: ANN001
    message: |
      Missing type annotation for function argument `mock_run_agent`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 226
    column: 53
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 255
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 255
    column: 41
    code: ANN001
    message: |
      Missing type annotation for function argument `mock_run_agent`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 255
    column: 57
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 274
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 274
    column: 44
    code: ANN001
    message: |
      Missing type annotation for function argument `mock_run_agent`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/evals/test_judge_scorer.py
    line: 274
    column: 60
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 89
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 92
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 95
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 98
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 149
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 165
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 203
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 217
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 228
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 269
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 280
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 311
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 322
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 432
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 439
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 448
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 506
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/branches/test_branch_lifecycle.py
    line: 520
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/coverage/test_cli.py
    line: 13
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/coverage/test_cli.py
    line: 14
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/coverage/test_cli.py
    line: 25
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/coverage/test_cli.py
    line: 36
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/coverage/test_cli.py
    line: 62
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/coverage/test_cli.py
    line: 63
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/detection/test_runtime_detector.py
    line: 20
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/detection/test_runtime_detector.py
    line: 27
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/detection/test_runtime_detector.py
    line: 31
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/detection/test_runtime_detector.py
    line: 39
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/detection/test_runtime_detector.py
    line: 52
    column: 9
    code: F841
    message: |
      Local variable `result` is assigned to but never used
    fix_available: true
    fix_message: |
      Remove assignment to unused variable `result`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/detection/test_runtime_detector.py
    line: 112
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/detection/test_runtime_detector.py
    line: 153
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/detection/test_runtime_detector.py
    line: 162
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/detection/test_runtime_detector.py
    line: 176
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/detection/test_runtime_detector.py
    line: 197
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/detection/test_runtime_detector.py
    line: 209
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/detection/test_runtime_detector.py
    line: 222
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/detection/test_runtime_detector.py
    line: 234
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/detection/test_runtime_detector.py
    line: 238
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/test_no_hardcoding_compliance.py
    line: 345
    column: 9
    code: RUF059
    message: |
      Unpacked variable `target_id` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/compliance/test_no_hardcoding_compliance.py
    line: 380
    column: 13
    code: B007
    message: |
      Loop control variable `pattern` not used within loop body
    fix_available: true
    fix_message: |
      Rename unused `pattern` to `_pattern`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/decomposition/test_cli.py
    line: 48
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_staging_discovery_directory`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/decomposition/test_cli.py
    line: 61
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_investigation_directory`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/decomposition/test_cli.py
    line: 73
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_investigation_files`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/decomposition/test_cli.py
    line: 88
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_resolves_by_source_path`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/decomposition/test_cli.py
    line: 98
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_none_for_unknown_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/decomposition/test_cli.py
    line: 110
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_resolves_by_source_path`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/decomposition/test_cli.py
    line: 122
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_none_for_unknown_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/decomposition/test_cli.py
    line: 136
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_fails_for_nonexistent_entity`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/decomposition/test_cli.py
    line: 197
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_remove_lines_marks_as_extracted`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 84
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_finds_two_segment_names`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 84
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 89
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_ignores_single_word`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 89
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 93
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_ignores_all_caps`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 93
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 97
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_ignores_lowercase`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 97
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 119
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_normative_sentence_detected`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 119
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 119
    column: 48
    code: ANN001
    message: |
      Missing type annotation for function argument `text`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 131
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_narrative_sentence_not_detected`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 131
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 131
    column: 52
    code: ANN001
    message: |
      Missing type annotation for function argument `text`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 142
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 143
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_splits_on_period_boundary`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 143
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 152
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_splits_on_semicolons`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 152
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 160
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_splits_on_colons`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 160
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 171
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_filters_short_fragments`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 171
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 182
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 183
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_reads_from_sections_subdirectory`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 183
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 183
    column: 53
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 193
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_reads_from_main_markdown`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 193
    column: 45
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 221
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 222
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_finds_treasury_libraries`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 222
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 222
    column: 45
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 240
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_assigns_correct_primary_sections`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 240
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 240
    column: 53
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 257
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_section_first_matching`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 257
    column: 43
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 279
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_best_candidate_for_section`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 298
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 299
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_treasury_extraction_produces_outputs`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 299
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 299
    column: 57
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 331
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_requirements_contain_dollar_amounts`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 331
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 331
    column: 56
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 335
    column: 101
    code: E501
    message: Line too long (102 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 340
    column: 9
    code: F841
    message: |
      Local variable `result` is assigned to but never used
    fix_available: true
    fix_message: |
      Remove assignment to unused variable `result`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 352
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_charter_has_intent_and_responsibilities`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 352
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 352
    column: 60
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 370
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_input_returns_error`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 370
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/orchestration/test_extraction.py
    line: 370
    column: 46
    code: ANN001
    message: |
      Missing type annotation for function argument `tmp_path`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/planning/test_cli.py
    line: 20
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/planning/test_cli.py
    line: 30
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/planning/test_cli.py
    line: 52
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/planning/test_cli.py
    line: 75
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/planning/test_cli.py
    line: 95
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/planning/test_cli.py
    line: 119
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/planning/test_cli.py
    line: 138
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/planning/test_cli.py
    line: 146
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/planning/test_cli.py
    line: 165
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/planning/test_cli.py
    line: 181
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/planning/test_cli.py
    line: 190
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/planning/test_cli.py
    line: 207
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/hollowed_spec/test_end_to_end.py
    line: 81
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_full_pipeline_hollow_index_search`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/hollowed_spec/test_end_to_end.py
    line: 122
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_ambiguity_resolved_from_evidence_store`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/hollowed_spec/test_end_to_end.py
    line: 150
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_ambiguity_not_resolved_creates_gap`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/hollowed_spec/test_end_to_end.py
    line: 187
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_index_persistence_roundtrip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/interactive/test_coordinator_with_evidence_store.py
    line: 35
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_coordinator_skips_web_when_evidence_found`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/interactive/test_coordinator_with_evidence_store.py
    line: 54
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_coordinator_falls_through_to_web_search`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/interactive/test_coordinator_with_evidence_store.py
    line: 75
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_coordinator_without_evidence_index`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/interactive/test_interactive_workflow_with_resolver.py
    line: 49
    column: 9
    code: ANN202
    message: |
      Missing return type annotation for private function `_detect_signals`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/interactive/test_interactive_workflow_with_resolver.py
    line: 49
    column: 25
    code: ANN001
    message: |
      Missing type annotation for function argument `spec_text`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/interactive/test_interactive_workflow_with_resolver.py
    line: 49
    column: 36
    code: ANN001
    message: |
      Missing type annotation for function argument `workspace`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/interactive/test_interactive_workflow_with_resolver.py
    line: 49
    column: 47
    code: ANN001
    message: |
      Missing type annotation for function argument `work_context`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 1
    column: 1
    code: D100
    message: Missing docstring in public module
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 10
    column: 34
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 10
    column: 38
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 21
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 21
    column: 33
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 21
    column: 37
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 33
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 33
    column: 36
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 33
    column: 40
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 41
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 41
    column: 31
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 41
    column: 35
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 49
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 49
    column: 29
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 49
    column: 33
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 56
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 56
    column: 28
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 56
    column: 32
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 63
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 63
    column: 36
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 63
    column: 40
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 85
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 85
    column: 37
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 85
    column: 41
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 107
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 107
    column: 42
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 107
    column: 46
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 126
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 126
    column: 38
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 126
    column: 42
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 146
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 146
    column: 39
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 146
    column: 43
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 156
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 156
    column: 44
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 156
    column: 48
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 170
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 170
    column: 26
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 170
    column: 30
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 184
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 184
    column: 35
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 184
    column: 39
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 190
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 190
    column: 36
    code: ANN001
    message: |
      Missing type annotation for function argument `fs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/refinement/test_cli.py
    line: 190
    column: 40
    code: ANN001
    message: |
      Missing type annotation for function argument `monkeypatch`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/test_cli_commands.py
    line: 27
    column: 9
    code: F841
    message: |
      Local variable `subparsers` is assigned to but never used
    fix_available: true
    fix_message: |
      Remove assignment to unused variable `subparsers`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/test_cli_commands.py
    line: 94
    column: 17
    code: SIM105
    message: |
      Use `contextlib.suppress(Exception)` instead of `try`-`except`-`pass`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/test_cli_commands.py
    line: 96
    column: 17
    code: S110
    message: |
      `try`-`except`-`pass` detected, consider logging the exception
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/integration/test_cli_commands.py
    line: 113
    column: 9
    code: F841
    message: |
      Local variable `expected_commands` is assigned to but never used
    fix_available: true
    fix_message: |
      Remove assignment to unused variable `expected_commands`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_data_flow.py
    line: 13
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_data_flow.py
    line: 27
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_data_flow.py
    line: 36
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_data_flow.py
    line: 46
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_data_flow.py
    line: 56
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_data_flow.py
    line: 63
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_data_flow.py
    line: 68
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_data_flow.py
    line: 81
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_generator.py
    line: 43
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_generator.py
    line: 110
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_generator.py
    line: 126
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_generator.py
    line: 168
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_generator.py
    line: 182
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_import_scanner.py
    line: 93
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_import_scanner.py
    line: 130
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_import_scanner.py
    line: 152
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_import_scanner.py
    line: 165
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_import_scanner.py
    line: 169
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_projection_classifier.py
    line: 106
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_projection_classifier.py
    line: 141
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_projection_classifier.py
    line: 155
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_projection_classifier.py
    line: 172
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_report_renderer.py
    line: 22
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_report_renderer.py
    line: 78
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_report_renderer.py
    line: 96
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_report_renderer.py
    line: 123
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_report_renderer.py
    line: 142
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_report_renderer.py
    line: 165
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/analysis/test_report_renderer.py
    line: 188
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 26
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 33
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 38
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 43
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 52
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 76
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 82
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 92
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 112
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 129
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 151
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 163
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 175
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 189
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 204
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_analysis.py
    line: 234
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_atoms.py
    line: 14
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_atoms.py
    line: 21
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_atoms.py
    line: 28
    column: 5
    code: ANN003
    message: |
      Missing type annotation for `**kwargs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_atoms.py
    line: 46
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_atoms.py
    line: 51
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_atoms.py
    line: 54
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_atoms.py
    line: 60
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_atoms.py
    line: 64
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_atoms.py
    line: 71
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_atoms.py
    line: 82
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_atoms.py
    line: 93
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_atoms.py
    line: 99
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_atoms.py
    line: 123
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_atoms.py
    line: 137
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_collapse.py
    line: 14
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_collapse.py
    line: 21
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_collapse.py
    line: 28
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_collapse.py
    line: 44
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_collapse.py
    line: 61
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_collapse.py
    line: 82
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_collapse.py
    line: 104
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_collapse.py
    line: 113
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_collapse.py
    line: 117
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_collapse.py
    line: 125
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_collapse.py
    line: 132
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_collapse.py
    line: 146
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_collapse.py
    line: 167
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_collapse.py
    line: 194
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 15
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 22
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 27
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 46
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 51
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 62
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 71
    column: 13
    code: RUF059
    message: |
      Unpacked variable `errors` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 78
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 79
    column: 13
    code: RUF059
    message: |
      Unpacked variable `errors` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 82
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 89
    column: 13
    code: RUF059
    message: |
      Unpacked variable `errors` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 92
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 101
    column: 13
    code: RUF059
    message: |
      Unpacked variable `errors` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 108
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 117
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 118
    column: 13
    code: RUF059
    message: |
      Unpacked variable `errors` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 121
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 127
    column: 13
    code: RUF059
    message: |
      Unpacked variable `errors` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 134
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 143
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 156
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 165
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_compliance.py
    line: 184
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_downward_flow.py
    line: 25
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_downward_flow.py
    line: 32
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_downward_flow.py
    line: 37
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_downward_flow.py
    line: 42
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_downward_flow.py
    line: 79
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_downward_flow.py
    line: 102
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_downward_flow.py
    line: 120
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_downward_flow.py
    line: 132
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_downward_flow.py
    line: 157
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_downward_flow.py
    line: 184
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_downward_flow.py
    line: 199
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_downward_flow.py
    line: 207
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_downward_flow.py
    line: 226
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 12
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 19
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 34
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 43
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 49
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 57
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 65
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 72
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 82
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 92
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 98
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 108
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 118
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 131
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 150
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 157
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_gap_detection.py
    line: 165
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_layout.py
    line: 16
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_layout.py
    line: 19
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_layout.py
    line: 22
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_layout.py
    line: 25
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_layout.py
    line: 28
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_layout.py
    line: 31
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_layout.py
    line: 34
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_layout.py
    line: 41
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_layout.py
    line: 46
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_layout.py
    line: 61
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_layout.py
    line: 67
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_layout.py
    line: 71
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 19
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 38
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 41
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 46
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 51
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 60
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 66
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 70
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 76
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 88
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 101
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 118
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 129
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 154
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 174
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 189
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 195
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 209
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 221
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 226
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 232
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 240
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_manager.py
    line: 266
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pin_function_schema.py
    line: 13
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pin_function_schema.py
    line: 24
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pin_function_schema.py
    line: 36
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pin_function_schema.py
    line: 45
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pin_function_schema.py
    line: 54
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pin_function_schema.py
    line: 63
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pin_function_schema.py
    line: 73
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pin_function_schema.py
    line: 83
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 21
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 28
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 64
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 69
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 72
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 78
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 82
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 91
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 97
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 103
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 110
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 116
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 123
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 131
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 140
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 151
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 172
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 194
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 205
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 218
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 223
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 231
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 243
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 247
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_pins.py
    line: 259
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_projection_extension.py
    line: 11
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_projection_extension.py
    line: 20
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_promotion.py
    line: 21
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_promotion.py
    line: 28
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_promotion.py
    line: 33
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_promotion.py
    line: 38
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_promotion.py
    line: 61
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_promotion.py
    line: 75
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_promotion.py
    line: 97
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_promotion.py
    line: 105
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_promotion.py
    line: 121
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_promotion.py
    line: 142
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_promotion.py
    line: 159
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 22
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 29
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 34
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 39
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 62
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 68
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 74
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 78
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 90
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 94
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 97
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 108
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 123
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 128
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 134
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 138
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 147
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 163
    column: 35
    code: E741
    message: |
      Ambiguous variable name: `l`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 168
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 188
    column: 35
    code: E741
    message: |
      Ambiguous variable name: `l`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 192
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 197
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 204
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 213
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 217
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 236
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 244
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 255
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 268
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 277
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 287
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 296
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 317
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_slices.py
    line: 330
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 20
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 25
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 30
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 35
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 45
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 53
    column: 32
    code: ANN003
    message: |
      Missing type annotation for `**overrides`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 66
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 74
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 81
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 101
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 107
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 126
    column: 25
    code: ANN003
    message: |
      Missing type annotation for `**overrides`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 136
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 141
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 156
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 171
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 178
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/branches/test_types.py
    line: 192
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_analyzer.py
    line: 93
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_analyzer.py
    line: 94
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_analyzer.py
    line: 120
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_analyzer.py
    line: 137
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_analyzer.py
    line: 154
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_analyzer.py
    line: 180
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_analyzer.py
    line: 209
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_analyzer.py
    line: 225
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_analyzer.py
    line: 243
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_analyzer.py
    line: 275
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_gate.py
    line: 46
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_gate.py
    line: 47
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_gate.py
    line: 74
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_gate.py
    line: 95
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_gate.py
    line: 113
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_gate.py
    line: 133
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_gate.py
    line: 164
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_gate.py
    line: 178
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_gate.py
    line: 193
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_gate.py
    line: 194
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 62
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 63
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 69
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 75
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 81
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 87
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 93
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 97
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 102
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 103
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 125
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 140
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 157
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 163
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 164
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 173
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 179
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 187
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 194
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 200
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 201
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 216
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 228
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 243
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 251
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 264
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 265
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 277
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 289
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 302
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/coverage/test_matching.py
    line: 306
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 19
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 30
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 39
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 48
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 60
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 70
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 85
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 97
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 109
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 132
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 147
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 169
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 174
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 185
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 212
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 221
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 238
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 249
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 265
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_call_graph.py
    line: 270
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 18
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 36
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 47
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 58
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 69
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 81
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 91
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 103
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 116
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 128
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 142
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 159
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 171
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 185
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 200
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 232
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 256
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 271
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_comment_scanner.py
    line: 275
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_coverage_analyzer.py
    line: 16
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_coverage_analyzer.py
    line: 43
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_coverage_analyzer.py
    line: 63
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_coverage_analyzer.py
    line: 110
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_coverage_analyzer.py
    line: 115
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_coverage_analyzer.py
    line: 135
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_coverage_analyzer.py
    line: 161
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_coverage_analyzer.py
    line: 179
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_gap_types.py
    line: 17
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_gap_types.py
    line: 20
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_gap_types.py
    line: 23
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_gap_types.py
    line: 26
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_gap_types.py
    line: 29
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_gap_types.py
    line: 32
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_gap_types.py
    line: 44
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_gap_types.py
    line: 63
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_gap_types.py
    line: 87
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_gap_types.py
    line: 92
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_gap_types.py
    line: 97
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_gap_types.py
    line: 102
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_gap_types.py
    line: 107
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_gap_types.py
    line: 112
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 18
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 32
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 44
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 56
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 68
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 82
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 94
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 107
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 123
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 137
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 149
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 161
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 187
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 200
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 218
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 246
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/detection/test_stub_scanner.py
    line: 250
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 26
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 27
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 42
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 58
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 63
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 68
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 93
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 94
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 108
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 122
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 136
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 150
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 164
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 170
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 171
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 181
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 191
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 200
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 214
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 215
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 231
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 257
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 270
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 276
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 277
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 290
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_algorithmic_gates.py
    line: 324
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_architectural_quality.py
    line: 45
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_architectural_quality.py
    line: 46
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_architectural_quality.py
    line: 85
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_architectural_quality.py
    line: 121
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_architectural_quality.py
    line: 167
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_architectural_quality.py
    line: 208
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_architectural_quality.py
    line: 215
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_architectural_quality.py
    line: 216
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_architectural_quality.py
    line: 246
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_architectural_quality.py
    line: 277
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_architectural_quality.py
    line: 309
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_architectural_quality.py
    line: 337
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_architectural_quality.py
    line: 351
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 21
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 22
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 25
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 29
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 30
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 34
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 53
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 54
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 61
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 75
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 76
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 82
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 89
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 104
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 111
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 118
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 124
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 125
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 144
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 158
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 159
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 176
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_config.py
    line: 201
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 46
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 47
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 50
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 53
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 56
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 59
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 62
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 66
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 67
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 99
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 124
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 148
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 149
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 180
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 209
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_introduction_checker.py
    line: 244
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_pin_coverage.py
    line: 39
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_pin_coverage.py
    line: 40
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_pin_coverage.py
    line: 80
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_pin_coverage.py
    line: 96
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_pin_coverage.py
    line: 116
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_pin_coverage.py
    line: 131
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_pin_coverage.py
    line: 155
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_pin_coverage.py
    line: 161
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_pin_coverage.py
    line: 192
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_pin_coverage.py
    line: 193
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_pin_coverage.py
    line: 219
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_pin_coverage.py
    line: 248
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_pin_coverage.py
    line: 263
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 41
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 42
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 52
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 63
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 81
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 98
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 115
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 116
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 129
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 133
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 151
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 165
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 184
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 189
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 206
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 207
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 221
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 244
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 266
    column: 7
    code: D101
    message: Missing docstring in public class
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 267
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 285
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 295
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_provenance.py
    line: 317
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/promotion/test_test_pin_gate.py
    line: 107
    column: 9
    code: F841
    message: |
      Local variable `test_file` is assigned to but never used
    fix_available: true
    fix_message: |
      Remove assignment to unused variable `test_file`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/test_evidence_field_lint.py
    line: 111
    column: 17
    code: RUF059
    message: |
      Unpacked variable `warnings` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/test_evidence_field_lint.py
    line: 121
    column: 17
    code: RUF059
    message: |
      Unpacked variable `warnings` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/test_evidence_field_lint.py
    line: 131
    column: 17
    code: RUF059
    message: |
      Unpacked variable `warnings` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/test_evidence_field_lint.py
    line: 159
    column: 17
    code: RUF059
    message: |
      Unpacked variable `warnings` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/test_evidence_field_lint.py
    line: 174
    column: 17
    code: RUF059
    message: |
      Unpacked variable `warnings` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/test_evidence_field_lint.py
    line: 182
    column: 17
    code: RUF059
    message: |
      Unpacked variable `warnings` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/test_evidence_field_lint.py
    line: 190
    column: 9
    code: RUF059
    message: |
      Unpacked variable `errors` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/test_evidence_field_lint.py
    line: 282
    column: 17
    code: RUF059
    message: |
      Unpacked variable `warnings` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/test_evidence_field_lint.py
    line: 288
    column: 9
    code: RUF059
    message: |
      Unpacked variable `errors` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/compliance/test_evidence_field_lint.py
    line: 294
    column: 17
    code: RUF059
    message: |
      Unpacked variable `warnings` is never used
    fix_available: true
    fix_message: Prefix it with an underscore or any other dummy variable pattern
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 44
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_valid_metrics`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 55
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_gate_passed_all_above_threshold`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 64
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_gate_failed_one_below_threshold`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 73
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_invalid_metric_above_one`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 82
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_invalid_metric_below_zero`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 91
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_invalid_threshold_above_one`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 101
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_boundary_values`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 111
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_to_dict_from_dict_roundtrip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 130
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_field_naming_clarity`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 141
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_to_dict_serializes_id`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 153
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_from_dict_requires_canonical_keys`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 179
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_recommended_variant_field`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 187
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_rank_variants_with_empty_variants_list`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 198
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_rank_variants_sets_recommended_variant`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 219
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_to_dict_serializes_recommended_variant`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 229
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_from_dict_requires_canonical_keys`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 252
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_stagnation_with_same_content_different_order`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 271
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_no_stagnation_with_different_content_same_length`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 284
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_progress_when_item_removed`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 296
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_to_dict_includes_content_hash`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 304
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_from_dict_deserializes_correctly`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 321
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_last_size_set_on_update`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 335
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_to_dict_includes_last_size`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 343
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_mark_progress_resets_stagnation`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 359
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_evidence_raises_error`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 364
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_deterministic_signature`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 378
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_order_independent`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 387
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_fully_deterministic_with_ties`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 412
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_confidence_rounding`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 422
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_different_confidence_different_signature`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 431
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_signature_length`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 441
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_dict`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 445
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_json_serializable_types`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 452
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_non_serializable_datetime`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 460
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_non_serializable_path`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 470
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_unsupported_type_raises_error`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 477
    column: 46
    code: RUF043
    message: |
      Pattern passed to `match=` contains metacharacters but is neither escaped nor raw
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 480
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_nested_non_serializable`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 491
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_deterministic_key_order`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 501
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_gap_creation_with_evidence`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 524
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_basic_creation`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 537
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creation_with_all_fields`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 553
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_serialization_roundtrip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 573
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_serialization_with_path_objects`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 585
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_serialization_with_datetime_objects`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 596
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_serialization_with_nested_structures`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 616
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_serialization_with_unsupported_types_raises_error`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 627
    column: 46
    code: RUF043
    message: |
      Pattern passed to `match=` contains metacharacters but is neither escaped nor raw
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 630
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_details_dict`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 643
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_from_dict_with_missing_optional_fields`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 659
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_gap_creation_with_evidence_list`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 674
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_serialization_roundtrip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 708
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_severity_serialization`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 730
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_valid_status_values`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 730
    column: 40
    code: ANN001
    message: |
      Missing type annotation for function argument `status`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 744
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_affected_elements_list`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 759
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_timestamps_auto_generated`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 770
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_resolution_notes_optional`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 791
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_evidence_list_deserialization`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 802
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_multiple_evidence_items`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 843
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_basic_creation`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 854
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_mark_validated_passed`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 863
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_mark_validated_failed_with_errors`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 872
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_mark_validated_clears_stale_errors_on_pass`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 882
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_mark_validated_failed_with_none_errors`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 890
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_serialization_roundtrip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 915
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_applied_at_auto_generated`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 921
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_unit_ids_serialization`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 932
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_metrics_dict_serialization`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 952
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_notes_field_optional`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 966
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_default_validation_status_is_pending`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 971
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_validation_errors_defaults_to_empty_list`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 976
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_validation_state_transitions`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 995
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_gap_with_gap_evidence_serialization_chain`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1034
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_conflict_bundle_with_multiple_variants_ranking`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1081
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_remainder_queue_duplicate_detection`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1097
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_compute_evidence_signature_with_complex_details`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1118
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_all_status_constants_are_valid_strings`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1147
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_compliance_metrics_custom_threshold`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1148
    column: 15
    code: ANN001
    message: |
      Missing type annotation for function argument `threshold`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1148
    column: 26
    code: ANN001
    message: |
      Missing type annotation for function argument `format_val`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1148
    column: 38
    code: ANN001
    message: |
      Missing type annotation for function argument `annotation_val`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1148
    column: 54
    code: ANN001
    message: |
      Missing type annotation for function argument `id_val`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1148
    column: 62
    code: ANN001
    message: |
      Missing type annotation for function argument `expected`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1173
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_gap_evidence_confidence_rounding_in_signature`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1173
    column: 66
    code: ANN001
    message: |
      Missing type annotation for function argument `confidence`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1173
    column: 78
    code: ANN001
    message: |
      Missing type annotation for function argument `rounded`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1197
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_compute_evidence_signature_with_large_evidence_list`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1217
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_remainder_queue_with_large_item_list`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1235
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_conflict_bundle_ranking_with_many_variants`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1259
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_serialization_of_large_gap_with_many_evidence_items`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/core/test_data_structures.py
    line: 1292
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_nested_details_serialization_depth`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 30
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_load_empty_workspace`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 35
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_load_existing_index`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 51
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_save_creates_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 59
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_save_load_roundtrip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 83
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_adds_new_entity`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 100
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_normalizes_keywords_to_lowercase`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 117
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_adds_name_as_keyword`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 130
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_removes_duplicate_keywords`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 150
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_adds_source_to_existing_entity`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 159
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_does_not_duplicate_source`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 167
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_ignores_nonexistent_entity`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 177
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_adds_keywords_to_existing_entity`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 186
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_does_not_duplicate_keywords`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 200
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_no_match_in_empty_index`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 205
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_exact_keyword_match`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 213
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_partial_keyword_match`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 222
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_name_as_keyword`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 229
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_no_match_below_threshold`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 239
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_matched_keywords`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 250
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_finds_best_match_among_multiple`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 266
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_index`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 271
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_maps_keywords_to_entities`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_entity_index.py
    line: 282
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_later_entity_overwrites_keyword`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 29
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_default_values`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 39
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_to_dict`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 57
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_from_dict`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 79
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_default_values`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 86
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_to_dict`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 102
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_from_dict`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 121
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_default_values`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 130
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_to_dict_roundtrip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 157
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_sha256_prefix`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 162
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_same_content_same_hash`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 169
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_different_content_different_hash`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 179
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_save_creates_execution_dir`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 190
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_load_returns_empty_ledger_when_no_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 199
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_save_load_roundtrip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 223
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_gaps_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 245
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_hashes_entity_files`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 261
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_hashes_relation_files`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 272
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_empty_for_empty_workspace`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 284
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detects_new_ids`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 297
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detects_modified_ids`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 310
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detects_deleted_ids`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 327
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_pending_ids`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 336
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_modified_ids`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 344
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_excludes_ids_blocked_by_gaps`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 354
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_includes_ids_with_resolved_gaps`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 369
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_prompt_files`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 383
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_prompts_contain_target_ids`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 394
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_empty_for_no_runnable_ids`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 406
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_updates_entry_status`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 433
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_adds_gaps_from_evidence`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 462
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_ledger_for_new_workspace`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 478
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_detects_modified_specs`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_execution.py
    line: 500
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_ingests_evidence_when_provided`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_extract.py
    line: 32
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_entity_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_extract.py
    line: 46
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_entity_document_has_correct_structure`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_extract.py
    line: 67
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_multiple_evidence_items`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_extract.py
    line: 93
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_relation_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_extract.py
    line: 107
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_relation_document_structure`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_extract.py
    line: 131
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_context_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_extract.py
    line: 144
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_context_document_structure`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_extract.py
    line: 162
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_handles_nested_evidence_structure`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_extract.py
    line: 182
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_appends_evidence_to_existing_entity`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_extract.py
    line: 203
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_raises_for_nonexistent_entity`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_extract.py
    line: 213
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_rich_relation_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_extract.py
    line: 234
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_rich_relation_structure`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_extract.py
    line: 270
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_discovered_entity_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_extract.py
    line: 283
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_discovered_entity_structure`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 88
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_workspace`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 99
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_builds_nodes_from_entities`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 109
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_builds_edges_from_relations`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 118
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_builds_adjacency_lists`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 132
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_edge_includes_type`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 142
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_statistics_correct`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 153
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_saves_json_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 169
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_saves_mermaid_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 189
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_generates_valid_mermaid`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 207
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_escapes_quotes_in_names`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 219
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_uses_different_arrow_styles`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 243
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_simple_chain`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 258
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_multiple_roots`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 274
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_handles_isolated_nodes`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 288
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_handles_cycle`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 307
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_no_cycles`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 321
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_finds_simple_cycle`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 339
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_finds_three_node_cycle`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_graph.py
    line: 353
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_graph`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 21
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_entity_type_value`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 25
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_relation_type_value`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 29
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_context_type_value`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 33
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_composition_type_value`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 37
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_orphan_type_value`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 41
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_snippet_type_value`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 49
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_generate_first_entity_id`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 55
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_generate_sequential_entity_ids`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 61
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_generate_first_relation_id`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 67
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_generate_id_with_mixed_types`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 83
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_generate_snippet_id`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 89
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_generate_id_with_gaps_in_sequence`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 95
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_generate_id_formatting_three_digits`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 106
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_load_id_map_empty_workspace`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 111
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_load_id_map_existing_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 123
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_save_id_map_creates_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 134
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_save_load_roundtrip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 154
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_entity_ids`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 165
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_relation_ids`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 176
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_ids_empty_result`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 182
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_ids_empty_map`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 192
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_source_lines_existing_id`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 205
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_source_lines_nonexistent_id`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_id_generator.py
    line: 211
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_get_source_lines_empty_map`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 58
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_staging_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 64
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_adds_header_comment`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 71
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_preserves_original_content`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 73
    column: 9
    code: F841
    message: |
      Local variable `original` is assigned to but never used
    fix_available: true
    fix_message: |
      Remove assignment to unused variable `original`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 84
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_embeds_id_at_correct_line`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 96
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_does_not_duplicate_id`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 104
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_can_embed_multiple_ids_same_line`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 117
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_removes_line_content`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 125
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_removed_content`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 135
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_removes_multiple_lines`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 145
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_removed_in_order`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 157
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_all_content_lines`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 165
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_excludes_extracted_lines`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 173
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_excludes_empty_lines`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 183
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_file_not_empty_initially`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 188
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_file_empty_after_all_extracted`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 203
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_correct_line`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 209
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_empty_for_invalid_line`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 219
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_embedded_ids`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 230
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_empty_when_no_ids`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 240
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_marks_line_with_snippet_comment`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 247
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_does_not_mark_already_marked`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 255
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_does_not_mark_extracted_lines`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 267
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_marked_snippets`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 278
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_empty_when_no_snippets`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 288
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_collects_and_removes_snippets`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 301
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_snippet_text`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 312
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_snippet_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 338
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_appends_to_existing_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 358
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_formats_with_line_numbers`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 368
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_excludes_extracted_lines`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 375
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_excludes_snippet_lines`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_staging.py
    line: 383
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_when_all_extracted`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_workspace.py
    line: 50
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_directory_structure`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_workspace.py
    line: 63
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_creates_initial_files`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_workspace.py
    line: 72
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_stages_single_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_workspace.py
    line: 82
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_stages_multiple_files_from_directory`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_workspace.py
    line: 94
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_initializes_state_correctly`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_workspace.py
    line: 109
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_cleans_existing_workspace`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_workspace.py
    line: 119
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_id_map_initialized_empty`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_workspace.py
    line: 127
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_entity_index_initialized_empty`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_workspace.py
    line: 139
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_loads_existing_state`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_workspace.py
    line: 152
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_returns_empty_dict_when_no_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_workspace.py
    line: 161
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_saves_state_to_file`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_workspace.py
    line: 175
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_overwrites_existing_state`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/decomposition/test_workspace.py
    line: 186
    column: 9
    code: ANN201
    message: |
      Missing return type annotation for public function `test_save_load_roundtrip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 52
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 61
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 70
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 81
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 91
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 101
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 114
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 123
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 135
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 144
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 149
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 154
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 159
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 164
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 169
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 174
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 179
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 187
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 194
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 206
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 216
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 226
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 249
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 260
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_adjacency.py
    line: 273
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 73
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 76
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 79
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 82
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 85
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 88
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 91
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 94
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 97
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 104
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 112
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 116
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 121
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 127
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 132
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 137
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 142
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 147
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 152
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 157
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 164
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 169
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 175
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 181
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 192
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 205
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 213
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 228
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 237
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 259
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 270
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 275
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 280
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_code_parser.py
    line: 285
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_evidence_store.py
    line: 18
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_evidence_store.py
    line: 30
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_evidence_store.py
    line: 41
    column: 20
    code: B011
    message: |
      Do not `assert False` (`python -O` removes these calls), raise `AssertionError()`
    fix_available: true
    fix_message: |
      Replace `assert False`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_evidence_store.py
    line: 49
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_evidence_store.py
    line: 61
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 45
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 69
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 89
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 104
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 119
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 135
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 155
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 176
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 195
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 218
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 232
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 244
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 261
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 269
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 277
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_gap_bridge.py
    line: 282
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 25
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 30
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 35
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 40
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 45
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 54
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 60
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 68
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 76
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 81
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 91
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 118
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 144
    column: 24
    code: RUF015
    message: |
      Prefer `next(l for l in result_lines if "# validate input" in l)` over single element slice
    fix_available: true
    fix_message: |
      Replace with `next(l for l in result_lines if "# validate input" in l)`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 144
    column: 31
    code: E741
    message: |
      Ambiguous variable name: `l`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 148
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 227
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 232
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 237
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 252
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_inserter.py
    line: 270
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 20
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 23
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 26
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 38
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 69
    column: 20
    code: B011
    message: |
      Do not `assert False` (`python -O` removes these calls), raise `AssertionError()`
    fix_available: true
    fix_message: |
      Replace `assert False`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 77
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 91
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 103
    column: 20
    code: B011
    message: |
      Do not `assert False` (`python -O` removes these calls), raise `AssertionError()`
    fix_available: true
    fix_message: |
      Replace `assert False`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 111
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 133
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 151
    column: 20
    code: B011
    message: |
      Do not `assert False` (`python -O` removes these calls), raise `AssertionError()`
    fix_available: true
    fix_message: |
      Replace `assert False`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 159
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 187
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 211
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 228
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_models.py
    line: 242
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 35
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 40
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 45
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 50
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 55
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 60
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 64
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 73
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 85
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 96
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 111
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 120
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 128
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 136
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 143
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 162
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 176
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/planning/test_reverser.py
    line: 188
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_adjacency.py
    line: 62
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_entity_co_occurrence_finds_related`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_adjacency.py
    line: 80
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_store_touch_finds_shared_store`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_adjacency.py
    line: 96
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_call_graph_finds_function_reference`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_adjacency.py
    line: 112
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_exclude_own_library`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_adjacency.py
    line: 120
    column: 101
    code: E501
    message: Line too long (101 > 100)
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_adjacency.py
    line: 127
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_all_evidence_deduplicates`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_adjacency.py
    line: 146
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_index_returns_empty_context`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_adjacency.py
    line: 165
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_max_results_per_signal`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_extractor.py
    line: 60
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_hollow_out_basic_spec`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_extractor.py
    line: 83
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_paragraph_classification`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_extractor.py
    line: 98
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_keyword_extraction`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_extractor.py
    line: 119
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_entity_ref_extraction`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_extractor.py
    line: 130
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_spec_hash_changes_on_content_change`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_extractor.py
    line: 140
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_spec_produces_empty_hollowed_spec`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_extractor.py
    line: 152
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_keyword_index_populated`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_extractor.py
    line: 167
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_entity_index_populated`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_extractor.py
    line: 179
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_paragraph_line_numbers`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_extractor.py
    line: 183
    column: 9
    code: B007
    message: |
      Loop control variable `para_id` not used within loop body
    fix_available: true
    fix_message: |
      Rename unused `para_id` to `_para_id`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_extractor.py
    line: 188
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_section_ids_unique`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_extractor.py
    line: 196
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_paragraph_ids_unique`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_hooks.py
    line: 63
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_on_spec_completed_creates_hollowed_spec`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_hooks.py
    line: 78
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_on_spec_completed_updates_index`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_hooks.py
    line: 91
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_rebuild_index_from_multiple_specs`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_hooks.py
    line: 116
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_hook_is_idempotent`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_hooks.py
    line: 132
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_hook_re_hollows_on_content_change`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_hooks.py
    line: 154
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_missing_spec_md_skips`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_indexer.py
    line: 60
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_build_index_from_single_spec`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_indexer.py
    line: 80
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_build_index_from_multiple_specs`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_indexer.py
    line: 103
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_remove_and_rebuild`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_indexer.py
    line: 126
    column: 9
    code: B007
    message: |
      Loop control variable `kw` not used within loop body
    fix_available: true
    fix_message: |
      Rename unused `kw` to `_kw`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_indexer.py
    line: 131
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_index_persistence_roundtrip`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_indexer.py
    line: 155
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_load_nonexistent_path`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_indexer.py
    line: 162
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_add_spec_replaces_existing`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_indexer.py
    line: 168
    column: 5
    code: F841
    message: |
      Local variable `para_count_1` is assigned to but never used
    fix_available: true
    fix_message: |
      Remove assignment to unused variable `para_count_1`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_indexer.py
    line: 172
    column: 5
    code: F841
    message: |
      Local variable `para_count_2` is assigned to but never used
    fix_available: true
    fix_message: |
      Remove assignment to unused variable `para_count_2`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_searcher.py
    line: 67
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_keyword_search_basic`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_searcher.py
    line: 82
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_entity_search_boost`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_searcher.py
    line: 90
    column: 5
    code: F841
    message: |
      Local variable `results_without_entity` is assigned to but never used
    fix_available: true
    fix_message: |
      Remove assignment to unused variable `results_without_entity`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_searcher.py
    line: 99
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_exclude_lib_ids`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_searcher.py
    line: 111
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_search_for_ambiguity`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_searcher.py
    line: 133
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_no_results_returns_empty`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_searcher.py
    line: 142
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_min_score_filters`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_searcher.py
    line: 155
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_max_results_limits`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_searcher.py
    line: 164
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_empty_query_returns_empty`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/hollowed_spec/test_searcher.py
    line: 173
    column: 5
    code: ANN201
    message: |
      Missing return type annotation for public function `test_entity_only_search`
    fix_available: true
    fix_message: |
      Add return type annotation: `None`
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/interactive/test_signal_exchange.py
    line: 32
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/interactive/test_signal_exchange.py
    line: 44
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/interactive/test_signal_exchange.py
    line: 55
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/interactive/test_signal_exchange.py
    line: 65
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/interactive/test_signal_exchange.py
    line: 70
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/interactive/test_signal_exchange.py
    line: 88
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/interactive/test_signal_exchange.py
    line: 99
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/interactive/test_signal_exchange.py
    line: 118
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/interactive/test_signal_exchange.py
    line: 133
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/interactive/test_signal_exchange.py
    line: 143
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/interactive/test_signal_exchange.py
    line: 162
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/interactive/test_signal_exchange.py
    line: 168
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/test_library_structure_review_fixtures.py
    line: 38
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/test_library_structure_review_fixtures.py
    line: 82
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/test_library_structure_review_fixtures.py
    line: 108
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/test_library_structure_review_fixtures.py
    line: 139
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/refinement/test_library_structure_review_fixtures.py
    line: 146
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 22
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 32
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 43
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 52
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 61
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 69
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 85
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 102
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 107
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 120
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 126
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 140
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 148
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 181
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 186
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 194
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 205
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 214
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/schemas/test_lineage.py
    line: 238
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_base.py
    line: 17
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_base.py
    line: 20
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_base.py
    line: 23
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_base.py
    line: 42
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_base.py
    line: 53
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_base.py
    line: 74
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_base.py
    line: 81
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 33
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 36
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 48
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 58
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 68
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 78
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 88
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 101
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 112
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 157
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 172
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 186
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 210
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 221
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 225
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 235
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 267
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 279
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 290
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 306
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 311
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 326
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 343
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 352
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 362
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 384
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 430
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_evolution.py
    line: 439
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_format_repair.py
    line: 1
    column: 1
    code: D100
    message: Missing docstring in public module
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_format_repair.py
    line: 22
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_format_repair.py
    line: 42
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_format_repair.py
    line: 66
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_format_repair.py
    line: 89
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_format_repair.py
    line: 92
    column: 37
    code: ANN401
    message: |
      Dynamically typed expressions (typing.Any) are disallowed in `**kwargs`
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 22
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 25
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 28
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 31
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 34
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 37
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 40
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 47
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 56
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 69
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 78
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 86
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 97
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 106
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 114
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 126
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 153
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_gap_evidence.py
    line: 168
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 39
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 43
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 49
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 54
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 60
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 63
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 66
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 86
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 96
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 104
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 114
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 127
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 131
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 144
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 157
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 167
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 175
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 191
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 204
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 218
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 228
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 245
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 259
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 277
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 291
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 311
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 324
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 337
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 349
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 363
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_implementations.py
    line: 367
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_persistence.py
    line: 29
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_persistence.py
    line: 52
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_persistence.py
    line: 86
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_persistence.py
    line: 92
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_persistence.py
    line: 114
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_persistence.py
    line: 139
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_persistence.py
    line: 149
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_persistence.py
    line: 181
    column: 9
    code: D102
    message: Missing docstring in public method
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_truncation_guard.py
    line: 1
    column: 1
    code: D100
    message: Missing docstring in public module
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_truncation_guard.py
    line: 20
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_truncation_guard.py
    line: 39
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_truncation_guard.py
    line: 62
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/strategies/test_truncation_guard.py
    line: 85
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/workflow/test_context_index_builder.py
    line: 1
    column: 1
    code: D100
    message: Missing docstring in public module
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/workflow/test_context_index_builder.py
    line: 21
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/workflow/test_context_index_builder.py
    line: 31
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/workflow/test_context_index_builder.py
    line: 55
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/workflow/test_context_index_builder.py
    line: 78
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false
  - linter: ruff
    file: /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager/tests/unit/workflow/test_context_index_builder.py
    line: 109
    column: 5
    code: D103
    message: Missing docstring in public function
    fix_available: false


Working directory: /mnt/c/Users/xteam/IdeaProjects/ai-workflow