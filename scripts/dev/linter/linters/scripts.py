"""Script naming convention linter."""

import sys

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    load_yaml_config,
)

LINT_SCRIPTS_CONFIG = REPO_ROOT / ".lint.scripts.yaml"


class ScriptsLinter(BaseLinter):
    """Validate pyproject.toml script entry point naming conventions."""

    name = "scripts"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run the scripts linter.

        Reads rules from .lint.scripts.yaml configuration file. Each rule maps
        a module prefix to the required script name prefix.

        Args:
            files: Optional list of files to filter. Only runs if pyproject.toml
                   is in the files list.

        Returns:
            LinterResult indicating success/failure.
        """
        # If files are specified, only run if pyproject.toml is in the list
        if files is not None:
            if "pyproject.toml" not in files and "scripts/pyproject.toml" not in files:
                print("pyproject.toml not in changed files, skipping scripts linter.")
                return LinterResult(success=True)

        # Load configuration
        config = load_yaml_config(LINT_SCRIPTS_CONFIG)
        if not isinstance(config, dict):
            config = {}
        prefix_rules: dict[str, str] = config.get("prefix_rules", {})

        if not prefix_rules:
            print("No prefix_rules defined in .lint.scripts.yaml", file=sys.stderr)
            return LinterResult(success=False)

        pyproject_path = REPO_ROOT / "pyproject.toml"
        if not pyproject_path.exists():
            print("pyproject.toml not found", file=sys.stderr)
            return LinterResult(success=False)

        # Parse pyproject.toml - use simple parsing for [project.scripts]
        content = pyproject_path.read_text(encoding="utf-8")
        violations: list[str] = []

        # Find [project.scripts] section
        in_scripts_section = False
        for line in content.splitlines():
            line = line.strip()

            # Track section transitions
            if line.startswith("["):
                in_scripts_section = line == "[project.scripts]"
                continue

            if not in_scripts_section:
                continue

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Parse script entry: "name" = "module:func" or name = "module:func"
            if "=" not in line:
                continue

            parts = line.split("=", 1)
            if len(parts) != 2:
                continue

            script_name = parts[0].strip().strip('"').strip("'")
            module_path = parts[1].strip().strip('"').strip("'")

            # Extract module path (before the colon)
            if ":" in module_path:
                module_path = module_path.split(":")[0]

            # Check naming conventions against configured rules
            for module_prefix, required_name_prefix in prefix_rules.items():
                if module_path.startswith(module_prefix):
                    if not script_name.startswith(required_name_prefix):
                        violations.append(
                            f"  '{script_name}' -> {module_path} "
                            f"(should be prefixed with '{required_name_prefix}')"
                        )
                    break

        if violations:
            print("Script naming convention violations:", file=sys.stderr)
            for v in violations:
                print(v, file=sys.stderr)
            return LinterResult(success=False)

        print("All script entry points follow naming conventions.")
        return LinterResult(success=True)
