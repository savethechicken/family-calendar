from pathlib import Path

import pytest

from app.config import ConfigError, load_config


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


BASE = """
display:
  timezone: "{tz}"
calendars:
{cals}
"""


def calendar_block(calendar_id: str, color: str = "#5b8cff", source_type: str = "demo") -> str:
    return f"""
  - id: {calendar_id}
    name: Test
    color: "{color}"
    source:
      type: {source_type}
"""


def test_loads_minimal_config(tmp_path: Path) -> None:
    path = write_config(tmp_path, BASE.format(tz="UTC", cals=calendar_block("family")))
    config = load_config(path)

    assert config.display.title == "Family Calendar"
    assert config.display.week_starts_on == "monday"
    assert config.display.tz.key == "UTC"
    assert [calendar.id for calendar in config.calendars] == ["family"]


def test_env_variables_are_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAMILY_URL", "https://example.com/family.ics")
    body = """
calendars:
  - id: family
    name: Family
    color: "#039be5"
    source:
      type: ics
      url: "${FAMILY_URL}"
"""
    config = load_config(write_config(tmp_path, body))
    assert config.calendars[0].source.url == "https://example.com/family.ics"


def test_rejects_duplicate_calendar_ids(tmp_path: Path) -> None:
    body = BASE.format(
        tz="UTC",
        cals=calendar_block("family") + calendar_block("family"),
    )
    with pytest.raises(ConfigError, match="Duplicate calendar id"):
        load_config(write_config(tmp_path, body))


def test_rejects_unknown_timezone(tmp_path: Path) -> None:
    body = BASE.format(tz="Mars/Olympus_Mons", cals=calendar_block("family"))
    with pytest.raises(ConfigError, match="Unknown timezone"):
        load_config(write_config(tmp_path, body))


def test_requires_source_url_for_ics(tmp_path: Path) -> None:
    body = BASE.format(tz="UTC", cals=calendar_block("family", source_type="ics"))
    with pytest.raises(ConfigError, match="no source.url"):
        load_config(write_config(tmp_path, body))


def test_weather_requires_coordinates(tmp_path: Path) -> None:
    body = """
weather:
  enabled: true
""" + BASE.format(tz="UTC", cals=calendar_block("family"))
    with pytest.raises(ConfigError, match="latitude"):
        load_config(write_config(tmp_path, body))
