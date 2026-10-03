"""Launch a local installation or explicitly promote a selected release artifact."""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from catlabel.core.release_artifacts import ReleaseManifest
from catlabel.core.release_slots import activate_artifact, load_active, rollback
from catlabel.core.runtime_lease import RuntimeBusyError

BOOTSTRAP_FLAGS = (
    "--setup-only",
    "--install-headless",
    "--skip-headless",
    "--install-ai",
    "--skip-ai",
    "--install-mcp",
    "--skip-mcp",
    "--repair",
    "--diagnose",
)
MCP_TIMEOUT_SECONDS = 60


def launcher_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _bootstrap_command(target_dir: Path, options: Sequence[str]) -> list[str]:
    if platform.system() == "Windows":
        script = target_dir / "run.ps1"
        command = [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ]
    else:
        script = target_dir / "run.sh"
        command = ["bash", str(script)]
    if not script.is_file():
        raise FileNotFoundError(f"Bootstrap script is missing: {script}")
    return [*command, *options]


def _runtime_environment(data_directory: Path) -> str:
    ai = (data_directory / ".ai-enabled").is_file()
    mcp = (data_directory / ".mcp-enabled").is_file()
    headless = (data_directory / ".headless-enabled").is_file() or mcp
    if ai:
        if mcp:
            return "ai-mcp-headless"
        return "ai-headless" if headless else "ai"
    if mcp:
        return "mcp-headless"
    return "headless" if headless else "default"


def _bootstrap_state_directory(data_directory: Path, target_dir: Path) -> Path:
    if (target_dir / "release-manifest.json").is_file():
        return target_dir / ".bootstrap-state"
    return data_directory


def _has_legacy_selection(data_directory: Path) -> bool:
    markers = (".ai-enabled", ".headless-enabled", ".mcp-enabled")
    if any((data_directory / marker).is_file() for marker in markers):
        return True
    return any(path.is_file() for path in data_directory.glob("bootstrap-*.sha256"))


def _child_environment(data_directory: Path, target_dir: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment["CATLABEL_DATA_DIR"] = str(data_directory)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PLAYWRIGHT_BROWSERS_PATH"] = (
        str(data_directory / "playwright-browsers")
        if platform.system() == "Windows"
        else "0"
    )
    bootstrap_state = _bootstrap_state_directory(data_directory, target_dir)
    if (target_dir / "release-manifest.json").is_file():
        environment["CATLABEL_BOOTSTRAP_STATE_DIR"] = str(bootstrap_state)
    if (bootstrap_state / ".mcp-enabled").is_file():
        environment["CATLABEL_MCP_ENABLED"] = "1"
    else:
        environment.pop("CATLABEL_MCP_ENABLED", None)
    if getattr(sys, "frozen", False) and platform.system() == "Linux":
        original_library_path = environment.get("LD_LIBRARY_PATH_ORIG")
        if original_library_path:
            environment["LD_LIBRARY_PATH"] = original_library_path
        else:
            environment.pop("LD_LIBRARY_PATH", None)
    if platform.system() == "Windows":
        # Python intermediates bypass PowerShell 7's Windows PowerShell path cleanup.
        # Let Windows PowerShell reconstruct its own compatible module search path.
        for key in list(environment):
            if key.casefold() == "psmodulepath":
                environment.pop(key)
    environment.setdefault("LITELLM_MODE", "PROD")
    environment.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    return environment


def _run_mcp_command(
    target_dir: Path,
    data_directory: Path,
    command: str,
    port: int,
    output: Path | None,
) -> int:
    state_directory = _bootstrap_state_directory(data_directory, target_dir)
    if not (state_directory / ".mcp-enabled").is_file():
        print(
            "The MCP add-on is not enabled for this installation. Enable it with --install-mcp first.",
            file=sys.stderr,
        )
        return 1

    executable = target_dir / ".pixi" / "envs" / _runtime_environment(state_directory)
    if platform.system() == "Windows":
        executable = executable / "python.exe"
    else:
        executable = executable / "bin" / "python"
    if not executable.is_file():
        print(
            f"The selected installation's MCP runtime is missing: {executable}",
            file=sys.stderr,
        )
        return 1

    arguments = [
        str(executable),
        "-m",
        "catlabel.mcp",
        command,
        "--port",
        str(port),
    ]
    if command == "config" and output is not None:
        arguments.extend(["--output", str(output.expanduser().resolve())])

    environment = _child_environment(data_directory, target_dir)
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        arguments,
        cwd=target_dir,
        env=environment,
        timeout=MCP_TIMEOUT_SECONDS,
        check=False,
    )
    return result.returncode


