import pandas as pd
import pytest

from core.risk import drill_anomaly


def test_heatwave_drill_is_anchored_to_forecast_window():
    df = pd.DataFrame({"timestamp_local": pd.to_datetime([
        "2026-01-10T00:00", "2026-01-11T00:00", "2026-01-12T00:00",
        "2026-01-13T00:00", "2026-01-14T00:00",
    ])})
    assert drill_anomaly(df, "heatwave").tolist() == [0, 0, 0, 1.5, 5.0]


def test_unknown_drill_rejected():
    df = pd.DataFrame({"timestamp_local": pd.to_datetime(["2026-01-10"])})
    with pytest.raises(ValueError):
        drill_anomaly(df, "not-a-drill")


def test_drill_anomaly_holds_final_value_after_schedule():
    df = pd.DataFrame({"timestamp_local": pd.date_range("2026-01-10", periods=8)})
    assert drill_anomaly(df, "heatwave").tolist() == [0, 0, 0, 1.5, 5.0, 8.5, 8.5, 8.5]


def test_drill_anomaly_preserves_frame_index():
    df = pd.DataFrame(
        {"timestamp_local": pd.to_datetime(["2026-02-01", "2026-02-02"])},
        index=[10, 20],
    )
    result = drill_anomaly(df, "heatwave")
    assert result.index.tolist() == [10, 20]


def test_drill_anomaly_accepts_timestamp_strings():
    df = pd.DataFrame({"timestamp_local": ["2026-03-04T12:00", "2026-03-07T12:00"]})
    assert drill_anomaly(df, "heatwave").tolist() == [0.0, 1.5]


def test_drill_anomaly_returns_numeric_series():
    df = pd.DataFrame({"timestamp_local": pd.to_datetime(["2026-04-01"])})
    result = drill_anomaly(df, "heatwave")
    assert result.dtype.kind in "fi"
