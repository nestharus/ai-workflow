"""Analyze test function calls to classify tests as unit, component, or integration.

Examines tests to determine their true classification based on:
- What functions they call (directly and transitively)
- Whether calls are mocked/faked
- Whether tests use real I/O (integration modules like anyio, httpx, redis, etc.)

Classification Rules:
- INTEGRATION: Has unmocked calls to integration modules (anyio, httpx, redis, etc.)
- UNIT: 0-1 project functions in the unmocked call graph
- COMPONENT: >1 project functions in the unmocked call graph

Mock Detection:
- @patch decorators and patch() context managers
- Fixture arguments (fake_redis, mock_httpx, etc.)
- Fake libraries (fakeredis, responses, pyfakefs, etc.)

Usage:
    # Report classification for a directory
    uv run python -m scripts.dev.test_call_analyzer scripts/tests/ --report

    # Preview reclassification (dry run)
    uv run python -m scripts.dev.test_call_analyzer --dry-run

    # Execute reclassification
    uv run python -m scripts.dev.test_call_analyzer --execute
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

# Project root modules (not test code)
PROJECT_ROOTS = frozenset({"app", "scripts"})

# Standard library modules
STDLIB = frozenset(
    {
        "__future__",
        "abc",
        "argparse",
        "ast",
        "asyncio",
        "base64",
        "builtins",
        "calendar",
        "collections",
        "contextlib",
        "copy",
        "csv",
        "dataclasses",
        "datetime",
        "decimal",
        "difflib",
        "email",
        "enum",
        "errno",
        "functools",
        "glob",
        "gzip",
        "hashlib",
        "hmac",
        "html",
        "http",
        "importlib",
        "inspect",
        "io",
        "itertools",
        "json",
        "logging",
        "math",
        "mimetypes",
        "multiprocessing",
        "numbers",
        "operator",
        "os",
        "pathlib",
        "pickle",
        "platform",
        "pprint",
        "queue",
        "random",
        "re",
        "secrets",
        "shlex",
        "shutil",
        "signal",
        "socket",
        "sqlite3",
        "ssl",
        "statistics",
        "string",
        "struct",
        "subprocess",
        "sys",
        "tempfile",
        "textwrap",
        "threading",
        "time",
        "traceback",
        "types",
        "typing",
        "unicodedata",
        "unittest",
        "urllib",
        "uuid",
        "warnings",
        "weakref",
        "xml",
        "zipfile",
        "zlib",
    }
)

# Test/mock libraries
TEST_LIBS = frozenset(
    {
        "pytest",
        "pyfakefs",
        "mock",
        "unittest",
        "fakeredis",
        "responses",
        "httpretty",
        "freezegun",
        "factory",
        "faker",
        "hypothesis",
    }
)

# Integration patterns - modules that indicate I/O, network, or external service calls
# Tests calling these (unmocked) are integration tests
INTEGRATION_MODULES = frozenset(
    {
        # Async I/O
        "anyio",
        "trio",
        "curio",
        # HTTP/REST clients
        "httpx",
        "requests",
        "aiohttp",
        "urllib3",
        # Database clients
        "redis",
        "aioredis",
        "pymongo",
        "motor",
        "psycopg",
        "psycopg2",
        "asyncpg",
        "sqlalchemy",
        "databases",
        "tortoise",
        # Message queues
        "celery",
        "kombu",
        "pika",
        "aio_pika",
        # Cloud services
        "boto3",
        "botocore",
        "google.cloud",
        "azure",
        # Other I/O
        "paramiko",
        "fabric",
        "grpc",
        "grpcio",
    }
)

# Mock/patch related names for detecting mocked calls
MOCK_NAMES = frozenset(
    {
        "patch",
        "Mock",
        "MagicMock",
        "AsyncMock",
        "PropertyMock",
        "mock_open",
        "create_autospec",
    }
)

# Fake libraries that substitute real implementations
FAKE_LIBS = frozenset(
    {
        "fakeredis",
        "responses",
        "httpretty",
        "moto",
        "pyfakefs",
        "aioresponses",
        "respx",
    }
)


@dataclass
class FunctionDef:
    """A function definition with its calls."""

    module: str  # e.g., "scripts.pr.client"
    name: str  # e.g., "get_pr"
    calls: set[str] = field(default_factory=set)  # Set of "module.func" it calls

    @property
    def full_name(self) -> str:
        """Return fully qualified function name."""
        return f"{self.module}.{self.name}"


@dataclass
class CallGraph:
    """Call graph of all project functions."""

    functions: dict[str, FunctionDef] = field(default_factory=dict)  # full_name -> FunctionDef

    def get_transitive_calls(self, func_name: str, visited: set[str] | None = None) -> set[str]:
        """Get all functions transitively called by a function.

        Args:
            func_name: The function to trace (module.name format).
            visited: Set of already visited functions (for cycle detection).

        Returns:
            Set of all function names in the call tree.
        """
        if visited is None:
            visited = set()

        if func_name in visited:
            return set()

        visited.add(func_name)
        result = {func_name}

        if func_name in self.functions:
            for called in self.functions[func_name].calls:
                result.update(self.get_transitive_calls(called, visited))

        return result


def _is_project_module(module: str) -> bool:
    """Check if a module is project code (not tests, not stdlib).

    Args:
        module: Module path like "scripts.pr.client".

    Returns:
        True if this is project code (app/ or scripts/ but not tests).
    """
    if not module:
        return False

    parts = module.split(".")
    root = parts[0]

    # Check if stdlib or test library
    if root in STDLIB or root in TEST_LIBS:
        return False

    # Check if project code
    if root not in PROJECT_ROOTS:
        return False

    # Check if test code (exclude)
    return "tests" not in parts


def _is_integration_module(module: str) -> bool:
    """Check if a module is an integration module (I/O, network, external services).

    Args:
        module: Module path like "httpx" or "redis.asyncio".

    Returns:
        True if this is an integration module.
    """
    if not module:
        return False

    parts = module.split(".")
    root = parts[0]

    return root in INTEGRATION_MODULES


def _parse_imports(tree: ast.AST) -> dict[str, tuple[str, str]]:
    """Extract all imports from an AST.

    Args:
        tree: The AST to analyze.

    Returns:
        Dict mapping imported name to (module, original_name).
    """
    imports: dict[str, tuple[str, str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name
                imports[name] = (alias.name, alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                name = alias.asname or alias.name
                imports[name] = (node.module, alias.name)

    return imports


def _resolve_call_target(node: ast.Call, imports: dict[str, tuple[str, str]]) -> str | None:
    """Resolve a function call to module.function format.

    Args:
        node: The Call AST node.
        imports: Import information for the file.

    Returns:
        "module.function" string or None if unresolved.
    """
    func = node.func

    # Simple name: foo()
    if isinstance(func, ast.Name):
        name = func.id
        if name in imports:
            module, orig_name = imports[name]
            if _is_project_module(module):
                return f"{module}.{orig_name}"
        return None

    # Attribute: foo.bar() or module.func()
    if isinstance(func, ast.Attribute):
        attr_name = func.attr

        if isinstance(func.value, ast.Name):
            base_name = func.value.id
            if base_name in imports:
                module, _ = imports[base_name]
                if _is_project_module(module):
                    return f"{module}.{attr_name}"
        return None

    return None


def _resolve_any_call_target(
    node: ast.Call, imports: dict[str, tuple[str, str]]
) -> tuple[str | None, str]:
    """Resolve any function call to module.function format.

    Like _resolve_call_target but returns all calls, not just project calls.

    Args:
        node: The Call AST node.
        imports: Import information for the file.

    Returns:
        Tuple of (full_name, call_type) where call_type is 'project', 'integration', or 'other'.
    """
    func = node.func

    # Simple name: foo()
    if isinstance(func, ast.Name):
        name = func.id
        if name in imports:
            module, orig_name = imports[name]
            full_name = f"{module}.{orig_name}"
            if _is_project_module(module):
                return full_name, "project"
            if _is_integration_module(module):
                return full_name, "integration"
            return full_name, "other"
        return None, "other"

    # Attribute: foo.bar() or module.func()
    if isinstance(func, ast.Attribute):
        attr_name = func.attr

        if isinstance(func.value, ast.Name):
            base_name = func.value.id
            if base_name in imports:
                module, _ = imports[base_name]
                full_name = f"{module}.{attr_name}"
                if _is_project_module(module):
                    return full_name, "project"
                if _is_integration_module(module):
                    return full_name, "integration"
                return full_name, "other"
        return None, "other"

    return None, "other"


def _extract_patch_targets(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    """Extract all patch/mock targets from a test function.

    Looks at @patch decorators and patch() context managers.

    Args:
        func_node: The function AST node.

    Returns:
        Set of module paths being patched.
    """
    targets: set[str] = set()

    # Check decorators for @patch("module.path")
    for decorator in func_node.decorator_list:
        if isinstance(decorator, ast.Call):
            # Check if this is a patch call
            func = decorator.func
            is_patch = False
            if (isinstance(func, ast.Name) and func.id in MOCK_NAMES) or (
                isinstance(func, ast.Attribute) and func.attr in MOCK_NAMES
            ):
                is_patch = True

            if is_patch and decorator.args:
                first_arg = decorator.args[0]
                if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                    targets.add(first_arg.value)

    # Check function body for patch() context managers
    for node in ast.walk(func_node):
        if isinstance(node, ast.With):
            for item in node.items:
                ctx = item.context_expr
                if isinstance(ctx, ast.Call):
                    func = ctx.func
                    is_patch = False
                    if (isinstance(func, ast.Name) and func.id in MOCK_NAMES) or (
                        isinstance(func, ast.Attribute) and func.attr in MOCK_NAMES
                    ):
                        is_patch = True

                    if is_patch and ctx.args:
                        first_arg = ctx.args[0]
                        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                            targets.add(first_arg.value)

    return targets


def _extract_fake_fixture_modules(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    """Extract modules faked by fixture arguments.

    Args:
        func_node: The function AST node.

    Returns:
        Set of modules likely faked by fixtures (e.g., 'redis' from 'fake_redis' fixture).
    """
    faked: set[str] = set()

    for arg in func_node.args.args:
        arg_name = arg.arg.lower()
        # Check for patterns like fake_redis, mock_httpx, etc.
        for fake_prefix in ("fake_", "mock_", "mocked_", "stub_"):
            if arg_name.startswith(fake_prefix):
                # Extract the module name after the prefix
                module_hint = arg_name[len(fake_prefix) :]
                # Map common hints to actual modules
                module_map = {
                    "redis": "redis",
                    "fs": "os",
                    "filesystem": "os",
                    "http": "httpx",
                    "httpx": "httpx",
                    "requests": "requests",
                    "aiohttp": "aiohttp",
                    "subprocess": "subprocess",
                }
                if module_hint in module_map:
                    faked.add(module_map[module_hint])

        # Check for pyfakefs fixture (commonly named 'fs' or 'fake_filesystem')
        if arg_name in ("fs", "fake_filesystem", "tmp_path"):
            faked.add("os")
            faked.add("pathlib")

    return faked


def _uses_fake_library(imports: dict[str, tuple[str, str]]) -> set[str]:
    """Check if the test uses a fake library that mocks external services.

    Args:
        imports: Import information.

    Returns:
        Set of modules that are faked by imported fake libraries.
    """
    faked: set[str] = set()

    # Map fake libraries to the modules they mock
    fake_lib_mocks = {
        "fakeredis": {"redis", "aioredis"},
        "responses": {"requests"},
        "httpretty": {"httpx", "requests", "aiohttp", "urllib3"},
        "moto": {"boto3", "botocore"},
        "pyfakefs": {"os", "pathlib", "io"},
        "aioresponses": {"aiohttp"},
        "respx": {"httpx"},
    }

    for imported_name, (module, _) in imports.items():
        root = module.split(".")[0]
        if root in fake_lib_mocks:
            faked.update(fake_lib_mocks[root])
        # Also check import name itself
        if imported_name in fake_lib_mocks:
            faked.update(fake_lib_mocks[imported_name])

    return faked


def _extract_integration_from_annotations(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, tuple[str, str]],
) -> set[str]:
    """Extract integration module usage from function parameter type annotations.

    Detects patterns like:
    - def test_foo(http_client: httpx.Client) -> httpx.Client is an integration type
    - def test_bar(redis: redis.Redis) -> redis.Redis is an integration type

    Args:
        func_node: The function AST node.
        imports: Import information for the file.

    Returns:
        Set of integration module references found in annotations.
    """
    integration_types: set[str] = set()

    def _check_annotation(annotation: ast.expr | None) -> None:
        if annotation is None:
            return

        # Handle Attribute: httpx.Client
        if isinstance(annotation, ast.Attribute):
            if isinstance(annotation.value, ast.Name):
                module_name = annotation.value.id
                if module_name in imports:
                    full_module, _ = imports[module_name]
                    if _is_integration_module(full_module):
                        integration_types.add(f"{full_module}.{annotation.attr}")
                elif _is_integration_module(module_name):
                    integration_types.add(f"{module_name}.{annotation.attr}")

        # Handle Name: could be an imported type
        elif isinstance(annotation, ast.Name):
            name = annotation.id
            if name in imports:
                module, orig_name = imports[name]
                if _is_integration_module(module):
                    integration_types.add(f"{module}.{orig_name}")

        # Handle Subscript: Iterator[httpx.Client], list[httpx.Response]
        elif isinstance(annotation, ast.Subscript):
            _check_annotation(annotation.value)
            if isinstance(annotation.slice, ast.Tuple):
                for elt in annotation.slice.elts:
                    _check_annotation(elt)
            else:
                _check_annotation(annotation.slice)

        # Handle BinOp: X | Y (union types)
        elif isinstance(annotation, ast.BinOp):
            _check_annotation(annotation.left)
            _check_annotation(annotation.right)

    # Check all function arguments
    for arg in func_node.args.args:
        _check_annotation(arg.annotation)

    # Check return annotation
    _check_annotation(func_node.returns)

    return integration_types


def _extract_function_calls(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, tuple[str, str]],
) -> set[str]:
    """Extract all project function calls from a function.

    Args:
        func_node: The function AST node.
        imports: Import information for the file.

    Returns:
        Set of "module.function" strings for project calls.
    """
    calls: set[str] = set()

    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            target = _resolve_call_target(node, imports)
            if target:
                calls.add(target)

    return calls


def _analyze_source_file(file_path: Path) -> list[FunctionDef]:
    """Analyze a source file to extract function definitions and their calls.

    Args:
        file_path: Path to the Python file.

    Returns:
        List of FunctionDef for each function in the file.
    """
    functions: list[FunctionDef] = []

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return functions

    # Determine module path from file path
    # Assumes file is under project root
    parts = file_path.parts
    try:
        # Find 'scripts' or 'app' in path
        for i, part in enumerate(parts):
            if part in ("scripts", "app"):
                rel_parts = parts[i:]
                break
        else:
            return functions

        # Convert to module path
        if rel_parts[-1].endswith(".py"):
            rel_parts = (*rel_parts[:-1], rel_parts[-1][:-3])
        if rel_parts[-1] == "__init__":
            rel_parts = rel_parts[:-1]
        module_path = ".".join(rel_parts)
    except (IndexError, ValueError):
        return functions

    imports = _parse_imports(tree)

    # Find all function definitions
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            # Skip test functions and private helpers in test files
            if node.name.startswith("test_"):
                continue

            calls = _extract_function_calls(node, imports)
            func_def = FunctionDef(
                module=module_path,
                name=node.name,
                calls=calls,
            )
            functions.append(func_def)

    return functions


def build_call_graph(project_root: Path) -> CallGraph:
    """Build a call graph of all project functions.

    Args:
        project_root: Root directory of the project.

    Returns:
        CallGraph with all functions and their calls.
    """
    graph = CallGraph()

    # Find all Python files in app/ and scripts/ (excluding tests)
    source_files: list[Path] = []
    for root_dir in ["app", "scripts"]:
        root_path = project_root / root_dir
        if root_path.exists():
            for py_file in root_path.rglob("*.py"):
                # Skip test files
                if "tests" in py_file.parts:
                    continue
                source_files.append(py_file)

    # Analyze in parallel
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(_analyze_source_file, source_files)

    for func_list in results:
        for func_def in func_list:
            graph.functions[func_def.full_name] = func_def

    return graph


class TestType:
    """Classification of test type."""

    UNIT = "unit"
    COMPONENT = "component"
    INTEGRATION = "integration"


@dataclass
class TestAnalysis:
    """Analysis of a single test function."""

    name: str
    file_path: Path
    direct_calls: set[str] = field(default_factory=set)  # Direct project calls
    transitive_calls: set[str] = field(
        default_factory=set
    )  # All transitive project calls (unmocked)
    integration_calls: set[str] = field(
        default_factory=set
    )  # Direct integration module calls (unmocked)
    mocked_targets: set[str] = field(default_factory=set)  # Patched/mocked module paths
    faked_modules: set[str] = field(default_factory=set)  # Modules faked by fixtures/libraries
    test_type: str = TestType.UNIT
    reason: str = ""

    @property
    def is_unit_test(self) -> bool:
        """Check if test is classified as unit test."""
        return self.test_type == TestType.UNIT

    @property
    def is_component_test(self) -> bool:
        """Check if test is classified as component test."""
        return self.test_type == TestType.COMPONENT

    @property
    def is_integration_test(self) -> bool:
        """Check if test is classified as integration test."""
        return self.test_type == TestType.INTEGRATION


@dataclass
class FileAnalysis:
    """Analysis of a test file."""

    path: Path
    tests: list[TestAnalysis] = field(default_factory=list)
    unit_tests: list[str] = field(default_factory=list)
    component_tests: list[str] = field(default_factory=list)
    integration_tests: list[str] = field(default_factory=list)


def _is_call_mocked(call_target: str, mocked_targets: set[str], faked_modules: set[str]) -> bool:
    """Check if a call target is mocked or faked.

    Args:
        call_target: The call target like "scripts.pr.client.get_pr".
        mocked_targets: Set of patch targets like "scripts.pr.client.get_pr".
        faked_modules: Set of module roots that are faked like "redis".

    Returns:
        True if this call is mocked/faked.
    """
    # Direct match
    if call_target in mocked_targets:
        return True

    # Check if any part of the path is mocked
    # e.g., if "scripts.pr.client" is mocked, then "scripts.pr.client.get_pr" is mocked
    for mocked in mocked_targets:
        if call_target.startswith(mocked + ".") or mocked.startswith(call_target + "."):
            return True
        # Also check if the mocked target matches the function being called
        if mocked == call_target:
            return True

    # Check if the root module is faked
    root_module = call_target.split(".")[0]
    return root_module in faked_modules


def _extract_all_calls(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, tuple[str, str]],
) -> tuple[set[str], set[str]]:
    """Extract all calls from a function, separated by type.

    Args:
        func_node: The function AST node.
        imports: Import information for the file.

    Returns:
        Tuple of (project_calls, integration_calls).
    """
    project_calls: set[str] = set()
    integration_calls: set[str] = set()

    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            target, call_type = _resolve_any_call_target(node, imports)
            if target:
                if call_type == "project":
                    project_calls.add(target)
                elif call_type == "integration":
                    integration_calls.add(target)

    return project_calls, integration_calls


def analyze_test_file(file_path: Path, call_graph: CallGraph) -> FileAnalysis:
    """Analyze a single test file.

    Args:
        file_path: Path to the test file.
        call_graph: Pre-built call graph for transitive analysis.

    Returns:
        FileAnalysis with test classification.
    """
    analysis = FileAnalysis(path=file_path)

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return analysis

    imports = _parse_imports(tree)

    # Get modules faked by imported fake libraries (applies to all tests in file)
    file_faked_modules = _uses_fake_library(imports)

    # Find test functions
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test_"
        ):
            test = TestAnalysis(name=node.name, file_path=file_path)

            # Extract mocked/faked targets
            test.mocked_targets = _extract_patch_targets(node)
            test.faked_modules = file_faked_modules | _extract_fake_fixture_modules(node)

            # Get all calls (project and integration)
            project_calls, integration_calls = _extract_all_calls(node, imports)

            # Also check type annotations for integration module usage
            # (e.g., def test_foo(http_client: httpx.Client))
            annotation_integration = _extract_integration_from_annotations(node, imports)
            integration_calls.update(annotation_integration)

            # Filter out mocked integration calls
            unmocked_integration = set()
            for call in integration_calls:
                if not _is_call_mocked(call, test.mocked_targets, test.faked_modules):
                    unmocked_integration.add(call)
            test.integration_calls = unmocked_integration

            # Filter out mocked project calls and get transitive calls
            unmocked_project_calls: set[str] = set()
            for call in project_calls:
                if not _is_call_mocked(call, test.mocked_targets, test.faked_modules):
                    unmocked_project_calls.add(call)

            test.direct_calls = unmocked_project_calls

            # Get transitive calls through call graph (only for unmocked calls)
            for direct_call in unmocked_project_calls:
                transitive = call_graph.get_transitive_calls(direct_call)
                # Filter transitive calls that are mocked
                for t_call in transitive:
                    if not _is_call_mocked(t_call, test.mocked_targets, test.faked_modules):
                        test.transitive_calls.add(t_call)

            # Classify the test
            _classify_test(test)

            analysis.tests.append(test)

            if test.is_unit_test:
                analysis.unit_tests.append(test.name)
            elif test.is_component_test:
                analysis.component_tests.append(test.name)
            else:
                analysis.integration_tests.append(test.name)

    return analysis


def _classify_test(test: TestAnalysis) -> None:
    """Classify a test as unit, component, or integration.

    Classification rules:
    - Integration: Has unmocked calls to integration modules (anyio, httpx, redis, etc.)
    - Unit: 0-1 project functions in the (unmocked) call graph
    - Component: >1 project functions in the (unmocked) call graph

    Args:
        test: TestAnalysis to classify (modified in place).
    """
    # Check for unmocked integration calls -> integration test
    if test.integration_calls:
        test.test_type = TestType.INTEGRATION
        calls_str = ", ".join(sorted(test.integration_calls)[:3])
        if len(test.integration_calls) > 3:
            calls_str += "..."
        test.reason = f"Integration calls ({len(test.integration_calls)}): {calls_str}"
        return

    # Count project functions in the call graph
    num_funcs = len(test.transitive_calls)

    if num_funcs == 0:
        test.test_type = TestType.UNIT
        test.reason = "No project functions called"
    elif num_funcs == 1:
        test.test_type = TestType.UNIT
        func = next(iter(test.transitive_calls))
        test.reason = f"Single function: {func}"
    else:
        test.test_type = TestType.COMPONENT
        funcs = sorted(test.transitive_calls)[:3]
        test.reason = f"Multiple functions ({num_funcs}): {', '.join(funcs)}"
        if num_funcs > 3:
            test.reason += "..."


def analyze_directory(
    test_dir: Path, call_graph: CallGraph, num_workers: int = 8
) -> list[FileAnalysis]:
    """Analyze all test files in a directory.

    Args:
        test_dir: Directory containing test files.
        call_graph: Pre-built call graph.
        num_workers: Number of parallel workers.

    Returns:
        List of FileAnalysis results.
    """
    test_files = list(test_dir.rglob("test_*.py"))

    # Can't use ThreadPoolExecutor easily with call_graph, so sequential
    analyses = [analyze_test_file(f, call_graph) for f in test_files]

    return analyses


@dataclass
class TestLocation:
    """Location info for a test function."""

    name: str
    start_line: int  # 1-indexed, includes decorators
    end_line: int  # 1-indexed
    parent_class: str | None = None
    class_start_line: int | None = None  # 1-indexed, includes decorators


def _parse_test_structure(source: str) -> dict[str, TestLocation]:
    """Parse test file structure to understand class membership.

    Args:
        source: Python source code.

    Returns:
        Dict mapping function name to TestLocation.
    """
    tree = ast.parse(source)
    tests: dict[str, TestLocation] = {}

    # Find module-level test functions
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name.startswith("test_"):
                start = node.lineno
                for dec in node.decorator_list:
                    if hasattr(dec, "lineno"):
                        start = min(start, dec.lineno)
                end = (
                    node.end_lineno
                    if hasattr(node, "end_lineno") and node.end_lineno is not None
                    else node.lineno
                )
                tests[node.name] = TestLocation(
                    name=node.name,
                    start_line=start,
                    end_line=end,
                    parent_class=None,
                    class_start_line=None,
                )

        # Find test classes and their methods
        elif isinstance(node, ast.ClassDef):
            class_start = node.lineno
            for dec in node.decorator_list:
                if hasattr(dec, "lineno"):
                    class_start = min(class_start, dec.lineno)

            for item in node.body:
                if isinstance(
                    item, ast.FunctionDef | ast.AsyncFunctionDef
                ) and item.name.startswith("test_"):
                    start = item.lineno
                    for dec in item.decorator_list:
                        if hasattr(dec, "lineno"):
                            start = min(start, dec.lineno)
                    end = (
                        item.end_lineno
                        if hasattr(item, "end_lineno") and item.end_lineno is not None
                        else item.lineno
                    )
                    tests[item.name] = TestLocation(
                        name=item.name,
                        start_line=start,
                        end_line=end,
                        parent_class=node.name,
                        class_start_line=class_start,
                    )

    return tests


def _extract_imports_and_fixtures(source: str) -> tuple[list[str], list[str]]:
    """Extract import statements and fixture definitions from source.

    Args:
        source: Python source code.

    Returns:
        Tuple of (import_lines, fixture_lines).
    """
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)

    import_end = 0
    fixtures: list[tuple[int, int]] = []

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Import | ast.ImportFrom)
            and hasattr(node, "end_lineno")
            and node.end_lineno
        ):
            import_end = max(import_end, node.end_lineno)

        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            is_fixture = False
            decorator_start = node.lineno

            for dec in node.decorator_list:
                if hasattr(dec, "lineno"):
                    decorator_start = min(decorator_start, dec.lineno)
                if (isinstance(dec, ast.Name) and dec.id == "fixture") or (
                    isinstance(dec, ast.Attribute) and dec.attr == "fixture"
                ):
                    is_fixture = True
                elif isinstance(dec, ast.Call):
                    func = dec.func
                    if (isinstance(func, ast.Name) and func.id == "fixture") or (
                        isinstance(func, ast.Attribute) and func.attr == "fixture"
                    ):
                        is_fixture = True

            if is_fixture and hasattr(node, "end_lineno") and node.end_lineno:
                fixtures.append((decorator_start, node.end_lineno))

    import_lines = lines[:import_end]

    fixture_lines: list[str] = []
    for start, end in sorted(fixtures):
        actual_start = start - 1
        if actual_start > 0 and not lines[actual_start - 1].strip():
            actual_start = start - 2
        fixture_lines.extend(lines[max(0, actual_start) : end])
        if end < len(lines) and lines[end].strip() == "":
            fixture_lines.append(lines[end])

    return import_lines, fixture_lines


def generate_split_file(source: str, functions: list[str]) -> str:
    """Generate a new file containing only specified functions.

    Handles both module-level test functions and class methods.
    Class methods are grouped under their class definition.

    Args:
        source: Original source code.
        functions: List of function names to include.

    Returns:
        New file source code.
    """
    lines = source.splitlines(keepends=True)
    import_lines, fixture_lines = _extract_imports_and_fixtures(source)
    test_structure = _parse_test_structure(source)

    result_lines = list(import_lines)

    if result_lines and result_lines[-1].strip():
        result_lines.append("\n")

    if fixture_lines:
        result_lines.append("\n")
        result_lines.extend(fixture_lines)

    # Group functions by parent class
    module_level: list[str] = []
    by_class: dict[str, list[str]] = defaultdict(list)

    for func_name in sorted(functions):
        if func_name in test_structure:
            loc = test_structure[func_name]
            if loc.parent_class:
                by_class[loc.parent_class].append(func_name)
            else:
                module_level.append(func_name)
        else:
            # Fallback - assume module level
            module_level.append(func_name)

    # Extract module-level functions
    for func_name in module_level:
        if func_name in test_structure:
            loc = test_structure[func_name]
            start_idx = loc.start_line - 1
            end_idx = loc.end_line

            # Include blank line before if present
            if start_idx > 0 and not lines[start_idx - 1].strip():
                start_idx -= 1

            result_lines.append("\n")
            result_lines.extend(lines[start_idx:end_idx])

    # Extract class-based tests
    for _class_name, class_funcs in sorted(by_class.items()):
        # Find class info from first function
        first_func = class_funcs[0]
        if first_func not in test_structure:
            continue
        class_start_line = test_structure[first_func].class_start_line
        if class_start_line is None:
            continue

        # Add class definition line
        result_lines.append("\n\n")
        class_def_idx = class_start_line - 1
        result_lines.append(lines[class_def_idx])

        # Add each method
        for func_name in class_funcs:
            loc = test_structure[func_name]
            start_idx = loc.start_line - 1
            end_idx = loc.end_line

            result_lines.append("\n")
            result_lines.extend(lines[start_idx:end_idx])

    result = "".join(result_lines)
    if not result.endswith("\n"):
        result += "\n"

    return result


def _move_or_merge_file(source_path: Path, target_path: Path, functions: list[str]) -> None:
    """Move or merge test functions to a target file.

    Args:
        source_path: Source file path.
        target_path: Target file path.
        functions: List of function names to include.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source = source_path.read_text(encoding="utf-8")

    if target_path.exists():
        # Merge with existing file
        existing = target_path.read_text(encoding="utf-8")
        new_tests = generate_split_file(source, functions)
        merged = existing.rstrip() + "\n\n" + new_tests
        target_path.write_text(merged, encoding="utf-8")
    else:
        # Write new file
        target_path.write_text(source, encoding="utf-8")


