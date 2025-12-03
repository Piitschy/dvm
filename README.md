# dvm – Docker Volume Migrator

`dvm` is a small Python CLI that lets you back up Docker volumes including permissions & metadata, upload them to a configurable [transfer.sh](https://github.com/dutchcoders/transfer.sh)-compatible endpoint, and restore them on another host. 

The focus is on:

* **1:1 migration** of volumes (incl. owners, groups, ACLs, xattrs)
* **zero setup** thanks to `transfer.sh` (or your own endpoint)
* **clean CLI UX** via [Click](https://click.palletsprojects.com/) with clear separation of logs (STDERR) and result output (STDOUT)
* **configurability** via `~/.dvm/config.toml` and CLI overrides

---

## Features

* `dvm backup`

  * Backs up one or all Docker volumes via `tar` (with `--xattrs --acls --numeric-owner`)
  * Uploads the archive to a `transfer.sh`-compatible endpoint
  * Prints **only the final URL to STDOUT** → perfect for shell pipes and `> url.txt`
* `dvm restore`

  * Downloads the archive from the URL
  * Extracts it under `<docker_root>/volumes/…`
* `dvm config`

  * Interactive wizard
  * Stores `docker_root` and `endpoint` in `~/.dvm/config.toml`
* `dvm show-config`

  * Shows current configuration and defaults

Default settings:

```toml
# ~/.dvm/config.toml
[settings]
docker_root = "/var/lib/docker"
endpoint = "https://transfer.sh"
```

`transfer.sh` is a minimal file sharing service for the command line that typically accepts files up to 10 GB and keeps them for 14 days by default. ([LFCS Certification eBook][1])
You can control the retention period for individual uploads via the `Max-Days` HTTP header. ([GitHub][2])

---

## Prerequisites

* Linux host with:

  * Docker (including the `docker` CLI)
  * `tar`
* Python ≥ 3.11 (the project currently targets `>=3.13`)
* uv – fast Python package/project manager
* Internet access to the desired transfer.sh endpoint

### Install uv

See the official docs: ([docs.astral.sh][3])

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Installation & Setup

### Direct installation via uv

The easiest way is to install dvm directly as a tool with `uv`:

```bash
uv tool install git+https://github.com/piitschy/dvm
```

Then make sure `dvm` is executable with sudo:

```bash
sudo ln -s "$(which dvm)" /usr/local/bin/dvm
```

After that you can use `dvm` like this:

```bash
dvm --help
```

Alternatively, you can clone the repo and run `dvm` directly from source:

### Installation from source

#### 1. Clone the repository

```bash
git clone https://github.com/Piitschy/dvm
cd dvm
```

#### 2. Run the CLI with `uv` (without installation)

In the project directory:

```bash
uv run dvm --help
```

This will:

* read `pyproject.toml`
* install `click`
* start the script entry point `dvm = main:cli`

#### 3. Optional: Install as a tool

If you want to use `dvm` like a global CLI:

```bash
uv tool install .
```

After that (assuming the `uv` tool path is in your `PATH`):

```bash
dvm --help
```

---

## `sudo` + `uv`

Since `dvm` works in `/var/lib/docker` and uses `docker volume ls`, you should run it as root:

```bash
sudo uv run dvm backup …
```

If you get `sudo: uv: command not found`, `uv` is probably only in your user `PATH`. Solutions:

**A. Full path:**

```bash
which uv
# e.g. /home/jan/.local/bin/uv

sudo /home/jan/.local/bin/uv run dvm backup …
```

**B. Symlink into `/usr/local/bin`:**

```bash
sudo ln -s "$(which uv)" /usr/local/bin/uv
```

After that:

```bash
sudo uv run dvm backup …
```

---

## Configuration

### Wizard: `dvm config`

Start the interactive wizard:

```bash
uv run dvm config
# or, for real backups:
sudo uv run dvm config
```

The wizard asks for:

1. **Docker root directory**

   * Default: `/var/lib/docker`
2. **transfer.sh endpoint**

   * Default: `https://transfer.sh`

The configuration is written to `~/.dvm/config.toml`:

```toml
# ~/.dvm/config.toml
[settings]
docker_root = "/var/lib/docker"
endpoint = "https://transfer.sh"
```

### Show configuration

```bash
uv run dvm show-config
```

Example output:

```text
Configuration file: /home/user/.dvm/config.toml
Status: File found ✅

Docker Root : /var/lib/docker
Endpoint    : https://transfer.sh
```

---

## Usage

### 1. Stop containers (recommended)

To get consistent volumes:

```bash
docker compose down
# or selectively:
docker stop <your-containers>
```

---

### 2. Backup

#### A specific volume

```bash
sudo uv run dvm backup -v my_volume
```

#### Multiple volumes

```bash
sudo uv run dvm backup -v vol1 -v vol2 -v vol3
```

#### All Docker volumes

```bash
sudo uv run dvm backup --all-volumes
```

#### Options

* `-v, --volume NAME` – name of a Docker volume (can be given multiple times)
* `--all-volumes` – all volumes from `docker volume ls`
* `--docker-root PATH` – overrides `docker_root` from the config
* `--endpoint URL` – overrides `endpoint` from the config
* `--name NAME` – filename for the archive on the endpoint (default: `docker-volumes.tar`)
* `--max-days N` – sets HTTP header `Max-Days: N` for the upload

Under the hood:

* `docker volume ls --format '{{.Name}}'` for listing (when using `--all-volumes`)
* `tar --xattrs --acls --numeric-owner -C <docker_root>/volumes -cpf <tmpfile> <volume-names>`
* Upload via `PUT https://transfer.sh/<name>` with optional `Max-Days` header ([GitHub][2])

---

### 3. Cleanly write the URL to a file

`dvm` is designed such that:

* **all logs** and status messages go to **STDERR**
* **only the final URL** goes to **STDOUT**

This means:

```bash
sudo uv run dvm backup -v my_volume > backup_url.txt
```

* In the terminal you see all logs (because STDERR)
* `backup_url.txt` contains **only** the URL, e.g.

```text
https://transfer.sh/AbCdEf/docker-volumes.tar
```

If you also want logs in a file:

```bash
sudo uv run dvm backup -v my_volume 1>backup_url.txt 2>backup.log
```

---

### 4. Restore

On the target system:

1. (Optional) run `dvm config` to set `docker_root` – or use the default.

2. Stop Docker:

   ```bash
   sudo systemctl stop docker
   # or: service docker stop
   ```

3. Run restore:

   ```bash
   sudo uv run dvm restore "$(cat backup_url.txt)"
   ```

   or directly with the URL:

   ```bash
   sudo uv run dvm restore "https://transfer.sh/AbCdEf/docker-volumes.tar"
   ```

`restore`:

* downloads the file via HTTP GET
* stores it in a temp location
* extracts it with:

  ```bash
  tar --xattrs --acls --numeric-owner -C <docker_root>/volumes -xpf <archive>
  ```

4. Start Docker again:

   ```bash
   sudo systemctl start docker
   ```

5. Start your stacks/containers with the same volume names as before:

   ```bash
   docker compose up -d
   # or the corresponding docker run commands
   ```

---

## How dvm works internally

* **Config**

  * `~/.dvm/config.toml`, read with `tomllib` (stdlib since Python 3.11)
  * falls back to defaults if the file is missing or broken
* **Backup flow**

  1. Root check via `os.geteuid()`
  2. Merge config + CLI overrides
  3. Determine volumes (either explicit or via `docker volume ls`)
  4. Create archive (`tar --xattrs --acls --numeric-owner`)
  5. Upload to `endpoint/name` via HTTP `PUT`
  6. Return URL on STDOUT
* **Restore flow**

  1. Root check
  2. Config + optional `--docker-root`
  3. Download via HTTP GET
  4. Extract to `<docker_root>/volumes`

The CLI itself is implemented with [Click](https://click.palletsprojects.com/), a popular Python library for command line tools. ([click.palletsprojects.com][4])

---

## Best practices & notes

* **Always run as root (`sudo`)**, otherwise access to `/var/lib/docker` and ownership will fail.
* **Stop containers during backup** to avoid partially written data in volumes.
* **transfer.sh is not long-term backup storage**

  * Default retention is ~14 days for the public instance; for your own instances your settings apply. ([LFCS Certification eBook][1])
  * Use `--max-days` if you want to adjust retention per upload. ([GitHub][2])
* **Sensitive data**:

  * Anyone with the URL can download the archive.
  * For highly sensitive volumes, you should additionally encrypt the archive before uploading (GPG, age, …). transfer.sh also supports optional passwords via the `X-Encrypt-Password` header, which could be integrated into future versions of `dvm`. ([GitHub][2])

---

## Development

### Install dependencies

In the project directory:

```bash
uv sync
```

or simply:

```bash
uv run dvm --help
```

### Type checking

`pyproject.toml` includes `mypy` as a dev dependency:

```bash
uv run mypy main.py
```

---

## Roadmap / ideas

* `dvm doctor`: checklist (Docker reachable, `tar` available, permissions OK)
* Optional encryption (e.g. via `age` or `gpg`)
* Support for:

  * bind mounts (`/srv/...`) in addition to volumes
  * other transport backends (S3, MinIO, SSH)

---

[1]: https://www.tecmint.com/file-sharing-from-linux-commandline/?utm_source=chatgpt.com "Transfer.sh - Easy File Sharing from Linux Commandline"
[2]: https://github.com/dutchcoders/transfer.sh?utm_source=chatgpt.com "dutchcoders/transfer.sh: Easy and fast file sharing from the ..."
[3]: https://docs.astral.sh/uv/getting-started/installation/?utm_source=chatgpt.com "Installation | uv - Astral Docs"
[4]: https://click.palletsprojects.com/?utm_source=chatgpt.com "Welcome to Click — Click Documentation (8.3.x)"
