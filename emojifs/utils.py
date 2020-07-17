#!/usr/bin/env python3

from emojifs import __version__, __repository__


def set_user_agent(x):
    """Sets a reasonable User-Agent. x should be a Request headers-like object."""
    x['User-Agent'] = f"emojifs/{__version__} ({__repository__}) {x['User-Agent']}"
