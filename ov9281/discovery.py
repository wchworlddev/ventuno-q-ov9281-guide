# SPDX-License-Identifier: MIT
"""Prevent v4l_id from opening CAMSS nodes before registration completes."""

import json
from pathlib import Path

from .common import (
    BOOT, PLATFORM, atomic_write, command, program, protected_directory,
    protected_file, require, root_required, sha256, write_json,
)

VENDOR = Path('/usr/lib/udev/rules.d/60-persistent-v4l.rules')
OVERRIDE = Path('/etc/udev/rules.d/60-persistent-v4l.rules')
RECORD = BOOT / 'discovery.json'
IMPORT = 'IMPORT{program}="v4l_id $devnode"'
GUARDED_IMPORT = '''# CAMSS registers video nodes before all VFE entities are ready.
ATTR{name}=="msm_vfe*_video*", ENV{ID_V4L_PRODUCT}="$attr{name}"
ATTR{name}!="msm_vfe*_video*", IMPORT{program}="v4l_id $devnode"'''


def vendor_rule():
    protected_file(VENDOR)
    require(sha256(VENDOR) == PLATFORM['udev_rule_sha256'],
            'Ubuntu video discovery rule changed; review the workaround before continuing.')
    source = VENDOR.read_text()
    require(source.splitlines().count(IMPORT) == 1 and source.count('v4l_id') == 1,
            'Expected one ordinary v4l_id import.')
    return source


def verify():
    protected_file(RECORD)
    protected_file(OVERRIDE)
    record = json.loads(RECORD.read_text())
    require(sha256(OVERRIDE) == record['override_sha256'], 'Discovery override changed; stop for review.')
    require(sha256(VENDOR) == record['vendor_sha256'] == PLATFORM['udev_rule_sha256'],
            'Vendor discovery rule changed; stop for review.')
    return record


def install():
    root_required()
    protected_directory(BOOT)
    if RECORD.exists() or RECORD.is_symlink():
        return verify()
    source = vendor_rule()
    require(not OVERRIDE.exists() and not OVERRIDE.is_symlink(),
            'Another local video discovery override exists; do not overwrite it.')
    protected_directory(OVERRIDE.parent)
    replacement = source.replace(IMPORT, GUARDED_IMPORT)
    created = False
    try:
        atomic_write(BOOT / 'original-video-discovery.rules', source)
        atomic_write(OVERRIDE, replacement)
        created = True
        command(program('udevadm'), 'verify', OVERRIDE)
        command(program('udevadm'), 'control', '--reload-rules')
        record = {'vendor_sha256': sha256(VENDOR), 'override_sha256': sha256(OVERRIDE)}
        write_json(RECORD, record)
        return record
    except BaseException:
        if created:
            require(OVERRIDE.read_text() == replacement, 'Discovery override changed during rollback.')
            OVERRIDE.unlink()
            command(program('udevadm'), 'control', '--reload-rules')
        RECORD.unlink(missing_ok=True)
        (BOOT / 'original-video-discovery.rules').unlink(missing_ok=True)
        raise


def remove():
    root_required()
    if not RECORD.exists() and not RECORD.is_symlink():
        return
    # Removal checks our override hash, even if Ubuntu has since updated its
    # vendor rule. Removing the override restores the current vendor rule.
    protected_file(RECORD)
    protected_file(OVERRIDE)
    record = json.loads(RECORD.read_text())
    require(sha256(OVERRIDE) == record['override_sha256'], 'Discovery override changed; refusing removal.')
    OVERRIDE.unlink()
    command(program('udevadm'), 'control', '--reload-rules')
    RECORD.unlink()
    (BOOT / 'original-video-discovery.rules').unlink(missing_ok=True)
