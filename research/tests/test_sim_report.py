"""Hash binding, escaped HTML, archived reports and actual computed charts."""

import hashlib
import json
from pathlib import Path

import pytest
from test_sim_evaluate import inputs
from test_sim_evaluate import setup as _evaluation_setup

from helios.registry.results import Split
from helios.sim.evaluate import EvaluationConfig, evaluate
from helios.sim.report import ReportError, generate_report

setup = pytest.fixture(_evaluation_setup.__wrapped__)


def test_report_has_real_computed_curves_gates_and_immutable_archive(setup, tmp_path: Path) -> None:
    engine, alpha_id, experiment_id = setup
    result = evaluate(
        alpha_id,
        Split.VALID,
        experiment_id,
        engine=engine,
        config=EvaluationConfig(warmup_rows=0),
        load_inputs=inputs,
        output_dir=tmp_path / "evidence",
        reported=False,
    )
    path = generate_report(result, output_root=tmp_path / "reports")
    content = path.read_text()
    assert "Reference equity curve" in content and "<polyline" in content
    assert "Cost sensitivity" in content and "Monthly stability" in content
    assert "Net P&amp;L cost curve" in content and "G6" in content
    assert "not self-financing portfolio NAV" in content
    assert list(path.parent.glob(result.run_id + "-*.html"))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    generate_report(result, output_root=tmp_path / "reports")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_modified_artifact_is_refused_and_text_is_escaped(setup, tmp_path: Path) -> None:
    engine, alpha_id, experiment_id = setup
    result = evaluate(
        alpha_id,
        Split.VALID,
        experiment_id,
        engine=engine,
        config=EvaluationConfig(warmup_rows=0),
        load_inputs=inputs,
        output_dir=tmp_path / "evidence",
        reported=False,
    )
    artifact = Path(result.evaluation_json["artifact"])
    data = json.loads(artifact.read_text())
    data["protocol"]["note"] = "<script>alert('unsafe')</script>"
    raw = json.dumps(data).encode()
    artifact.write_bytes(raw)
    with pytest.raises(ReportError, match="SHA-256"):
        generate_report(result, output_root=tmp_path / "reports")
    # Synthetic fixture with deliberately registered matching hash tests escaping.
    controlled = result.model_copy(
        update={
            "evaluation_json": result.evaluation_json
            | {"artifact_sha256": hashlib.sha256(raw).hexdigest()}
        }
    )
    content = generate_report(controlled, output_root=tmp_path / "reports").read_text()
    assert "<script>" not in content and "&lt;script&gt;" in content
    with pytest.raises(ReportError, match="identifier"):
        generate_report(
            controlled.model_copy(update={"alpha_id": "../outside"}),
            output_root=tmp_path / "reports",
        )
