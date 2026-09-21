import os
import pwd
import shutil
import subprocess
from pathlib import Path

from lib.print_fn import pr_error, pr_info
from src.pkgs.must_have_pkgs import PACKAGE_NAME


AUR_HELPERS = {
    "paru": "https://aur.archlinux.org/paru.git",
    "yay": "https://aur.archlinux.org/yay.git",
}


def _build_user(user: str | None) -> tuple[str, int, str] | None:
    username = user or pwd.getpwuid(os.getuid()).pw_name
    try:
        account = pwd.getpwnam(username)
    except KeyError:
        pr_error(f"Build user does not exist: {username}", "aur_setup")
        return None
    if account.pw_uid == 0:
        pr_error("AUR packages must be built as a non-root user", "aur_setup")
        return None
    return username, account.pw_uid, account.pw_dir


def _run_as_user(
    command: list[str],
    username: str,
    *,
    cwd: str | None = None,
    timeout: int = 900,
) -> bool:
    if os.geteuid() == 0:
        run_command = ["runuser", "-u", username, "--", *command]
    else:
        run_command = command
    try:
        result = subprocess.run(
            run_command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        pr_error(f"AUR command failed: {error}", "aur_setup")
        return False
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        pr_error(f"AUR command failed: {message}", "aur_setup")
        return False
    return True


def setup_aur_helper(
    helper: str = "paru",
    *,
    build_user: str | None = None,
    build_directory: str | None = None,
    confirm: bool = False,
    timeout: int = 900,
    dry_run: bool = False,
) -> bool:
    """Build and install paru or yay as a non-root user."""
    helper_name = helper.lower().strip()
    repository = AUR_HELPERS.get(helper_name)
    if repository is None:
        pr_error("helper must be 'paru' or 'yay'", "aur_setup")
        return False
    if dry_run:
        pr_info(f"Dry run: would build and install AUR helper '{helper_name}'", "aur_setup")
        return True
    if not confirm:
        pr_error("AUR setup requires confirm=True", "aur_setup")
        return False
    if shutil.which("git") is None:
        pr_error("git is required for AUR setup", "aur_setup")
        return False
    if shutil.which("makepkg") is None:
        pr_error("makepkg is required for AUR setup", "aur_setup")
        return False
    if os.geteuid() != 0 and shutil.which("sudo") is None:
        pr_error("sudo is required to install an AUR helper", "aur_setup")
        return False

    account = _build_user(build_user)
    if account is None:
        return False
    username, user_id, home = account
    directory = Path(build_directory or Path(home) / f".{helper_name}-build").expanduser()
    if directory.exists() and any(directory.iterdir()):
        pr_error(f"Build directory is not empty: {directory}", "aur_setup")
        return False
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if os.geteuid() == 0:
            shutil.chown(directory, user=username, group=account[0])
    except OSError as error:
        pr_error(f"Could not prepare build directory: {error}", "aur_setup")
        return False

    if not _run_as_user(
        ["git", "clone", "--depth=1", repository, str(directory)],
        username,
        timeout=timeout,
    ):
        return False
    if not _run_as_user(
        ["makepkg", "--syncdeps", "--install", "--noconfirm"],
        username,
        cwd=str(directory),
        timeout=timeout,
    ):
        return False
    pr_info(f"Installed AUR helper: {helper_name}", "aur_setup")
    return True


def install_aur_packages(
    packages: list[str],
    *,
    helper: str = "paru",
    build_user: str | None = None,
    confirm: bool = False,
    timeout: int = 900,
    dry_run: bool = False,
) -> bool:
    """Install AUR packages through an existing paru or yay helper."""
    if not packages or any(not isinstance(package, str) or not PACKAGE_NAME.fullmatch(package) for package in packages):
        pr_error("AUR package names are invalid", "install_aur_packages")
        return False
    if dry_run:
        pr_info(f"Dry run: would install AUR packages: {', '.join(packages)}", "install_aur_packages")
        return True
    if helper not in AUR_HELPERS:
        pr_error("helper must be 'paru' or 'yay'", "install_aur_packages")
        return False
    if not confirm:
        pr_error("AUR package installation requires confirm=True", "install_aur_packages")
        return False

    account = _build_user(build_user)
    if account is None:
        return False
    username = account[0]
    helper_path = shutil.which(helper)
    if helper_path is None:
        pr_error(f"{helper} is not installed; run setup_aur_helper first", "install_aur_packages")
        return False
    return _run_as_user(
        [helper_path, "-S", "--needed", "--noconfirm", *packages],
        username,
        timeout=timeout,
    )


def aur_setup(
    packages: list[str] | None = None,
    *,
    helper: str = "paru",
    build_user: str | None = None,
    confirm: bool = False,
    timeout: int = 900,
    dry_run: bool = False,
) -> bool:
    """Install an AUR helper and optionally install AUR packages."""
    if not setup_aur_helper(
        helper,
        build_user=build_user,
        confirm=confirm,
        timeout=timeout,
        dry_run=dry_run,
    ):
        return False
    if packages:
        return install_aur_packages(
            packages,
            helper=helper,
            build_user=build_user,
            confirm=confirm,
            timeout=timeout,
            dry_run=dry_run,
        )
    return True