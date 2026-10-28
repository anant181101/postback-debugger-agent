"""Ground truth for the seeded failure scenarios.

Used by tests and evals only. The agent must never read this module, because it contains
the expected answers. Click IDs are deliberately opaque so they do not hint at the cause.
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
        "clk_3f9a1c07",
        FailureType.NONE,
        "Install and purchase postbacks were delivered to AlphaAds.",
    ),
    Scenario(
        "clk_8b24e6d1",
        FailureType.NO_INSTALL,
        "The click never led to an install, so no postback was expected.",
    ),
    Scenario(
        "clk_c71d0f5a",
        FailureType.ATTRIBUTED_TO_OTHER_CLICK,
        "A later GammaNetwork click on the same device won last-click attribution.",
    ),
    Scenario(
        "clk_19e4b8c3",
        FailureType.OUTSIDE_ATTRIBUTION_WINDOW,
        "The install came 9 days after the click; AlphaAds has a 7-day window.",
    ),
    Scenario(
        "clk_e05a7f92",
        FailureType.FRAUD_REJECTED,
        "The install was rejected by fraud checks (click-to-install time of 4 seconds).",
    ),
    Scenario(
        "clk_6d3c91be",
        FailureType.EVENT_NOT_MAPPED,
        "Event 'purchase_v2' is missing from the AlphaAds event mapping, so it was never sent.",
    ),
    Scenario(
        "clk_a4f2083d",
        FailureType.PARTNER_4XX,
        "DeltaReach returned 401 because the configured API key expired before the postback.",
    ),
    Scenario(
        "clk_52b9d4e7",
        FailureType.PARTNER_5XX,
        "GammaNetwork returned 503 on all 3 attempts.",
    ),
    Scenario(
        "clk_f8c6a215",
        FailureType.TIMEOUT,
        "GammaNetwork did not respond within its 2000 ms timeout on all 3 attempts.",
    ),
    Scenario(
        "clk_0e7b3fa9",
        FailureType.MISSING_MACRO,
        "The iOS user opted out of tracking, so {advertising_id} was left unresolved "
        "and BetaMedia returned 400.",
    ),
    Scenario(
        "clk_b3a85c60",
        FailureType.DUPLICATE,
        "The SDK tracked the same purchase twice; AlphaAds rejected the second with 409.",
    ),
)

SCENARIOS_BY_TYPE: dict[FailureType, Scenario] = {s.failure_type: s for s in SCENARIOS}
