from src.pkgs.must_have_pkgs import install_packages


DESKTOP_PACKAGES = {
	"gnome": ["gnome", "gnome-extra", "gdm"],
	"kde": ["plasma-meta", "kde-applications-meta", "sddm"],
	"xfce": ["xfce4", "xfce4-goodies", "lightdm"],
	"cinnamon": ["cinnamon", "lightdm"],
	"mate": ["mate", "mate-extra", "lightdm"],
	"lxqt": ["lxqt", "sddm"],
	"sway": ["sway", "waybar", "wofi", "foot"],
	"hyprland": ["hyprland", "waybar", "wofi", "kitty"],
}


def install_desktop(
	desktop: str,
	*,
	confirm: bool = False,
	retries: int = 3,
	retry_delay: int = 5,
	dry_run: bool = False,
) -> bool:
	"""Install a supported Arch desktop environment and display manager."""
	desktop_name = desktop.lower().strip()
	packages = DESKTOP_PACKAGES.get(desktop_name)
	if packages is None:
		return False
	return install_packages(
		packages,
		confirm=confirm,
		retries=retries,
		retry_delay=retry_delay,
		dry_run=dry_run,
	)
