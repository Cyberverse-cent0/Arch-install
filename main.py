
import os
import sys
import argparse
import inspect
from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from config import ConfigError, load_config
from lib.print_fn import pr_dry, pr_error, pr_info

from src.disk.btrfs_disk_setup import (
    btrfs_disk_setup,
    crypt_setup,
    get_all_disks,
    get_disk_info,
    get_disk_size,
    generate_fstab,
    lv_create,
    pv_create,
    vg_create,
)

from src.disk.common_disk_fn import crypt_disk
from src.pkgs.must_have_pkgs import dev_tools, install_packages
from src.pkgs.desktop import install_desktop
from src.pkgs.aur_setup import (
    aur_setup,
    install_aur_packages,
    setup_aur_helper,
)
from src.boot.grub_setup import install_grub
from src.profile.system_profile import collect_profile, save_profile


VERSION = "1.0.2"


# Functions available to the JSON configuration.
FUNCTIONS: dict[str, Callable[..., Any]] = {
    "get_all_disks": get_all_disks,
    "get_disk_info": get_disk_info,
    "get_disk_size": get_disk_size,
    "btrfs_disk_setup": btrfs_disk_setup,
    "crypt_setup": crypt_setup,
    "pv_create": pv_create,
    "vg_create": vg_create,
    "lv_create": lv_create,
    "generate_fstab": generate_fstab,
    "crypt_disk": crypt_disk,
    "install_packages": install_packages,
    "dev_tools": dev_tools,
    "install_desktop": install_desktop,
    "aur_setup": aur_setup,
    "setup_aur_helper": setup_aur_helper,
    "install_aur_packages": install_aur_packages,
    "install_grub": install_grub,
    "collect_profile": collect_profile,
    "save_profile": save_profile,
}


# Read-only functions that don't modify the system.
READ_ONLY_FUNCTIONS = {
    "get_all_disks",
    "get_disk_info",
    "get_disk_size",
    "collect_profile",
}

# Destructive functions that modify the system.
DESTRUCTIVE_FUNCTIONS = {
    "btrfs_disk_setup",
    "crypt_setup",
    "pv_create",
    "vg_create",
    "lv_create",
    "generate_fstab",
    "crypt_disk",
    "install_packages",
    "dev_tools",
    "install_desktop",
    "aur_setup",
    "setup_aur_helper",
    "install_aur_packages",
    "install_grub",
    "save_profile",
}


def version() -> None:
    """Print the application version."""
    pr_info(f"Version {VERSION}", "version")


def help() -> None:
    """Print basic application information."""
    pr_info(
        """
Welcome to codecrafters custom Arch installer.

Use --config to specify a configuration file.
Use --dry-run to simulate supported operations.
Use --execute to override dry-run mode and execute operations.
        """,
        "help",
    )


def is_root() -> bool:
    """Return whether the current process is running as root."""
    return hasattr(os, "geteuid") and os.geteuid() == 0


def supports_dry_run(function: Callable[..., Any]) -> bool:
    """Check whether a function explicitly accepts dry_run."""
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return False

    return (
        "dry_run" in signature.parameters
        or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
    )


def execute_operation(
    function_name: str,
    function: Callable[..., Any],
    parameters: dict[str, Any],
    dry_run: bool,
) -> Any:
    """
    Execute one operation.

    In dry-run mode:
    - Read-only functions execute normally (safe to run)
    - Destructive functions with dry_run support get dry_run=True
    - Destructive functions without dry_run support are skipped
    """

    if dry_run:
        if function_name in READ_ONLY_FUNCTIONS:
            pr_info(
                f"Executing read-only function: '{function_name}'",
                "execute_operation",
            )
        elif function_name in DESTRUCTIVE_FUNCTIONS:
            if not supports_dry_run(function):
                pr_info(
                    f"Dry run: skipped '{function_name}'. "
                    "Function does not explicitly support dry_run.",
                    "execute_operation",
                )
                return None

            parameters = {
                **parameters,
                "dry_run": True,
            }

            pr_info(
                f"Dry run: simulating '{function_name}'",
                "execute_operation",
            )
        else:
            # Unknown function category, treat as destructive
            if supports_dry_run(function):
                parameters = {
                    **parameters,
                    "dry_run": True,
                }
                pr_info(
                    f"Dry run: simulating '{function_name}'",
                    "execute_operation",
                )
            else:
                pr_info(
                    f"Dry run: skipped '{function_name}'. "
                    "Function does not explicitly support dry_run.",
                    "execute_operation",
                )
                return None

    return function(**parameters)


