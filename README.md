# LANpack

**A portable toolkit for LAN parties.**

Bring a laptop, start LANpack, share the QR. Everyone gets a browser-based player directory with names, gaming nicknames and Steam friend codes. Built for a small event, with room to grow into a general LAN toolkit.

## What works today

- Registration, live directory, search and a player count (27 expected by default; no hard cap).
- Games tab with organizer-managed name, genre, players per game, optional URL/price and cracked flag; players independently mark ownership and intent to play, and each game lists those players.
- Private editing access remembered in the browser used to register.
- Copy friend codes, with a manual-copy fallback on browsers that restrict the clipboard over HTTP.
- QR code and join address generated locally; no CDNs, analytics or external runtime assets.
- First-run organizer setup, password changes, corrections, removals and JSON export.
- SQLite persistence, a Docker container and a small launcher for start/stop/backup.

Steam requests happen in Steam. LANpack does not log into Steam, collect Steam credentials, verify account ownership or send friend requests. We deliberately do not derive Steam profile links from codes: that behavior has not been verified against real accounts. Numeric input is bounded to 1–20 digits as an input-safety limit, **not** an assertion about Steam's official code format. Leading zeros are normalized to prevent duplicate numeric codes.

## Start on a Mac

Requirements: Docker Desktop running, Docker Compose v2 with `--wait` support, and Python 3.9+ for the dependency-free launcher. Python packages install inside Docker. The first build needs internet; the built app works without it. Steam itself still needs Steam connectivity.

```sh
git clone https://github.com/QuentinHourdeaux/lanpack.git
cd lanpack
./lanpack start
```

Open **http://127.0.0.1:8080** on the Mac. Click **Set up organizer**, sign in with **admin**, then choose a new password (12–128 characters). Registration and the directory stay locked until setup is complete. The launcher requires this local setup before publishing on a LAN IP. Do this before sharing access with anyone.

`start` generates a session secret in an ignored, owner-readable `.env`. The organizer password is stored as a salted scrypt hash in the database, in the dedicated Docker volume `lanpack_lanpack-data`.

For participants, find the Mac's active private IPv4 address in **System Settings → Network → your active connection → Details → TCP/IP**, then run:

```sh
./lanpack start --ip 192.168.1.42
```

Replace that example with your actual address. The launcher checks that the address belongs to this Mac, publishes only that IPv4 interface, and updates the QR and URL. The container always listens on port 8080 internally; use `--port 8090` to change the host port if necessary. Switching IPs recreates the container without deleting registrations. Editing cookies are tied to the browser's hostname: changing the IP may require organizer assistance for players who registered at the old address.

For existing installations, the previous `.env` password is imported once and continues to work. To check the initial password in your **private terminal** while the app is running:

```sh
./lanpack password
```

Use **Organizer access → Change password** at any time. Enter your current password, a new password and its confirmation. Other organizer sessions are signed out; players and their editing access are preserved. After changing it, `./lanpack password` cannot display the new password: only its hash is stored. The `.env` password is a bootstrap/migration value only and cannot override an existing database password. Keep the new password in your password manager.

Organizer sessions expire after eight hours of inactivity. Anyone who can reach an unconfigured instance knows the default `admin` password, so complete setup on the Mac before exposing it. If bypassing the launcher with Docker Compose, keep the default loopback binding until setup is complete.

## Games

The organizer signs in and opens **Games → Add game**. Each entry has a name, an optional genre (searchable alongside the game name), optional players per game (1–999; leave blank when unknown), an optional http(s) URL, an optional price label (for example `Free` or `€19.99`), and a **Cracked** checkbox. The player count describes the game/session size; it does not cap interest or registration. Only the organizer can add, edit or remove catalog entries.

Each registered player can independently tick **I own this** and **I want to play** on any number of games. Open a game's title to see the players and their selections. Lists update every five seconds. Selections use the same browser editing access as player details; other people cannot set your choices. Removing a game removes its selections, and removing a player removes their selections.

The full SQLite backup includes games and selections. **Export directory** remains a player-directory-only export. No store data is fetched and links open separately; prices and flags are entered by the organizer.

## Event checklist

1. Connect the Mac to the event network; prefer Ethernet. Start with its current LAN IP.
2. Confirm the network allows communication between participants. Guest Wi-Fi/client isolation may prevent access even when both devices have internet.
3. Check the host firewall/network policy for the selected TCP port. Binding an IP does **not** restrict access to a subnet. If a subnet restriction is required, have the host/network administrator scope the allowance to the actual event subnet and verify it from both permitted and excluded networks. The launcher does not modify macOS firewall or packet-filter rules.
4. Test the displayed URL from a phone **and** another PC on the same LAN: register, find the card, copy the code and edit it. A desktop viewport simulation cannot prove venue connectivity.
5. Keep the Mac plugged in, lid open, and awake. Run `caffeinate -i` in a terminal for the event and stop it with Ctrl+C afterward.
6. Export after registration. Take a full backup before deleting or correcting many entries.
7. Stop LANpack when finished and remove any temporary firewall allowance you created.

