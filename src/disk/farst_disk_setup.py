import os
import subprocess
import common_disk_fn as cdf


from dataclasses import dataclass
from typing import Optional

from .btrfs_disk_setup import get_disk_info
from lib.print_fn import pr_error


@dataclass(frozen=True)
class PartitionPlan:
    disk: str
    boot_size: str = "1GiB"
    root_size: str = "100%"
    boot_filesystem: str = "fat32"
    root_filesystem: str = "btrfs"


def first_disk_setup(
    disk: str,
    *,
    boot_size: str = "1GiB",
    root_size: str = "100%",
    confirm: bool = False,
) -> Optional[PartitionPlan]:
    """Validate a disk and return its planned boot/root partition layout.

    Partition creation is intentionally not performed here. A caller must use
    the returned plan with a dedicated partitioning implementation and opt in
    to that destructive operation explicitly.
    """
    disk_info = get_disk_info(disk)
    if disk_info is None:
        pr_error(f"Disk not found: {disk}", "first_disk_setup")
        return None

    if disk_info.type != "disk":
        pr_error(f"Target is not a whole disk: {disk}", "first_disk_setup")
        return None

    if not boot_size or not root_size:
        pr_error("boot_size and root_size are required", "first_disk_setup")
        return None

    if confirm:
        pr_error(
            "Partition creation is not implemented; no changes were made",
            "first_disk_setup",
        )
        return None

    return PartitionPlan(
        disk=f"/dev/{disk_info.name}",
        boot_size=boot_size,
        root_size=root_size,
    )
    gen_fstab()