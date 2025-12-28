import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.app.gen_openapi import (
    OpenAPISchemaTypeError,
    SchemaSerializationError,
    _debug_enabled,
    _is_local_environment,
    build_application,
    generate_schema,
    main,
    normalize_openapi_schema,
    parse_args,
    write_schema,
)


class TestMain:
    def test_sets_default_credentials_locally(self) -> None:
        """Should set default credentials in local environment."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("scripts.app.gen_openapi._is_local_environment", return_value=True),
            patch("scripts.app.gen_openapi._generate_openapi"),
        ):
            main()

            # Check credentials were set inside the context
            assert "SURREALDB_USER" in os.environ
            assert "SURREALDB_PASS" in os.environ

    def test_returns_one_without_credentials_in_ci(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when credentials missing in non-local environment."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("scripts.app.gen_openapi._is_local_environment", return_value=False),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "SURREALDB_USER" in captured.err

    def test_proceeds_with_credentials_in_non_local_env(self) -> None:
        """Should proceed when credentials are set in non-local environment."""
        with (
            patch.dict(
                os.environ,
                {"SURREALDB_USER": "ci-user", "SURREALDB_PASS": "ci-pass"},
                clear=True,
            ),
            patch("scripts.app.gen_openapi._is_local_environment", return_value=False),
            patch("scripts.app.gen_openapi._generate_openapi"),
        ):
            result = main()

        assert result == 0

    def test_returns_zero_on_success(self) -> None:
        """Should return 0 on successful generation."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("scripts.app.gen_openapi._is_local_environment", return_value=True),
            patch("scripts.app.gen_openapi._generate_openapi"),
        ):
            result = main()

        assert result == 0

    def test_handles_system_exit(self) -> None:
        """Should propagate SystemExit with correct code."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("scripts.app.gen_openapi._is_local_environment", return_value=True),
            patch("scripts.app.gen_openapi._generate_openapi") as mock_gen,
        ):
            mock_gen.side_effect = SystemExit(42)

            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 42

    def test_handles_exception(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 and print error on exception."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("scripts.app.gen_openapi._is_local_environment", return_value=True),
            patch("scripts.app.gen_openapi._generate_openapi") as mock_gen,
        ):
            mock_gen.side_effect = RuntimeError("Generation failed")

            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Generation failed" in captured.err

    def test_prints_traceback_in_debug_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print traceback when debug is enabled."""
        with (
            patch.dict(os.environ, {"DEBUG": "1"}, clear=True),
            patch("scripts.app.gen_openapi._is_local_environment", return_value=True),
            patch("scripts.app.gen_openapi._generate_openapi") as mock_gen,
        ):
            mock_gen.side_effect = RuntimeError("Generation failed")

            main()

        captured = capsys.readouterr()
        assert "Traceback" in captured.err or "RuntimeError" in captured.err


class TestParseArgs:
    def test_default_output_path(self) -> None:
        """Test default output path when no args provided."""
        with patch("sys.argv", ["gen_openapi"]):
            args = parse_args()

        assert args.output == Path("openapi/openapi.json")

    def test_custom_output_path(self) -> None:
        """Test custom output path from command line."""
        with patch("sys.argv", ["gen_openapi", "--output", "custom/path.json"]):
            args = parse_args()

        assert args.output == Path("custom/path.json")
