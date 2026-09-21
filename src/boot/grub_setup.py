import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Optional

from lib.print_fn import pr_error, pr_info


SUPPORTED_MODES = {"bios", "uefi"}


def detect_boot_mode() -> str:
    """Detect system boot mode (UEFI or BIOS)."""
    if Path("/sys/firmware/efi").is_dir():
        return "uefi"
    return "bios"


def find_efi_partition() -> str | None:
    """Find existing EFI system partition."""
    try:
        result = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS"],
            capture_output=True,
            text=True,
            check=True
        )
        import json
        devices = json.loads(result.stdout).get("blockdevices", [])
        
        for device in devices:
            if device.get("type") == "part":
                fstype = device.get("fstype", "")
                if fstype in ["vfat", "fat32", "fat16"]:
                    mountpoint = device.get("mountpoints", [None])[0]
                    if mountpoint and "efi" in mountpoint.lower():
                        return device.get("name")
        return None
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
        return None


def _run(command: list[str], function_name: str, timeout: int, dry_run: bool = False) -> bool:
    if dry_run:
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
        pr_error(f"Command failed: {error}", function_name)
        return False

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        pr_error(f"Command failed: {message}", function_name)
        return False
    return True


def _validate_device(device: str) -> bool:
    try:
        return stat.S_ISBLK(os.stat(device).st_mode)
    except OSError:
        return False


def get_device_uuid(device: str) -> Optional[str]:
    """Get UUID of a block device for kernel parameters."""
    try:
        result = subprocess.run(
            ["blkid", "-s", "UUID", "-o", "value", device],
            capture_output=True,
            text=True,
            check=True
        )
        uuid = result.stdout.strip()
        return uuid if uuid else None
    except (subprocess.CalledProcessError, OSError):
        return None


