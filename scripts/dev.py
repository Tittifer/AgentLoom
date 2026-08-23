"""Start the AgentLoom backend and frontend from one command."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def require_command(name: str) -> str:
    """Return an executable path or stop with an actionable error."""

    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"Required command '{name}' was not found on PATH")
    return executable


def run_checked(command: list[str], *, cwd: Path) -> None:
    """Run a setup command and fail when it does not complete successfully."""

    subprocess.run(command, cwd=cwd, check=True)


def start_process(command: list[str], *, cwd: Path) -> subprocess.Popen[bytes]:
    """Start a service in its own process group for reliable cleanup."""

    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen(
        command,
        cwd=cwd,
        creationflags=creation_flags,
        start_new_session=os.name != "nt",
    )


def stop_process(process: subprocess.Popen[bytes]) -> None:
    """Stop a service and all children it launched."""

    if process.poll() is not None:
        return

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def ensure_frontend_dependencies(npm: str) -> None:
    """Install the locked frontend dependencies only when they are absent."""

    vite_executable = (
        FRONTEND / "node_modules" / ".bin" / ("vite.cmd" if os.name == "nt" else "vite")
    )
    if not vite_executable.exists():
        print("Frontend dependencies are missing; running npm ci...", flush=True)
        run_checked([npm, "ci"], cwd=FRONTEND)


def should_start_postgres(arguments: list[str]) -> bool:
    """Parse the single optional Docker flag without adding a CLI dependency."""

    if not arguments:
        return False
    if arguments == ["--with-docker"]:
        return True
    raise RuntimeError("Usage: scripts/dev.py [--with-docker]")


def main(*, start_postgres: bool = False) -> int:
    """Start FastAPI and Vite, optionally starting PostgreSQL first."""

    npm = require_command("npm")

    if start_postgres:
        docker = require_command("docker")
        print("Starting PostgreSQL...", flush=True)
        run_checked([docker, "compose", "up", "-d", "postgres"], cwd=ROOT)
    ensure_frontend_dependencies(npm)

    backend_command = [
        sys.executable,
        "-m",
        "uvicorn",
        "agentloom.main:app",
        "--reload",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    frontend_command = [
        npm,
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "5173",
    ]

    processes: list[tuple[str, subprocess.Popen[bytes]]] = []
    try:
        processes.append(("backend", start_process(backend_command, cwd=ROOT)))
        processes.append(("frontend", start_process(frontend_command, cwd=FRONTEND)))
        print("AgentLoom development environment is running:", flush=True)
        print("  Frontend: http://localhost:5173/tasks", flush=True)
        print("  Backend:  http://localhost:8000/health", flush=True)
        print("Press Ctrl+C to stop the frontend and backend.", flush=True)

        while True:
            for name, process in processes:
                return_code = process.poll()
                if return_code is not None:
                    print(f"{name} exited unexpectedly with code {return_code}", file=sys.stderr)
                    return return_code or 1
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nStopping development services...", flush=True)
        return 0
    finally:
        for _, process in reversed(processes):
            stop_process(process)


if __name__ == "__main__":
    try:
        raise SystemExit(main(start_postgres=should_start_postgres(sys.argv[1:])))
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Unable to start development environment: {error}", file=sys.stderr)
        raise SystemExit(1) from error
