# Copenhagen Flight Tracker

A self-hosted Python service that tracks one-way flight prices between Copenhagen (CPH) and Amsterdam (AMS) in both directions. It scrapes Google Flights via the [`fast-flights`](https://github.com/AWeirdDev/flights) library (Protobuf-based, no browser needed), stores every observed price in SQLite, and spreads its requests throughout the day to avoid IP bans.

## Install

```bash
git clone https://github.com/Jens-Bremer/copenhagen-flight-tracker.git
cd copenhagen-flight-tracker
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mkdir -p data logs
python scripts/setup_db.py
```

## Usage

See below — filled in after MVP is complete.

## License

MIT