def configure_grub_kernel_params(
    target_root: str,
    crypt_device: Optional[str] = None,
    crypt_mapper: Optional[str] = None,
    *,
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Configure GRUB kernel parameters for encrypted boot."""
    function_name = "configure_grub_kernel_params"
    
    if not target_root or not os.path.isdir(target_root):
        pr_error(f"Target root does not exist: {target_root}", function_name)
        return False
    
    if dry_run:
        if crypt_device and crypt_mapper:
            pr_info(f"Dry run: would configure GRUB for encrypted boot with {crypt_device}", function_name)
        else:
            pr_info(f"Dry run: would configure GRUB kernel parameters", function_name)
        return True
    
    if not confirm:
        pr_error("GRUB kernel parameter configuration requires confirm=True", function_name)
        return False
    
    if os.geteuid() != 0:
        pr_error("GRUB kernel parameter configuration requires root privileges", function_name)
        return False
    
    grub_default_path = os.path.join(target_root, "etc", "default", "grub")
    
    try:
        # Read existing GRUB defaults
        if os.path.exists(grub_default_path):
            with open(grub_default_path, "r") as f:
                content = f.read()
        else:
            content = ""
        
        # Add or update GRUB_CMDLINE_LINUX_DEFAULT for encrypted boot
        if crypt_device and crypt_mapper:
            uuid = get_device_uuid(crypt_device)
            if uuid:
                crypt_param = f"cryptdevice=UUID={uuid}:{crypt_mapper}"
                root_param = "root=/dev/mapper/" + crypt_mapper
                
                # Update or add GRUB_CMDLINE_LINUX_DEFAULT
                lines = content.split("\n")
                cmdline_updated = False
                
                for i, line in enumerate(lines):
                    if line.strip().startswith("GRUB_CMDLINE_LINUX_DEFAULT="):
                        # Append encrypted boot parameters if not already present
                        if crypt_param not in line:
                            existing_params = line.split("=", 1)[1].strip('"\'')
                            new_params = f"{existing_params} {crypt_param} {root_param}"
                            lines[i] = f'GRUB_CMDLINE_LINUX_DEFAULT="{new_params}"'
                        cmdline_updated = True
                        break
                
                if not cmdline_updated:
                    cmdline_line = f'GRUB_CMDLINE_LINUX_DEFAULT="{crypt_param} {root_param}"'
                    lines.append(cmdline_line)
                
                content = "\n".join(lines)
                
                # Write updated configuration
                os.makedirs(os.path.dirname(grub_default_path), exist_ok=True)
                with open(grub_default_path, "w") as f:
                    f.write(content)
                
                pr_info(f"GRUB configured for encrypted boot: {crypt_param}", function_name)
            else:
                pr_error(f"Could not get UUID for device: {crypt_device}", function_name)
                return False
        else:
            pr_info("No encrypted boot parameters configured (plain setup)", function_name)
        
        return True
        
    except OSError as error:
        pr_error(f"Failed to configure GRUB parameters: {error}", function_name)
        return False


def install_grub(
    root_mount: str,
    *,
    boot_mode: str | None = None,
    boot_device: str | None = None,
    efi_directory: str | None = None,
    bootloader_id: str = "GRUB",
    crypt_device: str | None = None,
    crypt_mapper: str | None = None,
    configure_encrypted_boot: bool = False,
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Install and generate GRUB configuration for an Arch target system.

    ``root_mount`` must contain the target Arch filesystem. For UEFI, the EFI
    system partition must already be mounted below ``efi_directory``. This
    function does not mount partitions or run a shell/chroot command.
    """
    function_name = "install_grub"
    
    # Auto-detect boot mode if not specified
    if boot_mode is None:
        boot_mode = detect_boot_mode()
    
    mode = boot_mode.lower().strip()
    if mode not in SUPPORTED_MODES:
        pr_error("boot_mode must be 'uefi' or 'bios'", function_name)
        return False
    if not root_mount or not os.path.isdir(root_mount):
        pr_error(f"Root mount does not exist: {root_mount}", function_name)
        return False
    if not bootloader_id or "/" in bootloader_id:
        pr_error("bootloader_id is invalid", function_name)
        return False
    if dry_run:
        pr_info(f"Dry run: would install GRUB in {root_mount} ({mode})", function_name)
        return True
    if not confirm:
        pr_error("GRUB installation requires confirm=True", function_name)
        return False
    if os.geteuid() != 0:
        pr_error("GRUB installation requires root privileges", function_name)
        return False

    # Configure encrypted boot parameters if requested
    if configure_encrypted_boot and crypt_device and crypt_mapper:
        if not configure_grub_kernel_params(
            root_mount,
            crypt_device,
            crypt_mapper,
            confirm=confirm,
            timeout=timeout,
            dry_run=dry_run,
        ):
            return False

    grub_install = shutil.which("grub-install")
    grub_mkconfig = shutil.which("grub-mkconfig")
    if grub_install is None or grub_mkconfig is None:
        pr_error("grub-install and grub-mkconfig are required", function_name)
        return False

    if mode == "bios":
        if not boot_device or not _validate_device(boot_device):
            pr_error("A valid whole-disk boot_device is required for BIOS", function_name)
            return False
        install_command = [
            grub_install,
            "--target=i386-pc",
            f"--boot-directory={os.path.join(root_mount, 'boot')}",
            "--recheck",
            boot_device,
        ]
    else:
        efi_directory = efi_directory or os.path.join(root_mount, "boot")
        if not os.path.isdir(efi_directory):
            pr_error(f"EFI directory does not exist: {efi_directory}", function_name)
            return False
        install_command = [
            grub_install,
            "--target=x86_64-efi",
            f"--efi-directory={efi_directory}",
            f"--bootloader-id={bootloader_id}",
            "--recheck",
        ]

    if not _run(install_command, function_name, timeout, dry_run):
        return False

    config_path = os.path.join(root_mount, "boot", "grub", "grub.cfg")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    return _run(
        [grub_mkconfig, f"--output={config_path}"],
        function_name,
        timeout,
        dry_run,
    )