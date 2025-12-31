"""Script naming convention linter."""

import sys

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    LintError,
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
            LinterResult with structured errors for naming violations.
        """
        # If files are specified, only run if pyproject.toml is in the list
        if (
            files is not None
            and "pyproject.toml" not in files
            and "scripts/pyproject.toml" not in files
        ):
            print("pyproject.toml not in changed files, skipping scripts linter.")
            return LinterResult(success=True)

        # Load configuration
        config = load_yaml_config(LINT_SCRIPTS_CONFIG)
        if not isinstance(config, dict):
            config = {}
        prefix_rules: dict[str, str] = config.get("prefix_rules", {})

        if not prefix_rules:
            print("No prefix_rules defined in .lint.scripts.yaml", file=sys.stderr)
            return LinterResult(success=False, message="No prefix_rules in config")

        pyproject_path = REPO_ROOT / "pyproject.toml"
        if not pyproject_path.exists():
            print("pyproject.toml not found", file=sys.stderr)
            return LinterResult(success=False, message="pyproject.toml not found")

        # Parse pyproject.toml - use simple parsing for [project.scripts]
        content = pyproject_path.read_text(encoding="utf-8")
        errors: list[LintError] = []

        # Find [project.scripts] section
        in_scripts_section = False
        line_number = 0
        for line in content.splitlines():
            line_number += 1
            stripped = line.strip()

            # Track section transitions
            if stripped.startswith("["):
                in_scripts_section = stripped == "[project.scripts]"
                continue

            if not in_scripts_section:
                continue

            # Skip empty lines and comments
            if not stripped or stripped.startswith("#"):
                continue

            # Parse script entry: "name" = "module:func" or name = "module:func"
            if "=" not in stripped:
                continue

            parts = stripped.split("=", 1)
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
                        errors.append(
                            LintError(
                                file=str(pyproject_path),
                                line=line_number,
                                column=1,
                                code="SCRIPT001",
                                message=f"Script '{script_name}' uses module '{module_path}' "
                                f"but should be prefixed with '{required_name_prefix}'",
                                context=line,
                                fix_available=False,
                                fix_message=f"Rename script to start with '{required_name_prefix}'",
                            )
                        )
                    break

        if errors:
            return LinterResult(success=False, errors=errors)

        print("All script entry points follow naming conventions.")
        return LinterResult(success=True)