Do not use router port forwarding, a DMZ, a public tunnel or public hosting. This is an event LAN tool. Plain HTTP does not protect traffic from someone monitoring the network; use only low-sensitivity player details and a trusted event network. Browser edit tokens authorize editing but do not prove identity or Steam ownership. After organizer setup, anyone with network access can read the directory or register an entry.

## Everyday commands

```sh
./lanpack status                 # Container health and published port
./lanpack logs                   # Last 80 log lines
./lanpack backup                 # Consistent SQLite snapshot in ignored backups/
./lanpack stop                   # Stops the app, keeps registrations
./lanpack start --ip YOUR_LAN_IP  # Starts/reconfigures for the current network
./lanpack start --build          # Rebuild after source changes (host preview)
```

The organizer's **Export directory** button downloads participant fields as JSON without editing-token hashes or credentials. This is a portable directory export, not a full restore image. `./lanpack backup` is a full SQLite snapshot including the organizer password hash and hashed editing tokens; keep it private. Keep `.env` privately if you want existing organizer sessions to survive moving hosts. Raw participant editing cookies remain in the players' browsers.

### Restore a private database backup

Restoring replaces current registrations. Stop the app, choose the right backup, and keep a backup of any current data first. The app image must already be built. Replace `YOUR_BACKUP.sqlite` below with the desired file:

```sh
./lanpack stop
docker compose --project-name lanpack run --rm --no-deps -T lanpack python -c 'import sys,sqlite3; p="/tmp/restore.sqlite"; open(p,"wb").write(sys.stdin.buffer.read()); s=sqlite3.connect(p); d=sqlite3.connect("/app/data/lanpack.sqlite"); s.backup(d); d.close(); s.close()' < backups/YOUR_BACKUP.sqlite
./lanpack start --ip YOUR_LAN_IP
```

### Reset after the event

This permanently deletes the event database. Export or back up first. Stop with `./lanpack stop`, then explicitly remove only the LANpack volume:

```sh
docker volume rm lanpack_lanpack-data
```

The next start creates an empty directory and bootstraps from `.env` again. Set `LANPACK_ADMIN_PASSWORD=admin` before that start to require fresh organizer setup. Local exports/backups are separate files; delete them when no longer needed. Avoid `docker system prune` or commands affecting unrelated projects.

## Troubleshooting

- **Docker command failed:** open Docker Desktop and wait for its engine to become ready. Check `docker info` and `./lanpack logs`.
- **Address unavailable:** Wi-Fi/Ethernet changed. Check the active IPv4 address again.
- **Port already allocated:** run `./lanpack start --ip YOUR_LAN_IP --port 8090`.
- **Works on Mac, not phone:** check that the URL is the LAN IP (not localhost), that the phone is on the correct Wi-Fi, client isolation/VPNs, and the host firewall. Do not disable the whole firewall as a workaround.
- **Cannot edit an existing entry:** use the browser and address originally used to register. Private browsing or clearing cookies loses editing access. Ask the organizer to correct or remove the entry; registering a duplicate code is rejected.
- **Clipboard unavailable:** use the selected text in the manual-copy dialog. Hold to copy on a phone, Ctrl/Cmd+C on desktop.
- **Limited Steam account:** some accounts cannot send invites. The other player may be able to invite you. See [Steam's friend guidance](https://help.steampowered.com/en/faqs/view/1902-2D54-E445-59DD).

## Development and verification

Flask + Waitress + SQLite, plain HTML/CSS/JavaScript and locally generated SVG QR codes. One service, eight request threads, no frontend build step. The container runs as a non-root user, with a read-only root filesystem, all Linux capabilities dropped, no new privileges, a bounded temporary filesystem and only its own database volume. It does not mount host folders or the Docker socket.

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

Tests use temporary databases. They cover concurrent registrations, duplicate codes, validation, CSRF/origin/Host checks, editing isolation, organizer controls, forced first-run setup, password validation and changes, session revocation, request limits and persistence across app instances. CI's `verify` job runs tests and builds the container.

Public responses and directory exports omit editing credentials. SQL is parameterized; the UI renders participant input as text. Secrets, databases, logs, backups and local environments are ignored by Git and excluded from the build context. Rate limits are per source IP and reset on restart; shared NAT may group multiple players. They are basic abuse controls, not protection for an internet-facing deployment.

## Repository ownership

Outside contributors use forks and pull requests. `main` is protected with required code-owner review by **@QuentinHourdeaux**, stale-review dismissal, required `verify` CI, and force-push/deletion blocking. The owner's review bypass is limited to PRs so solo-authored changes remain possible; CI and force-push/deletion protection have no bypass. No auto-merge or bot merging is enabled.

## Next in the pack

Once the player directory has proved useful at a real event: game/availability status, host announcements and server details, then looking-for-players groups. Keep everything portable, local and usable in a browser. Chat, uploads and complex accounts are outside this first release.
