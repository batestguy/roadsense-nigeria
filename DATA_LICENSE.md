# Data licence and attribution

The **source code** in this repository is MIT licensed (see `LICENSE`).

The **derived data products** are licensed **CC BY-SA 4.0** because they inherit the share-alike
terms of their most restrictive upstream source.

## Why share-alike applies

GRID3 NGA Roads v1.0 is published under CC BY-SA 4.0:

> Users are free to download, store, access, use, copy, adapt, transform, alter, arrange, build upon,
> distribute and transmit this work and any derivative works. Attribution of the source must be
> provided, and further distribution of this work or derived work must maintain the same terms of
> data use and license as set forth in this Terms of Use.
> — GRID3 NGA Roads v1.0, Terms of Use, CC BY-SA 4.0

Any table in this project that contains road segment geometry, road accessibility attributes, or a
label matched to a segment is a derivative of that dataset. Those tables, and the map tiles rendered
from them, are therefore CC BY-SA 4.0.

Model weights and model code are **not** treated as derivative works of the underlying data for the
purposes of this project. If that position is ever contested, the conservative fallback is to license
the released model artefacts CC BY-SA 4.0 as well.

## Covered by CC BY-SA 4.0

- `segments` — GRID3-derived road segment table
- `labels` — procurement events matched to segments
- `s2_features`, `weather_features`, `model_input` — derived feature tables
- `predictions`, `allocation` — derived outputs containing segment identifiers
- Map tiles and GeoJSON served by the dashboard

## Attribution required

Derived data and any visualisation must carry all of:

1. **GRID3 NGA Roads v1.0** — Center for Integrated Earth System Information (CIESIN), Columbia
   University, 2025. DOI [10.7916/b42r-6w17](https://doi.org/10.7916/b42r-6w17). CC BY-SA 4.0.
2. **Sentinel-2 Rolling Monthly GeoMAD** — Digital Earth Africa. Contains modified Copernicus
   Sentinel data.
3. **Copernicus Sentinel-2** — European Space Agency / European Commission.
4. **Weather data** — Open-Meteo.com (ERA5 reanalysis), CC BY 4.0. Non-commercial use.
5. **Procurement data** — Nigeria Open Contracting Portal (NOCOPO), Bureau of Public Procurement,
   via the Open Contracting Data Standard registry.

## Upstream licence summary

| Source | Licence | Obligation |
|---|---|---|
| GRID3 NGA Roads v1.0 | CC BY-SA 4.0 | Attribution + share-alike |
| Digital Earth Africa GeoMAD | CC BY 4.0 | Attribution |
| Copernicus Sentinel data | Free, open (Copernicus) | Attribution |
| Open-Meteo / ERA5 | CC BY 4.0 | Attribution; **non-commercial only** |
| Nigeria OCDS (NOCOPO/BPP) | Open government data | Attribution |

## Non-commercial limitation

Open-Meteo's free tier is licensed for **non-commercial use only**. This project is a portfolio and
research artefact and qualifies. Any commercial deployment would need a paid Open-Meteo subscription,
which would break the zero-recurring-cost property. Commercial use would also need to re-examine the
share-alike obligations on any redistributed derived data.
