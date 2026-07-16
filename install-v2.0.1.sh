#!/usr/bin/env bash
#
# install_arch.sh - Professional Arch Linux Installation Script
#
# Features:
#   - Automatic or forced BIOS/UEFI boot mode detection
#   - Optional LUKS2 encryption, with or without LVM2
#   - Optional desktop environment + display manager installation
#   - Optional software bundles (development / networking / utilities)
#   - Polished ANSI-based terminal UI (no external dialog/whiptail/gum deps)
#   - Defensive programming, structured logging, and cleanup on failure
#
# Author: Expert Linux Systems Engineer
# Version: 2.0.0
# License: MIT
#

set -Eeuo pipefail
shopt -s nocasematch

# ============================================================================
# GLOBAL CONSTANTS
# ============================================================================
readonly SCRIPT_VERSION="2.0.0"
readonly LOG_FILE="/var/log/arch_install_$(date +%Y%m%d_%H%M%S).log"

# Colors / styles (ANSI escape codes only - no external UI tools)
readonly C_RESET=$'\033[0m'
readonly C_BOLD=$'\033[1m'
readonly C_DIM=$'\033[2m'
readonly C_RED=$'\033[0;31m'
readonly C_GREEN=$'\033[0;32m'
readonly C_YELLOW=$'\033[0;33m'
readonly C_BLUE=$'\033[0;34m'
readonly C_MAGENTA=$'\033[0;35m'
readonly C_CYAN=$'\033[0;36m'
readonly C_WHITE=$'\033[1;37m'
readonly C_BG_BLUE=$'\033[44m'

readonly ICON_OK="${C_GREEN}[OK]${C_RESET}"
readonly ICON_WARN="${C_YELLOW}[!!]${C_RESET}"
readonly ICON_ERR="${C_RED}[XX]${C_RESET}"
readonly ICON_INFO="${C_CYAN}[i]${C_RESET}"
readonly ICON_ARROW="${C_MAGENTA}==>${C_RESET}"

# ============================================================================
# MUTABLE CONFIGURATION (populated during the interview phase)
# ============================================================================
BOOT_MODE=""            # "uefi" or "bios"
BOOT_MODE_CHOICE="auto" # auto | force_bios | force_uefi

DISK=""
PART_SCHEME=""          # "gpt" or "mbr" (mbr only ever used for forced-BIOS + user choice)
DISK_LAYOUT=""           # "standard" | "luks_lvm" | "lvm_only"
USE_ENCRYPTION=false
USE_LVM=false

HOSTNAME=""
USERNAME=""
ROOT_PASSWORD=""
USER_PASSWORD=""
LUKS_PASSWORD=""
TIMEZONE="UTC"
LOCALE="en_US.UTF-8"

CPU_VENDOR=""
MICROCODE_PACKAGE=""
LUKS_UUID=""

# Partition device paths (populated by partition_disk)
EFI_PART=""
BIOS_BOOT_PART=""
BOOT_PART=""            # BIOS /boot partition (non-LVM legacy layouts)
ROOT_SRC_PART=""        # raw partition that becomes LUKS/LVM PV/root, pre-mapping
DATA_PART=""            # generic "everything else" partition

LUKS_NAME="crypt_root"
VG_NAME="vg_arch"
LV_ROOT="root"
LV_HOME="home"
LV_SWAP="swap"

DESKTOP_ENV="none"
DISPLAY_MANAGER="none"
SEPARATE_HOME_LV=true   # decided dynamically in setup_lvm() based on free space

# Arrays for optional software selections
declare -a SELECTED_DEV_PKGS=()
declare -a SELECTED_NET_PKGS=()
declare -a SELECTED_UTIL_PKGS=()

# Track mount state so cleanup knows what to unwind
MOUNTED_PATHS=()
SWAP_ACTIVE=false
LUKS_OPEN=false
VG_ACTIVE=false

# ============================================================================
# LOGGING
# ============================================================================
log_to_file() {
    echo -e "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "${LOG_FILE}"
}

log_info()    { echo -e "  ${ICON_INFO} $1"; log_to_file "[INFO] $1"; }
log_warn()    { echo -e "  ${ICON_WARN} ${C_YELLOW}$1${C_RESET}"; log_to_file "[WARN] $1"; }
log_error()  { echo -e "  ${ICON_ERR} ${C_RED}$1${C_RESET}" >&2; log_to_file "[ERROR] $1"; }
log_success() { echo -e "  ${ICON_OK} $1"; log_to_file "[SUCCESS] $1"; }

die() {
    log_error "$1"
    log_error "Installation aborted. See ${LOG_FILE} for details."
    exit 1
}

# ============================================================================
# UI HELPERS (pure ANSI - no dialog/whiptail/gum/fzf)
# ============================================================================
term_width() { tput cols 2>/dev/null || echo 80; }

hr() {
    local width; width=$(term_width)
    printf "${C_DIM}%${width}s${C_RESET}\n" '' | tr ' ' '-'
}

