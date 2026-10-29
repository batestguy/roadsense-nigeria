# Phase 3 pilot report

Generated 2026-10-29 05:32 by `scripts/sample_pilot.py`.

- State: **Lagos**
- Resolution: **40 m**
- Tiles sampled: 2 (111 available in state)
- Months: 2026-07
- Tile-months sampled: 2
- Rows: 66

| Metric | Measured |
|---|---:|
| Bytes downloaded | 0.6 MB |
| HTTP requests | 12 |
| Bytes per tile-month | 300 KB |
| Seconds per tile-month | 13.3 |
| National 24-month projection | 14.5 GB |
| Serial runtime projection | 178 h |

Byte figures come from a counting HTTP proxy in front of the S3 endpoint, so they are
measured response bodies rather than an estimate multiplied by a guess.
