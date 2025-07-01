#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""West extension command for packaging firmware."""

import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from datetime import datetime
from west.commands import WestCommand
from west import log

try:
    from jinja2 import Template
except ImportError:
    log.err("jinja2 is required for template rendering. Install with: pip install jinja2")
    raise


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
        parser.add_argument('-n', '--name',
                          help='Package name (defaults to application name)')
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
        # Extract metadata first to get app name and board for output directory
        metadata = self._extract_metadata(build_dir, args.name)

        # Determine output directory
        if args.output_dir:
            output_dir = Path(args.output_dir).resolve()
        else:
            app_name = metadata["package_info"]["name"] or "unknown"
            board = metadata["cmake_info"].get("BOARD", {}).get("value", "unknown")
            output_dir = Path(f"{app_name}-{board}").resolve()

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        # Package firmware files
        self._package_firmware_files(build_dir, output_dir, metadata)
        # Copy zephyr-package-fw module and generate resolved manifest
        self._copy_package_fw_module(output_dir)
        # Update metadata with resolved manifest info
        metadata["git_info"]["resolved_manifest_file"] = "zephyr-package-fw/west.yml"
        # Write metadata files
        self._write_metadata(output_dir, metadata)
        # Create zip archive if requested
        if args.zip:
            zip_path = self._create_zip_archive(output_dir)
            log.inf(f"Firmware packaged successfully in {output_dir}")
            log.inf(f"Zip archive created: {zip_path}")
        else:
            log.inf(f"Firmware packaged successfully in {output_dir}")

        return 0
    def _extract_metadata(self, build_dir, package_name=None):
        """Extract all metadata needed to rebuild the firmware."""
        metadata = {
            "package_info": {
                "name": package_name,
                "created_at": datetime.now().isoformat(),
                "packager_version": "1.0.0"
            },
            "build_info": {},
            "git_info": {},
            "cmake_info": {},
            "west_info": {}
        }

        # Extract CMake cache information
        cmake_cache = build_dir / "CMakeCache.txt"
        if cmake_cache.exists():
            metadata["cmake_info"] = self._parse_cmake_cache(cmake_cache)
            if not package_name:
                # Try CMAKE_PROJECT_NAME first, fallback to APPLICATION_NAME
                package_name = self._get_app_name_from_cmake(metadata["cmake_info"])

        metadata["package_info"]["name"] = package_name or "unknown"

        # Extract git information using west manifest --resolve
        metadata["git_info"] = self._extract_git_info()

        # Extract west manifest information
        metadata["west_info"] = self._extract_west_info()

        # Extract build information
        metadata["build_info"] = self._extract_build_info(build_dir)
        return metadata

    def _parse_cmake_cache(self, cmake_cache_path):
        """Parse CMakeCache.txt to extract build configuration."""
        cmake_info = {}

        with open(cmake_cache_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key_type, value = line.split('=', 1)
                    if ':' in key_type:
                        key, var_type = key_type.split(':', 1)
                    else:
                        key, var_type = key_type, 'STRING'

                    # Store important build variables
                    important_vars = ['CMAKE_BUILD_TYPE', 'BOARD', 'APPLICATION_NAME',
                                    'CMAKE_PROJECT_NAME', 'ZEPHYR_BASE', 'BOARD_DIR',
                                    'APPLICATION_SOURCE_DIR', 'CMAKE_C_COMPILER',
                                    'CMAKE_CXX_COMPILER', 'ZEPHYR_TOOLCHAIN_VARIANT',
                                    'CONF_FILE', 'DTC_OVERLAY_FILE']
                    if key in important_vars:
                        cmake_info[key] = {'value': value, 'type': var_type}

        return cmake_info

    def _get_app_name_from_cmake(self, cmake_info):
        """Extract application name from CMake info, trying multiple sources."""
        return (cmake_info.get("CMAKE_PROJECT_NAME", {}).get("value") or
                cmake_info.get("APPLICATION_NAME", {}).get("value"))

    def _extract_git_info(self):
        """Extract git commit information using west manifest --resolve."""
        git_info = {}

        try:
            result = subprocess.run(['west', 'topdir'], capture_output=True, text=True, check=True)
            workspace_root = Path(result.stdout.strip())
            zephyr_path = workspace_root / 'zephyr'
            if zephyr_path.is_dir():
                commit_result = subprocess.run(['git', 'rev-parse', 'HEAD'],
                                             cwd=zephyr_path, capture_output=True, text=True, check=True)
                git_info["zephyr_commit"] = commit_result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            log.wrn(f"Failed to extract git info: {e}")

        return git_info

    def _extract_west_info(self):
        """Extract west manifest and configuration information."""
        west_info = {}

        try:
            # Get west configuration
            result = subprocess.run(['west', 'config', '-l'], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                config = {}
                for line in result.stdout.strip().split('\n'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        config[key] = value
                west_info["config"] = config

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            log.wrn(f"Failed to extract west info: {e}")

        return west_info

    def _extract_build_info(self, build_dir):
        """Extract build-specific information."""
        build_info = {
            "build_dir": str(build_dir),
            "firmware_files": []
        }

        # Find firmware files (bin, hex, elf)
        for pattern in ['*.bin', '*.hex', '*.elf']:
            for file_path in build_dir.rglob(pattern):
                build_info["firmware_files"].append({
                    "name": file_path.name,
                    "path": str(file_path.relative_to(build_dir)),
                    "size": file_path.stat().st_size
                })

        return build_info

    def _package_firmware_files(self, build_dir, output_dir, metadata):
        """Copy firmware files to the package directory."""
        firmware_dir = output_dir / "firmware"
        firmware_dir.mkdir(exist_ok=True)

        # Copy firmware files
        for fw_file in metadata["build_info"]["firmware_files"]:
            src_path = build_dir / fw_file["path"]
            dst_path = firmware_dir / fw_file["name"]
            if src_path.exists():
                shutil.copy2(src_path, dst_path)
                log.inf(f"Copied {fw_file['name']}")

    def _copy_package_fw_module(self, output_dir):
        """Copy the zephyr-package-fw module to the package directory and generate resolved manifest."""
        # Find the zephyr-package-fw module directory
        module_path = Path(__file__).parent.parent  # Go up from scripts/ to zephyr-package-fw/

        if not module_path.exists():
            log.err("Could not find zephyr-package-fw module directory")
            return

        # Copy the entire module to the package
        dst_path = output_dir / "zephyr-package-fw"
        if dst_path.exists():
            shutil.rmtree(dst_path)

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

    def _write_metadata(self, output_dir, metadata):
        """Write metadata files to the package directory."""
        # Write main metadata file
        metadata_file = output_dir / "metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)

        # Write rebuild script
        rebuild_script = output_dir / "rebuild.sh"
        self._write_rebuild_script(rebuild_script, metadata)
        rebuild_script.chmod(0o755)


        # Write rebuild firmware script
        rebuild_fw_script = output_dir / "rebuild_fw.sh"
        self._write_rebuild_fw_script(rebuild_fw_script, metadata)
        rebuild_fw_script.chmod(0o755)

        log.inf("Metadata files written")

    def _get_relative_app_dir(self, cmake_info):
        """Get application source directory relative to the west workspace root."""
        app_dir = cmake_info.get("APPLICATION_SOURCE_DIR", {}).get("value")
        if not app_dir:
            return ""

        try:
            result = subprocess.run(['west', 'topdir'], capture_output=True, text=True, check=False)
            workspace_root = Path(result.stdout.strip())
            app_path = Path(app_dir)
            if app_path.is_absolute() and app_path.is_relative_to(workspace_root):
                return str(app_path.relative_to(workspace_root))
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            log.wrn(f"Could not determine relative path for {app_dir}: {e}. Using absolute path as fallback.")

        return app_dir

    def _write_rebuild_script(self, script_path, metadata):
        """Generate a shell script to rebuild the firmware using Docker from Jinja2 template."""
        # Read template file
        template_path = Path(__file__).parent / "rebuild.sh.template"
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()

        # Prepare template variables
        git_info = metadata.get("git_info", {})
        cmake_info = metadata.get("cmake_info", {})

        # Convert absolute app_dir to relative path from workspace root
        relative_app_dir = self._get_relative_app_dir(cmake_info)

        # Prepare template context
        template_vars = {
            "created_at": metadata['package_info']['created_at'],
            "package_name": metadata['package_info']['name'],
            "zephyr_commit": git_info.get("zephyr_commit", ""),
            "board": cmake_info.get("BOARD", {}).get("value", ""),
            "app_dir": relative_app_dir
        }

        # Render template
        template = Template(template_content)
        script_content = template.render(**template_vars)

        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)

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



    def _write_rebuild_fw_script(self, script_path, metadata):
        """Generate firmware rebuild script from Jinja2 template."""
        # Read template file
        template_path = Path(__file__).parent / "rebuild_fw.sh.template"
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()

        # Prepare template variables
        git_info = metadata.get("git_info", {})
        cmake_info = metadata.get("cmake_info", {})

        # Convert absolute app_dir to relative path from workspace root
        relative_app_dir = self._get_relative_app_dir(cmake_info)

        # Prepare template context
        template_vars = {
            "created_at": metadata['package_info']['created_at'],
            "package_name": metadata['package_info']['name'],
            "zephyr_commit": git_info.get("zephyr_commit", ""),
            "board": cmake_info.get("BOARD", {}).get("value", ""),
            "app_dir": relative_app_dir,
            "has_resolved_manifest": bool(git_info.get("resolved_manifest_file"))
        }

        # Render template
        template = Template(template_content)
        script_content = template.render(**template_vars)

        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
