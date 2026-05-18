from __future__ import annotations

from zoneinfo import ZoneInfoNotFoundError

from auxiliary_brain.scheduler.timezone_resolver import RuntimeTimezoneResolver
from auxiliary_brain.scheduler.trigger_parser import RuntimeTriggerParser


def test_configured_timezone_fallback_is_used_when_zoneinfo_database_is_missing(monkeypatch, tmp_path):
    config = tmp_path / "timezones.json"
    config.write_text(
        '{"fallback_offsets_minutes":{"Runtime/Configured":60}}',
        encoding="utf-8",
    )

    import auxiliary_brain.scheduler.timezone_resolver as resolver_module

    def missing_zoneinfo(key: str):
        raise ZoneInfoNotFoundError(key)

    monkeypatch.setattr(resolver_module, "ZoneInfo", missing_zoneinfo)
    resolver = RuntimeTimezoneResolver(config)
    parser = RuntimeTriggerParser(resolver)

    activation = parser.parse("10:10 AM", default_timezone="Runtime/Configured")

    assert activation["mode"] == "scheduled"
    assert activation["timezone"] == "Runtime/Configured"
    assert activation["metadata"]["timezone_resolution"]["source"] == "configured_fixed_offset"
    assert activation["metadata"]["timezone_resolution"]["offset_minutes"] == 60
