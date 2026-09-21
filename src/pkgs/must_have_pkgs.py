import os
import re
import shutil
import subprocess
import time

from lib.print_fn import pr_error, pr_info


PACKAGE_NAME = re.compile(r"^[A-Za-z0-9@._+:-]+$")


def _valid_packages(packages: list[str]) -> bool:
    if not packages:
        pr_error("At least one package is required", "install_packages")
        return False
    if any(
        not isinstance(package, str) or not PACKAGE_NAME.fullmatch(package)
        for package in packages
    ):
        pr_error("Package names contain invalid characters", "install_packages")
        return False
    return True


def install_packages(
    packages: list[str],
    *,
    confirm: bool = False,
    retries: int = 3,
    retry_delay: int = 5,
    timeout: int = 900,
    dry_run: bool = False,
) -> bool:
    """Install packages with pacman without deleting lock files."""
    if not _valid_packages(packages):
        return False
    if dry_run:
        pr_info(f"Dry run: would install packages: {', '.join(packages)}", "install_packages")
        return True
    if not isinstance(retries, int) or retries < 0:
        pr_error("retries must be a non-negative integer", "install_packages")
        return False
    if not confirm:
        pr_error("Package installation requires confirm=True", "install_packages")
        return False
    if os.geteuid() != 0:
        pr_error("Package installation requires root privileges", "install_packages")
        return False

    pacman = shutil.which("pacman")
    if pacman is None:
        pr_error("pacman is not installed", "install_packages")
        return False

    command = [pacman, "-S", "--needed", "--noconfirm", *packages]
    for attempt in range(retries + 1):
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            pr_error(f"Package installation failed: {error}", "install_packages")
            return False

        if result.returncode == 0:
            pr_info(f"Installed packages: {', '.join(packages)}", "install_packages")
            return True

        output = f"{result.stdout}\n{result.stderr}".lower()
        database_busy = "could not lock database" in output or "database is locked" in output
        if not database_busy or attempt == retries:
            message = result.stderr.strip() or result.stdout.strip() or "unknown error"
            pr_error(f"pacman failed: {message}", "install_packages")
            return False

        pr_info(
            f"pacman database is busy; retrying ({attempt + 1}/{retries})",
            "install_packages",
        )
        time.sleep(retry_delay)

    return False


def install_esential(
    packages: list[str],
    *,
    confirm: bool = False,
    retries: int = 3,
    retry_delay: int = 5,
    dry_run: bool = False,
) -> bool:
    """Backward-compatible spelling for the essential package installer."""
    return install_packages(
        packages,
        confirm=confirm,
        retries=retries,
        retry_delay=retry_delay,
        dry_run=dry_run,
    )


def dev_tools(
    *,
    confirm: bool = False,
    retries: int = 3,
    retry_delay: int = 5,
    dry_run: bool = False,
) -> bool:
    """Install the standard Arch build toolchain."""
    return install_packages(
        ["base-devel", "git", "vim"],
        confirm=confirm,
        retries=retries,
        retry_delay=retry_delay,
        dry_run=dry_run,
    )

