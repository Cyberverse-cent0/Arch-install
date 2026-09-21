# Configuration Reference

The application reads `app.json` by default. A different file can be selected with `--config`.

## Top-Level Shape

```json
{
  "application": {},
  "settings": {},
  "operations": []
}
```

### `application`

| Key | Type | Meaning |
| --- | --- | --- |
| `name` | string | Application name shown in the configuration. |
| `version` | string | Configuration/application version. |
| `require_root` | boolean | Requires root before non-dry-run operations. Keep `true`. |

### `settings`

| Key | Type | Meaning |
| --- | --- | --- |
| `dry_run` | boolean | When `true`, destructive operations are skipped. Default is `true`. |
| `stop_on_error` | boolean | Documents the intended workflow policy. Operation failures currently stop the runner. |

### `operations`

Operations run in order:

```json
{
  "function": "function_name",
  "parameters": {
    "key": "value"
  }
}
```

Function names must be registered in `main.py`. Parameters are passed as Python keyword arguments.

## Available Operations

### Inspection and profile

- `get_all_disks`
- `get_disk_info` with `disk`
- `get_disk_size` with `disk`
- `collect_profile`
- `save_profile` with `output_path` and `confirm`

The profile functions collect host, OS, CPU, memory, disk-usage, session, and boot-mode information. They do not collect passwords or secret keys.

### Official packages

```json
{
  "function": "install_packages",
  "parameters": {
    "packages": ["base-devel", "git"],
    "confirm": false
  }
}
```

Package installation requires `confirm: true`, root privileges, and `pacman`. The installer retries a busy pacman database and never deletes lock files.

`dev_tools` installs the standard development set: `base-devel`, `git`, and `vim`.

### Desktop environments

Use `install_desktop` with one of:

- `gnome`
- `kde`
- `xfce`
- `cinnamon`
- `mate`
- `lxqt`
- `sway`
- `hyprland`

Example:

```json
{
  "function": "install_desktop",
  "parameters": {
    "desktop": "gnome",
    "confirm": false
  }
}
```

### AUR

AUR builds must run as a non-root user. Supported helpers are `paru` and `yay`.

```json
{
  "function": "aur_setup",
  "parameters": {
    "helper": "paru",
    "build_user": "archuser",
    "packages": ["visual-studio-code-bin"],
    "confirm": false
  }
}
```

Before enabling this operation, replace `archuser` with an existing non-root account. The helper is cloned and built with `makepkg` through `runuser`; the application does not build AUR packages as root.

### Storage

Storage functions are destructive and must be ordered carefully:

1. `crypt_setup`
2. `pv_create`
3. `vg_create`
4. `lv_create`
5. `btrfs_disk_setup`
6. Mount the target system and EFI partition separately.
7. `install_grub`

Every storage operation requires `confirm: true` when real execution is intended. Verify every device path before enabling it.

### GRUB

For UEFI:

```json
{
  "function": "install_grub",
  "parameters": {
    "root_mount": "/mnt",
    "boot_mode": "uefi",
    "efi_directory": "/mnt/boot",
    "bootloader_id": "GRUB",
    "confirm": false
  }
}
```

For BIOS, use `boot_mode: "bios"` and provide the whole-disk `boot_device`, such as `/dev/sda`. The target root and EFI filesystems must already be mounted; the function does not mount them automatically.

## Enabling Real Changes

1. Back up important data.
2. Replace placeholder devices, passwords, users, and mount paths.
3. Set `confirm: true` only for the intended operations.
4. Set `settings.dry_run` to `false`.
5. Run as root and inspect every command result.

Never commit real encryption passwords or private configuration values to Git. Prefer a temporary, permission-restricted configuration file for secrets.