banner() {
    local title="$1"
    local width; width=$(term_width)
    clear
    echo -e "${C_BG_BLUE}${C_WHITE}"
    printf '%*s\n' "${width}" ''
    printf '%*s\n' $(( (width + ${#title}) / 2 )) "${title}"
    printf '%*s\n' "${width}" ''
    echo -e "${C_RESET}"
}

section() {
    echo
    hr
    echo -e "  ${C_BOLD}${C_MAGENTA}${ICON_ARROW} $1${C_RESET}"
    hr
}

box_menu() {
    # box_menu "Title" "opt1" "opt2" ...
    local title="$1"; shift
    local -a options=("$@")
    local width; width=$(term_width)
    (( width > 70 )) && width=70

    echo -e "  ${C_CYAN}+$(printf -- '-%.0s' $(seq 1 $((width-2))))+${C_RESET}"
    printf "  ${C_CYAN}|${C_RESET} ${C_BOLD}%-*s${C_CYAN}|${C_RESET}\n" $((width-4)) "${title}"
    echo -e "  ${C_CYAN}+$(printf -- '-%.0s' $(seq 1 $((width-2))))+${C_RESET}"
    local i=1
    for opt in "${options[@]}"; do
        printf "  ${C_CYAN}|${C_RESET}  ${C_WHITE}%2d)${C_RESET} %-*s ${C_CYAN}|${C_RESET}\n" "${i}" $((width-10)) "${opt}"
        ((i++))
    done
    echo -e "  ${C_CYAN}+$(printf -- '-%.0s' $(seq 1 $((width-2))))+${C_RESET}"
}

# Prompt the user to choose from a numbered box_menu; validates the range.
# Usage: choose_option result_var "Title" "opt1" "opt2" ...
choose_option() {
    local __resultvar="$1"; shift
    local title="$1"; shift
    local -a options=("$@")
    local count=${#options[@]}
    # NOTE: this must NOT be named the same as any variable a caller might
    # pass as __resultvar (e.g. "choice") - printf -v resolves against the
    # nearest matching variable, and a local here would shadow the caller's
    # variable of the same name, silently discarding the assignment.
    local __user_input

    box_menu "${title}" "${options[@]}"
    while true; do
        read -rp "$(echo -e "  ${C_WHITE}Enter choice [1-${count}]: ${C_RESET}")" __user_input
        if [[ "${__user_input}" =~ ^[0-9]+$ ]] && (( __user_input >= 1 && __user_input <= count )); then
            printf -v "${__resultvar}" '%s' "${__user_input}"
            return 0
        fi
        log_warn "Invalid choice. Please enter a number between 1 and ${count}."
    done
}

confirm_yes_no() {
    # confirm_yes_no "Question?" -> returns 0 for yes, 1 for no
    local prompt="$1"
    local answer
    while true; do
        read -rp "$(echo -e "  ${C_WHITE}${prompt} [y/n]: ${C_RESET}")" answer
        case "${answer}" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
            *) log_warn "Please answer 'y' or 'n'." ;;
        esac
    done
}

prompt_text() {
    # prompt_text result_var "Prompt text" ["default"]
    local __resultvar="$1"
    local prompt="$2"
    local default="${3:-}"
    local input

    if [[ -n "${default}" ]]; then
        read -rp "$(echo -e "  ${C_WHITE}${prompt} [${default}]: ${C_RESET}")" input
        input="${input:-${default}}"
    else
        read -rp "$(echo -e "  ${C_WHITE}${prompt}: ${C_RESET}")" input
    fi
    printf -v "${__resultvar}" '%s' "${input}"
}

prompt_password() {
    # prompt_password result_var "Prompt text" - requires confirmation match
    local __resultvar="$1"
    local prompt="$2"
    local pass1 pass2

    while true; do
        read -rsp "$(echo -e "  ${C_WHITE}${prompt}: ${C_RESET}")" pass1; echo
        if [[ -z "${pass1}" ]]; then
            log_warn "Password cannot be empty."
            continue
        fi
        read -rsp "$(echo -e "  ${C_WHITE}Confirm password: ${C_RESET}")" pass2; echo
        if [[ "${pass1}" != "${pass2}" ]]; then
            log_warn "Passwords do not match. Try again."
            continue
        fi
        printf -v "${__resultvar}" '%s' "${pass1}"
        return 0
    done
}

# Simple determinate progress bar for known-length step sequences.
# progress_bar current total label
progress_bar() {
    local current="$1" total="$2" label="$3"
    local width=40
    local filled=$(( current * width / total ))
    local empty=$(( width - filled ))
    printf "\r  ${C_CYAN}["
    (( filled > 0 )) && printf '%0.s#' $(seq 1 "${filled}")
    (( empty > 0 )) && printf '%0.s.' $(seq 1 "${empty}")
    printf "]${C_RESET} %-30s (%d/%d)" "${label}" "${current}" "${total}"
    if (( current == total )); then
        echo
    fi
}

# Run a sequence of "description|command_function" steps with a progress bar.
run_step_sequence() {
    local -a steps=("$@")
    local total=${#steps[@]}
    local i=0
    for step in "${steps[@]}"; do
        (( ++i ))
        local desc="${step%%|*}"
        local func="${step##*|}"
        progress_bar "${i}" "${total}" "${desc}"
        "${func}"
    done
}

# ============================================================================
# ERROR HANDLING / CLEANUP
# ============================================================================
on_error() {
    local line_number="$1" failed_command="$2"
    echo
    log_error "Script failed at line ${line_number}: ${failed_command}"
    cleanup_on_failure
    die "Installation failed. Review ${LOG_FILE} for details."
}
trap 'on_error ${LINENO} "${BASH_COMMAND}"' ERR

cleanup_on_failure() {
    log_warn "Rolling back mounts and storage layers..."

    # Unmount in reverse order of mounting
    for (( idx=${#MOUNTED_PATHS[@]}-1 ; idx>=0 ; idx-- )); do
        local path="${MOUNTED_PATHS[idx]}"
        if mountpoint -q "${path}" 2>/dev/null; then
            umount -R "${path}" 2>/dev/null || umount -lf "${path}" 2>/dev/null || true
        fi
    done

    if ${SWAP_ACTIVE}; then
        swapoff -a 2>/dev/null || true
    fi

    if ${USE_LVM} && ${VG_ACTIVE}; then
        vgchange -an "${VG_NAME}" 2>/dev/null || true
    fi

    if ${USE_ENCRYPTION} && ${LUKS_OPEN}; then
        cryptsetup close "${LUKS_NAME}" 2>/dev/null || true
    fi
}

# ============================================================================
# PRE-FLIGHT VALIDATION
# ============================================================================
validate_root() {
    [[ "${EUID}" -eq 0 ]] || die "This script must be run as root."
    log_success "Running with root privileges."
}

sync_clock() {
    timedatectl set-ntp true 2>/dev/null || true
    log_success "System clock synchronized via NTP."
}

# ============================================================================
# BOOT MODE DETECTION / SELECTION
# ============================================================================
detect_boot_mode() {
    if [[ -d /sys/firmware/efi/efivars ]]; then
        echo "uefi"
    else
        echo "bios"
    fi
}

select_boot_mode() {
    section "Boot Mode"
    local detected; detected=$(detect_boot_mode)
    log_info "Detected boot mode: ${C_BOLD}${detected^^}${C_RESET}"

    local choice
    choose_option choice "Boot Mode Selection" \
        "Automatic (use detected: ${detected^^})" \
        "Force Legacy BIOS" \
        "Force UEFI"

    case "${choice}" in
        1) BOOT_MODE="${detected}" ;;
        2) BOOT_MODE="bios" ;;
        3) BOOT_MODE="uefi"
           [[ "${detected}" == "bios" ]] && log_warn "Forcing UEFI on a system that booted in BIOS mode may fail." ;;
    esac
    log_success "Boot mode set to ${C_BOLD}${BOOT_MODE^^}${C_RESET}."
}

# ============================================================================
# CPU MICROCODE DETECTION
# ============================================================================
detect_cpu_vendor() {
    section "CPU Detection"
    local vendor_line
    vendor_line="$(grep -m1 'vendor_id' /proc/cpuinfo || true)"

    if grep -qi "intel" <<< "${vendor_line}"; then
        CPU_VENDOR="intel"
        MICROCODE_PACKAGE="intel-ucode"
    elif grep -qi "amd" <<< "${vendor_line}"; then
        CPU_VENDOR="amd"
        MICROCODE_PACKAGE="amd-ucode"
    else
        log_warn "Could not determine CPU vendor; skipping microcode package."
        CPU_VENDOR="unknown"
        MICROCODE_PACKAGE=""
    fi

    if [[ -n "${MICROCODE_PACKAGE}" ]]; then
        log_success "Detected ${CPU_VENDOR^^} CPU - will install ${MICROCODE_PACKAGE}."
    fi
}

# ============================================================================
# DISK SELECTION
# ============================================================================
list_disks() {
    lsblk -dpno NAME,SIZE,MODEL | grep -Ev 'loop|sr0|rom' || true
}

select_disk() {
    section "Target Disk"
    echo -e "  ${C_DIM}Available block devices:${C_RESET}"
    list_disks | sed 's/^/    /'
    echo

    while true; do
        prompt_text DISK "Enter target disk (e.g. /dev/sda, /dev/nvme0n1)"
        if [[ -b "${DISK}" ]]; then
            break
        fi
        log_warn "'${DISK}' is not a valid block device."
    done

    echo
    log_warn "ALL data on ${C_BOLD}${DISK}${C_RESET}${C_YELLOW} will be permanently erased.${C_RESET}"
    local confirmation
    prompt_text confirmation "Type YES (uppercase) to confirm"
    [[ "${confirmation}" == "YES" ]] || die "Installation cancelled by user."
    log_success "Disk ${DISK} confirmed for installation."
}

# ============================================================================
# DISK LAYOUT SELECTION
# ============================================================================
select_disk_layout() {
    section "Disk Layout"
    local choice
    choose_option choice "Choose a disk layout" \
        "Standard partitions (no LVM, no encryption)" \
        "LUKS2 encryption + LVM2 (recommended for security)" \
        "LVM2 only (no encryption)"

    case "${choice}" in
        1) DISK_LAYOUT="standard"; USE_ENCRYPTION=false; USE_LVM=false ;;
        2) DISK_LAYOUT="luks_lvm"; USE_ENCRYPTION=true;  USE_LVM=true  ;;
        3) DISK_LAYOUT="lvm_only"; USE_ENCRYPTION=false; USE_LVM=true  ;;
    esac
    log_success "Layout selected: ${DISK_LAYOUT}"

    if [[ "${BOOT_MODE}" == "bios" ]]; then
        choose_option choice "Partition table for BIOS boot" \
            "GPT with BIOS Boot Partition (recommended)" \
            "MBR (legacy, for older systems)"
        PART_SCHEME=$([[ "${choice}" == "1" ]] && echo "gpt" || echo "mbr")
    else
        PART_SCHEME="gpt"
    fi
    log_success "Partition table: ${PART_SCHEME^^}"
}

# ============================================================================
# USER / SYSTEM INPUT
# ============================================================================
gather_user_input() {
    section "System Configuration"

    while true; do
        prompt_text HOSTNAME "Enter hostname"
        [[ "${HOSTNAME}" =~ ^[a-zA-Z0-9-]+$ ]] && break
        log_warn "Hostname may only contain letters, digits, and hyphens."
    done

    while true; do
        prompt_text USERNAME "Enter username"
        [[ "${USERNAME}" =~ ^[a-z_][a-z0-9_-]*$ ]] && break
        log_warn "Username must start with a lowercase letter or underscore, and use only lowercase letters, digits, - or _."
    done

    prompt_password ROOT_PASSWORD "Enter root password"
    prompt_password USER_PASSWORD "Enter password for ${USERNAME}"

    if ${USE_ENCRYPTION}; then
        prompt_password LUKS_PASSWORD "Enter LUKS disk-encryption password"
    fi

    prompt_text TIMEZONE "Enter timezone (e.g. America/Chicago)" "UTC"
    if [[ ! -f "/usr/share/zoneinfo/${TIMEZONE}" ]]; then
        log_warn "Timezone '${TIMEZONE}' not found on install media; defaulting to UTC."
        TIMEZONE="UTC"
    fi

    prompt_text LOCALE "Enter locale" "en_US.UTF-8"

    log_success "System configuration collected."
}

# ============================================================================
# PARTITIONING
# ============================================================================
partition_name() {
    # Given a disk and partition number, return the correct device node
    # (handles nvme/mmcblk "pN" suffix convention).
    local disk="$1" num="$2"
    if [[ "${disk}" =~ (nvme|mmcblk) ]]; then
        echo "${disk}p${num}"
    else
        echo "${disk}${num}"
    fi
}

partition_disk() {
    section "Partitioning ${DISK}"
    log_info "Wiping existing signatures and partition table..."
    wipefs -af "${DISK}" &>/dev/null || true
    sgdisk --zap-all "${DISK}" &>/dev/null || true

    if [[ "${PART_SCHEME}" == "gpt" ]]; then
        parted -s "${DISK}" mklabel gpt

        local part_num=1
        if [[ "${BOOT_MODE}" == "uefi" ]]; then
            log_info "Creating EFI System Partition (1 GiB)..."
            parted -s "${DISK}" mkpart ESP fat32 1MiB 1025MiB
            parted -s "${DISK}" set "${part_num}" esp on
            EFI_PART=$(partition_name "${DISK}" "${part_num}")
            part_num=2
            local remainder_start="1025MiB"
        else
            log_info "Creating BIOS Boot Partition (1 MiB)..."
            parted -s "${DISK}" mkpart biosboot 1MiB 3MiB
            parted -s "${DISK}" set "${part_num}" bios_grub on
            BIOS_BOOT_PART=$(partition_name "${DISK}" "${part_num}")
            part_num=2
            local remainder_start="3MiB"
        fi

        log_info "Creating data partition (remaining space)..."
        parted -s "${DISK}" mkpart primary "${remainder_start}" 100%
        DATA_PART=$(partition_name "${DISK}" "${part_num}")

    else
        # MBR - only reachable for forced/legacy BIOS installs
        parted -s "${DISK}" mklabel msdos
        log_info "Creating primary boot/root partition (remaining space, bootable)..."
        parted -s "${DISK}" mkpart primary ext4 1MiB 100%
        parted -s "${DISK}" set 1 boot on
        DATA_PART=$(partition_name "${DISK}" 1)
    fi

    sleep 2
    partprobe "${DISK}" &>/dev/null || true
    udevadm settle || true

    [[ -n "${DATA_PART}" && -b "${DATA_PART}" ]] || die "Data partition ${DATA_PART} was not created."
    if [[ "${BOOT_MODE}" == "uefi" ]]; then
        [[ -b "${EFI_PART}" ]] || die "EFI partition ${EFI_PART} was not created."
    fi

    # A previous aborted run (or a re-purposed disk) can leave behind LUKS,
    # LVM, or filesystem signatures inside these partitions even though the
    # partition table itself was just rebuilt. Clear them explicitly so
    # cryptsetup/pvcreate/mkfs never encounter a stale-signature warning.
    log_info "Clearing any residual signatures on new partitions..."
    wipefs -af "${DATA_PART}" &>/dev/null || true
    [[ -n "${EFI_PART}" ]] && wipefs -af "${EFI_PART}" &>/dev/null || true

    log_success "Partitioning complete."
}

# ============================================================================
# ENCRYPTION (conditional)
# ============================================================================
setup_encryption() {
    ${USE_ENCRYPTION} || { ROOT_SRC_PART="${DATA_PART}"; return 0; }

    section "LUKS2 Encryption"
    log_info "Formatting ${DATA_PART} with LUKS2..."
    echo -n "${LUKS_PASSWORD}" | cryptsetup luksFormat \
        --type luks2 --cipher aes-xts-plain64 --hash sha512 \
        --key-size 512 --pbkdf argon2id --iter-time 3000 \
        --batch-mode \
        "${DATA_PART}" - \
        || die "LUKS format failed."

    echo -n "${LUKS_PASSWORD}" | cryptsetup open "${DATA_PART}" "${LUKS_NAME}" - \
        || die "Failed to open LUKS container."
    LUKS_OPEN=true

    LUKS_UUID="$(cryptsetup luksUUID "${DATA_PART}")"
    [[ -n "${LUKS_UUID}" ]] || die "Failed to read LUKS UUID."

    ROOT_SRC_PART="/dev/mapper/${LUKS_NAME}"
    log_success "LUKS2 container opened as ${LUKS_NAME}."
}

# ============================================================================
# LVM (conditional)
# ============================================================================
setup_lvm() {
    ${USE_LVM} || return 0

    section "LVM2 Setup"
    pvcreate -ff -y "${ROOT_SRC_PART}" || die "Failed to create physical volume."
    vgcreate "${VG_NAME}" "${ROOT_SRC_PART}" || die "Failed to create volume group."
    VG_ACTIVE=true

    # Work in MiB throughout so all arithmetic is integer and exact.
    local vg_size_mib
    vg_size_mib=$(vgs --noheadings --units m --nosuffix -o vg_size "${VG_NAME}" 2>/dev/null \
        | tr -d '[:space:]')
    vg_size_mib=${vg_size_mib%%.*}
    [[ "${vg_size_mib}" =~ ^[0-9]+$ ]] || die "Could not determine volume group size."

    # Swap: sized off RAM (capped 512M-8G), but never more than a quarter
    # of the whole VG so it can't crowd out root+home on small disks.
    local ram_kb swap_mib max_swap_mib
    ram_kb=$(awk '/MemTotal/{print $2}' /proc/meminfo)
    swap_mib=$(( (ram_kb / 1024) + 1024 ))
    (( swap_mib > 8192 )) && swap_mib=8192
    (( swap_mib < 512 )) && swap_mib=512
    max_swap_mib=$(( vg_size_mib / 4 ))
    (( swap_mib > max_swap_mib )) && swap_mib=${max_swap_mib}
    (( swap_mib < 256 )) && swap_mib=256

    log_info "Creating logical volume: swap (${swap_mib} MiB)..."
    lvcreate -L "${swap_mib}M" -n "${LV_SWAP}" "${VG_NAME}" || die "Failed to create swap LV."

    local remaining_mib=$(( vg_size_mib - swap_mib ))

    # Root: prefer 20 GiB, but never take more than 60% of what's left
    # after swap, and never so much that home would have no room.
    # On small disks (<=12 GiB remaining) skip a separate /home LV
    # entirely and let root use all remaining space.
    local root_mib
    if (( remaining_mib <= 12288 )); then
        SEPARATE_HOME_LV=false
        root_mib=${remaining_mib}
        log_warn "Disk is small - skipping a separate /home volume; root will use all remaining space."
    else
        SEPARATE_HOME_LV=true
        root_mib=20480
        local root_cap_mib=$(( remaining_mib * 60 / 100 ))
        (( root_mib > root_cap_mib )) && root_mib=${root_cap_mib}
        (( root_mib < 8192 )) && root_mib=8192
        # Always leave at least 1 GiB free for the home LV.
        (( root_mib > remaining_mib - 1024 )) && root_mib=$(( remaining_mib - 1024 ))
    fi

    log_info "Creating logical volume: root (${root_mib} MiB)..."
    lvcreate -L "${root_mib}M" -n "${LV_ROOT}" "${VG_NAME}" || die "Failed to create root LV."

    if ${SEPARATE_HOME_LV}; then
        log_info "Creating logical volume: home (remaining space)..."
        lvcreate -l 100%FREE -n "${LV_HOME}" "${VG_NAME}" || die "Failed to create home LV."
    fi

    log_success "LVM2 logical volumes created."
}

# ============================================================================
# FILESYSTEM CREATION
# ============================================================================
create_filesystems() {
    section "Filesystem Creation"

    if [[ "${BOOT_MODE}" == "uefi" ]]; then
        log_info "Formatting EFI partition as FAT32..."
        mkfs.fat -F32 "${EFI_PART}" || die "Failed to format EFI partition."
    fi

    if ${USE_LVM}; then
        log_info "Formatting root LV as ext4..."
        mkfs.ext4 -F "/dev/${VG_NAME}/${LV_ROOT}" || die "Failed to format root filesystem."
        if ${SEPARATE_HOME_LV}; then
            log_info "Formatting home LV as ext4..."
            mkfs.ext4 -F "/dev/${VG_NAME}/${LV_HOME}" || die "Failed to format home filesystem."
        fi
        log_info "Setting up swap LV..."
        mkswap "/dev/${VG_NAME}/${LV_SWAP}" || die "Failed to initialize swap."
    else
        log_info "Formatting root partition as ext4..."
        mkfs.ext4 -F "${ROOT_SRC_PART}" || die "Failed to format root filesystem."
    fi

    log_success "Filesystems created."
}

# ============================================================================
# MOUNTING
# ============================================================================
mount_filesystems() {
    section "Mounting Filesystems"

    local root_dev
    if ${USE_LVM}; then
        root_dev="/dev/${VG_NAME}/${LV_ROOT}"
    else
        root_dev="${ROOT_SRC_PART}"
    fi

    mount "${root_dev}" /mnt || die "Failed to mount root filesystem."
    MOUNTED_PATHS+=("/mnt")

    if [[ "${BOOT_MODE}" == "uefi" ]]; then
        mkdir -p /mnt/boot
        mount "${EFI_PART}" /mnt/boot || die "Failed to mount EFI partition."
        MOUNTED_PATHS+=("/mnt/boot")
    fi

    if ${USE_LVM}; then
        if ${SEPARATE_HOME_LV}; then
            mkdir -p /mnt/home
            mount "/dev/${VG_NAME}/${LV_HOME}" /mnt/home || die "Failed to mount home."
            MOUNTED_PATHS+=("/mnt/home")
        fi

        swapon "/dev/${VG_NAME}/${LV_SWAP}" || die "Failed to enable swap."
        SWAP_ACTIVE=true
    fi

    log_success "Filesystems mounted."
}

# ============================================================================
# BASE PACKAGE INSTALLATION
# ============================================================================
install_base_system() {
    section "Installing Base System"
    log_info "Refreshing package database..."
    pacman -Sy --noconfirm || die "Failed to refresh package database."

    local -a packages=(
        base base-devel linux linux-firmware linux-headers
        grub sudo vim nano networkmanager dosfstools e2fsprogs mtools
    )
    [[ -n "${MICROCODE_PACKAGE}" ]] && packages+=("${MICROCODE_PACKAGE}")
    ${USE_ENCRYPTION} && packages+=(cryptsetup)
    ${USE_LVM} && packages+=(lvm2)
    [[ "${BOOT_MODE}" == "uefi" ]] && packages+=(efibootmgr)

    log_info "Installing: ${packages[*]}"
    pacstrap -K /mnt "${packages[@]}" || die "Base package installation failed."
    log_success "Base system installed."
}

generate_fstab() {
    section "Generating fstab"
    genfstab -U /mnt >> /mnt/etc/fstab || die "Failed to generate fstab."
    log_success "fstab generated."
}

# ============================================================================
# CHROOT SYSTEM CONFIGURATION
# ============================================================================
configure_system() {
    section "Configuring System"

    cat > /mnt/root/chroot_setup.sh << 'CHROOT_EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
HOSTNAME="$1"; USERNAME="$2"; ROOT_PASSWORD="$3"
USER_PASSWORD="$4"; TIMEZONE="$5"; LOCALE="$6"

ln -sf "/usr/share/zoneinfo/${TIMEZONE}" /etc/localtime
hwclock --systohc

sed -i "s/^#${LOCALE} UTF-8/${LOCALE} UTF-8/" /etc/locale.gen
locale-gen
echo "LANG=${LOCALE}" > /etc/locale.conf
echo "KEYMAP=us" > /etc/vconsole.conf

echo "${HOSTNAME}" > /etc/hostname
cat > /etc/hosts << HOSTS_EOF
127.0.0.1   localhost
::1         localhost
127.0.1.1   ${HOSTNAME}.localdomain ${HOSTNAME}
HOSTS_EOF

echo "root:${ROOT_PASSWORD}" | chpasswd
useradd -m -G wheel -s /bin/bash "${USERNAME}"
echo "${USERNAME}:${USER_PASSWORD}" | chpasswd

echo "%wheel ALL=(ALL:ALL) ALL" > /etc/sudoers.d/wheel
chmod 440 /etc/sudoers.d/wheel

systemd-machine-id-setup
CHROOT_EOF

    chmod +x /mnt/root/chroot_setup.sh
    arch-chroot /mnt /root/chroot_setup.sh \
        "${HOSTNAME}" "${USERNAME}" "${ROOT_PASSWORD}" \
        "${USER_PASSWORD}" "${TIMEZONE}" "${LOCALE}" \
        || die "Chroot system configuration failed."
    rm -f /mnt/root/chroot_setup.sh

    log_success "System configuration complete."
}

# ============================================================================
# MKINITCPIO (conditional hooks)
# ============================================================================
configure_mkinitcpio() {
    section "Configuring mkinitcpio"

    # We intentionally use the classic (non-systemd) mkinitcpio hooks for
    # encrypted installs. The systemd hook "sd-encrypt" delegates password
    # entry to systemd-ask-password, which echoes an asterisk for every
    # keystroke on screen. The classic "encrypt" hook calls cryptsetup's
    # own prompt directly, which shows no characters at all while typing.
    local hooks
    if ${USE_ENCRYPTION} && ${USE_LVM}; then
        hooks="HOOKS=(base udev autodetect microcode modconf kms keyboard keymap block encrypt lvm2 filesystems fsck)"
    elif ${USE_ENCRYPTION}; then
        hooks="HOOKS=(base udev autodetect microcode modconf kms keyboard keymap block encrypt filesystems fsck)"
    elif ${USE_LVM}; then
        hooks="HOOKS=(base udev autodetect microcode modconf kms keyboard keymap block lvm2 filesystems fsck)"
    else
        hooks="HOOKS=(base udev autodetect microcode modconf kms keyboard keymap block filesystems fsck)"
    fi

    cp /mnt/etc/mkinitcpio.conf /mnt/etc/mkinitcpio.conf.bak
    sed -i "s/^HOOKS=.*/${hooks}/" /mnt/etc/mkinitcpio.conf

    arch-chroot /mnt mkinitcpio -P || die "Failed to regenerate initramfs."
    log_success "mkinitcpio configured (encryption: ${USE_ENCRYPTION}, lvm: ${USE_LVM})."
}

# ============================================================================
# BOOTLOADER (GRUB - UEFI or BIOS)
# ============================================================================
install_bootloader() {
    section "Installing Bootloader (GRUB - ${BOOT_MODE^^})"

    if ${USE_ENCRYPTION}; then
        if ! grep -q "^GRUB_ENABLE_CRYPTODISK=y" /mnt/etc/default/grub; then
            echo "GRUB_ENABLE_CRYPTODISK=y" >> /mnt/etc/default/grub
        fi

        local root_map
        if ${USE_LVM}; then
            root_map="/dev/mapper/${VG_NAME}-${LV_ROOT}"
        else
            root_map="/dev/mapper/${LUKS_NAME}"
        fi
        # cryptdevice= is what the classic "encrypt" mkinitcpio hook reads;
        # it auto-activates any LVM volume group found inside once opened,
        # so no separate rd.lvm.vg parameter is needed here.
        local cmdline="cryptdevice=UUID=${LUKS_UUID}:${LUKS_NAME} root=${root_map} quiet"
        sed -i "s|^GRUB_CMDLINE_LINUX=.*|GRUB_CMDLINE_LINUX=\"${cmdline}\"|" /mnt/etc/default/grub
    fi

    if [[ "${BOOT_MODE}" == "uefi" ]]; then
        arch-chroot /mnt grub-install --target=x86_64-efi \
            --efi-directory=/boot --bootloader-id=GRUB --recheck \
            || die "GRUB EFI installation failed."
    else
        arch-chroot /mnt grub-install --target=i386-pc --recheck "${DISK}" \
            || die "GRUB BIOS installation failed."
    fi

    arch-chroot /mnt grub-mkconfig -o /boot/grub/grub.cfg \
        || die "Failed to generate GRUB configuration."

    log_success "Bootloader installed and configured."
}

# ============================================================================
# ESSENTIAL SERVICES
# ============================================================================
enable_core_services() {
    section "Enabling Core Services"
    arch-chroot /mnt systemctl enable NetworkManager.service \
        || die "Failed to enable NetworkManager."
    log_success "NetworkManager enabled."
}

# ============================================================================
# DESKTOP ENVIRONMENT SELECTION (optional)
# ============================================================================
desktop_environment_packages() {
    # Echoes the space-separated package list for the chosen DE.
    case "$1" in
        "KDE Plasma")  echo "plasma-desktop konsole dolphin plasma-nm plasma-pa sddm-kcm" ;;
        "GNOME")       echo "gnome gnome-tweaks" ;;
        "XFCE")        echo "xfce4 xfce4-goodies" ;;
        "Cinnamon")    echo "cinnamon" ;;
        "MATE")        echo "mate mate-extra" ;;
        "LXQt")        echo "lxqt breeze-icons" ;;
        "Hyprland")    echo "hyprland xdg-desktop-portal-hyprland xdg-desktop-portal qt5-wayland qt6-wayland waybar kitty wofi mako hyprpaper hyprlock hypridle grim slurp wl-clipboard polkit-gnome" ;;
        "Sway")        echo "sway swaybg swaylock swayidle foot" ;;
        "i3")          echo "i3-wm i3status i3lock dmenu xterm" ;;
        *)             echo "" ;;
    esac
}

