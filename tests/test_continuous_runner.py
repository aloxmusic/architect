"""Actual subprocess checks for exit status, evidence and cross-process exclusion."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "continuous_tests.py"


def invoke(output: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNNER), "--output", str(output), *extra],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_bad_package_reports_failure_without_false_success(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "manifest.json").write_text(
        json.dumps({"files": {"payload.json": {"bytes": 2, "sha256": "0" * 64}}})
    )
    (package / "payload.json").write_text("{}")
    output = tmp_path / "results"
    result = invoke(output, "--package", str(package))
    assert result.returncode == 1, result.stderr
    report = json.loads((output / "latest-quick.json").read_text())
    assert report["status"] == "FAIL"
    assert "SHA-256 mismatch" in report["steps"]["package_integrity"]["error"]
    assert report["steps"]["http_smoke"]["status"] == "PASS"
    assert "attachment download" in report["not_executed"]


@pytest.mark.skipif(os.name != "nt", reason="Windows OS lock integration")
def test_concurrent_run_skips_and_lock_releases(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows OS lock integration")

    import msvcrt

    with (tmp_path / "runner.lock").open("w+b") as lock:
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        result = invoke(tmp_path)
        assert result.returncode == 2, result.stderr
        assert "another run" in result.stdout
        assert not (tmp_path / "latest-quick.json").exists()
    result = invoke(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "latest-quick.json").exists()


def test_quick_run_keeps_full_status_separate(tmp_path: Path) -> None:
    full = tmp_path / "latest-full.json"
    full.write_text('{"status": "FAIL"}')
    result = invoke(tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(full.read_text())["status"] == "FAIL"
    report = json.loads((tmp_path / "latest-quick.json").read_text())
    assert report["status"] == "PASS"
    assert report["image_provider_called"] is False
    assert report["project_persisted"] is False
