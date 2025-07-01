#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""West extension command for packaging firmware."""

import os
from pathlib import Path
from datetime import datetime

import shutil
import subprocess
import zipfile
import yaml
from west.commands import WestCommand
from west import log
from package_fw_helper import BuildInfo, WestBuildParser

def dict_to_bash_env(filename, env_dict):
    try:
        with open(filename, 'w') as f:
            # Write shebang
            f.write('#!/bin/bash\n\n')
            f.write('# Environment variables\n')
            f.write('# Generated automatically\n\n')

            # Write each environment variable
            for key, value in env_dict.items():
                # Escape special characters in the value
                escaped_value = str(value).replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
                f.write(f'export {key}="{escaped_value}"\n')

            # Add a blank line at the end
            f.write('\n')

        return filename

    except Exception as e:
        raise Exception(f"Error creating bash file: {str(e)}")

class PackageFw(WestCommand):
    """Package firmware for distribution."""

    def __init__(self):
        super().__init__(
            'package_fw',
            'package firmware',
            'Package firmware for distribution',
            accepts_unknown_args=False)

    def do_add_parser(self, parser_adder):
        """Add parser arguments for the package_fw command."""
        parser = parser_adder.add_parser(
            self.name,
            help=self.help,
            description=self.description)
        parser.add_argument('-b', '--build-dir', default='build',
                          help='Build directory containing the firmware '
                               '(default: build)')
        parser.add_argument('-o', '--output-dir',
                          help='Output directory for the firmware package '
                               '(default: <app_name>-<board>)')
        parser.add_argument('-z', '--zip', action='store_true',
                          help='Create a zip archive of the firmware package')
        return parser

    def do_run(self, args, unknown):
        """Package firmware with metadata for distribution."""
        build_dir = Path(args.build_dir).resolve()
        if not build_dir.exists():
            log.err(f"Build directory does not exist: {build_dir}")
            return 1
        log.inf(f"Packaging firmware from {build_dir}")

        # Extract the build info first to get app name and board for output directory
        build_info = BuildInfo(build_dir)

        # Determine output directory
        if args.output_dir:
            output_dir = Path(args.output_dir).resolve()
        else:
            app_name = build_info.application_name
            board = build_info.board
            output_dir = Path(f"{app_name}-{board}").resolve()

        # Create output directory
        log.inf(f"Package output dir: {output_dir}")
        if output_dir.exists():
            shutil.rmtree(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)

        # Copy firmwares
        self._package_firmware_files(build_dir, output_dir)

        west_command = self._west_command_for_docker(build_info)

        # Copy zephyr-package-fw module and generate resolved manifest
        self._copy_package_fw_module(output_dir)

        rebuild_fw_env = {
            "WEST_COMMAND": west_command,
            "APPLICATION": build_info.application_name,
            "ZEPHYR_REVISION": build_info.version,
        }
        dict_to_bash_env(output_dir / "rebuild_fw.env", rebuild_fw_env)

        # Create zip archive if requested
        if args.zip:
            zip_path = self._create_zip_archive(output_dir)
            log.inf(f"Firmware packaged successfully in {output_dir}")
            log.inf(f"Zip archive created: {zip_path}")
        else:
            log.inf(f"Firmware packaged successfully in {output_dir}")

        return 0

    def _west_command_for_docker(self, build_info):
        # Remove west path to just keep the west command itself
        west_command = build_info.west_command
        west_command = west_command.replace(west_command.split()[0], "west")

        app_source_dir = build_info.source_dir
        west_topdir = build_info.topdir
        relative_path = app_source_dir.relative_to(west_topdir)

        parser = WestBuildParser()
        parser.extract_from_command_line(west_command)
        command_source_dir = parser.build_command.args.source_dir

        # Convert source_dir to path we are going to use in docker image
        west_command = west_command.replace(command_source_dir, str(relative_path))

        return west_command

    def _package_firmware_files(self, build_dir, output_dir):
        """Copy firmware files to the package directory."""
        firmware_dir = output_dir / "firmware"
        firmware_dir.mkdir(exist_ok=True)

        # Find firmware files (bin, hex, elf)
        for pattern in ['*.bin', '*.hex', '*.elf']:
            for file_path in build_dir.rglob(pattern):
                rel_path = str(file_path.relative_to(build_dir))
                src_path = build_dir / rel_path
                dst_path = firmware_dir / rel_path

                dst_dir = Path(os.path.dirname(dst_path))
                dst_dir.mkdir(parents=True, exist_ok=True)

                shutil.copy2(src_path, dst_path)
                log.inf(f"Copied {rel_path}")

    def _copy_package_fw_module(self, output_dir):
        """Copy the zephyr-package-fw module to the package directory and generate resolved manifest."""
        # Find the zephyr-package-fw module directory
        module_path = Path(__file__).parent.parent  # Go up from scripts/ to zephyr-package-fw/

        if not module_path.exists():
            log.err("Could not find zephyr-package-fw module directory")
            return

        # Copy the entire module to the package
        dst_path = output_dir / "zephyr-package-fw"
        shutil.copytree(module_path, dst_path)
        log.inf("Copied zephyr-package-fw module to package")

        # Generate resolved manifest as zephyr-package-fw/west.yml
        resolved_manifest_path = dst_path / "west.yml"
        try:
            result = subprocess.run(['west', 'manifest', '--resolve', '-o', str(resolved_manifest_path)],
                                  capture_output=True, text=True, check=False)
            if result.returncode == 0:
                log.inf(f"Generated resolved manifest: {resolved_manifest_path}")
            else:
                log.err(f"Failed to generate resolved manifest: {result.stderr}")
                raise RuntimeError("Could not generate resolved manifest")
        except Exception as e:
            log.err(f"Failed to generate resolved manifest: {e}")
            raise

        shutil.move(dst_path / "scripts" / "rebuild.sh", output_dir)
        shutil.move(dst_path / "scripts" / "rebuild_fw.sh", output_dir)

    def _create_zip_archive(self, output_dir):
        """Create a zip archive of the firmware package."""
        zip_path = output_dir.with_suffix('.zip')

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in output_dir.rglob('*'):
                if file_path.is_file():
                    # Store with relative path from output_dir
                    arcname = file_path.relative_to(output_dir.parent)
                    zipf.write(file_path, arcname)

        return zip_path
