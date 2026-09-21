import getpass
import json
import os
import platform
import shutil
from pathlib import Path
from typing import Any, Optional


def collect_user_profile() -> dict[str, Any]:
    """Collect non-secret information about the current installer user."""
    home = str(Path.home())
    return {
        "name": getpass.getuser(),
        "home": home,
        "shell": os.environ.get("SHELL"),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP")
        or os.environ.get("XDG_SESSION_DESKTOP"),
        "session_type": os.environ.get("XDG_SESSION_TYPE"),
    }


def _memory_bytes() -> Optional[int]:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def collect_system_profile() -> dict[str, Any]:
    """Collect local hardware and operating-system facts without secrets."""
    root_usage = shutil.disk_usage("/")
    return {
        "hostname": platform.node(),
        "os": platform.system(),
        "distribution": platform.freedesktop_os_release().get("PRETTY_NAME", "")
        if hasattr(platform, "freedesktop_os_release")
        else "",
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "memory_bytes": _memory_bytes(),
        "root_disk": {
            "total_bytes": root_usage.total,
            "free_bytes": root_usage.free,
        },
        "boot_mode": "uefi"
        if Path("/sys/firmware/efi").is_dir()
        else "bios",
    }


def collect_profile() -> dict[str, Any]:
    """Return the user and system profile used by the installer."""
    return {
        "user": collect_user_profile(),
        "system": collect_system_profile(),
    }


def save_profile(output_path: str, *, confirm: bool = False, dry_run: bool = False) -> bool:
    """Save a profile as JSON after explicit confirmation."""
    if not confirm:
        return False
    if dry_run:
        return True
    try:
        with open(output_path, "w", encoding="utf-8") as profile_file:
            json.dump(collect_profile(), profile_file, indent=2)
            profile_file.write("\n")
    except OSError:
        return False
    return True