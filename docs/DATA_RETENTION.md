# Data Retention Policy

## Overview

This document describes how flight price observations are retained, archived, and removed from the primary database.

## Retention Periods

### Hot Data (Primary Database)
- **Duration**: 2 years of continuous history
- **Storage**: `data/flights.db` (SQLite)
- **Purpose**: Daily dashboards, analytics, price trending
- **Queries**: All active analysis and reporting

### Archive Data
- **Duration**: Indefinite (until manual removal)
- **Storage**: `data/archive/` (CSV format, one file per year)
- **Purpose**: Long-term reference, historical analysis
- **Access**: Manual query via spreadsheet or script

### Backups
- **Frequency**: Daily at 01:00
- **Count**: Last 7 backups retained (configurable: `BACKUP_KEEP_LAST_N`)
- **Storage**: `data/backups/` + off-disk copy (OneDrive/second drive)
- **Purpose**: Recovery from corruption or accidental deletion

## Archival Process

Observations older than 2 years should be:
1. Exported to CSV: `data/archive/flights_YYYY.csv`
2. Deleted from primary database
3. Verified: old data no longer present in DB
4. Backed up: archive CSV copied to off-disk location

### Manual Archival

```bash
# Export observations from 2022 and earlier
python scripts/archive_old_data.py --before 2023-01-01

# Verify deletion
python scripts/query_prices.py --stats
```

## Database Size Thresholds

- **Warning**: When `flights.db` exceeds 500 MB, the health check will alert you
- **Action**: Archive old data and trigger a cleanup
- **Expected timeline**: At 156 jobs/day (CPH↔AMS), you'll reach 500 MB in ~3 years

## Rationale

**Why 2 years?**
- Flight prices follow seasonal patterns (2-year cycle captures a full pattern)
- Older data is less relevant for future bookings
- Keeps queries fast and disk usage reasonable on a personal project

**Why keep backups separate?**
- Protects against accidental deletion
- Protects against disk corruption (backups on different drive)
- Allows point-in-time recovery if needed

## Implementation Notes

- Archival is currently **manual** (no automatic script yet)
- The health check monitors database size but does not auto-delete
- Archive files are plain CSV — can be imported to another database if needed
- Off-disk backup copy should be on a second drive or cloud sync (OneDrive/Dropbox)
