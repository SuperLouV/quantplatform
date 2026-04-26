"""Install or remove the macOS launchd job for daily refresh."""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LABEL = "com.louyilin.quantplatform.daily-refresh"
DEFAULT_POOL = "data/reference/system/stock_pools/preset/default_core.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the QuantPlatform daily refresh launchd job.")
    parser.add_argument("action", choices=["install", "uninstall", "status", "print-plist"])
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--hour", type=int, default=6, help="Beijing-time hour for daily refresh.")
    parser.add_argument("--minute", type=int, default=30, help="Beijing-time minute for daily refresh.")
    parser.add_argument("--pool", default=DEFAULT_POOL)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    plist_path = _plist_path(args.label)
    plist_payload = _plist_payload(
        label=args.label,
        hour=args.hour,
        minute=args.minute,
        pool=args.pool,
        workers=args.workers,
    )

    if args.action == "print-plist":
        print(plistlib.dumps(plist_payload).decode("utf-8"))
        return
    if args.action == "install":
        _write_plist(plist_path, plist_payload)
        _launchctl("bootout", args.label, check=False)
        _launchctl("bootstrap", args.label, plist_path=plist_path)
        _launchctl("enable", args.label)
        print(f"installed={plist_path}")
        print(f"label={args.label}")
        print(f"schedule={args.hour:02d}:{args.minute:02d} Asia/Shanghai")
        return
    if args.action == "uninstall":
        _launchctl("bootout", args.label, check=False)
        if plist_path.exists():
            plist_path.unlink()
        print(f"removed={plist_path}")
        return
    if args.action == "status":
        _launchctl("print", args.label, check=False)


def _plist_path(label: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def _plist_payload(*, label: str, hour: int, minute: int, pool: str, workers: int) -> dict[str, object]:
    python_bin = str(Path(sys.executable).resolve())
    log_dir = PROJECT_ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    command = (
        f"cd {PROJECT_ROOT!s} && "
        f"PYTHONPATH=src {python_bin} scripts/run_daily_refresh.py "
        f"--pool {pool} --workers {workers}"
    )
    return {
        "Label": label,
        "ProgramArguments": ["/bin/zsh", "-lc", command],
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": str(log_dir / "daily_refresh_launchd.out.log"),
        "StandardErrorPath": str(log_dir / "daily_refresh_launchd.err.log"),
        "WorkingDirectory": str(PROJECT_ROOT),
        "EnvironmentVariables": {
            "PYTHONPATH": "src",
            "TZ": "Asia/Shanghai",
        },
        "RunAtLoad": False,
    }


def _write_plist(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(payload, sort_keys=False))


def _launchctl(action: str, label: str, *, plist_path: Path | None = None, check: bool = True) -> None:
    domain = f"gui/{os.getuid()}"
    if action == "bootstrap":
        command = ["launchctl", "bootstrap", domain, str(plist_path)]
    elif action == "bootout":
        command = ["launchctl", "bootout", _service_target(label)]
    elif action == "enable":
        command = ["launchctl", "enable", _service_target(label)]
    elif action == "print":
        command = ["launchctl", "print", _service_target(label)]
    else:
        raise ValueError(f"Unsupported launchctl action: {action}")
    subprocess.run(command, check=check)


def _service_target(label: str) -> str:
    return f"gui/{os.getuid()}/{label}"


if __name__ == "__main__":
    main()
