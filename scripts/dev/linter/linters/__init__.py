"""Individual linter implementations."""

from scripts.dev.linter.linters.actionlint import ActionlintLinter
from scripts.dev.linter.linters.astgrep import AstgrepLinter
from scripts.dev.linter.linters.checkov import CheckovLinter
from scripts.dev.linter.linters.detect_secrets import DetectSecretsLinter
from scripts.dev.linter.linters.dotenvlint import DotenvlintLinter
from scripts.dev.linter.linters.gitleaks import GitleaksLinter
from scripts.dev.linter.linters.hadolint import HadolintLinter
from scripts.dev.linter.linters.languagetool import LanguageToolLinter
from scripts.dev.linter.linters.mypy import MypyLinter
from scripts.dev.linter.linters.pymarkdown import PymarkdownLinter
from scripts.dev.linter.linters.ruff import RuffLinter
from scripts.dev.linter.linters.scripts import ScriptsLinter
from scripts.dev.linter.linters.shellcheck import ShellcheckLinter
from scripts.dev.linter.linters.trivy import TrivyLinter
from scripts.dev.linter.linters.yamllint import YamllintLinter

# Linter instances in execution order
LINTERS = [
    ScriptsLinter(),
    RuffLinter(),
    AstgrepLinter(),
    MypyLinter(),
    HadolintLinter(),
    ShellcheckLinter(),
    PymarkdownLinter(),
    LanguageToolLinter(),
    YamllintLinter(),
    ActionlintLinter(),
    DotenvlintLinter(),
    CheckovLinter(),
    DetectSecretsLinter(),
    GitleaksLinter(),
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
    "AstgrepLinter",
    "CheckovLinter",
    "DetectSecretsLinter",
    "DotenvlintLinter",
    "GitleaksLinter",
    "HadolintLinter",
    "LanguageToolLinter",
    "MypyLinter",
    "PymarkdownLinter",
    "RuffLinter",
    "ScriptsLinter",
    "ShellcheckLinter",
    "TrivyLinter",
    "YamllintLinter",
]
