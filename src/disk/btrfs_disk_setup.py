import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from lib.print_fn import pr_error
from . import common_disk_fn as cdf

@dataclass
class DiskInfo:
    name: str
    size: str
    type: str
    mountpoint: Optional[str]
    uuid: Optional[str]


def get_disk_size(disk: str) -> Optional[str]:
    disk_info = get_disk_info(disk)
    return disk_info.size if disk_info else None


def _read_disk_info(disk: Optional[str] = None) -> list[DiskInfo]:
    command = ["lsblk", "-b", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINTS,UUID"]
    if disk:
        command.append(disk)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True
        )
        payload = json.loads(result.stdout)
        devices = payload.get("blockdevices", [])
        return [
            DiskInfo(
                name=device["name"],
                size=str(device["size"]),
                type=device["type"],
                mountpoint=next(iter(device.get("mountpoints") or []), None),
                uuid=device.get("uuid"),
            )
            for device in devices
            if device.get("name") and device.get("size") is not None
        ]
    except subprocess.CalledProcessError as e:
        pr_error(f"Failed to inspect disks: {e}", "get_disk_info")
    except (OSError, ValueError, KeyError) as e:
        pr_error(f"Invalid disk information: {e}", "get_disk_info")
    return []

def get_disk_info(disk: str) -> Optional[DiskInfo]:
    devices = _read_disk_info(disk)
    return devices[0] if devices else None


def get_all_disks() -> list[DiskInfo]:
    return _read_disk_info()


def btrfs_disk_setup(
    disk: str,
    *,
    label: Optional[str] = None,
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Format one unmounted block device as Btrfs."""
    if dry_run:
        from lib.print_fn import pr_info
        pr_info(f"Dry run: would format {disk} as Btrfs", "btrfs_disk_setup")
        return True

    disk_info = get_disk_info(disk)
    if disk_info is None:
        pr_error(f"Disk not found: {disk}", "btrfs_disk_setup")
        return False

    target = disk if disk.startswith("/dev/") else f"/dev/{disk_info.name}"
    return cdf.formart_target(
        target,
        filesystem="btrfs",
        label=label,
        confirm=confirm,
        timeout=timeout,
        dry_run=dry_run,
    )


def _run(command: list[str], function_name: str, timeout: int = 300, dry_run: bool = False) -> bool:
    if dry_run:
        from lib.print_fn import pr_info
        pr_info(f"Dry run: would execute {command[0]}", function_name)
        return True
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        pr_error(f"{function_name} failed: {error}", function_name)
        return False

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        pr_error(f"{function_name} failed: {message}", function_name)
        return False
    return True


def crypt_setup(
    disk: str,
    password: str,
    name: str,
    *,
    crypt_type: str = "luks2",
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Create and open a LUKS mapping using the shared safety checks."""
    return cdf.crypt_disk(
        disk_target=disk,
        crypt_password=password,
        crypt_name=name,
        crypt_type=crypt_type,
        confirm=confirm,
        timeout=timeout,
        dry_run=dry_run,
    )


def pv_create(device: str, *, confirm: bool = False, timeout: int = 300, dry_run: bool = False) -> bool:
    """Create an LVM physical volume on an explicit device."""
    if dry_run:
        from lib.print_fn import pr_info
        pr_info(f"Dry run: would create PV on {device}", "pv_create")
        return True
    if not confirm:
        pr_error("pvcreate requires confirm=True", "pv_create")
        return False
    if shutil.which("pvcreate") is None:
        pr_error("pvcreate is not installed", "pv_create")
        return False
    return _run(["pvcreate", "--yes", device], "pv_create", timeout)


def vg_create(
    vg_name: str,
    device: str,
    *,
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Create a volume group from one physical volume."""
    if dry_run:
        from lib.print_fn import pr_info
        pr_info(f"Dry run: would create VG {vg_name} on {device}", "vg_create")
        return True
    if not confirm:
        pr_error("vgcreate requires confirm=True", "vg_create")
        return False
    if not vg_name or not device:
        pr_error("vg_name and device are required", "vg_create")
        return False
    if shutil.which("vgcreate") is None:
        pr_error("vgcreate is not installed", "vg_create")
        return False
    return _run(["vgcreate", vg_name, device], "vg_create", timeout)


def lv_create(
    vg_name: str,
    lv_name: str,
    size: str,
    *,
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Create one logical volume in an existing volume group."""
    if dry_run:
        from lib.print_fn import pr_info
        pr_info(f"Dry run: would create LV {lv_name} ({size})", "lv_create")
        return True
    if not confirm:
        pr_error("lvcreate requires confirm=True", "lv_create")
        return False
    if not vg_name or not lv_name or not size:
        pr_error("vg_name, lv_name, and size are required", "lv_create")
        return False
    if shutil.which("lvcreate") is None:
        pr_error("lvcreate is not installed", "lv_create")
        return False
    return _run(
        ["lvcreate", "--yes", "--name", lv_name, "--size", size, vg_name],
        "lv_create",
        timeout,
    )


def generate_fstab(
    entries: list[dict[str, str]],
    output_path: str = "/etc/fstab",
    *,
    confirm: bool = False,
    dry_run: bool = False,
) -> bool:
    """Write validated fstab entries; never overwrites without confirmation."""
    if dry_run:
        from lib.print_fn import pr_info
        pr_info(f"Dry run: would write {len(entries)} fstab entries to {output_path}", "generate_fstab")
        return True
    if not confirm:
        pr_error("Writing fstab requires confirm=True", "generate_fstab")
        return False
    if not entries:
        pr_error("At least one fstab entry is required", "generate_fstab")
        return False


    lines = []
    for entry in entries:
        required = ("source", "mountpoint", "filesystem", "options")
        if any(not entry.get(field) for field in required):
            pr_error("Each fstab entry needs source, mountpoint, filesystem, and options", "generate_fstab")
            return False
        lines.append(
            f"{entry['source']} {entry['mountpoint']} "
            f"{entry['filesystem']} {entry['options']} "
            f"{entry.get('dump', '0')} {entry.get('pass', '2')}"
        )

    try:
        with open(output_path, "w", encoding="utf-8") as fstab_file:
            fstab_file.write("\n".join(lines) + "\n")
    except OSError as error:
        pr_error(f"Could not write {output_path}: {error}", "generate_fstab")
        return False
    return True