select_desktop_environment() {
    section "Desktop Environment"
    if ! confirm_yes_no "Would you like to install a desktop environment?"; then
        DESKTOP_ENV="none"
        log_info "Skipping desktop environment - base system only."
        return 0
    fi

    local -a de_names=("KDE Plasma" "GNOME" "XFCE" "Cinnamon" "MATE" "LXQt" "Hyprland" "Sway" "i3" "None")
    local choice
    choose_option choice "Select a Desktop Environment" "${de_names[@]}"
    DESKTOP_ENV="${de_names[$((choice-1))]}"

    if [[ "${DESKTOP_ENV}" == "None" ]]; then
        DESKTOP_ENV="none"
        log_info "No desktop environment selected."
        return 0
    fi

    log_success "Selected desktop environment: ${DESKTOP_ENV}"
}

select_display_manager() {
    [[ "${DESKTOP_ENV}" == "none" ]] && { DISPLAY_MANAGER="none"; return 0; }

    section "Display Manager"
    local -a dm_names=("SDDM" "GDM" "LightDM" "Ly" "None")
    local choice
    choose_option choice "Choose a Display Manager" "${dm_names[@]}"
    DISPLAY_MANAGER="${dm_names[$((choice-1))]}"
    log_success "Selected display manager: ${DISPLAY_MANAGER}"
}

