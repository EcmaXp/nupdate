#!/usr/bin/env python3.6

import sys

sys.path.append(r"C:\Users\EcmaXp\Documents\GitHub\pyfrez")

from pyfrez import setup, find_packages

setup(
    name='nupdate',
    packages=find_packages(
        include=[
            'nupdate',
            'nupdate.*',
        ],
    ),
    options={},
    platforms='any',
    install_requires=[],
    extras_require={},
    entry_points={
        'pyfrez': [  # .console vs .windows
            'SM-RE.console = nupdate.main:main',
        ],
    },
)
