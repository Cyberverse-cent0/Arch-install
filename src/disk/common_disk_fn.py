import subprocess
import os
import stat
import shutil
import re
from dataclasses import dataclass
from typing import Optional
from lib.print_fn import pr_dry, pr_error, pr_info, pr_warn



def formart_target(
    target: str,
    filesystem: str = "btrfs",
    *,
    confirm: bool = False,
    label: Optional[str] = None,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """
    Format a block device with a supported filesystem.

    Supported:
        btrfs, ext4, xfs, fat32

    Args:
        target: Block device, e.g. /dev/sdb1.
        filesystem: Filesystem to create.
        confirm: Must be True to permit destructive formatting.
        label: Optional filesystem label.
        timeout: Maximum formatting command duration in seconds.

    Returns:
        True if formatting succeeds, otherwise False.
    """

    supported_filesystems = {
        "btrfs": "mkfs.btrfs",
        "ext4": "mkfs.ext4",
        "xfs": "mkfs.xfs",
        "fat32": "mkfs.fat",
    }

    # 1. Validate filesystem
    filesystem = filesystem.lower().strip()

    if filesystem not in supported_filesystems:
        pr_error(
            f"Unsupported filesystem: {filesystem}",
            "formart_target",
        )
        return False

    # 2. Validate target
    if not target or not target.strip():
        pr_error("Target cannot be empty", "formart_target")
        return False

    target = os.path.realpath(target)

    if dry_run:
        pr_info(f"Dry run: would format {target} as {filesystem}", "formart_target")
        return True

    if not os.path.exists(target):
        pr_error(f"Target does not exist: {target}", "formart_target")
        return False

    # 3. Only allow block devices
    try:
        if not stat.S_ISBLK(os.stat(target).st_mode):
            pr_error(
                f"Target is not a block device: {target}",
                "formart_target",
            )
            return False
    except OSError as e:
        pr_error(f"Cannot inspect target: {e}", "formart_target")
        return False

    # 4. Require explicit confirmation
    if not confirm:
        pr_error(
            f"Formatting {target} requires confirm=True",
            "formart_target",
        )
        return False

    # 5. Require root privileges
    if os.geteuid() != 0:
        pr_error(
            "Formatting requires root privileges. "
            "Run this operation with sudo.",
            "formart_target",
        )
        return False

    # 6. Check required formatting utility
    mkfs_command = supported_filesystems[filesystem]
    mkfs_path = shutil.which(mkfs_command)

    if mkfs_path is None:
        pr_error(
            f"Required utility not installed: {mkfs_command}",
            "formart_target",
        )
        return False

    # 7. Inspect device and reject mounted targets
    try:
        result = subprocess.run(
            [
                "lsblk",
                "-J",
                "-o",
                "PATH,TYPE,MOUNTPOINTS",
                target,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )

        import json
        device_info = json.loads(result.stdout)

        devices = device_info.get("blockdevices", [])

        if not devices:
            pr_error(
                f"Could not identify block device: {target}",
                "formart_target",
            )
            return False

        def find_mounted(device):
            if device.get("mountpoints"):
                for mountpoint in device["mountpoints"]:
                    if mountpoint:
                        return mountpoint

            for child in device.get("children") or []:
                mounted = find_mounted(child)
                if mounted:
                    return mounted

            return None

        mounted_at = find_mounted(devices[0])

        if mounted_at:
            pr_error(
                f"Target is mounted at {mounted_at}. "
                "Unmount it before formatting.",
                "formart_target",
            )
            return False

    except subprocess.TimeoutExpired:
        pr_error("Timed out while inspecting device", "formart_target")
        return False

    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        pr_error(
            f"Failed to inspect block device: {e}",
            "formart_target",
        )
        return False

    # 8. Build filesystem-specific command
    command = [mkfs_path]

    if filesystem == "btrfs":
        command.append("-f")

    elif filesystem == "ext4":
        command.append("-F")

    elif filesystem == "xfs":
        command.append("-f")

    elif filesystem == "fat32":
        command.extend(["-F", "32"])

    # 9. Add optional label
    if label:
        if "\x00" in label:
            pr_error("Invalid label", "formart_target")
            return False

        if filesystem == "btrfs":
            command.extend(["-L", label])

        elif filesystem == "ext4":
            command.extend(["-L", label])

        elif filesystem == "xfs":
            command.extend(["-L", label])

        elif filesystem == "fat32":
            command.extend(["-n", label])

    command.append(target)

    # 10. Run formatting operation
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

        if result.returncode == 0:
            return True

        error_message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Unknown formatting error"
        )

        pr_error(
            f"Formatting failed for {target} "
            f"as {filesystem} "
            f"(exit code {result.returncode}): "
            f"{error_message}",
            "formart_target",
        )

        return False

    except subprocess.TimeoutExpired:
        pr_error(
            f"Formatting timed out after {timeout} seconds. "
            "The device may be partially formatted.",
            "formart_target",
        )
        return False

    except OSError as e:
        pr_error(
            f"Could not execute formatting utility: {e}",
            "formart_target",
        )
        return False



@dataclass
class CryptResult:
    success: bool
    formatted: bool = False
    opened: bool = False
    mapping_path: Optional[str] = None
    error: Optional[str] = None


def crypt_disk(
    disk_target: str,
    crypt_password: str,
    crypt_name: str,
    crypt_type: str = "luks2",
    *,
    confirm: bool = False,
    timeout: int = 300,
    allow_existing_luks: bool = False,
    dry_run: bool = False,
) -> bool:
    """
    Create a LUKS container and open it.

    WARNING:
        luksFormat destroys existing data on the target.

    Returns:
        True only if formatting and opening succeed.
    """

    # 1. Validate required parameters
    if not isinstance(disk_target, str) or not disk_target.strip():
        pr_error("disk_target is empty or invalid", "crypt_disk")
        return False

    if not isinstance(crypt_password, str) or not crypt_password:
        pr_error("crypt_password is empty or invalid", "crypt_disk")
        return False

    if not isinstance(crypt_name, str) or not crypt_name.strip():
        pr_error("crypt_name is empty or invalid", "crypt_disk")
        return False

    if dry_run:
        pr_info(f"Dry run: would encrypt and open {disk_target}", "crypt_disk")
        return True

    disk_target = disk_target.strip()
    crypt_name = crypt_name.strip()

    # 2. Validate encryption type
    crypt_type = crypt_type.lower().strip()

    if crypt_type not in ("luks1", "luks2"):
        pr_error(
            f"Unsupported LUKS type: {crypt_type}",
            "crypt_disk",
        )
        return False

    # 3. Validate mapping name
    if not re.fullmatch(r"[A-Za-z0-9_.+-]+", crypt_name):
        pr_error(
            "Invalid mapping name. Use letters, digits, _, ., +, or -.",
            "crypt_disk",
        )
        return False

    # 4. Require explicit destructive-operation authorization
    if not confirm:
        pr_error(
            "Encryption requires explicit confirmation: confirm=True",
            "crypt_disk",
        )
        return False

    # 5. Require root
    if os.geteuid() != 0:
        pr_error(
            "cryptsetup requires root privileges",
            "crypt_disk",
        )
        return False

    # 6. Find cryptsetup
    cryptsetup = shutil.which("cryptsetup")

    if cryptsetup is None:
        pr_error(
            "cryptsetup is not installed",
            "crypt_disk",
        )
        return False

    # 7. Validate target
    try:
        disk_target = os.path.realpath(disk_target)

        if not os.path.exists(disk_target):
            pr_error(
                f"Target does not exist: {disk_target}",
                "crypt_disk",
            )
            return False

        if not stat.S_ISBLK(os.stat(disk_target).st_mode):
            pr_error(
                f"Target is not a block device: {disk_target}",
                "crypt_disk",
            )
            return False

    except OSError as e:
        pr_error(
            f"Cannot inspect target: {e}",
            "crypt_disk",
        )
        return False

    # 8. Reject mounted targets
    try:
        result = subprocess.run(
            [
                "lsblk",
                "-J",
                "-o",
                "PATH,MOUNTPOINTS",
                disk_target,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )

        import json
        info = json.loads(result.stdout)

        def has_mount(device):
            if any(device.get("mountpoints") or []):
                return True

            return any(
                has_mount(child)
                for child in (device.get("children") or [])
            )

        devices = info.get("blockdevices", [])

        if not devices:
            pr_error("Unable to identify target device", "crypt_disk")
            return False

        if any(has_mount(device) for device in devices):
            pr_error(
                "Target or one of its child devices is mounted",
                "crypt_disk",
            )
            return False

    except subprocess.TimeoutExpired:
        pr_error("Timed out inspecting target", "crypt_disk")
        return False

    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        pr_error(f"Device inspection failed: {e}", "crypt_disk")
        return False

    # 9. Reject an already active mapping
    try:
        result = subprocess.run(
            [cryptsetup, "status", crypt_name],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode == 0:
            pr_error(
                f"Mapping already exists: {crypt_name}",
                "crypt_disk",
            )
            return False

    except (subprocess.TimeoutExpired, OSError) as e:
        pr_error(f"Mapping check failed: {e}", "crypt_disk")
        return False

    # 10. Check whether the target already contains LUKS
    try:
        result = subprocess.run(
            [cryptsetup, "isLuks", disk_target],
            capture_output=True,
            timeout=15,
        )

        if result.returncode == 0 and not allow_existing_luks:
            pr_error(
                "Target already contains a LUKS header. "
                "Refusing to overwrite it.",
                "crypt_disk",
            )
            return False

        if result.returncode not in (0, 1):
            pr_error(
                "Could not determine whether target contains LUKS",
                "crypt_disk",
            )
            return False

    except (subprocess.TimeoutExpired, OSError) as e:
        pr_error(f"LUKS detection failed: {e}", "crypt_disk")
        return False

    # Use bytes input: do not combine bytes with text=True.
    password = crypt_password.encode("utf-8") + b"\n"

    def run_cryptsetup(args):
        try:
            return subprocess.run(
                [cryptsetup, *args],
                input=password,
                capture_output=True,
                timeout=timeout,
                check=False,
            )

        except subprocess.TimeoutExpired:
            pr_error(
                f"cryptsetup timed out: {args[0]}",
                "crypt_disk",
            )
            return None

        except OSError as e:
            pr_error(
                f"Could not execute cryptsetup: {e}",
                "crypt_disk",
            )
            return None

    # 11. Format the target
    format_result = run_cryptsetup([
        "--batch-mode",
        "--type", crypt_type,
        "--key-file", "-",
        "luksFormat",
        disk_target,
    ])

    if format_result is None:
        return False

    if format_result.returncode != 0:
        error = (
            format_result.stderr.decode(
                "utf-8", errors="replace"
            ).strip()
            or "Unknown formatting error"
        )

        pr_error(
            f"LUKS formatting failed: {error}",
            "crypt_disk",
        )
        return False

    # 12. Open the newly created LUKS container
    open_result = run_cryptsetup([
        "--key-file", "-",
        "open",
        disk_target,
        crypt_name,
    ])

    if open_result is None:
        pr_error(
            "LUKS was formatted, but opening did not complete",
            "crypt_disk",
        )
        return False

    if open_result.returncode != 0:
        error = (
            open_result.stderr.decode(
                "utf-8", errors="replace"
            ).strip()
            or "Unknown opening error"
        )

        pr_error(
            "LUKS was formatted, but opening failed: "
            + error,
            "crypt_disk",
        )
        return False

    pr_info(
        f"Encrypted {disk_target} and opened as {crypt_name}",
        "crypt_disk",
    )

    return True





def mount(
    target: str,
    fs_type: str | None,
    mount_point: str,
    dry_run: bool = False,
) -> bool:

    # 1. Validate parameters
    if not target:
        pr_error("Disk partition is empty", "mount")
        return False

    if dry_run:
        pr_info(f"Dry run: would mount {target} at {mount_point}", "mount")
        return True

    if not os.path.exists(target):
        pr_error(f"Disk partition does not exist: {target}", "mount")
        return False

    if not mount_point:
        pr_error("Mount point is empty", "mount")
        return False


    if not os.path.isdir(mount_point):
        pr_error(
            f"Mount point does not exist: {mount_point}",
            "mount",
        )
        return False

    # 2. Build mount command
    command = ["mount"]

    if fs_type:
        command.extend(["-t", fs_type])

    command.extend([target, mount_point])

    try:
        # 3. Attempt mounting
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            pr_info(
                f"Mounted {target} at {mount_point}",
                "mount",
            )
            return True

        error = result.stderr.strip().lower()

        # 4. Handle filesystem errors
        if any(msg in error for msg in [
            "wrong fs type",
            "bad superblock",
            "unknown filesystem type",
        ]):
            pr_warn(
                "Filesystem type may be incorrect, "
                "or the filesystem may be damaged.",
                "mount",
            )

            # 5. Retry with automatic filesystem detection
            if fs_type:
                retry = subprocess.run(
                    ["mount", target, mount_point],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                if retry.returncode == 0:
                    pr_success(
                        "Mounted using automatic "
                        "filesystem detection",
                        "mount",
                    )
                    return True

                pr_error(
                    f"Automatic mount failed: "
                    f"{retry.stderr.strip()}",
                    "mount",
                )

                return False

        # 6. Handle unformatted or unrecognized filesystems
        if any(msg in error for msg in [
            "no such file or directory",
            "can't find",
        ]):
            pr_error(
                f"Target or mount point not found: {error}",
                "mount",
            )
            return False

        # 7. Handle other errors
        pr_error(
            f"Mount failed: {result.stderr.strip()}",
            "mount",
        )

        return False

    except FileNotFoundError:
        pr_error(
            "The mount command was not found",
            "mount",
        )
        return False

    except PermissionError:
        pr_error(
            "Permission denied. Try running with sudo.",
            "mount",
        )
        return False

    except OSError as e:
        pr_error(f"Operating system error: {e}", "mount")
        return False


def gen_fstab():
    pass