display_manager_package_and_service() {
    case "$1" in
        "SDDM")    echo "sddm sddm.service" ;;
        "GDM")     echo "gdm gdm.service" ;;
        "LightDM") echo "lightdm lightdm-gtk-greeter lightdm.service" ;;
        "Ly")      echo "ly ly.service" ;;
        *)         echo "" ;;
    esac
}

install_desktop_environment() {
    [[ "${DESKTOP_ENV}" == "none" ]] && return 0

    section "Installing Desktop Environment: ${DESKTOP_ENV}"
    local de_packages; de_packages="$(desktop_environment_packages "${DESKTOP_ENV}")"
    if [[ -n "${de_packages}" ]]; then
        log_info "Installing: ${de_packages}"
        # shellcheck disable=SC2086
        arch-chroot /mnt pacman -S --noconfirm ${de_packages} \
            || die "Desktop environment package installation failed."
    fi

    if [[ "${DISPLAY_MANAGER}" != "none" ]]; then
        local dm_info dm_pkg dm_service
        dm_info="$(display_manager_package_and_service "${DISPLAY_MANAGER}")"
        dm_pkg="${dm_info% *}"
        dm_service="${dm_info#* }"
        log_info "Installing display manager: ${dm_pkg}"
        arch-chroot /mnt pacman -S --noconfirm "${dm_pkg}" \
            || die "Display manager installation failed."
        arch-chroot /mnt systemctl enable "${dm_service}" \
            || die "Failed to enable ${dm_service}."
        log_success "Display manager ${DISPLAY_MANAGER} enabled."
    fi

    log_success "Desktop environment installation complete."
}

