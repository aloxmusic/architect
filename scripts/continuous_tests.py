"""Sequential local checks with durable evidence; never generate images or persist ADG."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(Path(sys.executable).with_name("python.exe")) if os.name == "nt" else sys.executable


def verify_package(directory: Path) -> None:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8-sig"))
    for name, expected in manifest["files"].items():
        path = (directory / name).resolve()
        if path.parent != directory.resolve():
            raise ValueError("Manifest path must be directly inside package directory")
        payload = path.read_bytes()
        if len(payload) != expected["bytes"]:
            raise ValueError(f"Byte count mismatch: {name}")
        if hashlib.sha256(payload).hexdigest().upper() != expected["sha256"].upper():
            raise ValueError(f"SHA-256 mismatch: {name}")
        json.loads(payload)


def run_step(command: list[str], log: Path, timeout: int) -> dict[str, object]:
    started = datetime.now(UTC)
    env = dict(os.environ)
    env["ARCHITECT_AI_RUN_LIVE_OPENAI_TESTS"] = "0"
    env["ARCHITECT_AI_MCP_LIVE_INTERPRETER_ENABLED"] = "false"
    with log.open("w", encoding="utf-8") as stream:
        try:
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            status = "PASS" if result.returncode == 0 else "FAIL"
            error = None
            code = result.returncode
        except (subprocess.TimeoutExpired, OSError) as exc:
            status, error, code = "FAIL", str(exc), None
    return {
        "status": status,
        "exit_code": code,
        "error": error,
        "started_at": started.isoformat(),
        "log": str(log),
        "command": command,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["quick", "full"], default="quick")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--build-python", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # OS lock releases on process exit, including crashes. Do not delete the lock file.
    with (args.output / "runner.lock").open("a+b") as lock:
        lock.seek(0)
        if os.name == "nt":
            import msvcrt

            if lock.seek(0, 2) == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                print("SKIP: another run owns the lock")
                return 2
        else:
            import fcntl

            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                print("SKIP: another run owns the lock")
                return 2
        run_dir = args.output / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        run_dir.mkdir()
        results: dict[str, object] = {}
        if args.package:
            try:
                verify_package(args.package)
                results["package_integrity"] = {"status": "PASS"}
            except (OSError, ValueError, KeyError, TypeError) as exc:
                results["package_integrity"] = {"status": "FAIL", "error": str(exc)}
        commands = [("http_smoke", [PYTHON, "scripts/smoke.py"])]
        if args.mode == "full":
            commands = [
                (
                    "pytest",
                    [PYTHON, "-m", "pytest", "--junitxml", str(run_dir / "pytest.xml")],
                ),
                ("ruff", [PYTHON, "-m", "ruff", "check", "."]),
                ("format", [PYTHON, "-m", "ruff", "format", "--check", "."]),
                ("mypy", [PYTHON, "-m", "mypy"]),
                (
                    "wheel",
                    [
                        str(args.build_python or Path(PYTHON)),
                        "-m",
                        "pip",
                        "wheel",
                        ".",
                        "--no-deps",
                        "--no-build-isolation",
                        "--wheel-dir",
                        str(run_dir / "wheel"),
                    ],
                ),
                *commands,
            ]
        for name, command in commands:
            results[name] = run_step(command, run_dir / f"{name}.log", 600)
        failed = any(item["status"] == "FAIL" for item in results.values())
        report = {
            "created_at": datetime.now(UTC).isoformat(),
            "mode": args.mode,
            "status": "FAIL" if failed else "PASS",
            "steps": results,
            "not_executed": [
                "registered ChatGPT connector",
                "attachment download",
                "Linux host transfer",
                "skill autoactivation",
            ],
            "image_provider_called": False,
            "project_persisted": False,
        }
        report_path = run_dir / "report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        previous_path = args.output / f"latest-{args.mode}.json"
        previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
        changed = previous.get("status") != report["status"]
        temporary = args.output / f"latest-{args.mode}.tmp"
        temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
        temporary.replace(previous_path)
        (run_dir / "summary.txt").write_text(
            f"{report['status']} | mode={args.mode} | status_changed={changed}\n"
            + "\n".join(f"{name}: {item['status']}" for name, item in results.items())
            + "\nHost UI and Linux transfer checks: NOT EXECUTED\n",
            encoding="utf-8",
        )
        print(f"{report['status']}: {report_path}")
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
