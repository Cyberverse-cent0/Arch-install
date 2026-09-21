import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from config import ConfigError, load_config
from src.disk.btrfs_disk_setup import get_all_disks, DiskInfo
from src.profile.system_profile import collect_profile


def detect_boot_mode() -> str:
    """Detect system boot mode (UEFI or BIOS)."""
    if Path("/sys/firmware/efi").is_dir():
        return "uefi"
    return "bios"


def select_target_disk() -> str:
    """Select the best target disk for installation based on size and type."""
    try:
        disks = get_all_disks()
    except Exception:
        return "/dev/sda"  # Fallback if detection fails
    
    # Filter out system disks and small disks
    target_disks = []
    for disk in disks:
        if disk.type != "disk":
            continue
        if disk.mountpoint:  # Skip mounted disks
            continue
        try:
            size_bytes = int(disk.size)
            # Minimum 10GB, prefer larger disks
            if size_bytes >= 10 * 1024 * 1024 * 1024:  # 10GB
                target_disks.append((disk, size_bytes))
        except (ValueError, TypeError):
            continue
    
    if not target_disks:
        return "/dev/sda"  # Fallback
    
    # Sort by size (largest first) and return the path
    target_disks.sort(key=lambda x: x[1], reverse=True)
    best_disk = target_disks[0][0]
    return f"/dev/{best_disk.name}" if not best_disk.name.startswith("/dev/") else best_disk.name


def detect_memory_size() -> int:
    """Detect system memory in bytes."""
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 8 * 1024 * 1024 * 1024  # Default to 8GB


def get_base_packages(memory_gb: int, boot_mode: str) -> list[str]:
    """Get appropriate base packages based on system configuration."""
    base = ["base", "linux", "linux-firmware"]
    
    if boot_mode == "uefi":
        base.extend(["grub", "efibootmgr"])
    else:
        base.append("grub")
    
    # Add swap file support for systems with less memory
    if memory_gb < 4:
        pass  # Could add swap-related packages here
    
    return base


def detect_desktop_environment() -> str:
    """Detect current desktop environment or suggest a default."""
    desktop = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("XDG_SESSION_DESKTOP")
    if desktop:
        desktop_lower = desktop.lower()
        if "gnome" in desktop_lower:
            return "gnome"
        elif "kde" in desktop_lower:
            return "kde"
        elif "xfce" in desktop_lower:
            return "xfce"
    return "gnome"  # Default to GNOME


def get_boot_config(boot_mode: str, target_disk: str) -> dict[str, str]:
    """Get boot configuration based on detected boot mode."""
    config = {
        "boot_mode": boot_mode,
        "efi_directory": "/mnt/boot"
    }
    
    if boot_mode == "bios":
        config["efi_directory"] = ""  # Not used for BIOS
    
    return config


def generate_config_from_template(
    template_path: str = "app.json.template",
    output: str = "app.generated.json",
    password: str = "CHANGE_ME"
) -> Path:
    """Generate configuration from template with hardware detection."""
    
    # Detect hardware
    boot_mode = detect_boot_mode()
    target_disk = select_target_disk()
    memory_bytes = detect_memory_size()
    memory_gb = memory_bytes // (1024 * 1024 * 1024)
    desktop_env = detect_desktop_environment()
    base_packages = get_base_packages(memory_gb, boot_mode)
    boot_config = get_boot_config(boot_mode, target_disk)
    
    # Load template
    template_path = Path(template_path).expanduser()
    with template_path.open("r", encoding="utf-8") as template_file:
        template_content = template_file.read()
    
    # Replace placeholders
    replacements = {
        "{{BOOT_MODE}}": boot_mode,
        "{{EFI_DIRECTORY}}": boot_config["efi_directory"],
        "{{TARGET_DISK}}": target_disk,
        "{{DESKTOP_ENV}}": desktop_env,
        "{{LUKS_PASSWORD}}": password,
        "{{BASE_PACKAGES}}": json.dumps(base_packages)
    }
    
    for placeholder, value in replacements.items():
        template_content = template_content.replace(placeholder, value)
    
    # Parse and validate the generated config
    config = json.loads(template_content)
    
    # Write output
    output_path = Path(output).expanduser()
    with output_path.open("w", encoding="utf-8") as config_file:
        json.dump(config, config_file, indent=2)
        config_file.write("\n")
    
    print(f"Generated configuration based on hardware detection:")
    print(f"  Boot mode: {boot_mode}")
    print(f"  Target disk: {target_disk}")
    print(f"  Memory: {memory_gb}GB")
    print(f"  Desktop: {desktop_env}")
    print(f"  Base packages: {', '.join(base_packages)}")
    
    return output_path


def generate_config(source: str = "app.json", output: str = "app.generated.json") -> Path:
    """Validate the global config and write a formatted copy."""
    config = load_config(source)
    output_path = Path(output).expanduser()
    with output_path.open("w", encoding="utf-8") as config_file:
        json.dump(config, config_file, indent=2)
        config_file.write("\n")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a validated installer config")
    parser.add_argument("--source", default="app.json", help="Source config file")
    parser.add_argument("--output", default="app.generated.json", help="Output config file")
    parser.add_argument("--template", action="store_true", help="Use template with hardware detection")
    parser.add_argument("--template-path", default="app.json.template", help="Template file path")
    parser.add_argument("--password", default="CHANGE_ME", help="LUKS encryption password")
    args = parser.parse_args()
    
    try:
        if args.template:
            output_path = generate_config_from_template(
                args.template_path,
                args.output,
                args.password
            )
        else:
            output_path = generate_config(args.source, args.output)
    except (ConfigError, OSError) as error:
        print(f"config generation failed: {error}")
        return 1
    except json.JSONDecodeError as error:
        print(f"template parsing failed: {error}")
        return 1
    
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())