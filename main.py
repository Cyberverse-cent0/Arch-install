
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


# Operations that may modify the system.
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
    - Pass dry_run=True to functions that support it.
    - Skip destructive functions without dry-run support.
    - Allow non-destructive functions to execute.
    """

    if dry_run:
        if function_name in DESTRUCTIVE_FUNCTIONS:
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

        elif supports_dry_run(function):
            parameters = {
                **parameters,
                "dry_run": True,
            }

    return function(**parameters)


def run_config(
    config: dict[str, Any],
    cli_dry_run: bool | None = None,
) -> bool:
    """Run the operations defined in the configuration."""

    settings = config.get("settings", {})

    if not isinstance(settings, dict):
        raise ConfigError("'settings' must be an object")

    config_dry_run = settings.get("dry_run", True)

    if not isinstance(config_dry_run, bool):
        raise ConfigError("'settings.dry_run' must be true or false")

    # CLI option takes precedence over the configuration.
    dry_run = (
        cli_dry_run
        if cli_dry_run is not None
        else config_dry_run
    )

    application = config.get("application", {})

    if not isinstance(application, dict):
        raise ConfigError("'application' must be an object")

    require_root = application.get("require_root", True)

    if not isinstance(require_root, bool):
        raise ConfigError(
            "'application.require_root' must be true or false"
        )

    if dry_run:
        pr_info("Dry-run mode enabled.", "run_config")
    else:
        pr_info("Execution mode enabled.", "run_config")

    if require_root and not dry_run and not is_root():
        pr_error(
            "Please run destructive operations as root.",
            "run_config",
        )
        return False

    operations = config.get("operations", [])

    if not isinstance(operations, list):
        raise ConfigError("'operations' must be a list")

    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            pr_error(
                f"Operation {index} must be an object.",
                "run_config",
            )
            return False

        function_name = operation.get("function")

        if not isinstance(function_name, str):
            pr_error(
                f"Operation {index} has no valid function name.",
                "run_config",
            )
            return False

        function = FUNCTIONS.get(function_name)

        if function is None:
            pr_error(
                f"Unsupported function in operation {index}: "
                f"{function_name}",
                "run_config",
            )
            return False

        parameters = operation.get("parameters", {})

        if not isinstance(parameters, dict):
            pr_error(
                f"Parameters for '{function_name}' must be an object.",
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
            return False

        except Exception as error:
            pr_error(
                f"Operation '{function_name}' failed: {error}",
                "run_config",
            )
            return False

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
            return False

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

    parser.set_defaults(dry_run=None)

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    args = parser.parse_args()

    try:
        config = load_config(args.config)

        return (
            0
            if run_config(config, cli_dry_run=args.dry_run)
            else 1
        )

    except ConfigError as error:
        pr_error(str(error), "main")
        return 2

    except OSError as error:
        pr_error(
            f"Unable to access configuration: {error}",
            "main",
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())