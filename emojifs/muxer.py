#!/usr/bin/env python3
"""Stuff for gluing together multiple FUSE filesystems in a hierarchy.  Basically bind mounts."""

__copyright__ = """
Copyright © 2020 Chris Danis

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import bisect
import errno
import itertools
import os
import stat

import refuse.high as fuse
from logzero import logger


class Muxer(fuse.LoggingMixIn, fuse.Operations):
    def __init__(self, map):
        """Muxer is a FUSE filesystem compositor.  map should be a dict of path prefixes
        with values of FUSE implementations (e.g. Slack).  Muxer will dispatch operations
        to those filesystems based on path.

        The paths in map cannot be prefixes of one another.
        """
        def pairwise(iterable):
            "s -> (s0,s1), (s1,s2), (s2, s3), ..."
            a, b = itertools.tee(iterable)
            next(b, None)
            return zip(a, b)
        map = dict(sorted(map.items()))
        self._map = map
        self._mountpoints = list(map)
        # self._intermediates really should be a tree, but that's no fun.
        self._intermediates = set('/')
        for item in self._mountpoints:
            s = set((f"/{x}" for x in itertools.accumulate(filter(len, item.split('/')),
                                                           lambda *x: '/'.join(x))))
            self._intermediates = self._intermediates.union(s)
        self._intermediates = self._intermediates - set(self._mountpoints)
        assert not any(b.startswith(a) for (a, b) in pairwise(map))
        logger.info('🔧 Muxer created: map %s --> mountpoints %s intermediates %s', self._map,
                    self._mountpoints, self._intermediates)

    def _map_path(self, path):
        """Given a path, find the responsible FS in our map, and return a tuple of the path with
        its prefix stripped and the delegated FS."""
        def find_le(a, x):
            'Find rightmost value less than or equal to x'
            i = bisect.bisect_right(a, x)
            if i:
                return a[i-1]
            raise ValueError
        candidate = find_le(self._mountpoints, path)
        if not path.startswith(candidate):
            raise ValueError
        if path == candidate:
            return ('/', self._map[candidate])
        return (path[len(candidate):], self._map[candidate])

    # TODO: this should probably also passthrough init and destroy to all delegates

    # TODO: there must be a better way to do what follows...

    def getattr(self, path, *args, **kwargs):
        # Serve directory entries for our intermediates.
        if path in self._intermediates:
            return dict(
                st_mode=stat.S_IFDIR | 0o555,
                st_nlink=2,
                st_uid=os.getuid(),
                st_gid=os.getgid(),
            )
        # Delegate to mountpoints their / and below.
        try:
            (path, fs) = self._map_path(path)
        except ValueError:
            raise fuse.FuseOSError(errno.ENOENT)
        return getattr(fs, 'getattr')(path, *args, **kwargs)

    def readdir(self, path, *args, **kwargs):
        # For intermediate paths, synthesize all child intermediates and mountpoints.
        if path in self._intermediates:
            if not path.endswith('/'):
                path = path + '/'

            def find_children(ll):
                return [x[len(path):] for x in ll       # remove the parent's prefix from child
                        if x.startswith(path)           # by definition, child has parent's prefix
                        and '/' not in x[len(path):]    # maxdepth=1
                        and x != '/']                   # don't serve '/' ('.' is always served)

            return (['.', '..']
                    + find_children(self._intermediates)
                    + find_children(self._mountpoints))
        # Delegate to mountpoints their / and below.
        (path, fs) = self._map_path(path)
        return getattr(fs, 'readdir')(path, *args, **kwargs)

    def readlink(self, path, *args, **kwargs):
        (path, fs) = self._map_path(path)
        return getattr(fs, 'readlink')(path, *args, **kwargs)

    def read(self, path, *args, **kwargs):
        (path, fs) = self._map_path(path)
        return getattr(fs, 'read')(path, *args, **kwargs)

    def open(self, path, *args, **kwargs):
        (path, fs) = self._map_path(path)
        return getattr(fs, 'open')(path, *args, **kwargs)

    def unlink(self, path, *args, **kwargs):
        (path, fs) = self._map_path(path)
        return getattr(fs, 'unlink')(path, *args, **kwargs)

    def create(self, path, *args, **kwargs):
        (path, fs) = self._map_path(path)
        return getattr(fs, 'create')(path, *args, **kwargs)

    def write(self, path, *args, **kwargs):
        (path, fs) = self._map_path(path)
        return getattr(fs, 'write')(path, *args, **kwargs)

    def release(self, path, *args, **kwargs):
        (path, fs) = self._map_path(path)
        return getattr(fs, 'release')(path, *args, **kwargs)

    def truncate(self, path, *args, **kwargs):
        (path, fs) = self._map_path(path)
        return getattr(fs, 'truncate')(path, *args, **kwargs)

    def symlink(self, path, *args, **kwargs):
        (path, fs) = self._map_path(path)
        return getattr(fs, 'symlink')(path, *args, **kwargs)

    # TODO other methods?  e.g. xattrs eventually
