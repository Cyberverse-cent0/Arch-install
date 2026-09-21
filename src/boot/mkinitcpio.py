import os
import shutil
import subprocess
from typing import Optional

from lib.print_fn import pr_error, pr_info


def _run_command(command: list[str], function_name: str, timeout: int = 300, dry_run: bool = False) -> bool:
    """Run a command with error handling."""
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


def regenerate_initramfs(
    target_root: str,
    *,
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Regenerate initramfs using mkinitcpio -P inside the target system."""
    function_name = "regenerate_initramfs"
    
    if not target_root or not os.path.isdir(target_root):
        pr_error(f"Target root does not exist: {target_root}", function_name)
        return False
    
    if dry_run:
        pr_info(f"Dry run: would regenerate initramfs in {target_root}", function_name)
        return True
    
    if not confirm:
        pr_error("Initramfs regeneration requires confirm=True", function_name)
        return False
    
    if os.geteuid() != 0:
        pr_error("Initramfs regeneration requires root privileges", function_name)
        return False
    
    # Check if mkinitcpio is available in target
    mkinitcpio_path = os.path.join(target_root, "usr", "bin", "mkinitcpio")
    if not os.path.exists(mkinitcpio_path):
        pr_error(f"mkinitcpio not found in target: {mkinitcpio_path}", function_name)
        return False
    
    # Use arch-chroot to run mkinitcpio in the target environment
    chroot = shutil.which("arch-chroot")
    if not chroot:
        pr_error("arch-chroot not found", function_name)
        return False
    
    if not _run_command([chroot, target_root, "mkinitcpio", "-P"], function_name, timeout, dry_run):
        return False
    
    pr_info("Initramfs regenerated successfully", function_name)
    return True


def configure_mkinitcpio_hooks(
    target_root: str,
    hooks: list[str],
    *,
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Configure mkinitcpio hooks for encrypted boot."""
    function_name = "configure_mkinitcpio_hooks"
    
    if not target_root or not os.path.isdir(target_root):
        pr_error(f"Target root does not exist: {target_root}", function_name)
        return False
    
    if not hooks:
        pr_error("Hooks list cannot be empty", function_name)
        return False
    
    if dry_run:
        pr_info(f"Dry run: would configure mkinitcpio hooks: {', '.join(hooks)}", function_name)
        return True
    
    if not confirm:
        pr_error("mkinitcpio hooks configuration requires confirm=True", function_name)
        return False
    
    if os.geteuid() != 0:
        pr_error("mkinitcpio hooks configuration requires root privileges", function_name)
        return False
    
    mkinitcpio_conf = os.path.join(target_root, "etc", "mkinitcpio.conf")
    
    if not os.path.exists(mkinitcpio_conf):
        pr_error(f"mkinitcpio.conf not found: {mkinitcpio_conf}", function_name)
        return False
    
    try:
        # Read existing configuration
        with open(mkinitcpio_conf, "r") as f:
            content = f.read()
        
        # Replace HOOKS line
        hooks_str = " ".join(hooks)
        new_hooks_line = f'HOOKS=({hooks_str})'
        
        # Replace existing HOOKS line or add it if not present
        lines = content.split("\n")
        hooks_updated = False
        
        for i, line in enumerate(lines):
            if line.strip().startswith("HOOKS="):
                lines[i] = new_hooks_line
                hooks_updated = True
                break
        
        if not hooks_updated:
            # Add HOOKS line after MODULES line or at the end
            for i, line in enumerate(lines):
                if line.strip().startswith("MODULES="):
                    lines.insert(i + 1, new_hooks_line)
                    hooks_updated = True
                    break
            
            if not hooks_updated:
                lines.append(new_hooks_line)
        
        # Write updated configuration
        with open(mkinitcpio_conf, "w") as f:
            f.write("\n".join(lines) + "\n")
        
        pr_info(f"mkinitcpio hooks configured: {hooks_str}", function_name)
        return True
        
    except OSError as error:
        pr_error(f"Failed to update mkinitcpio.conf: {error}", function_name)
        return False


def write_crypttab(
    target_root: str,
    entries: list[dict[str, str]],
    *,
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Write /etc/crypttab entries for automatic encrypted device unlocking."""
    function_name = "write_crypttab"
    
    if not target_root or not os.path.isdir(target_root):
        pr_error(f"Target root does not exist: {target_root}", function_name)
        return False
    
    if not entries:
        pr_error("Crypttab entries cannot be empty", function_name)
        return False
    
    if dry_run:
        pr_info(f"Dry run: would write {len(entries)} crypttab entries", function_name)
        return True
    
    if not confirm:
        pr_error("Crypttab writing requires confirm=True", function_name)
        return False
    
    if os.geteuid() != 0:
        pr_error("Crypttab writing requires root privileges", function_name)
        return False
    
    crypttab_path = os.path.join(target_root, "etc", "crypttab")
    
    try:
        # Validate entries
        for entry in entries:
            required_fields = ["target", "source", "key_file", "options"]
            if not all(field in entry for field in required_fields):
                pr_error(f"Invalid crypttab entry: missing required fields", function_name)
                return False
        
        # Write crypttab entries
        lines = []
        for entry in entries:
            line = f"{entry['target']} {entry['source']} {entry['key_file']} {entry['options']}"
            lines.append(line)
        
        with open(crypttab_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        
        # Set proper permissions
        os.chmod(crypttab_path, 0o640)
        
        pr_info(f"crypttab written with {len(entries)} entries", function_name)
        return True
        
    except OSError as error:
        pr_error(f"Failed to write crypttab: {error}", function_name)
        return False


def get_default_hooks_encrypted_lvm() -> list[str]:
    """Get default mkinitcpio hooks for encrypted LVM setup."""
    return [
        "base",
        "udev",
        "autodetect",
        "keyboard",
        "keymap",
        "consolefont",
        "block",
        "encrypt",
        "lvm2",
        "filesystems",
        "fsck"
    ]


def get_default_hooks_encrypted() -> list[str]:
    """Get default mkinitcpio hooks for encrypted (non-LVM) setup."""
    return [
        "base",
        "udev",
        "autodetect",
        "keyboard",
        "keymap",
        "consolefont",
        "block",
        "encrypt",
        "filesystems",
        "fsck"
    ]


def get_default_hooks_plain() -> list[str]:
    """Get default mkinitcpio hooks for plain (non-encrypted) setup."""
    return [
        "base",
        "udev",
        "autodetect",
        "keyboard",
        "keymap",
        "consolefont",
        "block",
        "filesystems",
        "fsck"
    ]
