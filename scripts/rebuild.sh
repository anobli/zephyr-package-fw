#!/bin/bash
# Orchestrator script for firmware rebuild

set -e

echo "Rebuilding the packaged firmware"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_IMAGE="${ZEPHYR_BUILD_IMAGE:-docker.io/zephyrprojectrtos/zephyr-build:main}"
OUTPUT_DIR="${OUTPUT_DIR:-$SCRIPT_DIR/rebuilt_firmware}"

# Step 1: Prepare workspace (runs outside Docker)
echo "Step 1: Preparing workspace..."

# Create workspace in package directory by default, or use ZEPHYR_WORKSPACE if set
if [ -n "$ZEPHYR_WORKSPACE" ]; then
    WORKSPACE_DIR="$ZEPHYR_WORKSPACE"
    echo "Using specified workspace directory: $WORKSPACE_DIR"
else
    WORKSPACE_DIR="$SCRIPT_DIR/workspace"
    echo "Creating workspace directory: $WORKSPACE_DIR"
fi

echo "Preparing Zephyr workspace"

# Create workspace directory
mkdir -p "$WORKSPACE_DIR"
echo "Created workspace directory: $WORKSPACE_DIR"

# Copy zephyr-package-fw module (always available in packages)
echo "Copying zephyr-package-fw module to workspace..."
cp -r "$SCRIPT_DIR/zephyr-package-fw" "$WORKSPACE_DIR/"
chmod -R a+rw  "$WORKSPACE_DIR/zephyr-package-fw"
echo "zephyr-package-fw module with resolved manifest copied to workspace"


# Copy rebuild_fw.sh script to workspace
echo "Copying rebuild firmware script..."
cp "$SCRIPT_DIR/rebuild_fw.sh" "$WORKSPACE_DIR/"
cp "$SCRIPT_DIR/rebuild_fw.env" "$WORKSPACE_DIR/"

chmod +x "$WORKSPACE_DIR/rebuild_fw.sh"

# Make workspace available to any user, which is required
# if host user id is not same a guest user id.
chmod a+rw "$WORKSPACE_DIR"

echo "Workspace preparation complete!"
echo ""
echo "Workspace location: $WORKSPACE_DIR"
echo ""
echo "To use this workspace location in other scripts:"
echo "  export ZEPHYR_WORKSPACE=\"$WORKSPACE_DIR\""
echo ""

# Step 2: Check Docker availability
echo "Step 2: Checking Docker availability..."
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed or not in PATH"
    exit 1
fi

# Step 3: Run rebuild inside Docker (Docker will auto-pull image if needed)
echo "Step 3: Running firmware rebuild in Docker..."
mkdir -p "$OUTPUT_DIR"
chmod a+rw "$OUTPUT_DIR"

docker run --rm \
    -v "$WORKSPACE_DIR:/workdir" \
    -v "$OUTPUT_DIR:/output" \
    -w /workdir \
    -e BUILD_DIR="${BUILD_DIR:-build_$(date +%Y%m%d_%H%M%S)}" \
    "$DOCKER_IMAGE" \
    ./rebuild_fw.sh

echo "Firmware rebuild complete!"
echo "Workspace: $WORKSPACE_DIR"
echo "Output: $OUTPUT_DIR"

# List output files
if [ -d "$OUTPUT_DIR" ] && [ "$(ls -A "$OUTPUT_DIR")" ]; then
    echo ""
    echo "Built firmware files:"
    ls -la "$OUTPUT_DIR"
else
    echo ""
    echo "Note: No firmware files in output directory (check workspace build directory)"
fi
