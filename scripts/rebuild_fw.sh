#!/bin/bash
# Firmware rebuild script - RUNS INSIDE DOCKER
# This script is designed to run inside a Docker container with the workspace mounted

set -e

source rebuild_fw.env

echo "Rebuilding firmware: $APPLICATION"

# Initialize west workspace if not already done
if [ ! -d ".west" ]; then
    echo "Initializing west workspace using packaged resolved manifest..."
    west init -l zephyr-package-fw
fi

# Update west workspace
echo "Updating west workspace..."
if ! west update -n; then
    echo "Narrow update failed, retrying without narrow option..."
    west update
fi

# Checkout specific zephyr commit if specified
if [ -d "zephyr" ]; then
    echo "Checking out Zephyr commit $ZEPHYR_REVISION"
    (cd zephyr && git checkout $ZEPHYR_REVISION)
fi

# Export Zephyr environment
echo "Exporting Zephyr environment..."
west zephyr-export

# Source the Zephyr environment
if [ -f "zephyr/zephyr-env.sh" ]; then
    echo "Sourcing Zephyr environment..."
    source zephyr/zephyr-env.sh
fi

# Build the firmware using adapted west command
echo "Building firmware using adapted west command..."
echo "Build command: $WEST_COMMAND"
eval "$WEST_COMMAND"

# Copy firmware files to /output if mounted
if [ -d "/output" ]; then
    echo "Copying firmware files to /output..."
    find "build/zephyr" -name '*.bin' -o -name '*.hex' -o -name '*.elf' -exec cp -v {} /output/ \; || echo "Warning: Some firmware files could not be copied to /output."
    echo "Firmware files copied to /output"
fi

echo "Firmware rebuilt successfully!"

# List built files
echo ""
echo "Built firmware files:"
find "build/zephyr" -name '*.bin' -o -name '*.hex' -o -name '*.elf' | head -10