def prepare_release(
    target_dir: Path,
    data_directory: Path,
    options: Sequence[str],
    selection_source: Path | None = None,
) -> None:
    state = target_dir / ".bootstrap-state"
    if not state.exists():
        state.mkdir()
        for marker in (".ai-enabled", ".headless-enabled", ".mcp-enabled"):
            source = (selection_source or data_directory) / marker
            if source.is_file():
                (state / marker).write_text("1\n", encoding="ascii")
    command = _bootstrap_command(target_dir, [*options, "--setup-only"])
    subprocess.run(
        command,
        cwd=target_dir,
        env=_child_environment(data_directory, target_dir),
        check=True,
    )


def probe_release(
    target_dir: Path, manifest: ReleaseManifest, probe_data: Path
) -> None:
    environment_name = _runtime_environment(target_dir / ".bootstrap-state")
    executable = target_dir / ".pixi" / "envs" / environment_name
    executable = (
        executable / "python.exe"
        if platform.system() == "Windows"
        else executable / "bin" / "python"
    )
    environment = _child_environment(probe_data, target_dir)
    # Run only the selected slot's modules; an inherited checkout must not shadow them.
    environment.pop("PYTHONPATH", None)
    subprocess.run(
        [
            str(executable),
            "-m",
            "tools.probe_release",
            "--root",
            str(target_dir),
            "--data-directory",
            str(probe_data),
            "--release-id",
            manifest.release_id,
            "--source-commit",
            manifest.source_commit,
            "--frontend-sha256",
            manifest.frontend_sha256,
        ],
        cwd=target_dir,
        env=environment,
        check=True,
        timeout=90,
    )


def run_app(target_dir: Path, data_directory: Path, options: Sequence[str] = ()) -> int:
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            _bootstrap_command(target_dir, options),
            cwd=target_dir,
            env=_child_environment(data_directory, target_dir),
        )
        return process.wait()
    except KeyboardInterrupt:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        return 130
    except (OSError, subprocess.SubprocessError) as error:
        print(f"CatLabel could not start: {error}", file=sys.stderr)
        return 1


def _data_directory(root: Path, supplied: Path | None) -> Path:
    if supplied is None:
        configured = os.environ.get("CATLABEL_DATA_DIR")
        if configured is not None:
            supplied = Path(configured).expanduser()
        else:
            legacy = root / "catlabel" / "data"
            supplied = legacy if (legacy / "catlabel.db").is_file() else root / "data"
    supplied = supplied.expanduser()
    if not supplied.is_absolute():
        raise ValueError("Data directory must be an absolute path")
    return supplied.resolve()


