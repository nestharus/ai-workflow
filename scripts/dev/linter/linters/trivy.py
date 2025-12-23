"""Trivy security scanner for filesystem and Docker images."""

import contextlib
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    get_executable,
    load_yaml_config,
)

TRIVY_CLI_REQUIRED = "trivy CLI required to run lint"
DOCKER_CLI_REQUIRED = "docker CLI required for trivy image scanning"
LINT_TRIVY_CONFIG = REPO_ROOT / ".lint.trivy.yaml"


class TrivyLinter(BaseLinter):
    """Run Trivy security scans for filesystem and Docker image."""

    name = "trivy"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run Trivy security scans.

        Runs two scan modes (controlled by enable_fs_scan and enable_image_scan):
        1. Filesystem scan: Scans uv.lock for Python dependency vulnerabilities
        2. Image scan: Builds temporary Docker image and scans for vulnerabilities

        Note: The filesystem scan runs first. If it fails (vulnerabilities found
        or errors), the function returns immediately and the image scan is skipped.
        This short-circuit behavior avoids running Docker operations when dependency
        vulnerabilities already need attention.

        Args:
            files: Optional list of files to filter. Only runs if uv.lock or
                   any Dockerfile file is in the files list.

        Returns:
            LinterResult indicating success/failure.
        """
        # If files are specified, only run if uv.lock or any Dockerfile is in the list
        if files is not None:
            has_uv_lock = any(f.endswith("uv.lock") for f in files)
            has_dockerfile = any(
                f.endswith("Dockerfile") or "Dockerfile" in f
                for f in files
            )
            if not (has_uv_lock or has_dockerfile):
                print("No uv.lock or Dockerfile in changed files, skipping trivy linter.")
                return LinterResult(success=True)

        trivy_exe = get_executable("trivy", TRIVY_CLI_REQUIRED)
        config = load_yaml_config(LINT_TRIVY_CONFIG)

        # Check which scans are enabled (both default to True for backward compatibility)
        enable_fs_scan = config.get("enable_fs_scan", True)
        enable_image_scan = config.get("enable_image_scan", True)

        # Filesystem scan (runs first, short-circuits on failure)
        if enable_fs_scan:
            fs_result = self._run_trivy_fs(trivy_exe, config)
            if not fs_result.success:
                return fs_result
        else:
            print("Filesystem scan disabled via enable_fs_scan: false")

        # Image scan (only runs if filesystem scan passes or is disabled)
        if enable_image_scan:
            return self._run_trivy_image(trivy_exe, config)
        else:
            print("Image scan disabled via enable_image_scan: false")

        return LinterResult(success=True)

    def _run_trivy_fs(self, trivy_exe: str, config: dict[str, Any]) -> LinterResult:
        """Run Trivy filesystem scan on uv.lock.

        Args:
            trivy_exe: Path to trivy executable.
            config: Configuration dictionary from .lint.trivy.yaml.

        Returns:
            LinterResult indicating success/failure.
        """
        fs_target = config.get("fs_target", "uv.lock")
        lockfile_path = REPO_ROOT / fs_target
        skip_if_missing = config.get("skip_fs_if_no_lockfile", False)

        if not lockfile_path.exists():
            if skip_if_missing:
                print(f"Warning: {fs_target} not found, skipping filesystem scan")
                return LinterResult(success=True)
            else:
                print(f"Error: {fs_target} not found")
                return LinterResult(success=False)

        # Run trivy fs scan from REPO_ROOT
        result = subprocess.call(
            [trivy_exe, "fs", "--config", ".trivy.yaml", str(fs_target)],
            cwd=str(REPO_ROOT),
        )
        return LinterResult(success=result == 0)

    def _run_trivy_image(self, trivy_exe: str, config: dict[str, Any]) -> LinterResult:
        """Run Trivy image scan on temporary Docker image.

        Builds the Docker image without a tag, using --iidfile to capture the unique
        image ID. This avoids clobbering existing tags and ensures cleanup only
        removes the image we just built.

        Args:
            trivy_exe: Path to trivy executable.
            config: Configuration dictionary from .lint.trivy.yaml.

        Returns:
            LinterResult indicating success/failure.
        """
        skip_if_no_dockerfile = config.get("skip_image_if_no_dockerfile", True)

        dockerfile_path = REPO_ROOT / "Dockerfile"
        if not dockerfile_path.exists():
            if skip_if_no_dockerfile:
                print("Warning: Dockerfile not found, skipping image scan")
                return LinterResult(success=True)
            else:
                print("Error: Dockerfile not found")
                return LinterResult(success=False)

        # Only check for Docker after confirming we need to build
        docker_exe = get_executable("docker", DOCKER_CLI_REQUIRED)

        # Build image without tag, using --iidfile to capture the unique image ID.
        # This avoids clobbering existing tags and ensures we only remove our image.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".iid", delete=False) as iid_file:
            iid_file_path = iid_file.name

        print("Building temporary image...")
        build_result = subprocess.call(
            [docker_exe, "build", "--iidfile", iid_file_path, "."],
            cwd=str(REPO_ROOT),
        )

        if build_result != 0:
            print("Error: Docker build failed")
            # Clean up iid file if build failed
            Path(iid_file_path).unlink(missing_ok=True)
            return LinterResult(success=False)

        # Read the image ID from the iidfile
        # Initialize image_id before try block so cleanup can attempt to read it if needed
        image_id: str | None = None
        try:
            image_id = Path(iid_file_path).read_text().strip()

            if not image_id:
                print("Error: Failed to get image ID from build")
                return LinterResult(success=False)

            # Run trivy image scan
            print(f"Scanning image: {image_id[:12]}...")
            scan_result = subprocess.call(
                [trivy_exe, "image", "--config", ".trivy.yaml", image_id],
                cwd=str(REPO_ROOT),
            )
            return LinterResult(success=scan_result == 0)
        finally:
            # If image_id is not set (read failed), try to read it again for cleanup.
            # We read into a local and reassign to avoid issues with contextlib.suppress
            # not allowing assignment expressions within the with block.
            if not image_id:
                recovered_id: str | None = None
                with contextlib.suppress(OSError):
                    recovered_id = Path(iid_file_path).read_text().strip()
                image_id = recovered_id

            # Clean up temp image if we have an ID
            if image_id:
                print(f"Removing temporary image: {image_id[:12]}...")
                cleanup_result = subprocess.call(
                    [docker_exe, "rmi", image_id],
                    cwd=str(REPO_ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if cleanup_result != 0:
                    print(
                        f"Warning: Failed to remove temporary image {image_id[:12]}",
                    )

            # Clean up IID file after image cleanup is complete
            Path(iid_file_path).unlink(missing_ok=True)
