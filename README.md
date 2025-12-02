# dvm – Docker Volume Migrator

`dvm` ist eine kleine Python-CLI, mit der du Docker-Volumes inklusive Rechte & Metadaten sichern, über einen konfigurierbaren [transfer.sh](https://github.com/dutchcoders/transfer.sh)-kompatiblen Endpoint hochladen und auf einem anderen Host wiederherstellen kannst. :contentReference[oaicite:0]{index=0}  

Der Fokus liegt auf:

- **1:1-Migration** von Volumes (inkl. Besitzer, Gruppen, ACLs, xattrs)
- **zero setup** dank `transfer.sh` (oder eigenem Endpoint)
- **sauberer CLI-UX** via [Click](https://click.palletsprojects.com/) mit klarer Trennung von Logs (STDERR) und Ergebnis-Output (STDOUT)
- **Konfigurierbarkeit** via `~/.dvm/config.toml` und CLI-Overrides

---

## Features

- `dvm backup`
  - Sichert ein oder alle Docker-Volumes via `tar` (mit `--xattrs --acls --numeric-owner`)
  - Lädt das Archiv zu einem `transfer.sh`-kompatiblen Endpoint hoch
  - Gibt **nur die finale URL auf STDOUT** aus → perfekt für Shell-Pipes und `> url.txt`
- `dvm restore`
  - Lädt das Archiv von der URL herunter
  - Entpackt es unter `<docker_root>/volumes/…`
- `dvm config`
  - Interaktiver Wizard
  - Speichert `docker_root` und `endpoint` in `~/.dvm/config.toml`
- `dvm show-config`
  - Zeigt aktuelle Konfiguration und Defaults an

Standard-Defaults:

```toml
# ~/.dvm/config.toml
[settings]
docker_root = "/var/lib/docker"
endpoint = "https://transfer.sh"
````

`transfer.sh` ist ein minimaler Filesharing-Dienst für die Kommandozeile, der Dateien typischerweise bis 10 GB akzeptiert und sie standardmäßig 14 Tage vorhält. ([LFCS Zertifizierung eBook][1])
Über den HTTP-Header `Max-Days` kannst du die Aufbewahrungsdauer für einen Upload einzeln steuern. ([GitHub][2])

---

## Voraussetzungen

* Linux-Host mit:

  * Docker (inkl. `docker` CLI)
  * `tar`
* Python ≥ 3.11 (im Projekt ist aktuell `>=3.13` konfiguriert)
* uv – schneller Python Package/Project Manager
* Internetzugriff zum gewünschten transfer.sh-Endpoint

### uv installieren

Siehe offizielle Doku: ([docs.astral.sh][3])

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Installation & Setup

### Direktinstallation via uv
Das einfachste ist, dvm direkt als Tool mit `uv` zu installieren:

```bash 
uv tool install git+https://github.com/piitschy/dvm
```

Anschließend sicherstellen, dass `dvm` mit sudo ausführbar ist:

```bash
sudo ln -s "$(which dvm)" /usr/local/bin/dvm
```

Danach kannst du `dvm` so nutzen:

```bash
dvm --help
```

Alternativ kannst du das Repo klonen und `dvm` direkt aus dem Quellcode ausführen:

### Installation aus dem Quellcode

#### 1. Repository klonen

```bash
git clone https://github.com/Piitschy/dvm
cd dvm
```

#### 2. CLI mit `uv` ausführen (ohne Installation)

Im Projektverzeichnis:

```bash
uv run dvm --help
```

Damit:

* liest `uv` die `pyproject.toml`
* installiert `click`
* startet den Script-Entry `dvm = main:cli`

#### 3. Optional: Als Tool installieren

Wenn du `dvm` wie ein globales CLI nutzen willst:

```bash
uv tool install .
```

Danach (sofern der `uv`-Tool-Pfad im `PATH` ist):

```bash
dvm --help
```

---

## `sudo` + `uv`

Da `dvm` in `/var/lib/docker` arbeitet und `docker volume ls` nutzt, solltest du es als root laufen lassen:

```bash
sudo uv run dvm backup …
```

Falls `sudo: uv: Befehl nicht gefunden` kommt, liegt `uv` nur in deinem User-PATH. Lösungen:

**A. Voller Pfad:**

```bash
which uv
# z.B. /home/jan/.local/bin/uv

sudo /home/jan/.local/bin/uv run dvm backup …
```

**B. Symlink nach `/usr/local/bin`:**

```bash
sudo ln -s "$(which uv)" /usr/local/bin/uv
```

Danach:

```bash
sudo uv run dvm backup …
```

---

## Konfiguration

### Wizard: `dvm config`

Starte den interaktiven Wizard:

```bash
uv run dvm config
# oder, für echte Backups:
sudo uv run dvm config
```

Der Wizard fragt:

1. **Docker Root-Verzeichnis**

   * Default: `/var/lib/docker`
2. **transfer.sh Endpoint**

   * Default: `https://transfer.sh`

Die Konfiguration wird in `~/.dvm/config.toml` geschrieben:

```toml
# ~/.dvm/config.toml
[settings]
docker_root = "/var/lib/docker"
endpoint = "https://transfer.sh"
```

### Konfiguration ansehen

```bash
uv run dvm show-config
```

Ausgabe z. B.:

```text
Konfigurationsdatei: /home/user/.dvm/config.toml
Status: Datei gefunden ✅

Docker Root : /var/lib/docker
Endpoint    : https://transfer.sh
```

---

## Usage

### 1. Container anhalten (empfohlen)

Um konsistente Volumes zu bekommen:

```bash
docker compose down
# oder gezielt:
docker stop <deine-container>
```

---

### 2. Backup

#### Ein bestimmtes Volume

```bash
sudo uv run dvm backup -v mein_volume
```

#### Mehrere Volumes

```bash
sudo uv run dvm backup -v vol1 -v vol2 -v vol3
```

#### Alle Docker-Volumes

```bash
sudo uv run dvm backup --all-volumes
```

#### Optionen

* `-v, --volume NAME` – Name eines Docker-Volumes (mehrfach)
* `--all-volumes` – alle Volumes aus `docker volume ls`
* `--docker-root PATH` – überschreibt `docker_root` aus der Config
* `--endpoint URL` – überschreibt `endpoint` aus der Config
* `--name NAME` – Dateiname für das Archiv auf dem Endpoint (Default: `docker-volumes.tar`)
* `--max-days N` – setzt HTTP-Header `Max-Days: N` beim Upload

Unter der Haube:

* `docker volume ls --format '{{.Name}}'` zum Auflisten (bei `--all-volumes`)
* `tar --xattrs --acls --numeric-owner -C <docker_root>/volumes -cpf <tmpfile> <volume-namen>`
* Upload via `PUT https://transfer.sh/<name>` mit optionalem `Max-Days`-Header ([GitHub][2])

---

### 3. URL sauber in Datei schreiben

`dvm` ist so gebaut, dass:

* **alle Logs** und Statusmeldungen auf **STDERR** ausgegeben werden
* **nur die finale URL** auf **STDOUT**

Damit funktioniert:

```bash
sudo uv run dvm backup -v mein_volume > backup_url.txt
```

* Terminal: du siehst alle Logs (weil STDERR)
* `backup_url.txt`: enthält **nur** die URL, z. B.

```text
https://transfer.sh/AbCdEf/docker-volumes.tar
```

Wenn du zusätzlich die Logs in eine Datei packen willst:

```bash
sudo uv run dvm backup -v mein_volume 1>backup_url.txt 2>backup.log
```

---

### 4. Restore

Auf dem Zielsystem:

1. (Optional) `dvm config` ausführen, um `docker_root` zu setzen – oder Default verwenden.

2. Docker anhalten:

   ```bash
   sudo systemctl stop docker
   # oder service docker stop
   ```

3. Restore ausführen:

   ```bash
   sudo uv run dvm restore "$(cat backup_url.txt)"
   ```

   oder direkt mit URL:

   ```bash
   sudo uv run dvm restore "https://transfer.sh/AbCdEf/docker-volumes.tar"
   ```

`restore`:

* lädt die Datei via HTTP GET
* speichert sie temporär
* entpackt mit:

  ```bash
  tar --xattrs --acls --numeric-owner -C <docker_root>/volumes -xpf <archiv>
  ```

4. Docker wieder starten:

   ```bash
   sudo systemctl start docker
   ```

5. Deine Stacks/Container mit denselben Volume-Namen wie zuvor starten:

   ```bash
   docker compose up -d
   # oder entsprechende docker run Kommandos
   ```

---

## Wie dvm intern arbeitet

* **Config**

  * `~/.dvm/config.toml`, gelesen mit `tomllib` (stdlib ab Python 3.11)
  * Fallback auf Defaults, falls Datei fehlt oder defekt
* **Backup-Flow**

  1. Root-Check via `os.geteuid()`
  2. Config + CLI-Overrides zusammenführen
  3. Volumes bestimmen (entweder explizit oder via `docker volume ls`)
  4. Archiv bauen (`tar --xattrs --acls --numeric-owner`)
  5. Upload zu `endpoint/name` per HTTP `PUT`
  6. URL auf STDOUT zurückgeben
* **Restore-Flow**

  1. Root-Check
  2. Config + optional `--docker-root`
  3. Download via HTTP GET
  4. Entpacken nach `<docker_root>/volumes`

Die CLI selbst ist mit [Click](https://click.palletsprojects.com/) implementiert, einer beliebten Python-Bibliothek für Kommandozeilentools. ([click.palletsprojects.com][4])

---

## Best Practices & Hinweise

* **Immer als root (`sudo`) ausführen**, sonst scheitert der Zugriff auf `/var/lib/docker` und die Besitzrechte.
* **Container während des Backups stoppen**, damit es keine halbgaren Writes in Volumes gibt.
* **transfer.sh ist kein langfristiger Backup-Speicher**

  * Standardaufbewahrung ~14 Tage für öffentliche Instanz; für eigene Instanzen gelten deine Einstellungen. ([LFCS Zertifizierung eBook][1])
  * Nutze ggf. `--max-days`, um die Lebensdauer pro Upload anzupassen. ([GitHub][2])
* **Sensible Daten**:

  * Jede Person mit der URL kann das Archiv herunterladen.
  * Für hochsensitive Volumes solltest du vor dem Upload zusätzlich verschlüsseln (GPG, age, …). transfer.sh unterstützt zudem optional Passwörter per `X-Encrypt-Password`-Header, was man in zukünftigen Versionen von `dvm` einbauen könnte. ([GitHub][2])

---

## Entwicklung

### Abhängigkeiten installieren

Im Projektverzeichnis:

```bash
uv sync
```

oder direkt:

```bash
uv run dvm --help
```

### Typprüfung

`pyproject.toml` enthält `mypy` als Dev-Dependency:

```bash
uv run mypy main.py
```

---

## Roadmap / Ideen

* `dvm doctor`: Checkliste (Docker erreichbar, `tar` vorhanden, Rechte ok)
* Optionale Verschlüsselung (z. B. via `age` oder `gpg`)
* Unterstützung für:

  * Bind-Mounts (`/srv/...`) zusätzlich zu Volumes
  * Andere Transport-Backends (S3, MinIO, SSH)

---

[1]: https://www.tecmint.com/file-sharing-from-linux-commandline/?utm_source=chatgpt.com "Transfer.sh - Easy File Sharing from Linux Commandline"
[2]: https://github.com/dutchcoders/transfer.sh?utm_source=chatgpt.com "dutchcoders/transfer.sh: Easy and fast file sharing from the ..."
[3]: https://docs.astral.sh/uv/getting-started/installation/?utm_source=chatgpt.com "Installation | uv - Astral Docs"
[4]: https://click.palletsprojects.com/?utm_source=chatgpt.com "Welcome to Click — Click Documentation (8.3.x)"
