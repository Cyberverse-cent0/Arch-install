from dataclasses import dataclass
from enum import Enum
from typing import Optional


class EncryptionLayout(Enum):
    """Supported encryption layout types."""
    PLAIN = "plain"           # No encryption
    LUKS_ONLY = "luks_only"   # LUKS encryption without LVM
    LUKS_LVM = "luks_lvm"     # LUKS encryption with LVM inside


@dataclass
class EncryptionConfig:
    """Configuration for encrypted system setup."""
    layout: EncryptionLayout
    crypt_device: str
    crypt_mapper: str
    crypt_type: str = "luks2"
    lvm_vg_name: Optional[str] = None
    lvm_lv_name: Optional[str] = None
    root_mapper: str = "cryptroot"
    
    def __post_init__(self):
        """Validate encryption configuration."""
        if self.layout == EncryptionLayout.LUKS_LVM:
            if not self.lvm_vg_name or not self.lvm_lv_name:
                raise ValueError("LVM layout requires vg_name and lv_name")
            self.root_mapper = f"{self.lvm_vg_name}-{self.lvm_lv_name}"
        elif self.layout == EncryptionLayout.LUKS_ONLY:
            self.root_mapper = self.crypt_mapper
        else:
            self.root_mapper = ""


def get_hooks_for_layout(layout: EncryptionLayout) -> list[str]:
    """Get appropriate mkinitcpio hooks for encryption layout."""
    hooks_map = {
        EncryptionLayout.PLAIN: [
            "base",
            "udev",
            "autodetect",
            "keyboard",
            "keymap",
            "consolefont",
            "block",
            "filesystems",
            "fsck"
        ],
        EncryptionLayout.LUKS_ONLY: [
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
        ],
        EncryptionLayout.LUKS_LVM: [
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
        ],
    }
    
    return hooks_map.get(layout, hooks_map[EncryptionLayout.PLAIN])


def get_crypttab_entry(config: EncryptionConfig) -> dict[str, str]:
    """Generate crypttab entry for encryption configuration."""
    if config.layout == EncryptionLayout.PLAIN:
        return {}
    
    return {
        "target": config.crypt_mapper,
        "source": config.crypt_device,
        "key_file": "none",
        "options": "luks"
    }


def get_kernel_params(config: EncryptionConfig) -> str:
    """Generate kernel parameters for encrypted boot."""
    if config.layout == EncryptionLayout.PLAIN:
        return ""
    
    if config.layout == EncryptionLayout.LUKS_LVM:
        return f"cryptdevice=UUID=UUID_{config.crypt_device}:{config.crypt_mapper} root=/dev/mapper/{config.root_mapper}"
    else:
        return f"cryptdevice=UUID=UUID_{config.crypt_device}:{config.crypt_mapper} root=/dev/mapper/{config.crypt_mapper}"


def validate_encryption_config(config: EncryptionConfig) -> bool:
    """Validate encryption configuration."""
    try:
        # Check if crypt device path is valid
        if not config.crypt_device.startswith("/dev/"):
            return False
        
        # Check if mapper name is valid
        if not config.crypt_mapper or "/" in config.crypt_mapper:
            return False
        
        # Validate LVM-specific requirements
        if config.layout == EncryptionLayout.LUKS_LVM:
            if not config.lvm_vg_name or not config.lvm_lv_name:
                return False
            if "/" in config.lvm_vg_name or "/" in config.lvm_lv_name:
                return False
        
        return True
    except Exception:
        return False


def create_encryption_config_from_dict(config_dict: dict) -> Optional[EncryptionConfig]:
    """Create EncryptionConfig from dictionary."""
    try:
        layout_str = config_dict.get("layout", "plain")
        layout = EncryptionLayout(layout_str)
        
        return EncryptionConfig(
            layout=layout,
            crypt_device=config_dict.get("crypt_device", ""),
            crypt_mapper=config_dict.get("crypt_mapper", "cryptroot"),
            crypt_type=config_dict.get("crypt_type", "luks2"),
            lvm_vg_name=config_dict.get("lvm_vg_name"),
            lvm_lv_name=config_dict.get("lvm_lv_name"),
        )
    except (ValueError, KeyError):
        return None


def detect_encryption_layout(
    has_luks: bool = False,
    has_lvm: bool = False,
) -> EncryptionLayout:
    """Detect encryption layout based on system features."""
    if has_luks and has_lvm:
        return EncryptionLayout.LUKS_LVM
    elif has_luks:
        return EncryptionLayout.LUKS_ONLY
    else:
        return EncryptionLayout.PLAIN