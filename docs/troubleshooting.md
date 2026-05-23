# Troubleshooting

## Scheduler stops collecting at midnight

Check the heartbeat at `data/last_run.json` and the daily log in `logs/tracker.log`.

## Dashboard shows "Not enough data yet"

Normal in early days. The When-to-buy card needs at least `RELIABLE_MIN_OBSERVATIONS` per lead-time bucket (default 10). Give it a week or two.

## No ntfy alerts arriving

Check `NTFY_TOPIC` in `config.py` is not the placeholder `your-topic-here`. The topic must match exactly between `config.py` and your ntfy app subscription.

## Health check reports "Bot challenge today"

Google may have rotated its cookie-consent flow or bot-detection heuristics. Check:
- `src/browser_fetcher.py` — `_STEALTH_SCRIPT` and the `SOCS` cookie pre-seeded on `.google.com`
- `config.BOT_CHALLENGE_TITLE_PATTERNS`

See `CLAUDE.md` → "Transport Layer" for the full stealth-stack picture.

## Proxy returning 407

The Squid proxy uses IP-based ACL, not credentials. If you're seeing `407 Proxy Auth Required`, your scraper machine's IP has changed and needs to be updated in `/etc/squid/squid.conf` on the proxy machine:

```squid
acl scraper_ip src <your-ip>
http_access allow scraper_ip
```

Do **not** add credentials to `data/proxies.txt` — Chrome ignores them when the `407` challenge comes first. See `CLAUDE.md` → "Proxy setup".

## Disk growing faster than expected

The persistent browser profiles at `data/browser_profiles/` can accumulate. Check their size with `du -sh data/browser_profiles/`. Safe to delete — they'll be recreated on next startup (you'll lose the cookie consent bypass for one run).
