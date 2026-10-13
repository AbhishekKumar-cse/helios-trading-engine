"""Check useful structural substitution and reject unsafe signatures statically."""

import subprocess
import sys
from pathlib import Path

from helios.common.interfaces import ExecutionVenue, MarketDataSource, RiskEngine
from helios.common.types import OrderAction, ReasonCode, RiskDecision


class RejectingRisk:
    def check(self, action: OrderAction) -> RiskDecision:
        return RiskDecision(accepted=False, reason=ReasonCode.MISSING_LIMITS, timestamp=0)


def test_risk_adapter_is_structural_and_keeps_fail_closed_result() -> None:
    risk: RiskEngine = RejectingRisk()
    assert isinstance(risk, RiskEngine)
    assert not isinstance(risk, ExecutionVenue)
    assert not isinstance(risk, MarketDataSource)


def test_type_checker_accepts_valid_and_rejects_unsafe_risk_adapter(tmp_path: Path) -> None:
    source = tmp_path / "adapter.py"
    template = """from helios.common.interfaces import RiskEngine
from helios.common.types import OrderAction, RiskDecision, ReasonCode
class Adapter:
    def check(self, action: OrderAction) -> RESULT:
        BODY
risk: RiskEngine = Adapter()
"""
    source.write_text(
        template.replace("RESULT", "RiskDecision").replace(
            "BODY",
            "return RiskDecision(accepted=False, reason=ReasonCode.INTERNAL_ERROR, timestamp=0)",
        )
    )
    command = [
        sys.executable,
        "-m",
        "mypy",
        "--strict",
        "--follow-imports=silent",
        "--cache-dir",
        str(tmp_path / "mypy-cache"),
        str(source),
    ]
    good = subprocess.run(command, capture_output=True, text=True, timeout=90)
    assert good.returncode == 0, good.stdout
    source.write_text(template.replace("RESULT", "str").replace("BODY", "return 'ACCEPT'"))
    bad = subprocess.run(command, capture_output=True, text=True, timeout=90)
    assert bad.returncode != 0 and "Incompatible types in assignment" in bad.stdout
