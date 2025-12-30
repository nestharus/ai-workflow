# How To Add Python Dependencies Correctly

When adding a new dependency to `pyproject.toml`, follow this workflow:

## Step 1: Fetch Latest Version from PyPI

Fetch the latest version from PyPI using either of the methods below. Both are valid:
use **curl + jq** for readability, or **Python stdlib** when external tools are unavailable.

**Environment requirements**:

* **Network access**: Requires outbound HTTPS connection to `pypi.org` (may fail behind
  corporate proxies or firewalls)
* **TLS/SSL**: Requires a working Python SSL/TLS stack (certificate verification enabled)
* **API stability**: Relies on the PyPI JSON API (`/pypi/<package>/json` endpoint)

**Troubleshooting**:

* **Proxy issues**: Set `HTTP_PROXY` and `HTTPS_PROXY` environment variables if behind a proxy
* **TLS errors**: Verify Python's SSL certificates are up-to-date
  (`uv run python -c "import ssl; print(ssl.OPENSSL_VERSION)"`)
* **Connectivity check**: Test network access with
  `uv run python -c "import urllib.request; urllib.request.urlopen('https://pypi.org')"`
* **Alternative tools**: Use `curl https://pypi.org/pypi/<package-name>/json | jq -r '.info.version'`
  or `wget` if urllib fails

**Option 1: curl + jq** (recommended for readability):

```bash
curl -s https://pypi.org/pypi/<package-name>/json | jq -r '.info.version'
```

**Option 2: Python one-liner** (works without external tools):

```bash
uv run python -c "import urllib.request, json; print(json.loads(urllib.request.urlopen('https://pypi.org/pypi/<package-name>/json').read())['info']['version'])"
```

Both options fetch the PyPI JSON API and extract the `info.version` field.

**Note**: If you do not have `jq` installed and prefer not to use the long Python one-liner,
save this script to a file (e.g., `scripts/get_pypi_version.py`) and run it with
`uv run python scripts/get_pypi_version.py <package-name>`:

```python
#!/usr/bin/env python3
import json
import sys
import urllib.request

package = sys.argv[1] if len(sys.argv) > 1 else input("Package name: ")
url = f"https://pypi.org/pypi/{package}/json"
data = json.loads(urllib.request.urlopen(url).read())
print(data["info"]["version"])
```

**Manual fallback**: If the command fails, verify the package name spelling and try one of:

* Visit `https://pypi.org/project/<package-name>/` directly in a browser
* Use `pip index versions <package-name>` to list available versions
* Use `uv pip show <package-name>` if the package is already installed locally

**Verify the version before proceeding**: The extracted version must match the semantic version
pattern `MAJOR.MINOR.PATCH` (e.g., `2025.11.3`, `1.5.2`). Reject values like `"latest"`, empty
strings, or malformed versions.

Then continue with Step 2.

## Step 2: Add with Upper Bound

Manually add the dependency to the appropriate section in `pyproject.toml` with version
constraints matching the project's pattern: `>=MAJOR.MINOR.PATCH,<MAJOR.NEXT_MINOR.0`
(bound to next minor version).

**Where to add the dependency** (based on the group from the table below):

| Group | pyproject.toml Location |
|-------|-------------------------|
| main | `[project]` section under `dependencies = [...]` |
| test | `[dependency-groups]` section under `test = [...]` |
| dev | `[dependency-groups]` section under `dev = [...]` |
| knowledge | `[dependency-groups]` section under `knowledge = [...]` |

Example for a package with version `2025.11.3` added to the knowledge group:

```toml
# In [dependency-groups] section
knowledge = [
    { include-group = "test" },
    ...existing dependencies...
    "regex>=2025.11.3,<2025.12.0",  # <-- Add here
]
```

Example for a package with version `1.5.2` added to main dependencies:

```toml
# In [project] section
dependencies = [
    ...existing dependencies...
    "somepackage>=1.5.2,<1.6.0",  # <-- Add here
]
```

## Step 3: Sync and Verify

```bash
uv sync --group <group-name>
```

For example, to sync the knowledge group: `uv sync --group knowledge`

## Dependency Groups

| Group | Purpose | pyproject.toml Location |
|-------|---------|------------------------|
| main | Runtime dependencies | `[project]` section, `dependencies = [...]` |
| test | pytest, test utilities | `[dependency-groups]` section, `test = [...]` |
| dev | linters, formatters, type checkers | `[dependency-groups]` section, `dev = [...]` |
| knowledge | ML/NLP for scripts/knowledge/ | `[dependency-groups]` section, `knowledge = [...]` |

Always use the 3-step workflow above to add dependencies.

**Rules**:

* **Always fetch latest from PyPI**: Use the Python urllib command to get the current version, never guess
* **Always include upper bound**: Prevent unexpected major version upgrades
* **Choose the correct group**: Match the dependency to its purpose (see table above), then
  sync with that group (e.g., `uv sync --group knowledge`)
* **Always use 3-step workflow**: PyPI fetch → manual pyproject.toml edit → `uv sync --group <group-name>`
* **Check compatibility**: Ensure the new dependency doesn't conflict with existing ones
