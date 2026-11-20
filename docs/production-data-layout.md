# Production data layout (outdoor PC)

Checked over ssh on 2026-11-20 (`outdoor-wsl`, the WSL instance behind the Windows host
`outdoor-pc`). Docker and the checkout `~/outdoor-data-monitoring` live there.

## Data mount

The ingestion container sees the host folder `~/outdoor-data-monitoring/data` as `/data`,
**read only** (`docker inspect` reports `RW=false`). Ingestion never writes to the exports.
The other mounts are not data mounts: Grafana's dashboards and provisioning folders are read
only, its data folder, SymmetricDS and the postgres volume are read-write.

```
data/
├── mppt_temp_irr/
│   ├── all_YYYYMMDD/         early exports, files directly in the folder (before 2023-06)
│   └── data_YYYYMMDD/        daily exports (about 70 folders)
│       └── data/             the files of that export, see below
└── test/                     scratch folder, not ingested
```

There is no separate irradiance folder: irradiance, temperature and MPP files all sit together
in `data_YYYYMMDD/data/`. (`data/spectral_data/` from the README does not exist on the PC yet.)

## Files in `data_YYYYMMDD/data/`

- `output_board<N>_channel<M>.txt` — MPP tracker data
- `m7004_ID_<hex>.txt` — temperature sensors
- `PT-104_channel_<NN>.txt` — irradiance (PT-104 + ML-02 reference cells)
- `mbox_ID_<serial>       .txt` — irradiance, sun tracker (EKO M-Box); the name has spaces
  before `.txt`. Present in 33 folders, `data_20250807` to `data_20261116`.
- `errorLog.txt`, `event_log.txt` — not ingested

## Database state on 2026-11-20

- `irradiance_sensor`: ids 3 and 4 (`PT-104_channel_01`, `_03`, about 2.4M rows each up to
  2026-11-16) and 24 (`MBox_sun_tracker`, serial `S19057654`, no measurements).
- `ingestion_log`: 107 completed (73 of them `data_*` folders), 234 failed, 5 started.
- The checkout was on `main` at the release "timezone fix for ingestion (#12)", without the
  sun tracker ingestion. The `ingestion` container did not know the `mbox_` file name, so it
  skipped the file in every folder.