def _bundled_artifact(root: Path) -> tuple[Path, str] | None:
    bundle_root = Path(getattr(sys, "_MEIPASS", root))
    archive = bundle_root / "CatLabel-release.zip"
    checksum = archive.with_suffix(".zip.sha256")
    if archive.is_file() and checksum.is_file():
        return archive, checksum.read_text(encoding="ascii").strip()
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation-root", type=Path)
    parser.add_argument("--data-directory", type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--update-bundled", action="store_true")
    mcp_commands = parser.add_mutually_exclusive_group()
    mcp_commands.add_argument("--mcp-config", action="store_true")
    mcp_commands.add_argument("--mcp-doctor", action="store_true")
    parser.add_argument("--mcp-port", type=int)
    parser.add_argument("--mcp-output", type=Path)
    for flag in BOOTSTRAP_FLAGS:
        parser.add_argument(flag, action="store_true")
    arguments = parser.parse_args(argv)
    mcp_command = (
        "config" if arguments.mcp_config else "doctor" if arguments.mcp_doctor else None
    )
    if mcp_command is None and (
        arguments.mcp_port is not None or arguments.mcp_output is not None
    ):
        parser.error("--mcp-port and --mcp-output require an MCP command")
    if arguments.mcp_output is not None and not arguments.mcp_config:
        parser.error("--mcp-output can be used only with --mcp-config")
    mcp_port = arguments.mcp_port if arguments.mcp_port is not None else 8000
    if mcp_command is not None and arguments.mcp_port is None:
        try:
            mcp_port = int(os.environ.get("CATLABEL_PORT", "8000"))
        except ValueError:
            parser.error("CATLABEL_PORT must be an integer between 1 and 65535")
    if mcp_command is not None and not 1 <= mcp_port <= 65535:
        parser.error("MCP port must be between 1 and 65535")
    if bool(arguments.artifact) != bool(arguments.sha256):
        parser.error("--artifact and --sha256 must be supplied together")
    if arguments.rollback and arguments.artifact:
        parser.error("Choose either --rollback or --artifact")
    if arguments.update_bundled and (
        arguments.artifact or arguments.rollback or arguments.diagnose
    ):
        parser.error(
            "--update-bundled cannot be combined with artifact, rollback, or diagnosis"
        )
    if arguments.install_ai and arguments.skip_ai:
        parser.error("Choose either --install-ai or --skip-ai")
    if arguments.install_headless and arguments.skip_headless:
        parser.error("Choose either --install-headless or --skip-headless")
    if arguments.install_mcp and arguments.skip_mcp:
        parser.error("Choose either --install-mcp or --skip-mcp")
    if arguments.diagnose and (arguments.artifact or arguments.rollback):
        parser.error("Run diagnosis separately from promotion or rollback")
    if mcp_command is not None:
        bootstrap_options = [
            flag
            for flag in BOOTSTRAP_FLAGS
            if getattr(arguments, flag[2:].replace("-", "_"))
        ]
        if (
            bootstrap_options
            or arguments.artifact
            or arguments.rollback
            or arguments.update_bundled
        ):
            parser.error(
                "MCP commands cannot be combined with bootstrap, artifact, rollback, or update options"
            )
    root = (arguments.installation_root or launcher_directory()).resolve()
    options = [
        flag
        for flag in BOOTSTRAP_FLAGS
        if getattr(arguments, flag[2:].replace("-", "_"))
    ]
    setup_options = [
        option for option in options if option not in {"--setup-only", "--diagnose"}
    ]
    try:
        data_directory = _data_directory(root, arguments.data_directory)
        current = load_active(root)
        if mcp_command is not None:
            if current is not None:
                target = current.path
            elif (root / "run.sh").is_file() or (root / "run.ps1").is_file():
                target = root
            else:
                print(
                    "No accepted release or source installation was found. Select an installation before running an MCP command.",
                    file=sys.stderr,
                )
                return 1
            return _run_mcp_command(
                target,
                data_directory,
                mcp_command,
                mcp_port,
                arguments.mcp_output,
            )
        selected = (
            (arguments.artifact, arguments.sha256) if arguments.artifact else None
        )
        if arguments.rollback:
            current = rollback(root, data_directory)
            print(
                f"Selected previous release {current.manifest.release_id}. Project data was retained."
            )
        elif arguments.update_bundled:
            selected = _bundled_artifact(root)
            if selected is None:
                print(
                    "No bundled release artifact is available for this launcher.",
                    file=sys.stderr,
                )
                return 1
        elif current is None and selected is None and not arguments.diagnose:
            selected = _bundled_artifact(root)
        if (
            getattr(sys, "frozen", False)
            and current is None
            and selected is not None
            and not arguments.skip_mcp
            and not arguments.skip_headless
            and not _has_legacy_selection(data_directory)
            and "--install-mcp" not in setup_options
        ):
            setup_options.append("--install-mcp")
        if selected is not None:
            archive, digest = selected
            try:
                current = activate_artifact(
                    root,
                    data_directory,
                    archive.resolve(),
                    digest,
                    lambda slot: prepare_release(
                        slot,
                        data_directory,
                        setup_options,
                        current.path / ".bootstrap-state"
                        if current is not None
                        else data_directory,
                    ),
                    lambda slot, manifest, probe_data: probe_release(
                        slot, manifest, probe_data
                    ),
                )
                print(
                    f"Accepted release {current.manifest.release_id}; previous code and database backup retained."
                )
            except RuntimeBusyError:
                print(
                    "Close the running CatLabel server before updating. Its current release remains selected.",
                    file=sys.stderr,
                )
                return 1
            except Exception as error:
                # No HEAD pull, implicit upgrade or database restoration occurs here.
                print(f"Selected update was not accepted: {error}", file=sys.stderr)
                current = load_active(root)
                if current is None:
                    return 1
                print(f"Continuing with local release {current.manifest.release_id}.")
                options = [
                    option
                    for option in options
                    if option in {"--setup-only", "--diagnose"}
                ]
        if current is not None:
            target = current.path
        elif (root / "run.sh").is_file() or (root / "run.ps1").is_file():
            target = root
        elif (root / "catlabel" / "run.sh").is_file() or (
            root / "catlabel" / "run.ps1"
        ).is_file():
            target = root / "catlabel"
            print(
                "Using the existing local installation. Updates require a selected release artifact."
            )
        else:
            print(
                "No accepted local installation or bundled release was found. Download a release bundle, or supply --artifact and its published --sha256.",
                file=sys.stderr,
            )
            return 1
        return run_app(target, data_directory, options)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"CatLabel launcher: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        raise SystemExit(main())
