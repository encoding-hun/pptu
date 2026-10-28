<p align="center"><img width="350" src="logo/logo.svg"><br>Python P2P Torrent Uploader</p>

## Requirements

- Python 3.10 to 3.13
- Python package dependencies (`uv sync --frozen` – requires uv 0.8.0 or newer – or `pip install .`)
- torrenttools (for creating torrents, optional)
- MediaInfo CLI (for generating tech info)
- FFmpeg (for generating snapshots)

## Supported trackers

<table>
  <tr>
    <th>Name</th>
    <th>Acronym</th>
    <th>Auth</th>
    <th>Protection</th>
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
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> None</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> No</td>
    <td><img src="https://github.githubassets.com/images/icons/emoji/unicode/26a0.png" width="14" /> Dedicated servers only, requires staff approval</td>
  </tr>
  <tr>
    <th>HDBits</th>
    <td align="center"><code>HDB</code></td>
    <td align="center">Credentials/<br />Cookies</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/2714.png" width="14" /> Cloudflare</td>
    <td align="center"><img width="14" src="https://github.githubassets.com/images/icons/emoji/unicode/2714.png"> Simple</td>
    <td><img src="https://github.githubassets.com/images/icons/emoji/unicode/2714.png" width="14" /> Yes, if IP whitelisted in profile or 2FA enabled</td>
  </tr>
  <tr>
    <th>nCore</th>
    <td align="center"><code>nC</code></td>
    <td align="center">Credentials/<br />Cookies</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> None</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> No</td>
    <td><img src="https://github.githubassets.com/images/icons/emoji/unicode/2714.png" width="14" /> Yes</td>
  </tr>
  <tr>
    <th>nekoBT</th>
    <td align="center"><code>nBT</code></td>
    <td align="center">API key</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> None</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> No</td>
    <td><img src="https://github.githubassets.com/images/icons/emoji/unicode/2714.png" width="14" /> Yes</td>
  </tr>
  <tr>
    <th>Nyaa</th>
    <td align="center"><code>nyaa</code></td>
    <td align="center">Credentials</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/26a0.png" width="14" /> DDoS-Guard</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> No</td>
    <td><img src="https://github.githubassets.com/images/icons/emoji/unicode/2714.png" width="14" /> Yes</td>
  </tr>
  <tr>
    <th>PassThePopcorn</th>
    <td align="center"><code>PTP</code></td>
    <td align="center">Credentials/<br />Cookies</td>
    <td align="center"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> None</td>
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
    <td align="center" rowspan="3"><img src="https://github.githubassets.com/images/icons/emoji/unicode/274c.png" width="14" /> None</td>
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

### Cloudflare-protected trackers

Some trackers (currently HDBits) sit behind a Cloudflare managed challenge that only a real, windowed browser can pass (headless browsers are detected and fail). The challenge yields a `cf_clearance` cookie that is bound to your IP and User-Agent. Settings go in the tracker's own config section (`[hdbits]` below).

**Desktop: built-in browser solver (automatic)**

- Install the extra: `pip install 'pptu[cloudflare]'` (or `pip install nodriver`). It needs Chrome, Chromium, Edge or Brave installed.
- pptu briefly opens the browser, clears the check, and stores the clearance and the browser's User-Agent next to the tracker's cookies. Later runs reuse them until they expire.
- If the browser isn't auto-detected, set `browser_path` (e.g. `/snap/bin/chromium`, `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` or `C:\Program Files\Google\Chrome\Application\chrome.exe`).
- On a Linux server with a browser but no display, run `xvfb-run pptu ...`.
- If Cloudflare shows a "Verify you are human" checkbox, click it in the opened window. For unattended runs (`--auto`, watch folders), set `2captcha_api_key` (the same key AvistaZ uses) instead: when the browser hasn't passed after 15 seconds, pptu has 2captcha solve the Turnstile check and hands the token back to the page, so no click is needed.

**Headless / CLI-only servers: exported cookies**

1. On a machine with a browser on the same network (same IP / VPN exit), pass the check on the tracker's site and export its cookies as Netscape `cookies.txt` (must include `cf_clearance`).
2. Save them as the tracker's cookie file in pptu's cookies directory (`~/.local/share/pptu/cookies/` on Linux): `<tracker>.txt` (e.g. `hdb.txt`), or `<tracker>_<sha1 of your username>.txt` if a `username` is set. No username or password is needed for this.
3. Tell pptu that browser's exact User-Agent, because a mismatch gets the clearance rejected:
   ```toml
   [hdbits]
   browser_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/131.0.0.0 Safari/537.36"
   ```

When run interactively without a solver, pptu prints the cookie file path, waits for you to drop the file in, and asks for the User-Agent, so steps 2 and 3 can be done on the spot.

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

Uploaders (9):
   AvistaZ          https://avistaz.to/
   BroadcasTheNet   https://broadcasthe.net/
   CinemaZ          https://cinemaz.to/
   HDBits           https://hdbits.org/
   nCore            https://ncore.pro/
   nekoBT           https://nekobt.to/
   Nyaa             https://nyaa.si/
   PassThePopcorn   https://passthepopcorn.me/
   PrivateHD        https://privatehd.to/

```

### Example

```shell
pptu -i /path/example.mkv -i /path/example2.mkv hdb nc --request-id 12356
```
