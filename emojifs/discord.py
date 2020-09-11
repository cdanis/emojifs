#!/usr/bin/env python3
"""Stuff for doing stuff with Discord."""

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

import base64
import errno
import io
import operator
import stat
import time

import cachetools
import refuse.high as fuse
import requests
from logzero import logger

import emojifs.constants as constants
import emojifs.utils as utils


class Discord(fuse.LoggingMixIn, fuse.Operations):
    """A FUSE filesystem implementation for a Discord user's guilds' emojis."""

    _base_url = 'https://discord.com/api/v6/'

    def __init__(self, token: str):
        self._retry_after = {}  # URL -> time.time() after which it's ok to retry
        self._write_buffers = {}  # path (not name!) -> BytesIO

        # emoji metadata for 100 guilds + 1 guild membership list
        self._emojis_cache = cachetools.TTLCache(maxsize=100, ttl=600)
        self._membership_cache = cachetools.TTLCache(maxsize=1, ttl=600)

        self._session = requests.Session()
        utils.set_user_agent(self._session.headers)
        self._session.headers['Authorization'] = token

        r = self._request('GET', 'users/@me')
        j = r.json()
        logger.info('👍 Successfully authenticated to Discord as %s', self._user_string(j))

    def _url(self, method):
        return f"{self._base_url}{method}"

    def _request(self, http_method, urlfrag, **kwargs):
        """Execute a request against our _session, respecting ratelimiting and raising if
        the response isn't okay.  Retry on ratelimiting (after sleeping) but not on other error."""
        # TODO: This doesn't actually line up with Discord's ratelimiting semantics all that well.
        #       Discord also returns an X-RateLimit-Bucket header -- a bucket can span across many
        #       possible URLs -- but there's not an obvious way to map from a URL to a bucket name
        #       without first being ratelimited for it (and then remembering that??)
        # TODO: Even if we were strictly following the vague recommendations, it wouldn't be
        #       sufficient: Discord special-cases emoji methods with per-guild limits, and doesn't
        #       expose that in any useful way in the API (which is weird, because you'd think that
        #       each guild could just be a different bucket?)
        #       See also https://discord.com/developers/docs/topics/rate-limits
        # TODO: this is very close to, but not quite, Slack._request().
        url = self._url(urlfrag)

        # Attempt to respect any known ratelimiting on the given URL path
        time.sleep(max(0, self._retry_after.get(url, 0) - time.time()))
        resp = self._session.request(http_method, url, **kwargs)
        if resp.status_code == 429:
            self._retry_after[url] = time.time() + resp.headers.get('X-RateLimit-Reset-After', 60)
            logger.warn('Got ratelimited by Discord; retrying after %s seconds for %s',
                        self._retry_after[url], url)
            return self._request(http_method, url, **kwargs)
        else:
            resp.raise_for_status()
        if resp.status_code == 204:
            logger.debug('resp for %s to %s: HTTP %s', http_method, url, resp.status_code)
        else:
            logger.debug('resp for %s to %s json: %s', http_method, url, resp.json())
        return resp

    @cachetools.cachedmethod(operator.attrgetter('_membership_cache'))
    def _get_guilds(self):
        '''Returns all the guilds we're a member of.'''
        j = self._request('GET', 'users/@me/guilds').json()
        return {g['id']: g for g in j}

    # NB: If you change the signature of this function, you must also update _invalidate_guild!
    @cachetools.cachedmethod(operator.attrgetter('_emojis_cache'))
    def _get_emojis(self, id: str):
        '''Returns all the emoji for a given guild.'''
        j = self._request('GET', f'guilds/{id}/emojis').json()
        return {e['name']: e for e in j}

    def _invalidate_guild(self, id: str):
        '''Clear the cache of a given guild.'''
        k = cachetools.keys.hashkey(id)
        if k in self._emojis_cache:
            del self._emojis_cache[k]

    def _emoji_url(self, e):
        extension = 'gif' if e['animated'] else 'png'
        return f"https://cdn.discordapp.com/emojis/{e['id']}.{extension}"

    def _emoji_filename(self, e) -> str:
        extension = 'gif' if e['animated'] else 'png'
        return f"{e['name']}.{extension}"

    def _user_string(self, u) -> str:
        return f"{u['username']}#{u['discriminator']}"

    # TODO: support aliases for guilds, with the alias becoming the 'primary' render if present

    # TODO: a guild-ignorelist and a guild-onlylist?

    def _guild_to_path(self, g) -> str:
        '''Render a guild object as a pathname component.'''
        # TODO: alias support
        if isinstance(g, dict):
            return self._guild_to_path(g['name'])
        if isinstance(g, str):
            return g.replace('/', '_')
        raise ValueError

    def _path_to_guild(self, path):
        '''Given a /discord/foo/bar path, find the guild matching foo.'''
        gh = path.split('/', maxsplit=2)[1]
        guilds = self._get_guilds()
        # Direct ID lookups
        if gh in guilds:
            return guilds[gh]
        # TODO: alias support
        # Match by names
        candidates = [g for g in guilds.values() if gh == self._guild_to_path(g)]
        if candidates:
            return candidates[0]
        return None

    def _path_to_emojiname(self, path):
        '''/discord/foo/bar.png --> bar'''
        split = path.split('/', maxsplit=2)
        if len(split) < 3 or not split[2]:
            return None
        # Strip off any file extension.
        eh = split[2].split('.', maxsplit=1)[0]
        return eh

    def _path_to_guildmoji(self, path):
        '''Given a /discord/foo/bar.png path, find and return (guild, emoji) objects.'''
        g = self._path_to_guild(path)
        if g:
            eh = self._path_to_emojiname(path)
            if eh:
                emojis = self._get_emojis(g['id'])
                if eh in emojis:
                    return (g, emojis[eh])
                else:
                    raise fuse.FuseOSError(errno.ENOENT)
            else:
                return (g, None)
            # TODO: Better document (& test!) the semantics of this.
        else:
            return (None, None)

    def _guild_is_writable(self, g) -> bool:
        MANAGE_EMOJIS = 0x40000000
        return bool(g['permissions'] & MANAGE_EMOJIS)

    def getattr(self, path, fh):
        if path == '/':
            return dict(
                st_mode=stat.S_IFDIR | 0o555 | stat.S_IWUSR,
                st_mtime=time.time(),
                st_ctime=time.time(),
                st_atime=time.time(),
                st_nlink=2,
                st_uid=utils.getuid(),
                st_gid=utils.getgid(),
            )

        if path in self._write_buffers:
            return dict(
                st_mode=stat.S_IFREG | 0o600,
                st_atime=time.time(),
                st_ctime=time.time(),
                st_mtime=time.time(),
                st_nlink=1,
                st_uid=utils.getuid(),
                st_gid=utils.getgid(),
                st_size=len(self._write_buffers[path].getbuffer())
            )

        # This will raise a Fuse ENOENT if a nonexistent emoji name was specified in the path
        (g, e) = self._path_to_guildmoji(path)
        if g is None:
            raise fuse.FuseOSError(errno.ENOENT)
        elif e is None:
            return dict(
                st_mode=stat.S_IFDIR | 0o555 | (stat.S_IWUSR if self._guild_is_writable(g)
                                                else 0),
                st_mtime=time.time(),
                st_ctime=time.time(),
                st_atime=time.time(),
                st_nlink=2,
                st_uid=utils.getuid(),
                st_gid=utils.getgid(),
            )
        else:
            return dict(
                st_mode=stat.S_IFREG | 0o444,
                st_atime=time.time(),
                st_ctime=time.time(),
                st_mtime=time.time(),
                st_nlink=1,
                st_uid=utils.getuid(),
                st_gid=utils.getgid(),
                st_size=utils.get_content_length(self._emoji_url(e))
            )

    def readdir(self, path, fh=None):
        rv = ['.', '..']
        if path == '/':
            rv.extend(self._guild_to_path(g) for g in self._get_guilds().values())
        (g, e) = self._path_to_guildmoji(path)
        if g is not None and e is None:
            rv.extend(self._emoji_filename(e) for e in self._get_emojis(g['id']).values())
        return rv

    def listxattr(self, path):
        if path == '/' or path in self._write_buffers:
            return []
        (g, e) = self._path_to_guildmoji(path)
        if not g and e:
            raise fuse.FuseOSError(errno.ENOENT)
        return [constants.URL_XATTR_NAME, constants.CREATEDBY_XATTR_NAME]

    def getxattr(self, path, attrname):
        if path == '/' or path in self._write_buffers:
            raise fuse.FuseOSError(errno.ENODATA)
        (g, e) = self._path_to_guildmoji(path)
        if not g and e:
            raise fuse.FuseOSError(errno.ENOENT)
        if attrname == constants.URL_XATTR_NAME:
            return bytes(self._emoji_url(e), 'utf-8')
        elif attrname == constants.CREATEDBY_XATTR_NAME:
            return bytes(self._user_string(e['user']), 'utf-8')
        else:
            raise fuse.FuseOSError(errno.ENODATA)

    def read(self, path, size, offset, fh):
        if path in self._write_buffers:
            b = self._write_buffers[path]
            b.seek(offset)
            return b.read(size)

        (g, e) = self._path_to_guildmoji(path)
        if g and e:
            b = utils.get_emoji_bytes(self._emoji_url(e))
            return b[offset:offset+size]
        else:
            raise fuse.FuseOSError(errno.ENOENT)

    def unlink(self, path):
        # TODO: what about an unlink on a new file open in _write_buffers ?
        (g, e) = self._path_to_guildmoji(path)
        if g and e:
            logger.info('🗑️ Deleting :%s: (id %s) from "%s" (id %s)',
                        e['name'], e['id'], g['name'], g['id'])
            self._request('DELETE', f"guilds/{g['id']}/emojis/{e['id']}")
            self._invalidate_guild(g['id'])
        elif g and not e:
            # Sorry, but we won't delete a whole discord.
            raise fuse.FuseOSError(errno.EPERM)
        else:
            raise fuse.FuseOSError(errno.ENOENT)

    def _path_to_extension(self, path):
        split = path.rsplit('.', maxsplit=1)
        if len(split) < 2:
            raise ValueError
        extension = split[-1]
        if extension.lower() not in ['jpg', 'jpeg', 'gif', 'png']:
            raise ValueError
        return extension

    def create(self, path, mode, fi=None):
        g = self._path_to_guild(path)
        if not g:
            raise fuse.FuseOSError(errno.ENOENT)
        if not self._guild_is_writable(g):
            raise fuse.FuseOSError(errno.EPERM)
        try:
            self._path_to_extension(path)
        except ValueError:
            raise fuse.FuseOSError(errno.EINVAL)
        self._write_buffers[path] = io.BytesIO()
        return 0

    def write(self, path, data, offset, fh):
        b = self._write_buffers[path]
        b.seek(offset)
        return b.write(data)

    def release(self, path, fh):
        if path in self._write_buffers:
            b = self._write_buffers[path]
            b.seek(0)
            g = self._path_to_guild(path)
            eh = self._path_to_emojiname(path)
            ext = self._path_to_extension(path)
            try:
                image_mime = 'jpeg' if ext == 'jpg' else ext
                payload = dict(
                    name=eh,
                    image=(f"data:image/{image_mime};base64,"
                           + base64.b64encode(b.getvalue()).decode('ascii'))
                )
                logger.info('📸 Creating :%s: on "%s" (id %s)', eh, g['name'], g['id'])
                self._request('POST', f"guilds/{g['id']}/emojis", json=payload)
            finally:
                b.close()
                del self._write_buffers[path]
                self._invalidate_guild(g['id'])

    # TODO: it looks like HTTP PATCH is supported, maybe we can re-write emojis in place??
