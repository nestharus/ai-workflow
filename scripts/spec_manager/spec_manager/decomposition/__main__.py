"""Allow running decomposition CLI as ``python -m scripts.spec_manager.spec_manager.decomposition``."""

from __future__ import annotations

import sys

from scripts.spec_manager.spec_manager.decomposition.cli import main

sys.exit(main())
