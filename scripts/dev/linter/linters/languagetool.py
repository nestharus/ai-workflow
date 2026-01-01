"""LanguageTool grammar and spelling linter for Markdown files."""

from pathlib import Path
from typing import Any, ClassVar, Protocol, cast

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    LintError,
    load_yaml_config,
)

LINT_LANGUAGETOOL_CONFIG = REPO_ROOT / ".lint.languagetool.yaml"
LANGUAGETOOL_CONFIG_MISSING = (
    ".lint.languagetool.yaml not found in repository root. "
    "This config file is required for LanguageTool settings."
)


class LanguageToolCheckError(Exception):
    """Raised when LanguageTool fails to check a file."""


class Match(Protocol):
    """Protocol for LanguageTool match objects."""

    rule_issue_type: str
    matched_text: str
    category: str
    rule_id: str
    message: str
    context: str
    offset: int
    replacements: list[str]


class LanguageToolAPI(Protocol):
    """Protocol for LanguageTool API instances."""

    def check(self, text: str) -> list[Match]:
        """Check text for grammar and spelling issues."""
        ...


class LanguageToolLinter(BaseLinter):
    """Run LanguageTool grammar/spelling checker on Markdown files."""

    name = "languagetool"
    config_file = ".lint.languagetool.yaml"
    extensions: ClassVar[list[str]] = [".md"]
    supports_file_filtering = True

    def __init__(self) -> None:
        """Initialize linter with lazy LanguageTool instance."""
        self._tool: LanguageToolAPI | None = None
        self._config: dict[str, Any] | None = None

    def close(self) -> None:
        """Close the LanguageTool instance to properly terminate the Java server.

        This must be called before Python exits to avoid errors during garbage
        collection. The psutil module used by language_tool_python for cleanup
        may already be partially unloaded during __del__, causing KeyError.
        """
        if self._tool is not None:
            try:
                # The LanguageTool instance has a close() method to terminate the server
                close_method = getattr(self._tool, "close", None)
                if callable(close_method):
                    close_method()
            except Exception as e:
                # Ignore cleanup errors during shutdown, but don't mask them completely
                # psutil may be partially unloaded, causing benign KeyError exceptions
                import sys

                print(f"Warning: LanguageTool cleanup failed: {e}", file=sys.stderr)
            self._tool = None

    @property
    def config(self) -> dict[str, Any]:
        """Load config lazily."""
        if self._config is None:
            if not LINT_LANGUAGETOOL_CONFIG.exists():
                raise RuntimeError(LANGUAGETOOL_CONFIG_MISSING)
            self._config = load_yaml_config(LINT_LANGUAGETOOL_CONFIG)
        return self._config

    def _get_tool(self) -> LanguageToolAPI:
        """Get or create LanguageTool instance (lazy initialization).

        Server preference order:
        1. Remote server (if remote_server is configured)
        2. Local server (default, requires Java 17+)
        3. Public API (only if use_public_api is explicitly True)

        The public API is an explicit opt-in because it sends Markdown content
        to an external service and makes lint runs dependent on internet availability.
        """
        if self._tool is not None:
            return self._tool

        try:
            import language_tool_python
        except ImportError as e:
            raise RuntimeError(
                "language-tool-python is not installed. Install with: uv add language-tool-python"
            ) from e

        language = self.config.get("language", "en-US")
        use_public_api = self.config.get("use_public_api", False)
        remote_server = self.config.get("remote_server")
        lt_config = self.config.get("config") or {}

        tool: LanguageToolAPI
        try:
            if remote_server:
                # Use custom remote server (highest priority)
                tool = cast(
                    "LanguageToolAPI",
                    language_tool_python.LanguageTool(
                        language,
                        remote_server=remote_server,
                        config=lt_config,
                    ),
                )
            elif use_public_api is True:
                # Use public API only if explicitly enabled
                # Note: use_public_api must be exactly True, not just truthy
                tool = cast(
                    "LanguageToolAPI",
                    language_tool_python.LanguageToolPublicAPI(language),
                )
            else:
                # Default: Use local server (requires Java)
                tool = cast(
                    "LanguageToolAPI",
                    language_tool_python.LanguageTool(
                        language,
                        config=lt_config,
                    ),
                )
        except Exception as e:
            if "Java" in str(e) or "java" in str(e):
                raise RuntimeError(
                    "LanguageTool local server requires Java 17+. "
                    "Options:\n"
                    "  1. Install Java 17+ (e.g., brew install openjdk@17)\n"
                    "  2. Set remote_server in .lint.languagetool.yaml for self-hosted server\n"
                    "  3. Set use_public_api: true to use public API (sends content externally)"
                ) from e
            raise RuntimeError(f"Failed to initialize LanguageTool: {e}") from e

        self._tool = tool
        return self._tool

    def _filter_dictionary_words(self, matches: list[Match]) -> list[Match]:
        """Filter out spelling matches for words in the project dictionary.

        Comparison is case-insensitive to handle capitalized technical terms
        (e.g., "Pymarkdown" at sentence start matches dictionary entry "pymarkdown").
        """
        # Normalize dictionary entries to lowercase for case-insensitive comparison
        # Handle various config value types:
        # - None (explicit YAML null): use empty list
        # - str: wrap in list (avoid iterating characters)
        # - list: use as-is
        # - other types: ignore (use empty list)
        raw_dict = self.config.get("dictionary")
        if raw_dict is None:
            items: list[str] = []
        elif isinstance(raw_dict, str):
            items = [raw_dict]
        elif isinstance(raw_dict, list):
            items = raw_dict
        else:
            items = []
        dictionary = {word.lower() for word in items if isinstance(word, str)}
        return [
            m
            for m in matches
            if not (m.rule_issue_type == "misspelling" and m.matched_text.lower() in dictionary)
        ]

    def _filter_disabled_rules(self, matches: list[Match]) -> list[Match]:
        """Filter out matches for disabled rules and categories."""
        # Normalize config values to sets, handling various types:
        # - None (explicit YAML null): use empty set
        # - str: wrap in set (avoid iterating characters)
        # - list: convert to set
        # - other types: ignore (use empty set)
        raw_categories = self.config.get("disabled_categories")
        if raw_categories is None:
            disabled_categories: set[str] = set()
        elif isinstance(raw_categories, str):
            disabled_categories = {raw_categories}
        elif isinstance(raw_categories, list):
            disabled_categories = {c for c in raw_categories if isinstance(c, str)}
        else:
            disabled_categories = set()

        raw_rules = self.config.get("disabled_rules")
        if raw_rules is None:
            disabled_rules: set[str] = set()
        elif isinstance(raw_rules, str):
            disabled_rules = {raw_rules}
        elif isinstance(raw_rules, list):
            disabled_rules = {r for r in raw_rules if isinstance(r, str)}
        else:
            disabled_rules = set()

        return [
            m
            for m in matches
            if m.category not in disabled_categories and m.rule_id not in disabled_rules
        ]

    def _check_file(self, file_path: Path) -> tuple[list[Match], str]:
        """Check a single file and return list of matches with content.

        Args:
            file_path: Path to the file to check.

        Returns:
            Tuple of (matches, content) where matches is a list of LanguageTool
            match objects and content is the file content (for use by _format_match).

        Raises:
            LanguageToolCheckError: If the file cannot be read or LanguageTool API fails.
        """
        tool = self._get_tool()

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            raise LanguageToolCheckError(f"Could not read {file_path}: {e}") from e

        try:
            matches = tool.check(content)
        except Exception as e:
            raise LanguageToolCheckError(f"LanguageTool check failed for {file_path}: {e}") from e

        # Apply filtering
        matches = self._filter_disabled_rules(matches)
        matches = self._filter_dictionary_words(matches)

        return matches, content

    def _match_to_lint_error(self, match: Match, file_path: Path, content: str) -> LintError:
        """Convert a LanguageTool match to a LintError.

        Args:
            match: LanguageTool match object.
            file_path: Path to the file containing the match.
            content: File content (used to calculate line/column).

        Returns:
            LintError with structured information.
        """
        # Calculate line number and column from offset
        line_num = content[: match.offset].count("\n") + 1
        # Column is offset from start of current line
        last_newline = content.rfind("\n", 0, match.offset)
        column = match.offset - last_newline if last_newline >= 0 else match.offset + 1

        try:
            rel_path = file_path.relative_to(REPO_ROOT)
        except ValueError:
            rel_path = file_path

        # Build context string with match info
        context_parts = [f"Context: ...{match.context}..."]
        context_parts.append(f"Matched: '{match.matched_text}'")
        if match.replacements:
            suggestions = ", ".join(match.replacements[:3])
            if len(match.replacements) > 3:
                suggestions += ", ..."
            context_parts.append(f"Suggestions: {suggestions}")

        return LintError(
            file=str(rel_path),
            line=line_num,
            column=column,
            code=match.rule_id,
            message=f"{match.message} ({match.category})",
            context="\n".join(context_parts),
            fix_available=bool(match.replacements),
            fix_message=match.replacements[0] if match.replacements else None,
        )

    def _parse_include_paths(self) -> tuple[list[str], list[str]]:
        """Parse include_paths into include and exclude patterns.

        Returns:
            Tuple of (include_patterns, exclude_patterns) where exclude patterns
            have the leading '!' stripped.
        """
        include_paths = self.config.get("include_paths") or []
        if isinstance(include_paths, str):
            include_paths = [include_paths]
        include_patterns: list[str] = []
        exclude_patterns: list[str] = []

        for pattern in include_paths:
            if not isinstance(pattern, str):
                continue
            if pattern.startswith("!"):
                # Exclusion pattern - strip the '!' prefix
                exclude_patterns.append(pattern[1:])
            else:
                include_patterns.append(pattern)

        return include_patterns, exclude_patterns

    def _matches_any_pattern(self, path: Path, patterns: list[str]) -> bool:
        """Check if a path matches any of the given glob patterns.

        Uses Path.full_match() for correct ** glob semantics (e.g., 'docs/**'
        matches all files under docs/, not just immediate children).

        Args:
            path: Absolute path to check.
            patterns: List of glob patterns to match against.

        Returns:
            True if the path matches any pattern.
        """
        try:
            rel_path = path.relative_to(REPO_ROOT)
        except ValueError:
            return False

        return any(rel_path.full_match(pattern) for pattern in patterns)

    def _get_target_files(self, files: list[str] | None) -> list[Path]:
        """Get list of Markdown files to check.

        Args:
            files: Optional list of specific files to check.

        Returns:
            List of Path objects for Markdown files to check.
        """
        include_patterns, exclude_patterns = self._parse_include_paths()

        if files is not None:
            # Filter provided files to .md only and apply exclusions
            md_files_list = []
            for f in files:
                if not f.endswith(".md"):
                    continue
                file_path = Path(f)
                abs_path = file_path if file_path.is_absolute() else REPO_ROOT / f
                # Check against exclude patterns
                if not self._matches_any_pattern(abs_path, exclude_patterns):
                    md_files_list.append(abs_path)
            return md_files_list

        # No files specified - use include patterns from config
        # Use a set to deduplicate files from overlapping patterns
        md_files: set[Path] = set()

        for pattern in include_patterns:
            if any(ch in pattern for ch in ("*", "?", "[")):
                # Glob pattern
                for path in REPO_ROOT.glob(pattern):
                    if (
                        path.is_file()
                        and path.suffix == ".md"
                        and not self._matches_any_pattern(path, exclude_patterns)
                    ):
                        md_files.add(path)
            else:
                # Direct file path
                path = REPO_ROOT / pattern
                if (
                    path.is_file()
                    and path.suffix == ".md"
                    and not self._matches_any_pattern(path, exclude_patterns)
                ):
                    md_files.add(path)

        return list(md_files)

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run LanguageTool on Markdown files.

        Args:
            files: Optional list of files to check. If None, checks configured targets.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        try:
            md_files = self._get_target_files(files)
        except Exception as e:
            msg = f"Failed to get target files: {e}"
            return LinterResult(success=False, message=msg)

        if not md_files:
            print("No Markdown files to check with LanguageTool")
            return LinterResult(success=True)

        # Check each file and collect errors
        all_errors: list[LintError] = []
        file_errors: list[str] = []  # Per-file I/O or API errors

        try:
            for file_path in md_files:
                try:
                    matches, content = self._check_file(file_path)
                except RuntimeError as e:
                    # Initialization or critical error (e.g., missing Java, import error)
                    return LinterResult(success=False, message=str(e))
                except LanguageToolCheckError as e:
                    # API failure or I/O error - log and continue with remaining files
                    file_errors.append(str(e))
                    continue

                for match in matches:
                    all_errors.append(self._match_to_lint_error(match, file_path, content))

            if all_errors or file_errors:
                issue_count = len(all_errors)
                error_count = len(file_errors)

                # Build summary message
                parts = []
                if issue_count > 0:
                    parts.append(f"{issue_count} issue(s)")
                if error_count > 0:
                    parts.append(f"{error_count} file error(s)")

                return LinterResult(
                    success=False,
                    message=f"LanguageTool found {', '.join(parts)}",
                    errors=all_errors,
                )

            return LinterResult(success=True)
        finally:
            # Always close the LanguageTool instance to properly terminate the Java server
            # This prevents errors during Python garbage collection when psutil is unloaded
            self.close()
