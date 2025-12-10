"""Individual linter implementations."""

from scripts.dev.linter.linters.actionlint import ActionlintLinter
from scripts.dev.linter.linters.checkov import CheckovLinter
from scripts.dev.linter.linters.detect_secrets import DetectSecretsLinter
from scripts.dev.linter.linters.dotenvlint import DotenvlintLinter
from scripts.dev.linter.linters.hadolint import HadolintLinter
from scripts.dev.linter.linters.mypy import MypyLinter
from scripts.dev.linter.linters.pymarkdown import PymarkdownLinter
from scripts.dev.linter.linters.ruff import RuffLinter
from scripts.dev.linter.linters.scripts import ScriptsLinter
from scripts.dev.linter.linters.trivy import TrivyLinter
from scripts.dev.linter.linters.yamllint import YamllintLinter

# Linter instances in execution order
LINTERS = [
    ScriptsLinter(),
    RuffLinter(),
    MypyLinter(),
    HadolintLinter(),
    PymarkdownLinter(),
    YamllintLinter(),
    ActionlintLinter(),
    DotenvlintLinter(),
    CheckovLinter(),
    DetectSecretsLinter(),
    TrivyLinter(),
]

# Linter names in execution order
LINTER_NAMES = [linter.name for linter in LINTERS]

# Map linter names to instances
LINTER_MAP = {linter.name: linter for linter in LINTERS}

__all__ = [
    "LINTERS",
    "LINTER_MAP",
    "LINTER_NAMES",
    "ActionlintLinter",
    "CheckovLinter",
    "DetectSecretsLinter",
    "DotenvlintLinter",
    "HadolintLinter",
    "MypyLinter",
    "PymarkdownLinter",
    "RuffLinter",
    "ScriptsLinter",
    "TrivyLinter",
    "YamllintLinter",
]
