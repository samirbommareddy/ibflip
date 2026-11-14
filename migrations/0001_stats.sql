-- IB-Flip anonymous game-activity aggregates (see docs/usage-stats.md).
-- Only daily counters: no names, IPs, user agents, room codes, chat or cards.

CREATE TABLE IF NOT EXISTS counters (
  day    TEXT    NOT NULL,            -- UTC date, YYYY-MM-DD
  metric TEXT    NOT NULL,            -- allow-listed metric name
  dim    TEXT    NOT NULL DEFAULT '', -- allow-listed dimension, e.g. "4p-1h"
  n      INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, metric, dim)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS peaks (
  day    TEXT    NOT NULL,
  metric TEXT    NOT NULL,            -- peak_rooms | peak_active_rooms | peak_players
  value  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, metric)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,             -- e.g. last_ingest
  value TEXT NOT NULL
) WITHOUT ROWID;
