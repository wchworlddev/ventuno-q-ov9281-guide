# SPDX-License-Identifier: MIT
"""Load a validated CAMSS correction without installing it."""

import json
from pathlib import Path
import time

from .build import modinfo
from . import discovery
from .common import (
    BUILD, PLATFORM, STOCK_MODULE,
    command, program, require, root_required, sensor_client, sha256, test_session,
)

VERSION = Path('/sys/module/qcom_camss/srcversion')


def loaded_version():
    return VERSION.read_text().strip() if VERSION.exists() else None


def idle():
    command(program('udevadm'), 'settle', '--timeout=8', timeout=12)
    deadline = time.monotonic() + 8
    refcount = Path('/sys/module/qcom_camss/refcnt')
    while refcount.exists() and refcount.read_text().strip() != '0':
        require(time.monotonic() < deadline, 'CAMSS remains busy; close camera applications and stop here.')
        time.sleep(0.2)


def healthy_kernel():
    text = command(program('dmesg'))
    require('Internal error: Oops' not in text and 'Unable to handle kernel NULL' not in text,
            'This kernel has faulted. Do not unload or reload drivers; use recovery reboot.')


def load():
    root_required()
    test_session()
    sensor_client()
    healthy_kernel()
    discovery.verify()
    require(sha256(STOCK_MODULE) == PLATFORM['stock_camss_sha256'], 'Installed stock module differs.')
    candidate = BUILD / 'qcom-camss-ov9281.ko'
    metadata = json.loads((BUILD / 'driver.json').read_text())
    require(metadata['kernel'] == PLATFORM['kernel'] and metadata['patched_abi_matches_stock'] is True
            and metadata['unpatched_rebuild_matches_stock'] is True, 'Build validation is incomplete.')
    require(sha256(candidate) == metadata['candidate_sha256']
            and sha256(STOCK_MODULE) == metadata['stock_sha256'], 'Module checksum differs from its build record.')
    require(modinfo(candidate, 'vermagic') == modinfo(STOCK_MODULE, 'vermagic') == metadata['vermagic'], 'Module ABI differs.')
    require(modinfo(candidate, 'srcversion') == PLATFORM['patched_srcversion'], 'Patched source version differs.')
    dependencies = modinfo(STOCK_MODULE, 'depends')
    require(modinfo(candidate, 'depends') == dependencies == metadata['depends'], 'Module dependencies differ.')
    lockdown = Path('/sys/kernel/security/lockdown')
    require(not lockdown.exists() or '[none]' in lockdown.read_text(),
            'Kernel lockdown is active. This helper does not change Secure Boot or signature enforcement.')
    old = loaded_version()
    require(old in (None, PLATFORM['stock_srcversion'], PLATFORM['patched_srcversion']), 'Unreviewed CAMSS module is loaded.')
    if old == PLATFORM['patched_srcversion']:
        require(Path('/sys/bus/platform/devices/ac7a000.isp/driver').resolve().name == 'qcom-camss', 'CAMSS is not bound.')
        idle()
        return {'corrected_camss_loaded': True, 'already_loaded': True, 'installed': False}
    idle()
    if old is not None:
        command(program('modprobe'), '-r', 'qcom-camss')
    try:
        names = [name for name in dependencies.split(',') if name]
        if names:
            command(program('modprobe'), '--all', *names)
        command(program('insmod'), candidate)
        require(loaded_version() == PLATFORM['patched_srcversion'], 'Corrected CAMSS did not load.')
        require(Path('/sys/bus/platform/devices/ac7a000.isp/driver').resolve().name == 'qcom-camss', 'CAMSS did not bind.')
        idle()
    except BaseException:
        healthy_kernel()
        if loaded_version() == PLATFORM['patched_srcversion']:
            idle()
            command(program('modprobe'), '-r', 'qcom-camss')
        if old == PLATFORM['stock_srcversion'] and loaded_version() is None:
            command(program('modprobe'), 'qcom-camss')
        raise
    return {'corrected_camss_loaded': True, 'installed': False, 'capture_started': False}


def restore():
    root_required()
    test_session()
    healthy_kernel()
    discovery.verify()
    require(sha256(STOCK_MODULE) == PLATFORM['stock_camss_sha256'], 'Installed stock module differs.')
    version = loaded_version()
    require(version in (None, PLATFORM['stock_srcversion'], PLATFORM['patched_srcversion']), 'Unreviewed CAMSS module is loaded.')
    idle()
    if version == PLATFORM['patched_srcversion']:
        command(program('modprobe'), '-r', 'qcom-camss')
    if loaded_version() is None:
        command(program('modprobe'), 'qcom-camss')
    require(loaded_version() == PLATFORM['stock_srcversion'], 'Stock CAMSS did not load.')
    return {'stock_camss_loaded': True, 'installed_module_changed': False}
