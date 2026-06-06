from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PresentationProfile:
    """Controls how much runtime detail is exposed to the user.

    Profiles change only presentation. They must not change verification,
    repair, task graph generation, or execution behavior.
    """

    name: str
    include_reasons: bool = True
    include_suggestions: bool = True
    include_location: bool = False
    include_technical: bool = False
    include_raw_report: bool = False
    max_reasons: int = 3
    max_suggestions: int = 3
    max_location: int = 0
    llm_allowed: bool = False


class PresentationProfileRegistry:
    """Small deterministic registry for user-facing presentation modes."""

    _profiles: dict[str, PresentationProfile] = {
        "user": PresentationProfile(
            name="user",
            include_reasons=True,
            include_suggestions=True,
            include_location=False,
            include_technical=False,
            max_reasons=2,
            max_suggestions=2,
            max_location=0,
            llm_allowed=False,
        ),
        "advanced": PresentationProfile(
            name="advanced",
            include_reasons=True,
            include_suggestions=True,
            include_location=True,
            include_technical=False,
            max_reasons=6,
            max_suggestions=6,
            max_location=4,
            llm_allowed=True,
        ),
        "developer": PresentationProfile(
            name="developer",
            include_reasons=True,
            include_suggestions=True,
            include_location=True,
            include_technical=True,
            max_reasons=10,
            max_suggestions=10,
            max_location=8,
            llm_allowed=True,
        ),
        "diagnostic": PresentationProfile(
            name="diagnostic",
            include_reasons=True,
            include_suggestions=True,
            include_location=True,
            include_technical=True,
            include_raw_report=True,
            max_reasons=20,
            max_suggestions=20,
            max_location=20,
            llm_allowed=True,
        ),
    }

    default_name = "advanced"

    @classmethod
    def normalize(cls, value: str | None) -> str:
        name = str(value or cls.default_name).strip().casefold()
        return name if name in cls._profiles else cls.default_name

    @classmethod
    def get(cls, value: str | None = None) -> PresentationProfile:
        return cls._profiles[cls.normalize(value)]

    @classmethod
    def list_profiles(cls) -> list[dict[str, Any]]:
        return [
            {
                "name": p.name,
                "include_reasons": p.include_reasons,
                "include_suggestions": p.include_suggestions,
                "include_location": p.include_location,
                "include_technical": p.include_technical,
                "include_raw_report": p.include_raw_report,
                "llm_allowed": p.llm_allowed,
            }
            for p in cls._profiles.values()
        ]


__all__ = ["PresentationProfile", "PresentationProfileRegistry"]