def _write_split_file(source: str, functions: list[str], target_path: Path) -> None:
    """Write a split file containing only specified functions.

    Args:
        source: Original source code.
        functions: List of function names to include.
        target_path: Target file path.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    split_source = generate_split_file(source, functions)

    if target_path.exists():
        existing = target_path.read_text(encoding="utf-8")
        merged = existing.rstrip() + "\n\n" + split_source
        target_path.write_text(merged, encoding="utf-8")
    else:
        target_path.write_text(split_source, encoding="utf-8")


def reclassify_tests(
    unit_dir: Path,
    component_dir: Path,
    integration_dir: Path,
    call_graph: CallGraph,
    dry_run: bool = True,
) -> dict[str, list[str]]:
    """Reclassify tests between unit, component, and integration based on call analysis.

    Args:
        unit_dir: Path to scripts/tests/unit/.
        component_dir: Path to scripts/tests/component/.
        integration_dir: Path to scripts/tests/integration/.
        call_graph: Pre-built call graph.
        dry_run: If True, only print what would be done.

    Returns:
        Summary of actions.
    """
    summary: dict[str, list[str]] = defaultdict(list)

    # Analyze all directories
    unit_analyses = analyze_directory(unit_dir, call_graph) if unit_dir.exists() else []
    component_analyses = (
        analyze_directory(component_dir, call_graph) if component_dir.exists() else []
    )
    integration_analyses = (
        analyze_directory(integration_dir, call_graph) if integration_dir.exists() else []
    )

    # Process unit/ -> find component and integration tests to move out
    for analysis in unit_analyses:
        if not analysis.component_tests and not analysis.integration_tests:
            continue

        rel_path = analysis.path.relative_to(unit_dir)
        component_target = component_dir / rel_path
        integration_target = integration_dir / rel_path

        # Determine what stays and what moves
        has_unit = bool(analysis.unit_tests)
        has_component = bool(analysis.component_tests)
        has_integration = bool(analysis.integration_tests)

        if not has_unit:
            # No unit tests - file needs to move entirely or split between component/integration
            if has_component and not has_integration:
                # All component
                summary["unit_to_component"].append(
                    f"MOVE {analysis.path} -> {component_target} "
                    f"({len(analysis.component_tests)} tests)"
                )
                if not dry_run:
                    _move_or_merge_file(analysis.path, component_target, analysis.component_tests)
                    analysis.path.unlink()
            elif has_integration and not has_component:
                # All integration
                summary["unit_to_integration"].append(
                    f"MOVE {analysis.path} -> {integration_target} "
                    f"({len(analysis.integration_tests)} tests)"
                )
                if not dry_run:
                    _move_or_merge_file(
                        analysis.path, integration_target, analysis.integration_tests
                    )
                    analysis.path.unlink()
            else:
                # Split between component and integration
                summary["split_unit"].append(
                    f"SPLIT {analysis.path}: move {len(analysis.component_tests)} to component, "
                    f"{len(analysis.integration_tests)} to integration"
                )
                if not dry_run:
                    source = analysis.path.read_text(encoding="utf-8")
                    if has_component:
                        _write_split_file(source, analysis.component_tests, component_target)
                    if has_integration:
                        _write_split_file(source, analysis.integration_tests, integration_target)
                    analysis.path.unlink()
        else:
            # Mixed - keep unit tests, move others
            moves = []
            if has_component:
                moves.append(f"{len(analysis.component_tests)} to component")
            if has_integration:
                moves.append(f"{len(analysis.integration_tests)} to integration")

            summary["split_unit"].append(
                f"SPLIT {analysis.path}: keep {len(analysis.unit_tests)} unit, "
                f"move {', '.join(moves)}"
            )
            if not dry_run:
                source = analysis.path.read_text(encoding="utf-8")

                # Rewrite unit file with only unit tests
                unit_source = generate_split_file(source, analysis.unit_tests)
                analysis.path.write_text(unit_source, encoding="utf-8")

                # Create/append component file
                if has_component:
                    _write_split_file(source, analysis.component_tests, component_target)

                # Create/append integration file
                if has_integration:
                    _write_split_file(source, analysis.integration_tests, integration_target)

    # Process component/ -> find unit and integration tests to move out
    for analysis in component_analyses:
        if not analysis.unit_tests and not analysis.integration_tests:
            continue

        rel_path = analysis.path.relative_to(component_dir)
        unit_target = unit_dir / rel_path
        integration_target = integration_dir / rel_path

        has_unit = bool(analysis.unit_tests)
        has_component = bool(analysis.component_tests)
        has_integration = bool(analysis.integration_tests)

        if not has_component:
            # No component tests - file needs to move entirely or split
            if has_unit and not has_integration:
                # All unit
                summary["component_to_unit"].append(
                    f"MOVE {analysis.path} -> {unit_target} ({len(analysis.unit_tests)} tests)"
                )
                if not dry_run:
                    _move_or_merge_file(analysis.path, unit_target, analysis.unit_tests)
                    analysis.path.unlink()
            elif has_integration and not has_unit:
                # All integration
                summary["component_to_integration"].append(
                    f"MOVE {analysis.path} -> {integration_target} "
                    f"({len(analysis.integration_tests)} tests)"
                )
                if not dry_run:
                    _move_or_merge_file(
                        analysis.path, integration_target, analysis.integration_tests
                    )
                    analysis.path.unlink()
            else:
                # Split between unit and integration
                summary["split_component"].append(
                    f"SPLIT {analysis.path}: move {len(analysis.unit_tests)} to unit, "
                    f"{len(analysis.integration_tests)} to integration"
                )
                if not dry_run:
                    source = analysis.path.read_text(encoding="utf-8")
                    if has_unit:
                        _write_split_file(source, analysis.unit_tests, unit_target)
                    if has_integration:
                        _write_split_file(source, analysis.integration_tests, integration_target)
                    analysis.path.unlink()
        else:
            # Mixed - keep component tests, move others
            moves = []
            if has_unit:
                moves.append(f"{len(analysis.unit_tests)} to unit")
            if has_integration:
                moves.append(f"{len(analysis.integration_tests)} to integration")

            summary["split_component"].append(
                f"SPLIT {analysis.path}: keep {len(analysis.component_tests)} "
                f"component, move {', '.join(moves)}"
            )
            if not dry_run:
                source = analysis.path.read_text(encoding="utf-8")

                # Rewrite component file with only component tests
                component_source = generate_split_file(source, analysis.component_tests)
                analysis.path.write_text(component_source, encoding="utf-8")

                # Create/append unit file
                if has_unit:
                    _write_split_file(source, analysis.unit_tests, unit_target)

                # Create/append integration file
                if has_integration:
                    _write_split_file(source, analysis.integration_tests, integration_target)

    # Process integration/ -> find unit and component tests to move out
    for analysis in integration_analyses:
        if not analysis.unit_tests and not analysis.component_tests:
            continue

        rel_path = analysis.path.relative_to(integration_dir)
        unit_target = unit_dir / rel_path
        component_target = component_dir / rel_path

        has_unit = bool(analysis.unit_tests)
        has_component = bool(analysis.component_tests)
        has_integration = bool(analysis.integration_tests)

        if not has_integration:
            # No integration tests - file needs to move entirely or split
            if has_unit and not has_component:
                # All unit
                summary["integration_to_unit"].append(
                    f"MOVE {analysis.path} -> {unit_target} ({len(analysis.unit_tests)} tests)"
                )
                if not dry_run:
                    _move_or_merge_file(analysis.path, unit_target, analysis.unit_tests)
                    analysis.path.unlink()
            elif has_component and not has_unit:
                # All component
                summary["integration_to_component"].append(
                    f"MOVE {analysis.path} -> {component_target} "
                    f"({len(analysis.component_tests)} tests)"
                )
                if not dry_run:
                    _move_or_merge_file(analysis.path, component_target, analysis.component_tests)
                    analysis.path.unlink()
            else:
                # Split between unit and component
                summary["split_integration"].append(
                    f"SPLIT {analysis.path}: move {len(analysis.unit_tests)} to unit, "
                    f"{len(analysis.component_tests)} to component"
                )
                if not dry_run:
                    source = analysis.path.read_text(encoding="utf-8")
                    if has_unit:
                        _write_split_file(source, analysis.unit_tests, unit_target)
                    if has_component:
                        _write_split_file(source, analysis.component_tests, component_target)
                    analysis.path.unlink()
        else:
            # Mixed - keep integration tests, move others
            moves = []
            if has_unit:
                moves.append(f"{len(analysis.unit_tests)} to unit")
            if has_component:
                moves.append(f"{len(analysis.component_tests)} to component")

            summary["split_integration"].append(
                f"SPLIT {analysis.path}: keep {len(analysis.integration_tests)} "
                f"integration, move {', '.join(moves)}"
            )
            if not dry_run:
                source = analysis.path.read_text(encoding="utf-8")

                # Rewrite integration file with only integration tests
                integration_source = generate_split_file(source, analysis.integration_tests)
                analysis.path.write_text(integration_source, encoding="utf-8")

                # Create/append unit file
                if has_unit:
                    _write_split_file(source, analysis.unit_tests, unit_target)

                # Create/append component file
                if has_component:
                    _write_split_file(source, analysis.component_tests, component_target)

    return dict(summary)


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze and reclassify tests based on transitive call analysis"
    )
    parser.add_argument(
        "test_dir", type=Path, nargs="?", help="Test directory to analyze (for --report mode)"
    )
    parser.add_argument("--unit-dir", type=Path, help="Unit test directory")
    parser.add_argument("--component-dir", type=Path, help="Component test directory")
    parser.add_argument("--integration-dir", type=Path, help="Integration test directory")
    parser.add_argument(
        "--project-root", type=Path, default=Path.cwd(), help="Project root for building call graph"
    )
    parser.add_argument(
        "--report", action="store_true", help="Just analyze and report a single directory"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Only show what would be done (default)",
    )
    parser.add_argument("--execute", action="store_true", help="Actually perform reclassification")

    args = parser.parse_args(argv)

    # Build call graph
    print("Building call graph of project functions...")
    call_graph = build_call_graph(args.project_root)
    print(f"  Found {len(call_graph.functions)} functions")

    if args.report:
        if not args.test_dir:
            print("Error: test_dir required for --report mode", file=sys.stderr)
            return 1

        print(f"\nAnalyzing {args.test_dir}...")
        analyses = analyze_directory(args.test_dir, call_graph)

        total_tests = sum(len(a.tests) for a in analyses)
        total_unit = sum(len(a.unit_tests) for a in analyses)
        total_component = sum(len(a.component_tests) for a in analyses)
        total_integration = sum(len(a.integration_tests) for a in analyses)

        print("\n=== Analysis Summary ===")
        if total_tests > 0:
            print(f"Total: {total_tests}")
            print(f"  Unit: {total_unit} ({100 * total_unit / total_tests:.1f}%)")
            print(f"  Component: {total_component} ({100 * total_component / total_tests:.1f}%)")
            print(
                f"  Integration: {total_integration} ({100 * total_integration / total_tests:.1f}%)"
            )
        else:
            print("No tests found.")

        # Detailed output for integration tests
        if total_integration > 0:
            print("\n=== Integration Tests (require real I/O) ===")
            for a in analyses:
                for test in a.tests:
                    if test.is_integration_test:
                        print(f"  {a.path.name}::{test.name}")
                        print(f"    Reason: {test.reason}")

        return 0

    # Reclassification mode
    unit_dir = args.unit_dir or args.project_root / "scripts" / "tests" / "unit"
    component_dir = args.component_dir or args.project_root / "scripts" / "tests" / "component"
    integration_dir = (
        args.integration_dir or args.project_root / "scripts" / "tests" / "integration"
    )

    if not unit_dir.exists():
        print(f"Error: {unit_dir} does not exist", file=sys.stderr)
        return 1
    if not component_dir.exists():
        print(f"Error: {component_dir} does not exist", file=sys.stderr)
        return 1
    # integration_dir may not exist yet - it will be created when needed

    # Analyze all directories for summary
    print(f"\nAnalyzing {unit_dir}...")
    unit_analyses = analyze_directory(unit_dir, call_graph)
    print(f"Analyzing {component_dir}...")
    component_analyses = analyze_directory(component_dir, call_graph)
    if integration_dir.exists():
        print(f"Analyzing {integration_dir}...")
        integration_analyses = analyze_directory(integration_dir, call_graph)
    else:
        integration_analyses = []

    # Summary
    unit_total = sum(len(a.tests) for a in unit_analyses)
    unit_true_unit = sum(len(a.unit_tests) for a in unit_analyses)
    unit_true_comp = sum(len(a.component_tests) for a in unit_analyses)
    unit_true_integ = sum(len(a.integration_tests) for a in unit_analyses)

    comp_total = sum(len(a.tests) for a in component_analyses)
    comp_true_unit = sum(len(a.unit_tests) for a in component_analyses)
    comp_true_comp = sum(len(a.component_tests) for a in component_analyses)
    comp_true_integ = sum(len(a.integration_tests) for a in component_analyses)

    integ_total = sum(len(a.tests) for a in integration_analyses)
    integ_true_unit = sum(len(a.unit_tests) for a in integration_analyses)
    integ_true_comp = sum(len(a.component_tests) for a in integration_analyses)
    integ_true_integ = sum(len(a.integration_tests) for a in integration_analyses)

    print("\n=== Current State ===")
    print(f"unit/: {unit_total} tests")
    print(f"  - True unit: {unit_true_unit}")
    print(f"  - Should be component: {unit_true_comp}")
    print(f"  - Should be integration: {unit_true_integ}")
    print(f"component/: {comp_total} tests")
    print(f"  - Should be unit: {comp_true_unit}")
    print(f"  - True component: {comp_true_comp}")
    print(f"  - Should be integration: {comp_true_integ}")
    print(f"integration/: {integ_total} tests")
    print(f"  - Should be unit: {integ_true_unit}")
    print(f"  - Should be component: {integ_true_comp}")
    print(f"  - True integration: {integ_true_integ}")

    print("\n=== After Reclassification ===")
    print(f"unit/: {unit_true_unit + comp_true_unit + integ_true_unit} tests")
    print(f"component/: {unit_true_comp + comp_true_comp + integ_true_comp} tests")
    print(f"integration/: {unit_true_integ + comp_true_integ + integ_true_integ} tests")

    dry_run = not args.execute

    if dry_run:
        print("\n=== DRY RUN (use --execute to apply) ===")
    else:
        print("\n=== EXECUTING RECLASSIFICATION ===")

    summary = reclassify_tests(unit_dir, component_dir, integration_dir, call_graph, dry_run)

    for category, actions in sorted(summary.items()):
        if actions:
            print(f"\n{category.upper()} ({len(actions)}):")
            for action in actions[:50]:
                print(f"  {action}")
            if len(actions) > 50:
                print(f"  ... and {len(actions) - 50} more")

    total_actions = sum(len(a) for a in summary.values())
    print(f"\nTotal: {total_actions} actions")

    if dry_run and total_actions > 0:
        print("\nRun with --execute to apply these changes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
