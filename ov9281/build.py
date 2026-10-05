# SPDX-License-Identifier: MIT
"""Fetch exact Ubuntu CAMSS source and build/validate a session-only module."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

from .common import (
    BUILD, KERNEL, PLATFORM, ROOT, STOCK_MODULE,
    command, program, require, reviewed_kernel, sha256,
)

SOURCE_BASE = 'https://ports.ubuntu.com/ubuntu-ports/pool/universe/l/linux-qcom/'
ARCHIVES = {
    'linux-qcom_6.8.0.orig.tar.gz': '26512115972bdf017a4ac826cc7d3e9b0ba397d4f85cd330e4e4ff54c78061c8',
    'linux-qcom_6.8.0-1084.89.diff.gz': 'a9654afb1345e35236146a8afc7adf851868910fd4b890c313b6d9bdb1672960',
}
CAMSS = 'drivers/media/platform/qcom/camss/'


def download(name, cache):
    destination = cache / name
    if destination.exists():
        require(sha256(destination) == ARCHIVES[name], f'Cached source checksum differs: {destination}')
        return destination
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache, prefix='.download-', delete=False) as output:
            temporary = Path(output.name)
            print(f'Downloading {name}', flush=True)
            with urllib.request.urlopen(SOURCE_BASE + name, timeout=60) as response:
                shutil.copyfileobj(response, output)
        require(sha256(temporary) == ARCHIVES[name], 'Ubuntu source checksum differs; stopping.')
        temporary.rename(destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def extract_source(cache, tree):
    """Extract only regular CAMSS files, then apply Ubuntu's CAMSS hunks."""
    archives = {name: download(name, cache) for name in ARCHIVES}
    destination = tree / CAMSS
    destination.mkdir(parents=True)
    count = 0
    with tarfile.open(archives['linux-qcom_6.8.0.orig.tar.gz'], 'r|gz') as archive:
        for member in archive:
            prefix = 'linux-6.8/' + CAMSS
            if not member.name.startswith(prefix) or not member.isfile():
                continue
            relative = member.name[len(prefix):]
            require(relative and '/' not in relative and relative not in ('.', '..'),
                    'Unexpected CAMSS archive member.')
            source = archive.extractfile(member)
            require(source is not None, 'Source archive member is unreadable.')
            with source, (destination / relative).open('xb') as output:
                shutil.copyfileobj(source, output)
            count += 1
    require(count > 20, 'Incomplete CAMSS source extraction.')
    with gzip.open(archives['linux-qcom_6.8.0-1084.89.diff.gz'], 'rt') as stream:
        diff = stream.read()
    headers = list(re.finditer(r'(?m)^--- linux-qcom[^\n]*\n\+\+\+ linux-qcom[^\n]*\n', diff))
    sections = []
    for index, match in enumerate(headers):
        new_path = match.group().splitlines()[1].split()[1].split('/', 1)[1]
        if not new_path.startswith(CAMSS):
            continue
        relative = new_path[len(CAMSS):]
        require(relative and '/' not in relative and relative not in ('.', '..'), 'Unexpected Ubuntu patch path.')
        end = headers[index + 1].start() if index + 1 < len(headers) else len(diff)
        sections.append(diff[match.start():end])
    require(sections, 'Ubuntu CAMSS changes are missing.')
    selected = tree.parent / 'ubuntu-camss.diff'
    selected.write_text(''.join(sections))
    command(program('patch'), '--batch', '--forward', '-p1', '-i', selected, cwd=tree)
    return destination


def modinfo(module, field):
    return command(program('modinfo'), '-F', field, module)


def symbol_versions(module, output):
    """Dump the exact ELF ABI section without modifying the input module."""
    section = output.with_suffix('.versions')
    command(program('objcopy'), '--dump-section', f'__versions={section}', module, output)
    require(section.is_file() and section.stat().st_size > 0, 'Module lacks a readable __versions section.')
    return section.read_bytes()


