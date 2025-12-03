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
import tomllib  # stdlib ab Python 3.11

import click

DEFAULT_DOCKER_ROOT = "/var/lib/docker"
DEFAULT_TRANSFERSH = "https://transfer.sh"

CONFIG_DIR = Path("~/.dvm").expanduser()
CONFIG_PATH = CONFIG_DIR / "config.toml"


# ---------------------------------------------------------------------------
# Hilfsfunktionen: Rechte, tar, HTTP
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
        echo("Dieses Kommando muss als root laufen (sudo ...).", err=True)
        sys.exit(1)


def run_tar_create(tar_path: str, volumes_dir: str, volume_names: list[str]) -> None:
    """
    Erzeugt ein Tar-Archiv mit den angegebenen Volume-Verzeichnissen.

    Struktur im Archiv:
        vol1/...
        vol2/...

    => Restore erfolgt mit -C <volumes_dir>.
    """
    if not os.path.isdir(volumes_dir):
        raise click.ClickException(
            f"Volumes-Verzeichnis existiert nicht: {volumes_dir}"
        )

    # Prüfen, ob die Volume-Ordner da sind
    missing = [
        v for v in volume_names if not os.path.isdir(os.path.join(volumes_dir, v))
    ]
    if missing:
        raise click.ClickException(
            "Folgende Volume-Verzeichnisse fehlen unter "
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
    echo(f"Erzeuge Tar-Archiv mit: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def run_tar_extract(tar_path: str, volumes_dir: str) -> None:
    """
    Entpackt ein Tar-Archiv in das Docker-Volumes-Verzeichnis.
    """
    if not os.path.isdir(volumes_dir):
        raise click.ClickException(
            f"Volumes-Verzeichnis existiert nicht: {volumes_dir}"
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
    echo(f"Entpacke Tar-Archiv mit: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def upload_to_transfersh(
    file_path: str,
    endpoint: str,
    name: str | None = None,
    max_days: int | None = None,
) -> str:
    """
    Lädt file_path per HTTP PUT zu einem transfer.sh-kompatiblen Endpoint hoch.

    Entspricht in etwa:
        curl --upload-file file_path https://transfer.sh/name
    """
    if name is None:
        name = os.path.basename(file_path)

    base = endpoint.rstrip("/")
    url = f"{base}/{name}"

    echo(f"Lade Archiv nach {url} hoch ...")

    req = urllib.request.Request(url, method="PUT")
    if max_days is not None:
        # transfer.sh unterstützt z.B. Max-Days als Header (je nach Implementation)
        req.add_header("Max-Days", str(max_days))

    with open(file_path, "rb") as f:
        try:
            with urllib.request.urlopen(req, data=f) as resp:
                body = resp.read().decode().strip()
        except HTTPError as e:
            raise click.ClickException(
                f"Upload fehlgeschlagen: HTTP {e.code} - {e.reason}"
            )
        except URLError as e:
            raise click.ClickException(f"Upload fehlgeschlagen: {e.reason}")

    echo("Upload fertig.")
    echo(f"Antwort: {body}")
    return str(body)


def download_file(url: str, dest_path: str) -> None:
    """
    Lädt eine Datei per HTTP GET herunter.
    """
    echo(f"Lade {url} herunter ...")
    try:
        with urllib.request.urlopen(url) as resp, open(dest_path, "wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    except HTTPError as e:
        raise click.ClickException(
            f"Download fehlgeschlagen: HTTP {e.code} - {e.reason}"
        )
    except URLError as e:
        raise click.ClickException(f"Download fehlgeschlagen: {e.reason}")
    echo(f"Download gespeichert unter: {dest_path}")


# ---------------------------------------------------------------------------
# Config-Handling (~/.dvm/config.toml)
# ---------------------------------------------------------------------------


class Config(TypedDict):
    docker_root: str
    endpoint: str


def load_config() -> Config:
    """
    Lädt die Konfiguration aus ~/.dvm/config.toml.

    Struktur der Datei (einfach gehalten):

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
            f"Warnung: Konnte Konfiguration nicht lesen ({CONFIG_PATH}): {e}",
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
    Speichert Konfiguration nach ~/.dvm/config.toml (einfaches TOML-Write).
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    content_lines = [
        "# Konfiguration für dvm",
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
    """Kleine CLI zum Migrieren von Docker-Volumes via transfer.sh."""
    pass


@cli.command()
def show_config():
    """
    Aktuelle Konfiguration anzeigen (inkl. Defaults, falls keine Datei existiert).
    """
    cfg = load_config()
    echo(f"Konfigurationsdatei: {CONFIG_PATH}")
    if CONFIG_PATH.exists():
        echo("Status: Datei gefunden ✅")
    else:
        echo("Status: Datei existiert noch nicht (Defaults werden verwendet)")

    echo("")
    echo(f"Docker Root : {cfg['docker_root']}")
    echo(f"Endpoint    : {cfg['endpoint']}")


@cli.command(name="config")
def config_cmd():
    """
    Interaktiver Wizard zum Setzen der Konfiguration (~/.dvm/config.toml).
    """
    echo(f"Konfigurations-Wizard für dvm")
    echo(f"Datei: {CONFIG_PATH}")
    echo("Bestehende Werte werden als Default verwendet.\n")

    current = load_config()

    docker_root = click.prompt(
        "Docker Root-Verzeichnis (enthält 'volumes/')",
        default=current["docker_root"],
        show_default=True,
    )

    endpoint = click.prompt(
        "transfer.sh Endpoint",
        default=current["endpoint"],
        show_default=True,
    )

    save_config(Config(docker_root=docker_root, endpoint=endpoint))

    echo("\nKonfiguration gespeichert ✅")
    echo(f"Docker Root : {docker_root}")
    echo(f"Endpoint    : {endpoint}")
    echo(f"\nDatei liegt unter: {CONFIG_PATH}")


@cli.command()
@click.option(
    "-v",
    "--volume",
    "volumes",
    multiple=True,
    help="Name eines Docker-Volumes (mehrfach angeben möglich).",
)
@click.option(
    "--all-volumes",
    "-a",
    is_flag=True,
    help="Alle Docker-Volumes sichern (liest Namen aus 'docker volume ls').",
)
@click.option(
    "--docker-root",
    "--dr",
    default=None,
    help="Docker Root-Verzeichnis (override Konfiguration).",
    show_default=False,
)
@click.option(
    "--endpoint",
    "-e",
    default=None,
    help="transfer.sh-kompatibler Endpoint (override Konfiguration).",
    show_default=False,
)
@click.option(
    "--name",
    "-n",
    "--output",
    "-o",
    default=None,
    help="Dateiname für das Archiv auf transfer.sh (z.B. docker-volumes.tar).",
)
@click.option(
    "--max-days",
    default=None,
    type=int,
    help="Optional: Ablaufzeit in Tagen (falls vom Endpoint unterstützt).",
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
    Volumes packen und nach transfer.sh hochladen.
    """
    ensure_root()

    # Konfiguration laden und CLI-Argumente darüberlegen
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
                f"Fehler bei 'docker volume ls': {e.stderr.strip()}"
            )

        names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not names:
            raise click.ClickException("Es wurden keine Docker-Volumes gefunden.")
        volume_names = names

    if not volume_names:
        raise click.ClickException(
            "Keine Volumes angegeben. Nutze --volume ... oder --all-volumes."
        )

    echo(f"Sichere Volumes: {', '.join(volume_names)}")
    echo(f"Verwende Volumes-Verzeichnis: {volumes_dir}")
    echo(f"Endpoint: {endpoint}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tar_path = os.path.join(tmpdir, "docker-volumes.tar")

        run_tar_create(tar_path, volumes_dir, volume_names)

        archive_name = name or "docker-volumes.tar"
        url = upload_to_transfersh(tar_path, endpoint, archive_name, max_days=max_days)

        echo("\nFERTIG ✅")
        echo("Nutze folgenden Link auf dem Zielsystem für 'restore':")
        stdout(url)


@cli.command()
@click.argument("url")
@click.option(
    "--docker-root",
    default=None,
    help="Docker Root-Verzeichnis (override Konfiguration).",
    show_default=False,
)
@click.option(
    "--replace",
    "-r",
    "replacements",
    multiple=True,
    help="String-Ersetzung für Volume-Namen, z. B. 'alt=neu'. Mehrfach möglich.",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Vorhandene Volume-Verzeichnisse überschreiben ohne Nachfrage.",
)
def restore(url: str, docker_root: Optional[str], replacements: str|list[str]) -> None:
    """
    Tar-Archiv von transfer.sh herunterladen und Volumes wiederherstellen.

    URL: Download-Link von transfer.sh
    """
    ensure_root()

    cfg = load_config()
    if docker_root is None:
        docker_root = cfg["docker_root"]

    volumes_dir = os.path.join(docker_root, "volumes")
    if not os.path.isdir(volumes_dir):
        raise click.ClickException(
            f"Volumes-Verzeichnis existiert nicht: {volumes_dir}"
        )

    # Replacements parsen: "alt=neu"
    replace_pairs: list[tuple[str, str]] = []
    for spec in list(replacements):
        if "=" not in spec:
            raise click.ClickException(
                f"Ungültiges --replace-Argument '{spec}', erwartet Form 'alt=neu'."
            )
        old, new = spec.split("=", 1)
        if not old:
            raise click.ClickException(
                f"Ungültiges --replace-Argument '{spec}', linker Teil darf nicht leer sein."
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
                        f"Warnung: Ziel-Volume-Verzeichnis existiert bereits: {dst}",
                    )
                    if not click.confirm("Überschreiben?", default=False):
                        echo(f"Überspringe Volume '{name}'.")
                        continue
                    echo(f"Überschreibe vorhandenes Volume-Verzeichnis '{dst}'.")

                echo(
                    f"Volume-Verzeichnis '{name}' -> '{new_name}'",
                )
                shutil.move(src, dst)

        echo("\nFERTIG ✅")
        echo(
            f"Volumes wurden unter {volumes_dir} wiederhergestellt.\n"
            "Docker neu starten und Container mit den passenden Volume-Namen wie konfiguriert starten.",
        )


if __name__ == "__main__":
    cli()
