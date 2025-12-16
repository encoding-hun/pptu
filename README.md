[![builds](https://img.shields.io/github/actions/workflow/status/pcroland/pptu/build.yaml?logo=github&style=flat-square)](https://github.com/pcroland/pptu/actions/workflows/build.yaml)
[![github_release](https://img.shields.io/github/v/release/pcroland/pptu?logo=github&color=70920c&style=flat-square)](https://github.com/pcroland/pptu/releases)
[![pypi_release](https://img.shields.io/pypi/v/pptu?label=PyPI&logo=pypi&logoColor=ffffff&color=70920c&style=flat-square)](https://pypi.org/project/pptu)
[![pypi_downloads](https://img.shields.io/pypi/dm/pptu?color=70920c&logo=pypi&logoColor=white&style=flat-square)](https://pypi.org/project/pptu)
[![license](https://img.shields.io/github/license/pcroland/pptu?color=blueviolet&style=flat-square)](https://github.com/pcroland/pptu/blob/master/LICENSE)
\
[![telegram](https://img.shields.io/endpoint?label=Discussion%20%26%20support&style=flat-square&url=https%3A%2F%2Fmogyo.ro%2Fquart-apis%2Ftgmembercount%3Fchat_id%3Dpptu_community)](https://t.me/pptu_community)
[![commits](https://img.shields.io/github/last-commit/pcroland/pptu?color=355ab8&logo=github&style=flat-square)](https://github.com/pcroland/pptu/commits/main)
[![open_issues](https://img.shields.io/github/issues/pcroland/pptu?color=718bcd&logo=github&style=flat-square)](https://github.com/pcroland/pptu/issues)
[![closed_issues](https://img.shields.io/github/issues-closed/pcroland/pptu?color=253e80&logo=github&style=flat-square)](https://github.com/pcroland/pptu/issues?q=is%3Aissue+is%3Aclosed)
\
[![name](https://img.shields.io/badge/platform-win%20%7C%20linux%20%7C%20osx-eeeeee?style=flat-square)](https://github.com/pcroland/pptu)
[![name](https://img.shields.io/pypi/pyversions/pptu?logo=Python&logoColor=eeeeee&color=eeeeee&style=flat-square)](https://github.com/pcroland/pptu)

<hr>
<p align="center"><img width="350" src="logo/logo.svg"><br>Python P2P Torrent Uploader</p>

## Requirements

- Python 3.10 to 3.13
- Python package dependencies (`uv sync --frozen` – requires uv 0.8.0 or newer – or `pip install .`)
- torrenttools (for creating torrents, optional)
- MediaInfo CLI (for generating tech info)
- FFmpeg (for generating snapshots)
- ImageMagick/libmagickwand (for optimizing snapshots)

## Supported trackers

<table>
  <tr>
    <th>Name</th>
    <th>Acronym</th>
    <th>Auth</th>
    <th>Cloudflare</th>
    <th>Captcha</th>
    <th>Server upload allowed</th>
  </tr>
  <tr>
    <th colspan="6">General</th>
  </tr>
  <tr>
    <th>BroadcasTheNet</th>
    <td align="center"><code>BTN</code></td>
    <td align="center">Credentials/<br />Cookies</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> No</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> No</td>
    <td><img src="https://github.githubassets.com/images/icons/emoji/unicode/26a0.png" width="14" /> Dedicated servers only, requires staff approval</td>
  </tr>
  <tr>
    <th>HDBits</th>
    <td align="center"><code>HDB</code></td>
    <td align="center">Credentials/<br />Cookies</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/2714.png" width="14" /> Yes</td>
    <td align="center"><img width="14" src="https://github.githubassets.com/images/icons/emoji/unicode/2714.png"> Simple</td>
    <td><img src="https://github.githubassets.com/images/icons/emoji/unicode/2714.png" width="14" /> Yes, if IP whitelisted in profile or 2FA enabled</td>
  </tr>
  <tr>
    <th>nCore</th>
    <td align="center"><code>nC</code></td>
    <td align="center">Credentials/<br />Cookies</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> No</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> No</td>
    <td><img src="https://github.githubassets.com/images/icons/emoji/unicode/2714.png" width="14" /> Yes</td>
  </tr>
    <tr>
    <th>PassThePopcorn</th>
    <td align="center"><code>PTP</code></td>
    <td align="center">Credentials/<br />Cookies</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> No</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> No</td>
    <td><img src="https://github.githubassets.com/images/icons/emoji/unicode/26a0.png" width="14" /> Dedicated servers only, requires staff approval</td>
  </tr>
  <tr>
    <th colspan="6">AvistaZ Network</th>
  </tr>
  <tr>
    <th>AvistaZ</td>
    <td align="center"><code>AvZ</code></td>
    <td align="center" rowspan="3">Credentials/<br />Cookies</td>
    <td align="center" rowspan="3"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> No</td>
    <td align="center" rowspan="3"><img src="https://github.githubassets.com/images/icons/emoji/unicode/2714.png" width="14" /> Yes</td>
    <td rowspan="3"><img src="https://github.githubassets.com/images/icons/emoji/unicode/2714.png" width="14" /> Yes, if IP whitelisted in profile</td>
  </tr>
  <tr>
    <th>CinemaZ</th>
    <td align="center"><code>CZ</code></td>
  </tr>
  <tr>
    <th>PrivateHD</th>
    <td align="center"><code>PHD</code></td>
  </tr>
</table>

For sites with captcha, a 2captcha API key is required to solve the captcha. Manual solving may be added in the future.
"Simple" captchas can be solved automatically without 2captcha or user interaction.

### PassThePopcorn

- Credential auth requires passkey in addition to username and password.

### AvistaZ Network

- Using credential auth is strongly recommended as cookies always expire within a few days.

## Installation

Install dependencies and the script with `./install.py`. You can re-run the script to update after a git pull.

## Setup

Copy `config.example.toml` to `~/.config/pptu/config.toml` and edit it as appropriate.

For credential-based auth, add your credentials in `~/.config/pptu/config.toml`:

```
[TRACKER]
username = "yourusername"
password = "yourpassword"
```

Optionally, you may specify `totp_secret` for automating 2FA logins.
Optionally, you may specify `img_uploader` for image host site.

For cookie-based auth, place cookies in `~/.local/share/pptu/cookies/TRACKER.txt`.

`TRACKER` is the name or the abbreviation of the tracker above (all lowercase).

## Usage

```
❯ pptu -h

Usage: pptu [OPTIONS] COMMAND1 [ARGS]... [COMMAND2 [ARGS]...]...

Options:
   -v, --version                      Show the version and exit.
   -i, --input PATH                   Files or directories to create torrents for.
   --fast-upload / --no-fast-upload   Upload only after all steps succeed (or force-disable).
   -c, --confirm                      Ask for confirmation before uploading.
   -a, --auto                         Run non-interactively (never prompt).
   -ds, --disable-snapshots           Skip creating description snapshots.
   -s, --skip-upload                  Create torrents but don't upload.
   -n, --note TEXT                    Note to attach to the upload.
   -lt, --list-trackers               Show the list of supported trackers and exit.
   -h, --help                         Show this message and exit.

Uploaders (8):
   AvistaZ          https://avistaz.to/
   BroadcasTheNet   https://broadcasthe.net/
   CinemaZ          https://cinemaz.to/
   HDBits           https://hdbits.org/
   nCore            https://ncore.pro/
   nekoBT           https://nekobt.to/
   PassThePopcorn   https://passthepopcorn.me/
   PrivateHD        https://privatehd.to/

```

### Example

```shell
pptu -i /path/example.mkv -i /path/example2.mkv hdb nc --request-id 12356
```
