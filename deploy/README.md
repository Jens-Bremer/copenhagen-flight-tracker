# deploy/ (Linux/Historical)

> **Important:** This directory contains Linux/systemd deployment files for historical reference only.
> This project is deployed on **Windows** via Task Scheduler. See `docs/WINDOWS_SETUP.md` for the current setup.

**Linux only** — Deployment files for systemd-based systems (no longer actively maintained; reference only).

Deployment files for Linux systems using systemd. These assume the project lives at `/opt/copenhagen-flight-tracker` and runs as user `flighttracker`.

| File | Purpose |
|------|---------|
| `copenhagen-flight-tracker.service` | systemd unit — runs `scripts/run_scheduler.py` as a daemon with `Restart=on-failure` and graceful `SIGTERM` shutdown |
| `copenhagen-flight-tracker.logrotate` | logrotate config — rotates `/opt/copenhagen-flight-tracker/logs/*.log` daily, keeps 14 compressed copies |
