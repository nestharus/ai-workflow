#!/bin/bash

# scripts/sonar_scan.sh
# Wrapper script to run SonarScanner via Docker with caching enabled.

# Default values
DEFAULT_SONAR_HOST_URL="http://localhost:9000"
SONAR_HOST_URL=${SONAR_HOST_URL:-"$DEFAULT_SONAR_HOST_URL"}
SONAR_TOKEN=${SONAR_TOKEN:-""}
PROJECT_DIR=$(pwd)
CACHE_DIR="$PROJECT_DIR/.sonar/cache"

# Help function
function show_help {
    echo "Usage: ./scripts/sonar_scan.sh [options] [-- scanner_args]"
    echo ""
    echo "Options:"
    echo "  -h, --help          Show this help message"
    echo "  -t, --token TOKEN   SonarQube authentication token (overrides SONAR_TOKEN env var)"
    echo "  -u, --url URL       SonarQube server URL (default: http://localhost:9000)"
    echo ""
    echo "Scanner Arguments:"
    echo "  Any arguments after '--' are passed directly to the sonar-scanner-cli."
    echo ""
    echo "Environment Variables:"
    echo "  SONAR_TOKEN         SonarQube authentication token"
    echo "  SONAR_HOST_URL      SonarQube server URL"
}

# Parse arguments
EXTRA_ARGS=()
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -h|--help) show_help; exit 0 ;;
        -t|--token)
            if [[ -z "$2" || "$2" == -* ]]; then
                echo "Error: --token requires a value."
                exit 1
            fi
            SONAR_TOKEN="$2"
            shift
            ;;
        -u|--url)
            if [[ -z "$2" || "$2" == -* ]]; then
                echo "Error: --url requires a value."
                exit 1
            fi
            SONAR_HOST_URL="$2"
            shift
            ;;
        --) shift; EXTRA_ARGS+=("$@"); break ;; 
        *) echo "Unknown parameter passed: $1"; exit 1 ;; 
    esac
    shift
done

# Check for token (unless running help or just checking version)
# We allow running without token if it's not strictly required by the server (e.g. public projects), 
# but usually it is. We'll warn if missing but proceed, letting the scanner fail if needed.
if [ -z "$SONAR_TOKEN" ]; then
    echo "Warning: SONAR_TOKEN is not set. Authentication might fail."
fi

# Create cache directory
if [ ! -d "$CACHE_DIR" ]; then
    echo "Creating cache directory: $CACHE_DIR"
    mkdir -p "$CACHE_DIR"
fi

# Verify Docker availability before running the scanner
if ! command -v docker >/dev/null 2>&1; then
    echo "Error: Docker is not installed or not on PATH. Install Docker and ensure the daemon is running."
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "Error: Docker daemon is not running or not accessible (check permissions/group membership)."
    exit 1
fi

echo "Starting SonarScanner..."
echo "  Host: $SONAR_HOST_URL"
echo "  Project: $PROJECT_DIR"
echo "  Cache: $CACHE_DIR"

# Prevent accidental scans against the default local host unless explicitly allowed.
if [[ "$SONAR_HOST_URL" == "$DEFAULT_SONAR_HOST_URL" && -z "${ALLOW_DEFAULT_SONAR_HOST_URL:-}" ]]; then
    echo "Warning: SONAR_HOST_URL is using the default $DEFAULT_SONAR_HOST_URL. Set --url or SONAR_HOST_URL to your intended server, or export ALLOW_DEFAULT_SONAR_HOST_URL=1 to proceed locally."
    exit 1
fi

# Run Docker command
docker run \
    --rm \
    -v "$CACHE_DIR":/opt/sonar-scanner/.sonar/cache \
    -v "$PROJECT_DIR":/usr/src \
    -e SONAR_TOKEN="$SONAR_TOKEN" \
    -e SONAR_HOST_URL="$SONAR_HOST_URL" \
    sonarsource/sonar-scanner-cli \
    "${EXTRA_ARGS[@]}"

status=$?
if [ $status -ne 0 ]; then
    echo "SonarScanner Docker run failed with exit code $status"
    exit $status
fi
