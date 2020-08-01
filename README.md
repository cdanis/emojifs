<img align="right"
  src="extras/ablobcouncil.gif"
  title="yes! but no! but also, yes."
  alt="the emojifs mascot: a blobmoji holding a 'yes' sign as well as a 'no' sign and emphatically waving both simultaneously">

# emojifs

## Introduction
`emojifs` is a FUSE filesystem that allows you to manipulate custom emojis on your various Slacks and Discords.


## Example usage applications

    # Copy one emote from Slack to Discord.
    cp /emoji/slack/xooglers/docker-fire.gif /emoji/discord/unchaind/

    # Upload a whole pile of emoji.
    cp ~/emojipacks/parrots/* /emoji/slack/mynewslack/

    # Grab all those blobmoji across all my Discords and put them on Slack.
    cp /emoji/discord/*/*blob* /emoji/slack/myslack/

<!-- TODO xattr? -->

## ⚠️ WARNING! ⚠️
**☢️ 😱 DO NOT USE THIS PROGRAM. 😱 ☢️**  
This program is not a program of honor.  

No highly esteemed function is executed here.  

What is here is dangerous and repulsive to us.  

The danger [is still present](https://support.discord.com/hc/en-us/articles/115002192352), in your time, as it was in ours,  
without even the implied warranty of MERCHANTABILITY  
or FITNESS FOR A PARTICULAR PURPOSE.  

This program is best shunned and left unused (but it is free software,  
and you are welcome to redistribute it under certain conditions).  
**😱 ☢️ DO NOT USE THIS PROGRAM. ☢️ 😱**  

## Getting your Slack and Discord secrets

**⚠️ SERIOUS WARNING! I MEAN IT! ⚠️**  
Don't share your cookies or tokens with anyone or anything, including this program.  
They allow full control of your account!  
**⚠️ SERIOUS WARNING! I MEAN IT! ⚠️**  

### Slack
For Slack, the easiest thing to do is:
* In your web browser, log in to all the Slacks you want to use with this hunk of junk.
* Open your browser devtools network panel
* Find a request going towards edgeapi.slack.com or api.slack.com or a URL path starting with /api.  In Chrome, you can just type `api` in the Filter box above the timeline.
* Extract the cookie header value from your request, and use it in the config file below.

### Discord
* In your web browser, go to https://discord.com/app
* Open your browser devtools network panel
* Find a request going towards `https://discord.com/api/v6`.  In Chrome, you can just type `api` in the Filter box above the timeline.
* Extract the value of the `authorization:` header from one of your requests, and use it in the config file below.

<img align="left"
  src="https://cdn.discordapp.com/emojis/739162266284458045.gif"
  title="monkaTOS"
  alt="Pepe the Frog, sweating, his eyes replaced with a blinking marquee reading TOS">
**⚠️ SERIOUS WARNING! I MEAN IT! ⚠️**  
Using this program with Discord violates their [Terms of Service](https://support.discord.com/hc/en-us/articles/115002192352).  
It is possible your account could be banned.  
**⚠️ SERIOUS WARNING! I MEAN IT! ⚠️**  

&nbsp;  

## Requirements
* Python 3.7+
* A system that supports libfuse2
  * Linux or MacOS (or probably most BSDs, but I haven't tried)
  * Windows might work with [WinFsp](https://github.com/billziss-gh/winfsp), also untested
* A profound amount of either fearlessness, or foolishness, or both

## Installation

Like most Python packages, just `pip install emojifs`, or you can `git clone` the repo and `python setup.py install`.

You probably want to do either of the above inside a venv.

If you have [`poetry`](https://python-poetry.org/) installed, then `poetry install` will work great.

## Writing a config file

The format is [TOML](https://toml.io/).  It looks a lot like an INI file, if that means something to you.

The default location for the configuration file is `~/.emojifs.toml`

### A barebones config file

```toml
[emojifs]
mountpoint = '~/emoji'

[slack]
cookies = ['d=wpwQ4182w08qxmE4YP0gvlMb2L...']

[discord]
token = 'mfa.x91xxxxx......'
acknowledged = "I understand that using this program violates Discord's ToS"
```

That's all you need.  All Slacks you logged into will be autodetected.

On Windows, your mountpoint should be a drive letter:
```toml
[emojifs]
mountpoint = 'E:'
```

### A comprehensive configuration
There are a few niceties available:
```toml
[emojifs]
mountpoint = '/emoji'  # if you want to feel extra cool
foreground = true

[slack]
tokens = [
  'xoxp-asdf...',
  'xoxs-qwer...',
]

cookies = [
  'd=dvfib...',
  'd=ivu80...',
]

[slack.renames]
thisisaverylongname = 'short'

```

This will:
* mount everything under `/emoji`
* keep emojifs in the foreground as it runs (necessary if you want verbose logging output)
* first read the auth tokens one by one, then scrape logins for the cookies listed
* instead of mounting `thisisaverylongname.slack.com`'s emojis under the usual path, they'll appear under `/emoji/slack/short`.


## Invoking emojifs

```
usage: emojifs [-h] [-m MOUNTPOINT] [-f FOREGROUND] [-c CONFIG] [-v] [-V]

optional arguments:
  -h, --help            show this help message and exit
  -m MOUNTPOINT, --mountpoint MOUNTPOINT
                        Where to mount emojifs. If present here, overrides
                        mountpoint from config. (default: None)
  -f FOREGROUND, --foreground FOREGROUND
                        If set, stay in the foreground. (default: False)
  -c CONFIG, --config CONFIG
                        Path to your config file with secrets
                        (default: ~/.emojifs.toml)
  -v, --verbose         Verbosity (-v, -vv, etc). Higher verbosities will log
                        all HTTP traffic (NB: at higher levels, this will log
                        your auth secrets!) (default: 0)
  -V, --version         show program's version number and exit

```


## A note on semantics
Emojis are always 'rendered' in the filesystem with extensions (`.png`, `.gif`, etc) attached; however, the filesystem will accept reads and writes to filenames without extensions (assuming, of course, the filenames are valid emoji names).

## Known issues
* The first time you `ls` a directory for a Slack or Discord, it will take a very long time: possibly dozens of seconds 😬 but will be much faster afterwards.  Sorry, there are hopefully some reasonable ways to fix this.  (If you're morbidly curious, look for `real_sizes` in `emojifs/slack.py`.)
* While deletions and creations are supported, overwriting emojis in place is *not* yet supported.  As a workaround, you can use `cp --remove-destination` which, before writing new versions, will delete any existent emojis.
* Some Slacks have emojis from long ago which are aliases to emojis that don't themselves appear in the emoji listing -- although there isn't actually data missing, as they have a `data:` URL.
* The use of this program with Discord violates their Terms of Service.
* The existence of this program is an unforgivable sin.

## Future work
* Aliases for Discord guild names, as they can be unwieldly from the CLI.
* EaaFS: Integrating popular emojipacks as a filesystem.

## Acknowledgements
* The lovely [Requests library](https://requests.readthedocs.io/)
* [FUSE and its predecessors](https://en.wikipedia.org/wiki/Filesystem_in_Userspace)
* [SlackPirate by emtunc](https://github.com/emtunc/SlackPirate)
* [slackmoji by ksindi](https://github.com/ksindi/slackmoji) and [emojipacks by lambtron](https://github.com/lambtron/emojipacks)
* [Cult of the Party Parrot](https://cultofthepartyparrot.com/)
* [blobs.gg](https://blobs.gg/)
