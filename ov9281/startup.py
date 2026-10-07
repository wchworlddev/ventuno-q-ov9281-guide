# SPDX-License-Identifier: MIT
"""Optional CAMERA0 startup with protected assets and a stock-boot fallback."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from . import boot, capture, discovery, kernel
from .common import (
    BOOT, BUILD, GRUBENV, KERNEL, MENU, PERSIST_MARKER, ROOT,
    atomic_write, boot_id, command, program, protected_directory, protected_file,
    require, reviewed_kernel, root_required, sha256, write_json,
)

INSTALLED = Path('/usr/local/lib/ov9281-guide')
RECORD = BOOT / 'startup.json'
UNIT = Path('/etc/systemd/system/ov9281-guide-camera.service')
HOOK = Path('/etc/kernel/postinst.d/zzzz-ov9281-guide')
PENDING = 'ov9281_guide_pending'
DISABLED = 'ov9281_guide_disabled'
PERSIST_ENTRY = 'ov9281-guide-persistent'
UNIT_TEXT = f'''[Unit]
Description=OV9281 CAMERA0 on the reviewed VENTUNO Q kernel
After=systemd-udev-settle.service
Wants=systemd-udev-settle.service
ConditionKernelCommandLine={PERSIST_MARKER}
Before=multi-user.target

[Service]
Type=oneshot
Environment=PYTHONNOUSERSITE=1
ExecStart=/usr/bin/python3 -s {INSTALLED}/camera.py startup-configure
RemainAfterExit=yes
TimeoutStartSec=45

[Install]
WantedBy=multi-user.target
'''
HOOK_TEXT = f'''#!/bin/sh
# A module built for another kernel must be reviewed again.
if [ "$1" != "{KERNEL}" ]; then
    rm -f {BOOT}/enabled
    /usr/bin/grub-editenv {GRUBENV} set {DISABLED}=1 || :
    echo "OV9281 guide: new kernel; automatic camera boot disabled."
fi
exit 0
'''


def flags(pending, disabled):
    command(program('grub-editenv'), GRUBENV, 'set', f'{PENDING}={pending}', f'{DISABLED}={disabled}')


def latest_kernel():
    require(Path('/boot/vmlinuz').resolve() == Path('/boot/vmlinuz-' + KERNEL),
            'Latest installed kernel differs. Review/rebuild before enabling camera startup.')


def checked_environment():
    env = boot.environment()
    require(set(env) <= {'next_entry', PENDING, DISABLED} and not env.get('next_entry'),
            'Another boot selection exists; stop before changing it.')
    return env


def installed():
    state = boot.state()
    protected_directory(INSTALLED)
    protected_file(RECORD)
    record = json.loads(RECORD.read_text())
    for relative, digest in record['files'].items():
        path = Path(relative)
        require(not path.is_absolute() and '..' not in path.parts, 'Invalid installed asset path.')
        for parent in path.parents:
            protected_directory(INSTALLED / parent)
        protected_file(INSTALLED / path)
        require(sha256(INSTALLED / path) == digest, 'Installed asset changed: ' + relative)
    for path, content in ((UNIT, UNIT_TEXT), (HOOK, HOOK_TEXT)):
        protected_file(path)
        require(path.read_text() == content, 'Startup service/hook differs; stop for review.')
    for path, field in ((BOOT / 'original-test-menu.cfg', 'original_menu_sha256'),
                        (BOOT / 'original-test-state.json', 'original_state_sha256')):
        protected_file(path)
        require(sha256(path) == record[field], 'Original boot backup differs.')
    return state, record


def menu(state, original):
    for field in ('stock_arguments', 'camera_arguments'):
        require(all(re.fullmatch(r'[A-Za-z0-9_.,:/=+@-]+', word) for word in state[field].split()),
                'Saved kernel arguments need quoting review.')
    uuid = state['root_uuid']
    require(re.fullmatch(r'[0-9a-fA-F-]{36}', uuid), 'Saved root UUID differs.')
    candidate = BOOT / 'candidate/camera0-ov9281-candidate.dtb'
    return original.rstrip() + f'''

# Explicit one-time selections retain priority. An unfinished camera boot
# selects the stock default on the next restart.
if [ "${{boot_once}}" != true ]; then
    if [ "${{{DISABLED}}}" != 1 ]; then
        if [ "${{{PENDING}}}" != 1 ]; then
            if [ -e {BOOT}/enabled ]; then
                if [ -e /boot/vmlinuz-{KERNEL} ]; then
                    if [ -e /boot/initrd.img-{KERNEL} ]; then
                        set default={PERSIST_ENTRY}
                    fi
                fi
            fi
        fi
    fi
fi

menuentry 'Ubuntu - OV9281 CAMERA0 automatic startup' --id {PERSIST_ENTRY} {{
    insmod gzio
    insmod part_gpt
    insmod ext2
    search --no-floppy --fs-uuid --set=root {uuid}
    set {PENDING}=1
    if save_env {PENDING}; then
        insmod fdt
        if devicetree {candidate}; then
            if linux /boot/vmlinuz-{KERNEL} {state['camera_arguments']} {PERSIST_MARKER}; then
                if initrd /boot/initrd.img-{KERNEL}; then
                    boot
                fi
            fi
        fi
    else
        echo 'Cannot save camera recovery flag; booting stock Ubuntu.'
        if linux /boot/vmlinuz-{KERNEL} {state['stock_arguments']}; then
            if initrd /boot/initrd.img-{KERNEL}; then
                boot
            fi
        fi
    fi
    echo 'Camera entry failed; restarting into stock Ubuntu.'
    insmod reboot
    reboot
}}
'''


def enable():
    root_required()
    reviewed_kernel()
    latest_kernel()
    kernel.healthy_kernel()
    checked_environment()
    if RECORD.exists() or RECORD.is_symlink():
        state, _ = installed()
        discovery.verify()
        require(sha256(BOOT / 'candidate/camera0-ov9281-candidate.dtb') == state['candidate_sha256'],
                'Candidate device tree changed.')
        require(boot.root_uuid() == state['root_uuid'], 'Root disk changed.')
        command(program('systemctl'), 'enable', UNIT.name)
        atomic_write(BOOT / 'enabled', 'Reviewed CAMERA0 startup enabled\n')
        flags(0, 0)
        os.sync()
        return {'startup_enabled': True, 'reboot_required': True, 'capture_started': False}
    return install()


def install():
    state = boot.state()
    old_environment = checked_environment()
    require(not INSTALLED.exists() and not INSTALLED.is_symlink(), 'Startup assets already exist.')
    require(not any(path.exists() or path.is_symlink() for path in (UNIT, HOOK)),
            'A service or kernel hook already occupies the startup path.')
    discovery.verify()
    kernel.load()
    pipeline = capture.discover()
    capture.verify_format(pipeline)
    require(capture.controls(pipeline) == capture.NORMAL, 'Restore normal controls before enabling startup.')
    proof = json.loads((BUILD / 'normal-capture.json').read_text())
    require(proof['boot_id'] == boot_id() and proof['success'] and proof['frames'] >= 1
            and proof['candidate_sha256'] == sha256(BUILD / 'qcom-camss-ov9281.ko')
            and proof['controls'] == capture.NORMAL and not proof['sequence_gaps'],
            'Complete a successful normal capture in this boot before enabling startup.')
    require(boot.root_uuid() == state['root_uuid']
            and sha256(BOOT / 'candidate/camera0-ov9281-candidate.dtb') == state['candidate_sha256'],
            'Root disk or candidate device tree changed.')
    old_menu, old_state = MENU.read_bytes(), (BOOT / 'state.json').read_bytes()
    original = old_menu.decode()
    updated = menu(state, original)
    preview = BOOT / 'startup-menu-candidate.cfg'
    atomic_write(preview, updated)
    command(program('grub-script-check'), preview)
    checked_environment()
    paths = [Path('camera.py'), Path('data/platform.json'),
             Path('build/driver.json'), Path('build/qcom-camss-ov9281.ko')]
    paths.extend(path.relative_to(ROOT) for path in sorted((ROOT / 'ov9281').glob('*.py')))
    require({path.name for path in paths if path.parent == Path('ov9281')} >=
            {'__init__.py', 'startup.py', 'discovery.py', 'kernel.py', 'capture.py', 'common.py', 'boot.py', 'dtree.py', 'build.py'},
            'Checkout is incomplete.')
    record = {'kernel': KERNEL, 'files': {},
              'original_menu_sha256': hashlib.sha256(old_menu).hexdigest(),
              'original_state_sha256': hashlib.sha256(old_state).hexdigest()}
    created = False
    try:
        INSTALLED.mkdir(mode=0o755)
        created = True
        for relative in paths:
            source = ROOT / relative
            require(source.is_file() and not source.is_symlink(), 'Unexpected source asset: ' + str(source))
            target = INSTALLED / relative
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            atomic_write(target, source.read_bytes(), 0o755 if relative == Path('camera.py') else 0o644)
            record['files'][str(relative)] = sha256(target)
        atomic_write(BOOT / 'original-test-menu.cfg', old_menu)
        atomic_write(BOOT / 'original-test-state.json', old_state)
        atomic_write(UNIT, UNIT_TEXT)
        atomic_write(HOOK, HOOK_TEXT, 0o755)
        command(program('systemd-analyze'), 'verify', UNIT)
        command(program('systemctl'), 'daemon-reload')
        command(program('systemctl'), 'enable', UNIT.name)
        require(MENU.read_bytes() == old_menu and (BOOT / 'state.json').read_bytes() == old_state
                and boot.environment() == old_environment, 'Boot state changed during installation.')
        write_json(RECORD, record)
        atomic_write(BOOT / 'enabled', 'Reviewed CAMERA0 startup enabled\n')
        atomic_write(MENU, updated)
        state['menu_sha256'] = sha256(MENU)
        write_json(BOOT / 'state.json', state)
        flags(0, 0)
        os.sync()
        return {'startup_enabled': True, 'reboot_required': True, 'capture_started': False,
                'installed_assets': str(INSTALLED), 'normal_controls': capture.NORMAL,
                'stock_module_replaced': False}
    except BaseException:
        atomic_write(MENU, old_menu)
        atomic_write(BOOT / 'state.json', old_state)
        for key in (PENDING, DISABLED):
            if key in old_environment:
                command(program('grub-editenv'), GRUBENV, 'set', f'{key}={old_environment[key]}')
            else:
                command(program('grub-editenv'), GRUBENV, 'unset', key)
        if created:
            if UNIT.exists():
                command(program('systemctl'), 'disable', UNIT.name)
            UNIT.unlink(missing_ok=True)
            HOOK.unlink(missing_ok=True)
            shutil.rmtree(INSTALLED)
        for path in (RECORD, BOOT / 'enabled', BOOT / 'original-test-menu.cfg', BOOT / 'original-test-state.json'):
            path.unlink(missing_ok=True)
        command(program('systemctl'), 'daemon-reload')
        os.sync()
        raise
    finally:
        preview.unlink(missing_ok=True)


def configure():
    root_required()
    require(ROOT == INSTALLED, 'Startup configuration must use the protected installed copy.')
    require(PERSIST_MARKER in Path('/proc/cmdline').read_text().split(), 'Not an automatic camera boot.')
    installed()
    discovery.verify()
    kernel.load()
    configured = capture.configure_normal()
    result = dict(boot_id=boot_id(), kernel=KERNEL, pipeline={key: configured[key]
                  for key in ('media', 'sensor_entity', 'sensor_node', 'video')},
                  controls=configured['controls'], configuration_verified=True,
                  capture_started=False, boot_health_flag_cleared=False)
    write_json(BOOT / 'last-startup.json', result)
    command(program('grub-editenv'), GRUBENV, 'set', f'{PENDING}=0')
    require(boot.environment().get(PENDING) == '0', 'Camera boot health flag did not clear.')
    result['boot_health_flag_cleared'] = True
    write_json(BOOT / 'last-startup.json', result)
    return result


def status():
    root_required()
    _, record = installed()
    last = BOOT / 'last-startup.json'
    if last.exists():
        protected_file(last)
    return {'installed_kernel': record['kernel'], 'running_kernel': os.uname().release,
            'grub_environment': boot.environment(), 'enabled_marker': (BOOT / 'enabled').exists(),
            'service': command(program('systemctl'), 'show', UNIT.name, '-p', 'ActiveState', '-p', 'SubState', '-p', 'Result'),
            'last_startup': json.loads(last.read_text()) if last.exists() else None,
            'discovery': discovery.verify()}


def disable():
    root_required()
    installed()
    checked_environment()
    command(program('grub-editenv'), GRUBENV, 'set', f'{DISABLED}=1')
    os.sync()
    return {'startup_enabled': False, 'next_restart': 'stock Ubuntu', 'running_driver_changed': False}


def remove():
    root_required()
    installed()
    checked_environment()
    for path in (BOOT / 'original-test-menu.cfg', BOOT / 'original-test-state.json'):
        protected_file(path)
    original = json.loads((BOOT / 'original-test-state.json').read_text())
    require(original['menu_sha256'] == sha256(BOOT / 'original-test-menu.cfg'), 'Original boot state differs.')
    # Disable first: a partial removal must not select an incomplete camera boot.
    command(program('grub-editenv'), GRUBENV, 'set', f'{DISABLED}=1')
    command(program('systemctl'), 'disable', UNIT.name)
    atomic_write(MENU, (BOOT / 'original-test-menu.cfg').read_bytes())
    write_json(BOOT / 'state.json', original)
    command(program('grub-editenv'), GRUBENV, 'unset', PENDING, DISABLED)
    UNIT.unlink()
    HOOK.unlink()
    shutil.rmtree(INSTALLED)
    for path in (RECORD, BOOT / 'enabled', BOOT / 'last-startup.json', BOOT / 'original-test-menu.cfg', BOOT / 'original-test-state.json'):
        path.unlink(missing_ok=True)
    command(program('systemctl'), 'daemon-reload')
    os.sync()
    return {'automatic_startup_removed': True, 'temporary_boot_setup_retained': True,
            'running_driver_changed': False, 'next_step': 'cleanup-boot, then reboot'}
