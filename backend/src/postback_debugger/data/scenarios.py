"""Ground truth for the seeded failure scenarios.

Used by tests and evals only. The agent must never read this module, because it contains
the expected answers. Click IDs are deliberately opaque so they do not hint at the cause.

Click IDs are MongoDB ObjectIds, as in real MMPs: 8 hex digits of Unix timestamp (the
click time set in seed.py), 10 of process id, 6 of counter. test_seed checks they match.
"""

from dataclasses import dataclass

from postback_debugger.data.models import FailureType


@dataclass(frozen=True)
class Scenario:
    click_id: str
    failure_type: FailureType
    description: str


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "6abe2f209e4c2a71d35b3c01",
        FailureType.NONE,
        "Install and purchase postbacks were delivered to AlphaAds.",
    ),
    Scenario(
        "6abf80a09e4c2a71d35b3c02",
        FailureType.NO_INSTALL,
        "The click never led to an install, so no postback was expected.",
    ),
    Scenario(
        "6ac0c4109e4c2a71d35b3c03",
        FailureType.ATTRIBUTED_TO_OTHER_CLICK,
        "A later GammaNetwork click on the same device won last-click attribution.",
    ),
    Scenario(
        "6ac223a09e4c2a71d35b3c04",
        FailureType.OUTSIDE_ATTRIBUTION_WINDOW,
        "The install came 9 days after the click; AlphaAds has a 7-day window.",
    ),
    Scenario(
        "6ac391409e4c2a71d35b3c05",
        FailureType.FRAUD_REJECTED,
        "The install was rejected by fraud checks (click-to-install time of 4 seconds).",
    ),
    Scenario(
        "6ac4c6a09e4c2a71d35b3c06",
        FailureType.EVENT_NOT_MAPPED,
        "Event 'purchase_v2' is missing from the AlphaAds event mapping, so it was never sent.",
    ),
    Scenario(
        "6aca0ca09e4c2a71d35b3c07",
        FailureType.PARTNER_4XX,
        "DeltaReach returned 401 because the configured API key expired before the postback.",
    ),
    Scenario(
        "6ac618209e4c2a71d35b3c08",
        FailureType.PARTNER_5XX,
        "GammaNetwork returned 503 on all 3 attempts.",
    ),
    Scenario(
        "6ac769a09e4c2a71d35b3c09",
        FailureType.TIMEOUT,
        "GammaNetwork did not respond within its 2000 ms timeout on all 3 attempts.",
    ),
    Scenario(
        "6acb5e209e4c2a71d35b3c0a",
        FailureType.MISSING_MACRO,
        "The iOS user opted out of tracking, so {advertising_id} was left unresolved "
        "and BetaMedia returned 400.",
    ),
    Scenario(
        "6accafa09e4c2a71d35b3c0b",
        FailureType.DUPLICATE,
        "The SDK tracked the same purchase twice; AlphaAds rejected the second with 409.",
    ),
)

SCENARIOS_BY_TYPE: dict[FailureType, Scenario] = {s.failure_type: s for s in SCENARIOS}
