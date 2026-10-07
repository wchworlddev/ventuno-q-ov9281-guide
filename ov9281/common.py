# SPDX-License-Identifier: MIT
"""Paths, checked commands and compatibility checks shared by the tools."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = json.loads((ROOT / 'data/platform.json').read_text())
KERNEL = PLATFORM['kernel']
BUILD = ROOT / 'build'
BOOT = Path('/boot/ov9281-guide')
MENU = Path('/boot/grub/custom.cfg')
GRUB = Path('/boot/grub/grub.cfg')
GRUBENV = Path('/boot/grub/grubenv')
ENTRY = 'ov9281-guide-camera0'
MARKER = 'ov9281_guide_test=1'
PERSIST_MARKER = 'ov9281_guide_persistent=1'
STOCK_MODULE = Path('/lib/modules') / KERNEL / 'kernel/drivers/media/platform/qcom/camss/qcom-camss.ko.zst'
VENDOR_MODULES = ('camera_qcs8300', 'camera_qcs9100', 'camera_qcm6490')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def command(*args, timeout=25, cwd=None):
    result = subprocess.run([str(x) for x in args], cwd=cwd, text=True,
                            capture_output=True, timeout=timeout)
    require(result.returncode == 0,
            result.stderr.strip() or result.stdout.strip() or f'Command failed: {args[0]}')
    return result.stdout.strip()


def program(name):
    path = shutil.which(name)
    require(path is not None, f'Missing command: {name}. Install the prerequisites in README.md.')
    return path


def root_required():
    require(os.geteuid() == 0, 'Run this action with sudo on the VENTUNO Q.')


def protected_file(path):
    info = Path(path).lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
            f'Expected a protected regular root-owned file: {path}')


def protected_directory(path):
    info = Path(path).lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
            f'Expected a protected root-owned directory: {path}')


def atomic_write(path, content, mode=0o644):
    """Replace one file without following a destination symlink."""
    path = Path(path)
    require(not path.is_symlink(), f'Refusing a symlink: {path}')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.ov9281-', delete=False) as output:
            temporary = Path(output.name)
            os.fchmod(output.fileno(), mode)
            output.write(content.encode() if isinstance(content, str) else content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path, value):
    atomic_write(path, json.dumps(value, indent=2) + '\n')


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def reviewed_kernel():
    require(os.uname().release == KERNEL and os.uname().machine == 'aarch64',
            f'This port is scoped to AArch64 Ubuntu kernel {KERNEL}.')
    require(b'arduino,monza\0' in Path('/proc/device-tree/compatible').read_bytes(),
            'Expected the reviewed VENTUNO Q platform.')


def test_session():
    reviewed_kernel()
    require(MARKER in Path('/proc/cmdline').read_text().split(),
            'Boot the one-time CAMERA0 entry before this action.')
    require(not any((Path('/sys/module') / name).exists() for name in VENDOR_MODULES),
            'A downstream vendor camera driver is loaded; stop and reboot into the test entry.')


def sensor_client(bound=True):
    clients = [p for p in Path('/sys/bus/i2c/devices').glob('*-0060')
               if str((p / 'of_node').resolve()).endswith('/cci@ac13000/i2c-bus@0/sensor@60')]
    require(len(clients) == 1, 'Expected exactly one declared CAMERA0 OV9281 client.')
    client = clients[0]
    require((client / 'of_node/compatible').read_bytes() == b'ovti,ov9281\0',
            'Sensor compatible differs.')
    if bound:
        require((client / 'driver').exists() and (client / 'driver').resolve().name == 'ov9282',
                'OV9281 sensor has not bound. Stop here; capture is unavailable.')
    return client


def emit(value):
    print(json.dumps(value, indent=2))
