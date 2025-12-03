#!/usr/bin/env python3
import os
import sys
import tempfile
import subprocess
import shutil
from typing import Optional, TypedDict, Any, IO
import urllib.request
from urllib.error import URLError, HTTPError
from pathlib import Path
import tomllib  # stdlib as of Python 3.11

import click

DEFAULT_DOCKER_ROOT = "/var/lib/docker"
DEFAULT_TRANSFERSH = "https://transfer.sh"

CONFIG_DIR = Path("~/.dvm").expanduser()
CONFIG_PATH = CONFIG_DIR / "config.toml"


# ---------------------------------------------------------------------------
# Helper functions: permissions, tar, HTTP
# ---------------------------------------------------------------------------


def echo(
    message: str,
    file: Optional[IO[Any]] = None,
    nl: bool = True,
    err: bool = True,
    color: Optional[bool] = None,
) -> None:
    click.echo(
        message,
        file=file,
        nl=nl,
        err=err,
        color=color,
    )


def stdout(message: str, **kwargs: Any) -> None:
    echo(message, err=False, **kwargs)


def ensure_root():
    if os.geteuid() != 0:
        echo("This command must be run as root (sudo ...).", err=True)
        sys.exit(1)


def run_tar_create(tar_path: str, volumes_dir: str, volume_names: list[str]) -> None:
    """
    Create a tar archive with the given volume directories.

    Archive structure:
        vol1/...
        vol2/...

    => Restore is done with -C <volumes_dir>.
    """
    if not os.path.isdir(volumes_dir):
        raise click.ClickException(
            f"Volumes directory does not exist: {volumes_dir}"
        )

    # Check whether the volume folders exist
    missing = [
        v for v in volume_names if not os.path.isdir(os.path.join(volumes_dir, v))
    ]
    if missing:
        raise click.ClickException(
            "The following volume directories are missing under "
            f"{volumes_dir}: {', '.join(missing)}"
        )

    cmd = [
        "tar",
        "--xattrs",
        "--acls",
        "--numeric-owner",
        "-C",
        volumes_dir,
        "-cpf",
        tar_path,
        *volume_names,
    ]
    echo(f"Creating tar archive with: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def run_tar_extract(tar_path: str, volumes_dir: str) -> None:
    """
    Extract a tar archive into the Docker volumes directory.
    """
    if not os.path.isdir(volumes_dir):
        raise click.ClickException(
            f"Volumes directory does not exist: {volumes_dir}"
        )

    cmd = [
        "tar",
        "--xattrs",
        "--acls",
        "--numeric-owner",
        "-C",
        volumes_dir,
        "-xpf",
        tar_path,
    ]
    echo(f"Extracting tar archive with: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def upload_to_transfersh(
    file_path: str,
    endpoint: str,
    name: str | None = None,
    max_days: int | None = None,
) -> str:
    """
    Uploads file_path via HTTP PUT to a transfer.sh-compatible endpoint.

    Roughly equivalent to:
        curl --upload-file file_path https://transfer.sh/name
    """
    if name is None:
        name = os.path.basename(file_path)

    base = endpoint.rstrip("/")
    url = f"{base}/{name}"

    echo(f"Uploading archive to {url} ...")

    req = urllib.request.Request(url, method="PUT")
    if max_days is not None:
        # transfer.sh supports e.g. Max-Days as header (depending on implementation)
        req.add_header("Max-Days", str(max_days))

    with open(file_path, "rb") as f:
        try:
            with urllib.request.urlopen(req, data=f) as resp:
                body = resp.read().decode().strip()
        except HTTPError as e:
            raise click.ClickException(
                f"Upload failed: HTTP {e.code} - {e.reason}"
            )
        except URLError as e:
            raise click.ClickException(f"Upload failed: {e.reason}")

    echo("Upload complete.")
    echo(f"Response: {body}")
    return str(body)


def download_file(url: str, dest_path: str) -> None:
    """
    Download a file via HTTP GET.
    """
    echo(f"Downloading {url} ...")
    try:
        with urllib.request.urlopen(url) as resp, open(dest_path, "wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    except HTTPError as e:
        raise click.ClickException(
            f"Download failed: HTTP {e.code} - {e.reason}"
        )
    except URLError as e:
        raise click.ClickException(f"Download failed: {e.reason}")
    echo(f"Download saved to: {dest_path}")


# ---------------------------------------------------------------------------
# Config handling (~/.dvm/config.toml)
# ---------------------------------------------------------------------------


class Config(TypedDict):
    docker_root: str
    endpoint: str


def load_config() -> Config:
    """
    Load configuration from ~/.dvm/config.toml.

    File structure (kept simple):

        [settings]
        docker_root = "/var/lib/docker"
        endpoint = "https://transfer.sh"
    """
    cfg = Config(
        docker_root=DEFAULT_DOCKER_ROOT,
        endpoint=DEFAULT_TRANSFERSH,
    )

    if not CONFIG_PATH.is_file():
        return cfg

    try:
        with CONFIG_PATH.open("rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        echo(
            f"Warning: Could not read configuration ({CONFIG_PATH}): {e}",
            err=True,
        )
        return cfg

    settings = data.get("settings", {})
    if isinstance(settings, dict):
        docker_root = settings.get("docker_root")
        endpoint = settings.get("endpoint")
        if isinstance(docker_root, str) and docker_root:
            cfg["docker_root"] = docker_root
        if isinstance(endpoint, str) and endpoint:
            cfg["endpoint"] = endpoint

    return cfg


def save_config(cfg: Config) -> None:
    """
    Save configuration to ~/.dvm/config.toml (simple TOML write).
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    content_lines = [
        "# Configuration for dvm",
        "[settings]",
        f'docker_root = "{cfg["docker_root"]}"',
        f'endpoint = "{cfg["endpoint"]}"',
        "",
    ]

    CONFIG_PATH.write_text("\n".join(content_lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def cli():
    """Small CLI to migrate Docker volumes via transfer.sh."""
    pass


@cli.command()
def show_config():
    """
    Show current configuration (including defaults if no file exists).
    """
    cfg = load_config()
    echo(f"Configuration file: {CONFIG_PATH}")
    if CONFIG_PATH.exists():
        echo("Status: File found ✅")
    else:
        echo("Status: File does not exist yet (defaults are used)")

    echo("")
    echo(f"Docker Root : {cfg['docker_root']}")
    echo(f"Endpoint    : {cfg['endpoint']}")


@cli.command(name="config")
def config_cmd():
    """
    Interactive wizard to set configuration (~/.dvm/config.toml).
    """
    echo("Configuration wizard for dvm")
    echo(f"File: {CONFIG_PATH}")
    echo("Existing values are used as defaults.\n")

    current = load_config()

    docker_root = click.prompt(
        "Docker root directory (contains 'volumes/')",
        default=current["docker_root"],
        show_default=True,
    )

    endpoint = click.prompt(
        "transfer.sh endpoint",
        default=current["endpoint"],
        show_default=True,
    )

    save_config(Config(docker_root=docker_root, endpoint=endpoint))

    echo("\nConfiguration saved ✅")
    echo(f"Docker Root : {docker_root}")
    echo(f"Endpoint    : {endpoint}")
    echo(f"\nFile located at: {CONFIG_PATH}")


@cli.command()
@click.option(
    "-v",
    "--volume",
    "volumes",
    multiple=True,
    help="Name of a Docker volume (can be specified multiple times).",
)
@click.option(
    "--all-volumes",
    "-a",
    is_flag=True,
    help="Backup all Docker volumes (reads names from 'docker volume ls').",
)
@click.option(
    "--docker-root",
    "--dr",
    default=None,
    help="Docker root directory (override configuration).",
    show_default=False,
)
@click.option(
    "--endpoint",
    "-e",
    default=None,
    help="transfer.sh-compatible endpoint (override configuration).",
    show_default=False,
)
@click.option(
    "--name",
    "-n",
    "--output",
    "-o",
    default=None,
    help="Filename for the archive on transfer.sh (e.g. docker-volumes.tar).",
)
@click.option(
    "--max-days",
    default=None,
    type=int,
    help="Optional: Expiration time in days (if supported by the endpoint).",
)
def backup(
    volumes: str | list[str],
    all_volumes: bool,
    docker_root: str,
    endpoint: str,
    name: Optional[str],
    max_days: Optional[int],
) -> None:
    """
    Pack volumes and upload them to transfer.sh.
    """
    ensure_root()

    # Load configuration and override with CLI arguments
    cfg = load_config()
    docker_root = docker_root or cfg["docker_root"]
    endpoint = endpoint or cfg["endpoint"]

    volumes_dir = os.path.join(docker_root, "volumes")

    volume_names: list[str] = list(volumes)

    if all_volumes:
        # docker volume ls --format '{{.Name}}'
        try:
            result = subprocess.run(
                ["docker", "volume", "ls", "--format", "{{.Name}}"],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise click.ClickException(
                f"Error running 'docker volume ls': {e.stderr.strip()}"
            )

        names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not names:
            raise click.ClickException("No Docker volumes were found.")
        volume_names = names

    if not volume_names:
        raise click.ClickException(
            "No volumes specified. Use --volume ... or --all-volumes."
        )

    echo(f"Backing up volumes: {', '.join(volume_names)}")
    echo(f"Using volumes directory: {volumes_dir}")
    echo(f"Endpoint: {endpoint}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tar_path = os.path.join(tmpdir, "docker-volumes.tar")

        run_tar_create(tar_path, volumes_dir, volume_names)

        archive_name = name or "docker-volumes.tar"
        url = upload_to_transfersh(tar_path, endpoint, archive_name, max_days=max_days)

        echo("\nDONE ✅")
        echo("Use the following link on the target system for 'restore':")
        stdout(url)


@cli.command()
@click.argument("url")
@click.option(
    "--docker-root",
    default=None,
    help="Docker root directory (override configuration).",
    show_default=False,
)
@click.option(
    "--replace",
    "-r",
    "replacements",
    multiple=True,
    help="String replacement for volume names, e.g. 'old=new'. Can be specified multiple times.",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Overwrite existing volume directories without asking.",
)
def restore(url: str, docker_root: Optional[str], replacements: str | list[str]) -> None:
    """
    Download tar archive from transfer.sh and restore volumes.

    URL: Download link from transfer.sh
    """
    ensure_root()

    cfg = load_config()
    if docker_root is None:
        docker_root = cfg["docker_root"]

    volumes_dir = os.path.join(docker_root, "volumes")
    if not os.path.isdir(volumes_dir):
        raise click.ClickException(
            f"Volumes directory does not exist: {volumes_dir}"
        )

    # Parse replacements: "old=new"
    replace_pairs: list[tuple[str, str]] = []
    for spec in list(replacements):
        if "=" not in spec:
            raise click.ClickException(
                f"Invalid --replace argument '{spec}', expected format 'old=new'."
            )
        old, new = spec.split("=", 1)
        if not old:
            raise click.ClickException(
                f"Invalid --replace argument '{spec}', left side must not be empty."
            )
        replace_pairs.append((old, new))

    with tempfile.TemporaryDirectory() as tmpdir:
        tar_path = os.path.join(tmpdir, "docker-volumes.tar")

        download_file(url, tar_path)

        if not replace_pairs:
            run_tar_extract(tar_path, volumes_dir)
        else:
            extract_dir = os.path.join(tmpdir, "extract")
            os.mkdir(extract_dir)

            run_tar_extract(tar_path, extract_dir)

            for name in os.listdir(extract_dir):
                src = os.path.join(extract_dir, name)
                if not os.path.isdir(src):
                    continue

                new_name = name
                for old, new in replace_pairs:
                    new_name = new_name.replace(old, new)

                dst = os.path.join(volumes_dir, new_name)

                if os.path.exists(dst):
                    echo(
                        f"Warning: Target volume directory already exists: {dst}",
                    )
                    if not click.confirm("Overwrite?", default=False):
                        echo(f"Skipping volume '{name}'.")
                        continue
                    echo(f"Overwriting existing volume directory '{dst}'.")

                echo(
                    f"Volume directory '{name}' -> '{new_name}'",
                )
                shutil.move(src, dst)

        echo("\nDONE ✅")
        echo(
            f"Volumes have been restored under {volumes_dir}.\n"
            "Restart Docker and start containers with the corresponding volume names as configured.",
        )


if __name__ == "__main__":
    cli()