def compile_driver(headers, source):
    command(program('make'), '-C', headers, f'M={source}', 'CONFIG_VIDEO_QCOM_CAMSS=m',
            'CC=gcc-13', f'-j{min(os.cpu_count() or 2, 8)}', 'modules', timeout=300)
    result = source / 'qcom-camss.ko'
    require(result.is_file(), 'CAMSS module was not produced.')
    return result


def build_driver():
    require(os.geteuid() != 0, 'Build as a normal user; sudo is only needed for boot/module actions.')
    reviewed_kernel()
    require(sha256(STOCK_MODULE) == PLATFORM['stock_camss_sha256'], 'Installed stock CAMSS differs.')
    headers = Path('/lib/modules') / KERNEL / 'build'
    require((headers / 'Module.symvers').is_file(), f'Install the exact linux-headers-{KERNEL} package.')
    require(sha256(ROOT / 'patches/qcs8300-csiphy.patch') == PLATFORM['patch_sha256'],
            'Reviewed CAMSS patch differs.')
    require(command(program('gcc-13'), '-dumpfullversion') == '13.3.0',
            'Use the GCC 13.3.0 compiler used for the reviewed Ubuntu kernel.')
    for name in ('make', 'patch', 'zstd', 'objcopy', 'modinfo'):
        program(name)
    BUILD.mkdir(exist_ok=True)
    cache = BUILD / 'downloads'
    cache.mkdir(exist_ok=True)
    work = BUILD / 'work'
    require(not work.exists() and not (BUILD / 'driver.json').exists(),
            'Build outputs already exist; use a fresh checkout/build directory.')
    work.mkdir()
    source = extract_source(cache, work / 'tree')
    stock = work / 'installed-stock.ko'
    with stock.open('xb') as output:
        subprocess.run([program('zstd'), '-d', '-c', str(STOCK_MODULE)], stdout=output,
                       stderr=subprocess.PIPE, check=True, timeout=30)
    original_versions = symbol_versions(stock, work / 'stock-copy.ko')
    rebuilt = compile_driver(headers, source)
    require(modinfo(rebuilt, 'srcversion') == modinfo(STOCK_MODULE, 'srcversion')
            == PLATFORM['stock_srcversion'], 'Unpatched rebuild source version differs from stock.')
    require(symbol_versions(rebuilt, work / 'rebuild-copy.ko') == original_versions,
            'Unpatched rebuild ABI differs from stock.')
    command(program('make'), '-C', headers, f'M={source}', 'clean', timeout=60)
    command(program('patch'), '--batch', '--forward', '-p1', '-i', ROOT / 'patches/qcs8300-csiphy.patch',
            cwd=work / 'tree')
    patched = compile_driver(headers, source)
    require(symbol_versions(patched, work / 'patched-copy.ko') == original_versions,
            'Patched module ABI differs from stock.')
    require(modinfo(patched, 'vermagic') == modinfo(STOCK_MODULE, 'vermagic'), 'Patched vermagic differs.')
    require(modinfo(patched, 'depends') == modinfo(STOCK_MODULE, 'depends'), 'Patched dependencies differ.')
    require(modinfo(patched, 'srcversion') == PLATFORM['patched_srcversion'], 'Patched source version differs.')
    target = BUILD / 'qcom-camss-ov9281.ko'
    shutil.copy2(patched, target)
    metadata = {'kernel': KERNEL, 'source_version': PLATFORM['ubuntu_source_version'],
                'stock_sha256': sha256(STOCK_MODULE), 'candidate_sha256': sha256(target),
                'vermagic': modinfo(target, 'vermagic'), 'depends': modinfo(target, 'depends'),
                'srcversion': modinfo(target, 'srcversion'),
                'symbol_versions_sha256': hashlib.sha256(original_versions).hexdigest(),
                'unpatched_rebuild_matches_stock': True, 'patched_abi_matches_stock': True}
    (BUILD / 'driver.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return metadata
