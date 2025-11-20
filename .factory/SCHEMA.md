# Custom Droid Settings Schema

This schema documents `.factory/settings.json` keys and expected values for Droid tooling.

| Key | Type | Units | Default | Description |
| --- | --- | --- | --- | --- |
| `env.BASH_DEFAULT_TIMEOUT_MS` | integer (ms) | milliseconds | `600000` | Default timeout for bash operations invoked by Droid. |
| `env.BASH_MAX_TIMEOUT_MS` | integer (ms) | milliseconds | `1200000` | Hard cap for bash operations; higher values are rejected. |

Notes:
- Values should be positive integers encoded as strings in the JSON file.
- Update `.factory/settings.json` to change timeouts; the orchestrator rejects values above `1200000` ms (20 minutes) to align with CI limits.
