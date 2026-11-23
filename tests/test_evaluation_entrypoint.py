"""Exercise the actual bootstrap the way Spark Python tasks execute source."""

from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_evaluation.py"


def test_jobs_exec_without_file_uses_script_argument_from_an_unrelated_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--limit", "1"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    namespace = {"__name__": "entrypoint_bootstrap_test"}
    exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), namespace)
    assert namespace["ROOT"] == SCRIPT.parents[1]
    assert sys.path[0] == str(SCRIPT.parents[1])
    assert "__file__" not in namespace


def test_regular_script_execution_prefers_file_over_launcher_argv(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["/unrelated/launcher.py"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    namespace = {"__name__": "entrypoint_bootstrap_test", "__file__": str(SCRIPT)}
    exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), namespace)
    assert namespace["ROOT"] == SCRIPT.parents[1]


def test_missing_source_fails_with_a_deployment_action(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["-c"])
    with pytest.raises(RuntimeError, match="bundle's workspace files"):
        exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), {"__name__": "bootstrap_test"})
