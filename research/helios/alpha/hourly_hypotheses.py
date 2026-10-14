"""Eight fixed development hypotheses, declared before their VALID attempts (127)."""

from dataclasses import dataclass

from sqlalchemy import Connection, text

from helios.alpha.definition import AlphaDefinition
from helios.alpha.safety import validate_expression
from helios.common.config import config_hash
from helios.common.lineage import git_commit
from helios.features import basic  # noqa: F401 - populate registry
from helios.features.registry import REGISTRY
from helios.registry.experiments import Experiment, register_experiment


@dataclass(frozen=True)
class HourlyHypothesis:
    alpha_id: str
    name: str
    hypothesis: str
    expression: str

    def definition(self) -> AlphaDefinition:
        return AlphaDefinition(
            alpha_id=self.alpha_id,
            version=1,
            name=self.name,
            provenance="QUANT",
            feature_set_version="v1",
            horizon_family="H-HOURLY",
            horizon_periods=1,
            expression=self.expression,
            params={},
            author="helios_hourly",
        )


HOURLY_HYPOTHESES = (
    HourlyHypothesis(
        "hourly_h01",
        "Fast momentum",
        "Four-hour momentum may persist after accepted costs.",
        "sign(log_return_4)",
    ),
    HourlyHypothesis(
        "hourly_h02",
        "Momentum blend",
        "Combining four-hour and daily momentum may reduce directional noise.",
        "sign(log_return_4 + log_return_24)",
    ),
    HourlyHypothesis(
        "hourly_h03",
        "Volatility-scaled momentum",
        "Scaling daily momentum by trailing volatility may moderate exposure.",
        "clip(log_return_24 / (volatility_24 + 0.001), -1, 1)",
    ),
    HourlyHypothesis(
        "hourly_h04",
        "One-hour reversal",
        "A recent hourly move may partially reverse after accepted costs.",
        "-sign(log_return_1)",
    ),
    HourlyHypothesis(
        "hourly_h05",
        "Slow mean reversal",
        "Deviation from the trailing 48-hour mean may reverse.",
        "-sign(close_over_mean_48)",
    ),
    HourlyHypothesis(
        "hourly_h06",
        "Taker flow blend",
        "Taker-flow imbalance may add direction information to fast momentum.",
        "sign(log_return_4 + 0.001 * taker_buy_ratio_zscore_168)",
    ),
    HourlyHypothesis(
        "hourly_h07",
        "Volume shock momentum",
        "Fast momentum during positive volume shocks may persist.",
        "sign(log_return_4) * clip(volume_zscore_168 / 3, 0, 1)",
    ),
    HourlyHypothesis(
        "hourly_h08",
        "Quiet-regime reversal",
        "Fast momentum may reverse when short volatility is below long volatility.",
        "where(clip(sign(volatility_168 - volatility_24), 0, 1), -sign(log_return_4), 0)",
    ),
)


def preregister_hourly(connection: Connection, snapshot_id: str) -> tuple[Experiment, ...]:
    """One atomic experiment per candidate. Never loads observations or evaluates."""
    definitions = [h.definition() for h in HOURLY_HYPOTHESES]
    for definition in definitions:
        assert definition.expression is not None
        validate_expression(
            definition.expression, feature_names=REGISTRY.names(), params={}, interval="1h"
        )
        exists = connection.execute(
            text(
                "SELECT 1 FROM experiments WHERE author='helios_hourly' "
                "AND params->'definition'->>'alpha_id'=:alpha "
                "AND params->'definition'->>'version'='1' LIMIT 1"
            ),
            {"alpha": definition.alpha_id},
        ).first()
        if exists is not None:
            raise ValueError("hourly candidate version already preregistered")
    return tuple(
        register_experiment(
            connection,
            hypothesis=idea.hypothesis,
            params=dict(
                definition=definition.model_dump(mode="json", exclude={"code_commit"}),
                evaluation=dict(symbol="BTCUSDT", split="valid", warmup_rows=168, seed=0),
                retain_all=True,
                tune=False,
                test_access=False,
                prior_valid_exposure="Prior baseline, linear and LightGBM VALID results are known.",
            ),
            author="helios_hourly",
            code_commit=git_commit(),
            config_hash=config_hash(definition),
            snapshot_id=snapshot_id,
            notes="Fixed single-instrument development candidates; no measured outcome promised.",
        )
        for idea, definition in zip(HOURLY_HYPOTHESES, definitions, strict=True)
    )
