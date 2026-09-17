# Observed PM2.5 validation artifact

`coupled_aqi_validation.json` is a deliberately limited, reproducible
comparison of an **observed station concentration** with the Open-Meteo CAMS
archive—not a visual calibration exercise and not a retrospective operational
forecast verification.

## Exact input and replay

The workflow retrieves this pinned public historical export and rejects it if
the bytes change:

- station: Anand Vihar, Delhi — DPCC CAAQMS
- period requested: 2025-10-01 through 2025-11-26
- immutable source: <https://github.com/Vibhor2702/airsen/blob/6207c163deff4b2ee2afcd20a28570b036ad6d7b/team-pipeline/forecasting/data/raw/Anand_Vihar__PM25__20251001_20251126.csv>
- SHA-256: `187ca64971fab42614f3a199ba07bb51608de3f9f7b807a7f5dbfff2361429eb`
- primary collection interface described by that export: DPCC Advance Search
  PM2.5 endpoint, `https://www.dpccairdata.com/dpccairdata/display/AallAdvanceSearchMet.php`

The raw source export is intentionally **not copied into this repository**.
The workflow uploads it for 30 days as a review artifact and stores the
verifiable hash in the JSON report. To reproduce outside Actions:

```bash
curl --fail --location --output /tmp/anand-vihar-pm25.csv \
  https://raw.githubusercontent.com/Vibhor2702/airsen/6207c163deff4b2ee2afcd20a28570b036ad6d7b/team-pipeline/forecasting/data/raw/Anand_Vihar__PM25__20251001_20251126.csv
printf '%s  %s\n' \
  187ca64971fab42614f3a199ba07bb51608de3f9f7b807a7f5dbfff2361429eb \
  /tmp/anand-vihar-pm25.csv | sha256sum --check --strict
python -m scripts.validate_coupled_aqi \
  --observations /tmp/anand-vihar-pm25.csv \
  --lat 28.6469 --lon 77.3160 \
  --station "Anand Vihar, Delhi — DPCC CAAQMS" \
  --source-provider "Delhi Pollution Control Committee (DPCC) CAAQMS station export" \
  --source-url "https://github.com/Vibhor2702/airsen/blob/6207c163deff4b2ee2afcd20a28570b036ad6d7b/team-pipeline/forecasting/data/raw/Anand_Vihar__PM25__20251001_20251126.csv" \
  --min-observation-hours 18 --min-days 30 \
  --output data/validation/coupled_aqi_validation.json
```

The stream format is `zone,param,timestamp,value`; the validator explicitly
keeps only `param == PM2.5`, interprets the DPCC timestamps as IST, removes
invalid readings, and groups valid hourly values by local calendar day.
It retains daily means only when at least 18 values are present. This is a
transparent 75% coverage screen, **not** a statement that the export has
regulatory data-validation status.

## What the report means

The report has 47 retained station/CAMS daily pairs (1 October–25 November
2025). It reports concentration MAE, RMSE, bias and correlation, plus event
hits/misses/false alarms, CSI and HSS at 90 µg/m³. Its persistence baseline
uses *only adjacent calendar days*, so missing coverage never masquerades as a
yesterday-observed forecast.

`validated-limited` means only that the named station concentration comparison
meets the configured 30-paired-day minimum. It does **not** validate the
parameterised `heat_aqi_load` multiplier, health outcomes, every NCR location,
or an archived operational forecast issued ahead of the observation. The CAMS
side is explicitly an archive/reanalysis-style retrospective comparison; it
must not be described as operational lead-time skill.
