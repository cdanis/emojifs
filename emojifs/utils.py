#!/usr/bin/env python3

import base64
import os

import cachetools
import requests

from emojifs import __repository__, __version__


def set_user_agent(x):
    """Sets a reasonable User-Agent. x should be a Request headers-like object."""
    x['User-Agent'] = f"emojifs/{__version__} (An Abomination, like Gecko) ({__repository__}) {x['User-Agent']}"


def getuid():
    """Windows doesn't have os.getuid; WinFsp is happy with -1 though."""
    return os.getuid() if hasattr(os, 'getuid') else -1


def getgid():
    """Windows doesn't have os.getgid; WinFsp is happy with -1 though."""
    return os.getgid() if hasattr(os, 'getgid') else -1


@cachetools.cached(cachetools.LRUCache(maxsize=200))
def get_emoji_bytes(url: str) -> bytes:
    """Returns the bytes for a given emoji URL.  Handles HTTP(S) and data URLs."""
    if url.startswith('http'):
        r = _session.get(url)
        r.raise_for_status()
        return r.content
    elif url.startswith('data:'):
        (prefix, data) = url.split(',', maxsplit=1)
        if not prefix.endswith('base64'):
            raise ValueError
        return base64.b64decode(data)


@cachetools.cached(cachetools.LRUCache(maxsize=20000))
def get_content_length(url: str) -> int:
    """Returns the size of an emoji.  Handles HTTP(S) and data URLs."""
    if url.startswith('http'):
        r = _session.head(url)
        r.raise_for_status()
        # Slack emojis are served over CloudFront which provides Content-Length.
        return int(r.headers['Content-Length'])
    elif url.startswith('data:'):
        (prefix, data) = url.split(',', maxsplit=1)
        if not prefix.endswith('base64'):
            raise ValueError
        padding = data[-2:].count('=')
        return int(3*len(data)/4 - padding)


_session = requests.Session()
set_user_agent(_session.headers)
