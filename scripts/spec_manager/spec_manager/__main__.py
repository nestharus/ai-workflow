"""Allow running as python -m scripts.spec_manager."""

from spec_manager.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