# ============================================================================
# OPTIONAL SOFTWARE MENUS
# ============================================================================
# multi_select: prompts a comma-separated numeric selection against a menu
# and returns the corresponding package names via a nameref-style echo.
multi_select_packages() {
    local title="$1"; shift
    local -a labels=("$@")
    box_menu "${title}" "${labels[@]}" "Skip this category"
    local raw
    prompt_text raw "Enter numbers separated by spaces (e.g. 1 3 4), or press Enter to skip"

    local -a chosen=()
    local skip_index=$(( ${#labels[@]} + 1 ))
    for token in ${raw}; do
        [[ "${token}" =~ ^[0-9]+$ ]] || continue
        (( token >= 1 && token <= ${#labels[@]} )) || continue
        (( token == skip_index )) && continue
        chosen+=("${labels[$((token-1))]}")
    done
    echo "${chosen[@]}"
}

select_optional_software() {
    section "Optional Software"
    if ! confirm_yes_no "Would you like to install any optional software bundles?"; then
        return 0
    fi

    section "Development Tools"
    read -ra SELECTED_DEV_PKGS <<< "$(multi_select_packages "Development" \
        "Git" "VS Code (code)" "Neovim" "Docker" "Podman")"

    section "Networking Tools"
    read -ra SELECTED_NET_PKGS <<< "$(multi_select_packages "Networking" \
        "OpenSSH" "Tailscale" "WireGuard Tools")"

    section "Utilities"
    read -ra SELECTED_UTIL_PKGS <<< "$(multi_select_packages "Utilities" \
        "htop" "fastfetch" "tree" "tmux" "btop")"
}

# Translate friendly labels to actual pacman package names.
map_label_to_package() {
    case "$1" in
        "Git") echo "git" ;;
        "VS Code (code)") echo "code" ;;
        "Neovim") echo "neovim" ;;
        "Docker") echo "docker" ;;
        "Podman") echo "podman" ;;
        "OpenSSH") echo "openssh" ;;
        "Tailscale") echo "tailscale" ;;
        "WireGuard Tools") echo "wireguard-tools" ;;
        "htop") echo "htop" ;;
        "fastfetch") echo "fastfetch" ;;
        "tree") echo "tree" ;;
        "tmux") echo "tmux" ;;
        "btop") echo "btop" ;;
        *) echo "" ;;
    esac
}

