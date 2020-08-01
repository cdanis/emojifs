#!/usr/bin/env python3
"""Stuff for doing stuff with Slack.

Slack: a FUSE implementation for Slack.

enumerate_tokens: a function that, given a login cookie, yields a list of Bearer tokens.
"""

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
import logging
import os
import re
import stat
import time
import http.cookies
import urllib.parse
from collections import defaultdict

import cachetools
import refuse.high as fuse
import requests
from logzero import logger

import emojifs.utils as utils


class Slack(fuse.LoggingMixIn, fuse.Operations):
    """A FUSE filesystem implementation for an individual Slack team."""
    def __init__(self, token: str, *, real_sizes: bool = True, name: str = ''):
        """Given an authentication token (xox.-....), construct a Slack instance."""

        # TODO: real_sizes=False is a big speedup on common tasks like `ls -l`, but, if you lie
        # about sizes you break reads and such, presumably unless you set direct_io (which disables
        # kernel buffer cache and probably introduces some other performance penalty for other
        # usages, although probably they're less bad/annoying).
        assert(real_sizes)

        self.name = name  # the identifying part before .slack.com
        self._token = token
        self._real_sizes = real_sizes
        self._base_url = f"https://{name}.slack.com/api/" if name else 'https://api.slack.com/api/'
        self._retry_after = {}  # URL -> time.time() after which it's ok to retry
        self._write_buffers = {}  # path (not name!) -> BytesIO
        self.__cached_metadata = cachetools.TTLCache(maxsize=1, ttl=600)  # for _get_all_emoji()

        self._session = requests.Session()
        utils.set_user_agent(self._session.headers)
        self._session.headers['Authorization'] = f"Bearer {token}"

        # Our token should be usable for a single Slack.
        # To see if we have an admin token, first, we need our user ID.
        r = self._request('GET', self._url('auth.test'))
        j = r.json()
        self._user_id = j['user_id']
        self._base_url = j['url'] + 'api/'
        if not self.name:
            m = re.match(r'https://([^.]+)\.slack\.com/', j['url'])
            if m:
                self.name = m[1]
        r = self._request('GET', self._url('users.info'), params={'user': self._user_id})
        j = r.json()
        # TODO: we thought we cared about is_admin, but of course is_admin is sufficient but not
        # necessary to upload emoji.
        self._is_admin = (j['user']['is_admin'] or j['user']['is_owner']
                          or j['user']['is_primary_owner'])
        logger.info('👍 Successfully authenticated to %s as user %s', self.name, j['user']['name'])

    def _url(self, method):
        return f"{self._base_url}{method}"

    def _request(self, method, url, **kwargs):
        """Execute a request against our _session, respecting ratelimiting and raising if
        the response isn't okay.  Retry on ratelimiting (after sleeping) but not on other error."""
        # Respect any ratelimiting on the given URL path
        time.sleep(max(0, self._retry_after.get(url, 0) - time.time()))
        resp = self._session.request(method, url, **kwargs)
        if resp.status_code == 429:
            self._retry_after[url] = time.time() + resp.headers.get('retry-after', 60)
            logger.warn('Got ratelimited by Slack; retrying after %s seconds for %s',
                        self._retry_after[url], url)
            return self._request(method, url, **kwargs)
        else:
            resp.raise_for_status()
        logger.debug('resp for %s to %s json: %s', method, url, resp.json())
        assert(resp.json()['ok'])
        return resp

    def _request_all_pages(self, method, url, *, _paged_key: str, **kwargs):
        """Wrapper around _request for paginated APIs.  Will fetch all pages and return an array
        of results.  Must be provided _paged_key as a special arg telling the name of the key that
        contains the API results you want.  All other kwargs follow the usual Requests conventions
        (but it messes with params['page'] because it must).
        """
        accum = []
        pages_fetched = 0
        j = defaultdict(lambda: defaultdict(lambda: 1))  # Thanks to Guru Ibynaf.
        params = kwargs.pop('params', {})
        while pages_fetched < j['paging']['pages']:
            params['page'] = pages_fetched
            j = self._request(method, url, params=params, **kwargs).json()
            accum.extend(j[_paged_key])
            pages_fetched += 1
        return accum

    def _upload_emoji(self, name: str, file):
        """Upload an emoji to Slack.  file should be a file-like object (e.g. BytesIO)"""
        # The official API endpoint admin.emoji.add is *only for Enterprise*.  Sigh.
        try:
            self._request('POST', self._url('emoji.add'),
                          data={'mode': 'data', 'name': name},
                          files={'image': file})
        finally:
            self._invalidate_metadata()

    def _delete_emoji(self, name: str):
        """Delete the named emoji from Slack."""
        try:
            self._request('POST', self._url('emoji.remove'), data={'name': name})
        finally:
            self._invalidate_metadata()

    def _alias_emoji(self, src: str, dst: str):
        """Create an alias so that you can use :dst: as another name for :src:."""
        try:
            self._request('POST', self._url('emoji.add'),
                          data={'mode': 'alias', 'name': dst, 'alias_for': src})
        finally:
            self._invalidate_metadata()

    def _get_all_emoji(self):
        @cachetools.cached(self.__cached_metadata)
        def real(self):
            r = self._request_all_pages('GET', self._url('emoji.adminList'), _paged_key='emoji')
            return {e['name']: e for e in r}
        return real(self)

    def _invalidate_metadata(self):
        self.__cached_metadata.clear()

    def _path_to_name(self, path: str) -> str:
        """Translates a path-like string (e.g. umactually.png, parrotdad.gif) to an
        emoji name (umactually, parrotdad).  Path-like strings are allow to omit a suffix."""
        rv = path.split('/', maxsplit=1)[-1].split('.')[0]
        logger.debug("mapped '%s' to emoji name %s", path, rv)
        return rv

    def _emoji_to_filename(self, e, *, name: str = None) -> str:
        """Convert an emoji API dict to a pseudo-filename, including an extension."""
        real_name = e['name'] if not name else name
        if e['url'].startswith('http'):
            # grab the extension (gif/png) from the end of the URL
            rv = f"{real_name}.{e['url'].rsplit('.', maxsplit=1)[-1]}"
            logger.debug('mapped %s to file %s', real_name, rv)
            return rv
        elif e['url'].startswith('data:image/'):
            # grab the extension (gif/png) from the data URL MIME type
            extension = e['url'].split('data:image/')[1].split(';', maxsplit=1)[0]
            rv = f"{real_name}.{extension}"
            logger.debug('mapped %s to file %s (data:image/ URL)', e['url'], real_name, rv)
            return rv

    # Now, the main course: FUSE operations implementations.

    def getattr(self, path, fh):
        emojis = self._get_all_emoji()

        # TODO: if we don't set allow_others in our fuse_main invocation,
        #       the 0o555 is probably just confusing.
        if path == '/':
            return dict(
                st_mode=stat.S_IFDIR | 0o555 | stat.S_IWUSR,
                st_mtime=max([e['created'] for e in emojis.values()]),
                st_ctime=min([e['created'] for e in emojis.values()]),
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

        name = self._path_to_name(path)
        if name not in emojis:
            raise fuse.FuseOSError(errno.ENOENT)

        e = emojis[name]

        return dict(
            st_mode=(stat.S_IFLNK if e['is_alias'] else stat.S_IFREG) | 0o444,
            st_mtime=e['created'],
            st_ctime=e['created'],
            st_atime=time.time(),
            st_nlink=1,
            st_uid=utils.getuid(),
            st_gid=utils.getgid(),
            st_size=(utils.get_content_length(e['url']) if self._real_sizes else 256*1024),
        )

    def readdir(self, path, fh=None):
        return ['.', '..'] + [self._emoji_to_filename(e) for e in self._get_all_emoji().values()]

    def readlink(self, path):
        emojis = self._get_all_emoji()
        name = self._path_to_name(path)
        if name not in emojis:
            raise fuse.FuseOSError(errno.ENOENT)
        e = emojis[name]
        if not e['is_alias']:
            raise fuse.FuseOSError(errno.EINVAL)
        # We don't 'deference' it ourselves using our metadata table, because it could be an alias
        # to a regular Unicode emoji.
        # This will represent it as a dangling symlink instead of throwing.
        # TODO: do something smart and/or reasonable about regular Unicode emoji
        #       (possibly, have another mountpoint for them?)
        return self._emoji_to_filename(e, name=e['alias_for'])

    def read(self, path, size, offset, fh):
        if path in self._write_buffers:
            b = self._write_buffers[path]
            b.seek(offset)
            return b.read(size)

        emojis = self._get_all_emoji()
        name = self._path_to_name(path)
        if name not in emojis:
            raise fuse.FuseOSError(errno.ENOENT)
        e = emojis[name]
        b = utils.get_emoji_bytes(e['url'])
        return b[offset:offset+size]

    # TODO: override open() s.t. we don't allow non-create write modes.
    # TODO: eventually consider support re-writes of emoji, even though it's much more
    #       complicated on the client side.

    # Time for the scary stuff: Mutating operations!

    def unlink(self, path):
        emojis = self._get_all_emoji()
        name = self._path_to_name(path)
        if name not in emojis:
            raise fuse.FuseOSError(errno.ENOENT)
        self._delete_emoji(name)

    # TODO: both create() and symlink() need to check that the name being created is valid-ish
    #       (for now they'll just throw errors on release(), which may not reach the client)

    def create(self, path, mode, fi=None):
        self._write_buffers[path] = io.BytesIO()
        return 0

    def write(self, path, data, offset, fh):
        b = self._write_buffers[path]
        b.seek(offset)
        return self._write_buffers[path].write(data)

    # This is where the write() magic actually happens.  We need to make a single POST call, with
    # a valid and complete image file, so it's the only place where it really can.
    def release(self, path, fh):
        # release() is called for any opened file, including files that were only opened for read.
        if path in self._write_buffers:
            b = self._write_buffers[path]
            try:
                name = self._path_to_name(path)
                b.seek(0)
                self._upload_emoji(name, b)
            finally:
                b.close()
                del self._write_buffers[path]

    def truncate(self, path, length, fh=None):
        b = self._write_buffers[path]
        b.seek(0)
        b.truncate(length)

    def symlink(self, target_path, source_path):
        emojis = self._get_all_emoji()
        source = self._path_to_name(source_path)
        if source not in emojis:
            raise fuse.FuseOSError(errno.ENOENT)
        target = self._path_to_name(target_path)
        self._alias_emoji(source, target)


# Heavily inspired by https://github.com/emtunc/SlackPirate
# particularly the display_cookie_tokens function.
def enumerate_tokens(cookie: str):
    """Given a Slack login cookie string, enumerate all logged-in Slacks and
    return a list of tokens.

    cookie need only be the d= portion of the cookie."""

    rv = []

    try:
        cookies = http.cookies.SimpleCookie(cookie)
        if 'd' not in cookies:
            # Make a guess that we got passed only the value after `d=`.
            cookies = http.cookies.SimpleCookie()
            cookies['d'] = cookie
        cookies = dict(d=urllib.parse.quote(urllib.parse.unquote(cookies['d'].value)))
        sess = requests.Session()
        # a 'real' cookie jar was too annoying to figure out and seemed of dubious benefit anyway
        sess.headers['cookie'] = f"d={cookies['d']}"
        utils.set_user_agent(sess.headers)
        # This Slack exists, but no one has access to it.
        # So, Slack helpfully lists all your logged-in teams.
        r = sess.get("https://emojifs-wasteland.slack.com")
        r.raise_for_status()
        ALREADY_SIGNED_IN_TEAM_REGEX = r"(https://[a-zA-Z0-9\-]+\.slack\.com)"
        QUOTED_ALREADY_SIGNED_IN_TEAM_REGEX = r"&quot;url&quot;:&quot;(https:\\/\\/[a-zA-Z0-9\-]+\.slack\.com)"
        SLACK_API_TOKEN_REGEX = r"\"api_token\":\"(xox[a-zA-Z]-[a-zA-Z0-9-]+)\""
        teams = (set(re.findall(ALREADY_SIGNED_IN_TEAM_REGEX, r.text))
                 | set(t.replace('\\', '')
                       for t in re.findall(QUOTED_ALREADY_SIGNED_IN_TEAM_REGEX, r.text))
                 - set(['https://status.slack.com', 'https://api.slack.com']))
        for team in teams:
            try:
                r = sess.get(team + "/customize/emoji")
                r.raise_for_status()
                parsed = re.findall(SLACK_API_TOKEN_REGEX, r.text)
                logger.debug('👀 Found %s tokens from %s', len(parsed), team)
                rv.extend(parsed)
            except Exception:
                logger.error("😖 Something went wrong when scraping token from %s", team, exc_info=1)
                # then continue
        return rv
    except Exception:
        logger.error("😖 Something went wrong when scraping login cookies", exc_info=True)
    finally:
        return rv


if __name__ == '__main__':
    # For debugging and/or manual testing in isolation.
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('mount')
    p.add_argument('token')
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG)
    fuse = fuse.FUSE(Slack(token=args.token), args.mount, foreground=True)
