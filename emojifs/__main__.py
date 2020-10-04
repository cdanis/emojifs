#!/usr/bin/env python3
"""emojifs is a FUSE filesystem for manipulating Slack & Discord emoji.

⚠️  WARNING! ⚠️
😱☢️  DO NOT USE THIS PROGRAM. 😱☢️
This program is not a program of honor.

No highly esteemed function is executed here.

What is here is dangerous and repulsive to us.

The danger is still present, in your time, as it was in ours,
without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE.

This program is best shunned and left unused (but it is free software,
and you are welcome to redistribute it under certain conditions).
😱☢️  DO NOT USE THIS PROGRAM. 😱☢️
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

import argparse
import functools
import logging
import operator
import os
import sys
from http.client import HTTPConnection

import logzero
import refuse.high as fuse
import tomlkit
from logzero import logger

import emojifs
import emojifs.slack
from emojifs.muxer import Muxer
from emojifs.slack import Slack
from emojifs.discord import Discord


class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter,
                      argparse.RawDescriptionHelpFormatter):
    """Trivially combines RawDescriptionHelpFormatter with ArgumentDefaultsHelpFormatter."""
    pass


def _get(tree, branches, *, default=None):
    """Multi-level dict.get().  branches is an iterable of keys to traverse in tree."""
    try:
        return functools.reduce(operator.getitem, branches, tree)
    except KeyError:
        return default


def main():
    p = argparse.ArgumentParser(
        prog='emojifs',
        description=__doc__,
        formatter_class=CustomFormatter,
    )
    p.add_argument('-m', '--mountpoint', help='Where to mount emojifs.  If present here, '
                   'overrides mountpoint from config.')
    p.add_argument('-f', '--foreground', help='If set, stay in the foreground.', default=False)
    p.add_argument('-c', '--config', help='Path to your config file with secrets',
                   default=os.path.join(os.path.expanduser("~"), ".emojifs.toml"),
                   type=argparse.FileType('r'))
    p.add_argument('-v', '--verbose', action='count', default=0,
                   help='Verbosity (-v, -vv, etc).  Higher verbosities will log all HTTP traffic '
                        '(NB: at higher levels, this will log your auth secrets!)')
    p.add_argument('-V', '--version', action='version',
                   version='%(prog)s {}'.format(emojifs.__version__))

    args = p.parse_args()

    loglevel = logging.WARNING
    if args.verbose >= 1:
        loglevel = logging.INFO
    if args.verbose >= 2:
        loglevel = logging.DEBUG
    if args.verbose >= 3:
        HTTPConnection.debuglevel = 1
        requests_log = logzero.setup_logger("urllib3", level=loglevel)
        requests_log.propagate = True

    logzero.setup_logger("fuse", level=loglevel)
    logzero.setup_logger("fuse.log-mixin", level=loglevel)
    logzero.loglevel(loglevel)

    # We parsed args, now parse the config file.

    config = tomlkit.parse(args.config.read())

    mountpoint = (args.mountpoint
                  or os.path.expanduser(_get(config, ['emojifs', 'mountpoint'], default='')))
    if not mountpoint:
        logger.error('A mountpoint must be specified either in the config file '
                     'or on the command line 😬')
        sys.exit(1)

    muxer_map = {}
    if 'slack' in config:
        slacks = {}
        slack_renames = _get(config, ['slack', 'renames'], default={})

        # TODO: maybe allow parsing a single string cookie from those sections? (or token?)

        def _add_slack_from_token(token: str):
            """Given a token, construct a Slack, fetch its associated name, then apply any
            name remappings, and stash it in our Slacks dict."""
            s = Slack(token=t)
            our_name = slack_renames.get(s.name, s.name)
            if our_name not in slacks:
                slacks[our_name] = s
                logger.debug("Added slack '%s' as '%s'", s.name, our_name)

        for t in _get(config, ['slack', 'tokens'], default=[]):
            _add_slack_from_token(t)

        for c in _get(config, ['slack', 'cookies'], default=[]):
            logger.info('🔑 trying Slack login cookie scrape... 🥠')
            tokens = emojifs.slack.enumerate_tokens(c)
            for t in tokens:
                _add_slack_from_token(t)

        # assemble a slack_mounts dict to be passed to Muxer
        muxer_map = {f"/slack/{our_name}": s for (our_name, s) in slacks.items()}

    if 'discord' in config:
        ack = _get(config, ['discord', 'acknowledged'])
        token = _get(config, ['discord', 'token'])
        if token:
            ACKSPECTED = "I understand that using this program violates Discord's ToS"
            if ack != ACKSPECTED:
                logger.error("⚠️  Using this program violates Discord's Terms of Service and could"
                             " potentially result in your account being banned.  For details, see "
                             "https://support.discord.com/hc/en-us/articles/115002192352  "
                             "If you accept the risk, add this to your config under [discord]:"
                             "\nacknowledged = \"%s\"", ACKSPECTED)
                logger.error("Not mounting /discord as you didn't acknowledge the risk.")
            else:
                muxer_map['/discord'] = Discord(token)

    if not muxer_map:
        logger.warn("We didn't discover any Slacks or Discords to use. "
                    "Check your configuration file for errors?")
    mux = Muxer(muxer_map)

    foreground = args.foreground or _get(config, ['emojifs', 'foreground'], default=False)
    if args.verbose >= 1 and not foreground:
        logger.warn("You asked for verbose logging, but didn't also --foreground, "
                    "so I hope you only wanted logs during startup.  Seeya later 👋")
    logger.info('🚀 All systems go! About to mount at 🔜 %s (foreground %s)', mountpoint, foreground)
    try:
        fuse.FUSE(mux, mountpoint, foreground=foreground)
    except Exception:
        logger.error('😖 Something went wrong in FUSE setup', exc_info=True)


# TODO: signal handler (USR1?) to invalidate the TTL caches of all things

# TODO: SIGHUP to re-load config and adjust as necessary?

if __name__ == '__main__':
    main()
