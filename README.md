# Copenhagen Flight Tracker

I fly CPH ↔ AMS a lot and wanted to know: *when should I buy my ticket?*

So I built a scraper. It drives a real Chromium browser to hit Google Flights daily, stores every price observation in SQLite, and pings me when something cheap shows up. Requests are spread across the day (not at night) and split across two home ISP connections to look less robotic. (since those bastards at Google started throwing captchas at me)

Live data: [stats.jensbremer.nl](https://stats.jensbremer.nl/copenhagen-flight-tracker/frontend/)

**Most of this was written by [Claude Code](https://claude.ai/code).** Hobby project. Works for me.

---

## Quick start

### Linux / macOS

```bash
git clone https://github.com/Jens-Bremer/copenhagen-flight-tracker.git
cd copenhagen-flight-tracker
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install chromium          # one-time browser download
python scripts/setup_db.py
python scripts/run_scheduler.py      # leave this running
```

### Windows (PowerShell)

```powershell
git clone https://github.com/Jens-Bremer/copenhagen-flight-tracker.git
cd copenhagen-flight-tracker
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
playwright install chromium          # one-time browser download — do this BEFORE Task Scheduler setup
python scripts\setup_db.py
python scripts\run_scheduler.py      # leave this running, or register a Scheduled Task (see WINDOWS_SETUP.md)
```

For unattended runs as a Windows scheduled task, see [docs/WINDOWS_SETUP.md](docs/WINDOWS_SETUP.md).

Edit `config.py` for your routes, ntfy alert topic, and price thresholds before starting.

## Docs

| | |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Architecture, module contract, design rules, commands cheatsheet |
| [docs/FRONTEND.md](docs/FRONTEND.md) | Dashboard pipeline, JSON data contract, extension recipes |
| [scripts/README.md](scripts/README.md) | Every script in one table |
| [deploy/README.md](deploy/README.md) | systemd setup on Linux (historical — Windows setup is current) |
| [frontend/README.md](frontend/README.md) | Frontend file map and dev workflow |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common issues and fixes |

## License

MIT — *(i have no clue how this works, take your own responsibility)*
