#!/usr/bin/env python3

from emojifs import __version__, __repository__

import os

def set_user_agent(x):
    """Sets a reasonable User-Agent. x should be a Request headers-like object."""
    x['User-Agent'] = f"emojifs/{__version__} ({__repository__}) {x['User-Agent']}"

def getuid():
    """Windows doesn't have os.getuid; WinFsp is happy with -1 though."""
    return os.getuid() if hasattr(os, 'getuid') else -1

def getgid():
    """Windows doesn't have os.getgid; WinFsp is happy with -1 though."""
    return os.getgid() if hasattr(os, 'getgid') else -1