def run_config(
    config: dict[str, Any],
    cli_dry_run: bool | None = None,
) -> bool:
    """Run the operations defined in the configuration."""

    settings = config.get("settings", {})
    config_dry_run = settings.get("dry_run", True)
    stop_on_error = settings.get("stop_on_error", True)

    # CLI option takes precedence over the configuration.
    dry_run = (
        cli_dry_run
        if cli_dry_run is not None
        else config_dry_run
    )

    application = config.get("application", {})
    require_root = application.get("require_root", True)

    operations = config.get("operations", [])

    if dry_run:
        pr_info("Dry-run mode enabled.", "run_config")
    else:
        pr_info("Execution mode enabled.", "run_config")

    pr_info(f"Stop on error: {stop_on_error}", "run_config")
    pr_info(f"Total operations to execute: {len(operations)}", "run_config")

    if require_root and not dry_run and not is_root():
        pr_error(
            "Please run destructive operations as root.",
            "run_config",
        )
        return False

    for index, operation in enumerate(operations):
        function_name = operation.get("function")
        parameters = operation.get("parameters", {})

        pr_info(f"Executing operation {index + 1}/{len(operations)}: {function_name}", "run_config")

        function = FUNCTIONS.get(function_name)

        if function is None:
            pr_error(
                f"Unsupported function in operation {index}: "
                f"{function_name}",
                "run_config",
            )
            return False

        try:
            result = execute_operation(
                function_name=function_name,
                function=function,
                parameters=parameters,
                dry_run=dry_run,
            )

        except TypeError as error:
            pr_error(
                f"Invalid parameters for '{function_name}': {error}",
                "run_config",
            )
            if stop_on_error:
                return False
            continue

        except Exception as error:
            pr_error(
                f"Operation '{function_name}' failed: {error}",
                "run_config",
            )
            if stop_on_error:
                return False
            continue

        if is_dataclass(result):
            result = asdict(result)

        if result is not None:
            pr_dry(
                f"{function_name}: {result}",
                "run_config",
            )

        if isinstance(result, bool) and not result:
            pr_error(
                f"Operation '{function_name}' returned False.",
                "run_config",
            )
            if stop_on_error:
                return False
            continue

    pr_info(
        "Configuration processing completed.",
        "run_config",
    )

    return True


def main() -> int:
    """Application entry point."""

    parser = argparse.ArgumentParser(
        description="JSON-driven Arch installer"
    )

    parser.add_argument(
        "--config",
        default="app.json",
        help="Path to the installer JSON configuration",
    )

    mode = parser.add_mutually_exclusive_group()

    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Simulate supported operations without executing "
             "destructive functions",
    )

    mode.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="Override configuration and execute operations",
    )

    parser.set_defaults(dry_run=None, version=False, help_installer=False)

    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version information",
    )

    parser.add_argument(
        "--help-installer",
        action="store_true",
        help="Show installer help information",
    )

    args = parser.parse_args()

    if args.version:
        version()
        return 0

    if args.help_installer:
        help()
        return 0

    try:
        config = load_config(args.config)
        pr_info(f"Configuration loaded from {args.config}", "main")

        return (
            0
            if run_config(config, cli_dry_run=args.dry_run)
            else 1
        )

    except ConfigError as error:
        pr_error(f"Configuration error: {error}", "main")
        return 2

    except OSError as error:
        pr_error(f"Unable to access configuration: {error}", "main")
        return 2

    except Exception as error:
        pr_error(f"Unexpected error: {error}", "main")
        return 3


if __name__ == "__main__":
    sys.exit(main())