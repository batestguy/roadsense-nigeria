# Phase 3 pilot report

Generated 2026-10-29 04:48 by `scripts/sample_pilot.py`.

- State: **Lagos**
- Resolution: **40 m**
- Tiles sampled: 5 (111 available in state)
- Months: 2026-05, 2026-06, 2026-07
- Tile-months sampled: 10
- Rows: 310

| Metric | Measured |
|---|---:|
| Bytes downloaded | 7.4 MB |
| HTTP requests | 62 |
| Bytes per tile-month | 744 KB |
| Seconds per tile-month | 30.5 |
| National 24-month projection | 36.0 GB |
| Serial runtime projection | 410 h |

Byte figures come from a counting HTTP proxy in front of the S3 endpoint, so they are
measured response bodies rather than an estimate multiplied by a guess.
