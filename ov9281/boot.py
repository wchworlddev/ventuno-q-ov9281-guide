# SPDX-License-Identifier: MIT
"""Add an optional CAMERA0 entry, select one boot, and remove it afterwards."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat

from .common import (
    BOOT, ENTRY, GRUB, GRUBENV, KERNEL, MARKER, MENU, PLATFORM, STOCK_MODULE,
    command, program, protected_file, require, reviewed_kernel, root_required, sha256,
)
from .dtree import build_candidate, read_fdt

VOLATILE = {
    '/serial-number', '/chosen/bootargs', '/chosen/linux,initrd-start',
    '/chosen/linux,initrd-end', '/chosen/kaslr-seed', '/chosen/rng-seed',
    '/chosen/linux,uefi-system-table', '/chosen/linux,uefi-mmap-start',
    '/chosen/linux,uefi-mmap-size', '/firmware/qcom,platform-parts-info/serial-number',
}


def hardware_fingerprint(properties):
    stable = {key: value.hex() for key, value in properties.items()
              if key not in VOLATILE and not key.endswith(('/mac-address', '/local-mac-address'))}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def environment():
    output = command(program('grub-editenv'), GRUBENV, 'list')
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


def root_uuid():
    value = command(program('findmnt'), '-n', '-o', 'UUID', '/')
    require(re.fullmatch(r'[0-9a-fA-F-]{36}', value), 'Root filesystem UUID is unavailable.')
    return value


def inspect():
    root_required()
    reviewed_kernel()
    protected_file(GRUB)
    protected_file(GRUBENV)
    props, _, _ = read_fdt('/sys/firmware/fdt')
    uuid = root_uuid()
    words = Path('/proc/cmdline').read_text().split()
    info = GRUBENV.lstat()
    layout_hash = hashlib.sha256(GRUB.read_text().replace(uuid, '<ROOT_UUID>').encode()).hexdigest()
    checks = {
        'stock_boot': not any(word.startswith('ov9281_') for word in words),
        'root_uuid_matches': 'root=UUID=' + uuid in words,
        'reviewed_hardware': hardware_fingerprint(props) == PLATFORM['hardware_properties_sha256'],
        'reviewed_grub_layout': layout_hash == PLATFORM['grub_layout_sha256'],
        'reviewed_stock_module': sha256(STOCK_MODULE) == PLATFORM['stock_camss_sha256'],
        'optional_menu_unused': not MENU.exists() and not MENU.is_symlink(),
        'test_directory_unused': not BOOT.exists() and not BOOT.is_symlink(),
        'no_earlier_persistent_port': not Path('/usr/local/lib/ov9281-camera').exists(),
        'no_pending_grub_state': not any(environment().values()),
        'regular_allocated_grub_environment': stat.S_ISREG(info.st_mode) and info.st_uid == 0
            and info.st_size == 1024 and info.st_blocks * 512 >= 1024,
        'direct_reviewed_storage': command(program('grub-probe'), '--target=device', GRUBENV) == PLATFORM['grub_device']
            and command(program('grub-probe'), '--target=fs', GRUBENV) == 'ext2'
            and not command(program('grub-probe'), '--target=abstraction', GRUBENV),
        'kernel_and_initrd_present': all((Path('/boot') / (prefix + KERNEL)).is_file()
                                       for prefix in ('vmlinuz-', 'initrd.img-')),
    }
    return {'kernel': KERNEL, 'root_uuid': uuid, 'checks': checks,
            'ready': all(checks.values()), 'grub_sha256': sha256(GRUB)}


def menu_text(uuid, candidate, arguments):
    return f'''# OV9281 guide: optional CAMERA0 entry for one boot.
menuentry 'Ubuntu - OV9281 CAMERA0 one-time test' --id {ENTRY} {{
    insmod gzio
    insmod part_gpt
    insmod ext2
    search --no-floppy --fs-uuid --set=root {uuid}
    insmod fdt
    if devicetree {candidate}; then
        if linux /boot/vmlinuz-{KERNEL} {arguments}; then
            if initrd /boot/initrd.img-{KERNEL}; then
                boot
            fi
        fi
    fi
    echo 'Camera entry failed; restarting into stock Ubuntu.'
    sleep 3
    insmod reboot
    reboot
}}
'''


def cancel_own_selection():
    if environment().get('next_entry') == ENTRY:
        command(program('grub-editenv'), GRUBENV, 'unset', 'next_entry')


def prepare():
    report = inspect()
    require(report['ready'], 'Preflight failed: ' + ', '.join(k for k, v in report['checks'].items() if not v))
    words = [word for word in Path('/proc/cmdline').read_text().split() if not word.startswith('BOOT_IMAGE=')]
    require(all(re.fullmatch(r'[A-Za-z0-9_.,:/=+@-]+', word) for word in words), 'Kernel arguments need quoting review.')
    for name in ('dtc', 'fdtoverlay', 'grub-script-check', 'grub-reboot'):
        program(name)
    BOOT.mkdir(mode=0o755)
    created_menu = False
    text = None
    try:
        base = BOOT / 'stock-firmware.dtb'
        with base.open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(Path('/sys/firmware/fdt').read_bytes())
        validation = build_candidate(base, BOOT / 'candidate')
        candidate = BOOT / 'candidate/camera0-ov9281-candidate.dtb'
        arguments = ' '.join(words) + ' module_blacklist=camera_qcs8300,camera_qcs9100,camera_qcm6490 ov9281_port_test=1 ' + MARKER
        text = menu_text(report['root_uuid'], candidate, arguments)
        preview = BOOT / 'menu.cfg'
        preview.write_text(text)
        command(program('grub-script-check'), preview)
        require(sha256(GRUB) == report['grub_sha256'] and not any(environment().values()), 'Boot state changed during preparation.')
        with MENU.open('xb') as output:
            created_menu = True
            os.fchmod(output.fileno(), 0o644)
            output.write(text.encode())
            output.flush()
            os.fsync(output.fileno())
        report.update(menu_sha256=sha256(MENU), candidate_sha256=validation['candidate_sha256'])
        with (BOOT / 'state.json').open('x') as output:
            os.fchmod(output.fileno(), 0o644)
            output.write(json.dumps(report, indent=2) + '\n')
            output.flush()
            os.fsync(output.fileno())
        command(program('grub-reboot'), ENTRY)
        require(environment() == {'next_entry': ENTRY}, 'One-time selection differs.')
        os.sync()
        return {'selected_for_one_boot': True, 'reboot_command': 'sudo reboot', 'following_restart': 'stock Ubuntu'}
    except BaseException:
        # Keep the candidate/menu intact if cancellation fails, so recovery
        # remains possible rather than deleting a still-selected entry.
        cancel_own_selection()
        if created_menu:
            require(MENU.is_file() and not MENU.is_symlink() and MENU.read_text() == text,
                    'The optional menu changed; staged files retained for manual review.')
            MENU.unlink()
        shutil.rmtree(BOOT)
        os.sync()
        raise


def state():
    root_required()
    info = BOOT.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
            'Expected a protected guide boot directory.')
    for path in (BOOT / 'state.json', GRUB, MENU):
        protected_file(path)
    record = json.loads((BOOT / 'state.json').read_text())
    require(not MENU.is_symlink() and sha256(GRUB) == record['grub_sha256']
            and sha256(MENU) == record['menu_sha256'], 'Boot files changed; stop for manual review.')
    return record


def repeat():
    reviewed_kernel()
    record = state()
    require(root_uuid() == record['root_uuid'] and not any(environment().values()), 'Root disk or pending GRUB state differs.')
    require(sha256(BOOT / 'candidate/camera0-ov9281-candidate.dtb') == record['candidate_sha256'], 'Candidate differs.')
    try:
        command(program('grub-reboot'), ENTRY)
        require(environment() == {'next_entry': ENTRY}, 'One-time selection differs.')
    except BaseException:
        cancel_own_selection()
        raise
    os.sync()
    return {'selected_for_one_boot': True, 'reboot_command': 'sudo reboot'}


def cleanup():
    state()
    cancel_own_selection()
    MENU.unlink()
    shutil.rmtree(BOOT)
    os.sync()
    return {'temporary_boot_files_removed': True, 'active_session_changed': False, 'next_restart': 'stock Ubuntu'}
