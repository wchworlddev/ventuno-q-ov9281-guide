#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Temporary OV9281 CAMERA0 bring-up on the reviewed VENTUNO Q Ubuntu kernel."""

import argparse
import subprocess
import sys

sys.dont_write_bytecode = True

from ov9281 import boot, build, capture, kernel
from ov9281.common import emit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    descriptions = {
        'inspect': 'Read-only boot compatibility check (sudo).',
        'build-driver': 'Fetch exact Ubuntu source and validate an out-of-tree module (normal user).',
        'prepare-boot': 'Prepare CAMERA0 and select one boot (sudo); reboot manually.',
        'repeat-boot': 'Select the existing CAMERA0 entry for one further boot (sudo).',
        'cleanup-boot': 'Remove only this guide\'s temporary boot files (sudo).',
        'load': 'Load the validated CAMSS correction for this session (sudo).',
        'restore-driver': 'Restore the installed stock CAMSS driver for this session (sudo).',
        'plan': 'Discover the CAMERA0 media and video nodes (read-only).',
        'configure': 'Configure RAW8 and normal exposure/blanking without capturing.',
        'capture': 'Capture 1..32 normal frames and save two PGM previews.',
        'benchmark-144': 'Capture at most 720 frames at approximately 144 fps; restore controls.',
    }
    for name, description in descriptions.items():
        action = actions.add_parser(name, help=description, description=description)
        if name in ('capture', 'benchmark-144'):
            action.add_argument('--frames', type=int, default=8 if name == 'capture' else 720)
            action.add_argument('--output', help='New directory for PGM previews and result.json.')
    args = parser.parse_args()
    functions = {'inspect': boot.inspect, 'build-driver': build.build_driver,
                 'prepare-boot': boot.prepare, 'repeat-boot': boot.repeat, 'cleanup-boot': boot.cleanup,
                 'load': kernel.load, 'restore-driver': kernel.restore, 'plan': capture.discover,
                 'configure': capture.configure_normal}
    if args.action == 'capture':
        result = capture.capture(args.frames, args.output)
    elif args.action == 'benchmark-144':
        result = capture.benchmark(args.frames, args.output)
    else:
        result = functions[args.action]()
    emit(result)
    return 1 if args.action == 'inspect' and not result['ready'] else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'Stopped: {error}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('Interrupted.', file=sys.stderr)
        sys.exit(130)
