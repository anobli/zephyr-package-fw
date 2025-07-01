import argparse
import sys
from pathlib import Path
import yaml

# Get the west workspace root
from west.util import west_topdir
workspace_root = Path(west_topdir())
zephyr_west_scripts = workspace_root / "zephyr" / "scripts" / "west_commands"

sys.path.insert(0, str(zephyr_west_scripts))

from build import Build
from west.app.main import WestArgumentParser
from west import log
from git import Repo

class WestBuildParser:
    def __init__(self):
        self.build_command = Build()
        self.parser = None
        self._setup_parser()
    
    def _setup_parser(self):
        """Setup argument parser using west's existing infrastructure"""
        # Create the main parser
        main_parser = WestArgumentParser(
            prog='west',
            description='West build command parser'
        )
        
        # Add subparsers
        subparsers = main_parser.add_subparsers(dest='command')
        
        # Add the build command parser
        self.parser = self.build_command.add_parser(subparsers)
    
    def parse_build_args(self, args):
        """
        Parse west build arguments using the actual Build class logic
        
        Args:
            args: List of command line arguments (without 'west build')
        
        Returns:
            dict: Parsed arguments with extracted data
        """

        # Step 1: Parse known arguments and get remainder (unrecognized arguments)
        parsed_args, remainder = self.parser.parse_known_args(args)
        
        # Step 2: Create a mock args object for the Build class to use
        self.build_command.args = argparse.Namespace()
        
        # Step 3: Use the Build class's _parse_remainder method to handle the remainder
        # This processes source_dir and cmake_opts from the unrecognized arguments
        self.build_command._parse_remainder(remainder)

    def extract_from_command_line(self, full_command):
        """
        Extract build info from a full west build command line
        
        Args:
            full_command: String like "west build -b nrf52840dk_nrf52840 samples/hello_world -- -DCONFIG_FOO=y"
        
        Returns:
            dict: Extracted build information
        """
        import shlex
        
        # Use shlex to properly split the command line
        parts = shlex.split(full_command)
        if len(parts) >= 2 and parts[0] == 'west' and parts[1] == 'build':
            build_args = parts[2:]
            return self.parse_build_args(build_args)
        else:
            raise ValueError("Command doesn't start with 'west build'")

class BuildInfo:
    """
    Extract builf info using first build_info.yml and complete with CMakeCache.txt if needed 
    """
    def __init__(self, build_dir):
        self.west_command = None
        self.sysbuild = False
        self.source_dir = None
        self.application_name = None
        self.topdir = None
        self.version = None
        self.board = None
        self._extract_build_info(build_dir)
        if not self.sysbuild:
            self._parse_cmake_cache(build_dir)
        else:
            self._extract_zephyr_revision()

    def _extract_build_info(self, build_dir):
        build_info_yaml = build_dir / "build_info.yml"
        if not build_info_yaml.exists():
            log.err(f"build_info.yml not found in {build_dir}")
            raise RuntimeError(f"build_info.yml not found in {build_dir}")

        try:
            with open(build_info_yaml, 'r', encoding='utf-8') as f:
                build_data = yaml.safe_load(f)

                # Extract the complete west build command
                west_command = build_data['west']['command']

                # Remove west path to just keep the west command itself
                self.west_command = west_command.replace(west_command.split()[0], "west")

                # Determine if we are using sysbuild
                self.sysbuild = build_data.get('cmake', {}).get('sysbuild', {}) == "true"

                # Find the application source dir and the application name if we use sysbuild
                if self.sysbuild:
                    for image in build_data['cmake']['images']:
                        # TODO: manage if we don't find main image
                        if image.get('type', '') == "MAIN":
                            self.source_dir = Path(image['source-dir'])
                            self.application_name = image['name']
                else:
                    self.source_dir = Path(build_data['cmake']['application']['source-dir'])

                    # Get zephyr version
                    self.version = build_data['cmake']['zephyr']['version']

                # Get west topdir
                self.topdir = Path(build_data['west']['topdir'])

                # Get board name
                self.board = build_data['cmake']['board']['name']

        except Exception as e:
            log.err(f"Failed to parse build_info.yml: {e}")
            raise RuntimeError(f"Failed to parse build_info.yml: {e}")

    def _parse_cmake_cache(self, build_dir):
        """Parse CMakeCache.txt to extract build configuration."""

        # Extract CMake cache information
        cmake_cache = build_dir / "CMakeCache.txt"
        if not cmake_cache.exists():
            log.err("Failed to found CMakeCache.txt, check your build directory")
            raise Exception()

        with open(cmake_cache, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key_type, value = line.split('=', 1)
                    if ':' in key_type:
                        key = key_type.split(':', 1)[0]
                    else:
                        key = key_type

                    if key == "CMAKE_PROJECT_NAME":
                        self.application_name = value

    def _extract_zephyr_revision(self):
        # TODO: get zephyr path from manifest
        repo = Repo(self.topdir / "zephyr")
        self.version = repo.commit("HEAD")
