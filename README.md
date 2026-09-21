# Codecrafters Arch Installer

JSON-driven Arch Linux installation tooling for system discovery, package setup, storage preparation, user configuration, initramfs, and GRUB.

The project is intended for controlled installation environments. It can inspect the current machine, simulate the complete workflow, or execute explicitly confirmed system changes.

## Install

Clone or copy the project onto an Arch Linux environment with Python 3.10 or newer.

Check the interpreter and source tree:

```bash
python3 --version
python3 -m py_compile main.py config.py config_gen.py lib/*.py src/boot/*.py src/disk/*.py src/pkgs/*.py src/profile/*.py src/user/*.py
```

The application uses only the Python standard library. External commands are needed only for the operations that use them, such as `pacman`, `cryptsetup`, LVM tools, `grub-install`, and `makepkg`.

## Run Safely

The default command loads `app.json` and uses its configured mode:

```bash
python3 main.py
```

Run a complete simulation regardless of the JSON setting:

```bash
python3 main.py --dry-run
```

Dry-run mode does not format disks, install packages, alter users, write system files, change initramfs, or install GRUB. It executes read-only discovery and calls supported operations with `dry_run=True` so they report what they would do.

Real execution requires deliberate confirmation in both places:

1. Set `"dry_run": false` in the configuration or pass `--execute`.
2. Set the operation's `"confirm": true` where the function requires it.

```bash
sudo python3 main.py --execute
```

Do not use `--execute` against an unreviewed disk configuration.

## Command-Line Flags

| Flag | Purpose |
| --- | --- |
| `--config FILE` | Load a configuration other than `app.json`. |
| `--dry-run` | Override JSON and simulate operations. |
| `--execute` | Override JSON and execute operations. Requires root for system changes. |
| `--version` | Print the application version. |
| `--help` | Show command usage and available flags. |

Examples:

```bash
python3 main.py --help
python3 main.py --version
python3 main.py --config profiles/test.json --dry-run
```

The mode flags are mutually exclusive. A command-line mode overrides `settings.dry_run` in the JSON file.

## Configuration

The global workflow lives in [app.json](app.json). Each operation has a registered function and keyword parameters:

```json
{
	"function": "install_packages",
	"parameters": {
		"packages": ["git"],
		"confirm": false
	}
}
```

Validate and format a configuration without running it:

```bash
python3 config_gen.py --source app.json --output /tmp/app.generated.json
```

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the full schema, operation list, storage order, desktop choices, AUR setup, and GRUB parameters.

## Project Structure

- `main.py`: CLI, function registry, operation dispatch, root check, dry-run handling, and stop-on-error behavior.
- `config.py`: strict JSON loading and configuration validation.
- `app.json`: global workflow and default settings.
- `config_gen.py`: configuration validation and formatting utility.
- `src/disk/`: disk discovery, LUKS, LVM, Btrfs, mounts, fstab, and partition planning.
- `src/pkgs/`: pacman packages, developer tools, desktop environments, and AUR helpers.
- `src/boot/`: GRUB and initramfs configuration for BIOS/UEFI Arch systems.
- `src/profile/`: non-secret user and system profile collection.
- `src/user/`: user, group, password, and sudo configuration.
- `src/init_instation.py`: time, network, Wi-Fi, keyboard, font, and connectivity helpers.
- `lib/`: logging and terminal output helpers.

## Installation Flow

The operation order in the global configuration is meaningful. A typical storage workflow is:

1. Inspect disks and collect a system profile.
2. Install official packages and developer tools.
3. Create LUKS, PV, VG, and LV layers.
4. Format the target filesystem and generate fstab.
5. Create the target user and configure groups/sudo.
6. Configure mkinitcpio and regenerate the initramfs.
7. Mount the target root and EFI filesystems.
8. Install GRUB and generate its configuration.

Every device path, mount point, username, and boot mode must be reviewed for the target machine.

## Debugging

Start with the safest checks:

```bash
python3 main.py --dry-run
python3 -m json.tool app.json >/dev/null
python3 config_gen.py --source app.json --output /tmp/app.checked.json
```

Useful targeted checks:

```bash
python3 -m py_compile main.py config.py config_gen.py lib/*.py src/boot/*.py src/disk/*.py src/pkgs/*.py src/profile/*.py src/user/*.py
python3 -c "from config import load_config; print(load_config('app.json')['settings'])"
python3 -c "from src.profile.system_profile import collect_profile; print(collect_profile())"
```

Exit codes:

- `0`: configuration completed successfully.
- `1`: an operation failed or execution was blocked by permissions.
- `2`: the configuration could not be loaded or validated.

If the log file warning mentions `/var/log/arch_installer_jhiuqdiua`, the process cannot write the configured system log directory. Console output still works; run with appropriate permissions or configure a writable log location before real execution.

Common failures:

- Invalid JSON: run `python3 -m json.tool app.json` and inspect the reported line.
- Unsupported function: check that the name exists in `FUNCTIONS` in `main.py`.
- Invalid parameters: compare the JSON parameters with the function signature.
- AUR failure: use an existing non-root build user and verify `git`, `makepkg`, and the selected helper.
- GRUB failure: verify the target root and EFI filesystems are already mounted and select the correct BIOS/UEFI mode.
- Storage failure: stop, verify device paths, and do not retry destructive operations blindly.

## Safety Rules

- Keep `settings.dry_run` set to `true` while editing configuration.
- Never store real encryption or Wi-Fi passwords in committed JSON.
- AUR packages must be built as a non-root user.
- Storage, user, package, initramfs, and bootloader operations require explicit confirmation and appropriate privileges.
- Back up important data before any real disk operation.