install_optional_software() {
    local -a all_labels=("${SELECTED_DEV_PKGS[@]-}" "${SELECTED_NET_PKGS[@]-}" "${SELECTED_UTIL_PKGS[@]-}")
    local -a packages=()
    local -a services=()

    for label in "${all_labels[@]}"; do
        [[ -z "${label}" ]] && continue
        local pkg; pkg="$(map_label_to_package "${label}")"
        [[ -n "${pkg}" ]] && packages+=("${pkg}")
        case "${label}" in
            "Docker")   services+=("docker.service") ;;
            "OpenSSH")  services+=("sshd.service") ;;
            "Tailscale") services+=("tailscaled.service") ;;
        esac
    done

    (( ${#packages[@]} == 0 )) && { log_info "No optional software selected."; return 0; }

    section "Installing Optional Software"
    log_info "Installing: ${packages[*]}"
    arch-chroot /mnt pacman -S --noconfirm "${packages[@]}" \
        || die "Optional software installation failed."

    for svc in "${services[@]}"; do
        arch-chroot /mnt systemctl enable "${svc}" 2>/dev/null \
            && log_success "Enabled ${svc}." \
            || log_warn "Could not enable ${svc} (package may not provide a matching unit)."
    done

    log_success "Optional software installation complete."
}

# ============================================================================
# FINAL CLEANUP (successful path)
# ============================================================================
final_cleanup() {
    section "Final Cleanup"
    cp "${LOG_FILE}" /mnt/root/install_log.txt 2>/dev/null || true
    sync
    log_success "Cleanup complete."
}

# ============================================================================
# SUMMARY / CONFIRMATION
# ============================================================================
print_summary_and_confirm() {
    section "Installation Summary"
    cat << EOF
  ${C_WHITE}Boot mode:${C_RESET}      ${BOOT_MODE^^}
  ${C_WHITE}Partitioning:${C_RESET}   ${PART_SCHEME^^}
  ${C_WHITE}Disk:${C_RESET}           ${DISK}
  ${C_WHITE}Layout:${C_RESET}         ${DISK_LAYOUT}
  ${C_WHITE}Encryption:${C_RESET}     ${USE_ENCRYPTION}
  ${C_WHITE}LVM:${C_RESET}            ${USE_LVM}
  ${C_WHITE}Hostname:${C_RESET}       ${HOSTNAME}
  ${C_WHITE}Username:${C_RESET}       ${USERNAME}
  ${C_WHITE}Timezone:${C_RESET}       ${TIMEZONE}
  ${C_WHITE}Locale:${C_RESET}         ${LOCALE}
  ${C_WHITE}CPU:${C_RESET}            ${CPU_VENDOR}
EOF
    echo
    confirm_yes_no "Proceed with installation? This will erase ${DISK}" \
        || die "Installation cancelled by user."
}

# ============================================================================
# MAIN
# ============================================================================
main() {
    banner "Arch Linux Installer  v${SCRIPT_VERSION}"
    echo "Arch Linux Installation Log - $(date)" > "${LOG_FILE}"

    section "Pre-flight Checks"
    validate_root
    sync_clock

    select_boot_mode
    detect_cpu_vendor
    select_disk
    select_disk_layout
    gather_user_input
    select_desktop_environment
    select_display_manager
    select_optional_software

    print_summary_and_confirm

    run_step_sequence \
        "Partitioning disk|partition_disk" \
        "Configuring encryption|setup_encryption" \
        "Configuring LVM|setup_lvm" \
        "Creating filesystems|create_filesystems" \
        "Mounting filesystems|mount_filesystems" \
        "Installing base system|install_base_system" \
        "Generating fstab|generate_fstab" \
        "Configuring system|configure_system" \
        "Configuring mkinitcpio|configure_mkinitcpio" \
        "Installing bootloader|install_bootloader" \
        "Enabling core services|enable_core_services" \
        "Installing desktop environment|install_desktop_environment" \
        "Installing optional software|install_optional_software" \
        "Finalizing installation|final_cleanup"

    banner "Installation Complete"
    local width; width=$(term_width); (( width > 70 )) && width=70
    echo -e "  ${C_GREEN}+$(printf -- '-%.0s' $(seq 1 $((width-2))))+${C_RESET}"
    printf "  ${C_GREEN}|${C_RESET} ${ICON_OK} ${C_BOLD}%-*s${C_GREEN}|${C_RESET}\n" $((width-9)) "Arch Linux installed successfully"
    echo -e "  ${C_GREEN}+$(printf -- '-%.0s' $(seq 1 $((width-2))))+${C_RESET}"
    printf "  ${C_GREEN}|${C_RESET} %-*s ${C_GREEN}|${C_RESET}\n" $((width-4)) ""
    printf "  ${C_GREEN}|${C_RESET} %-*s ${C_GREEN}|${C_RESET}\n" $((width-4)) "  Hostname:   ${HOSTNAME}"
    printf "  ${C_GREEN}|${C_RESET} %-*s ${C_GREEN}|${C_RESET}\n" $((width-4)) "  Username:   ${USERNAME}"
    printf "  ${C_GREEN}|${C_RESET} %-*s ${C_GREEN}|${C_RESET}\n" $((width-4)) "  Boot mode:  ${BOOT_MODE^^}"
    [[ "${DESKTOP_ENV}" != "none" ]] && \
        printf "  ${C_GREEN}|${C_RESET} %-*s ${C_GREEN}|${C_RESET}\n" $((width-4)) "  Desktop:    ${DESKTOP_ENV} (${DISPLAY_MANAGER})"
    printf "  ${C_GREEN}|${C_RESET} %-*s ${C_GREEN}|${C_RESET}\n" $((width-4)) ""
    echo -e "  ${C_GREEN}+$(printf -- '-%.0s' $(seq 1 $((width-2))))+${C_RESET}"
    echo
    echo -e "  ${C_CYAN}Next steps:${C_RESET}"
    echo -e "    1) ${C_WHITE}umount -R /mnt${C_RESET}"
    if ${SWAP_ACTIVE}; then
        echo -e "    2) ${C_WHITE}swapoff -a${C_RESET}"
        echo -e "    3) ${C_WHITE}reboot${C_RESET}"
    else
        echo -e "    2) ${C_WHITE}reboot${C_RESET}"
    fi
    echo
    echo -e "  Log saved to: ${C_DIM}${LOG_FILE}${C_RESET}"
    echo
}

main "$@"
