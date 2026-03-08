
# Repomancer

A self-hosted web app inspired by [Ketarin](https://github.com/canneverbe/Ketarin) that tracks software installers and automatically keeps your collection current. It can scrape metadata and download the binary files from various publisher websites, including [GitHub](https://github.com), [GitLab](https://gitlab.com), [Codeberg](https://codeberg.org), [SourceForge](https://sourceforge.net), and generic websites.

**Disclaimer:** This software contains a lot of AI-generated code written by [Copilot](https://copilot.microsoft.com). This is my personal project. I built this to satisfy a personal need. If you use this software, be advised that I do not offer any support or warranty.

## Build

Clone this repository and run `docker build .` from where Dockerfile is.

Pre-built images are available at https://hub.docker.com/r/austozi/repomancer.

## Install

Clone this repository and edit docker-compose.yml as appropriate. Then, from the directory containing docker-compose.yml, run `docker compose up -d`.

## Configure

The following environment variables can be defined in docker-compose.yml:

- `REPOMANCER_USER_AGENT`: default user-agent string for all scrapes (can be overriden per app in the UI).
- `REPOMANCER_REFERRER`: default referrer string (can be override per app).
- `REPOMANCER_PAGE_SIZE`: number of apps per page on public front page (default = 15).
- `REPOMANCER_DB_PATH`: path to SQLite DB inside container (default: /data/repomancer.db).
- `REPOMANCER_DOWNLOAD_DIR`: directory for downloaded installers inside container (default: /data/repo.
- `REPOMANCER_UPDATE_INTERVAL_MINUTES`: A background update check will run at this interval. Set to 0 to disable periodic checks.
- `REPOMANCER_REQUEST_TIMEOUT`: per request timeout in seconds.

**Security notice:** Protect /admin with basic auth at the reverse proxy.

## Update check strategy

### Generic (regex)
```json
{
  "page_url": "https://example.com/downloads",
  "version": {"type": "regex", "pattern": "Latest version: ([0-9.]+)"},
  "download": {"type": "template", "template": "https://example.com/app-{version}-x64.exe"}
}
```

### Generic (XPath)
```json
{
  "page_url": "https://example.com/releases",
  "version": {"type": "xpath", "expr": "//span[@id='ver']/text()"},
  "download": {"type": "xpath", "expr": "//a[contains(@href, '.msi')]/@href"}
}
```

### GitHub
```json
{
  "repo": "owner/project",
  "allow_prerelease": false,
  "asset_regex": "win64.*\.zip$"
}
```

### GitLab
```json
{
  "repo": "gitlab-org/project",
  "asset_regex": "windows.*(msi|exe)$"
}
```

### Codeberg
```json
{
  "repo": "user/project",
  "asset_regex": "portable.*zip$"
}
```

### SourceForge
```json
{
  "project": "sevenzip",
  "path": "/7-Zip/",
  "asset_regex": "x64.*\.exe$"
}
```

## CLI

```bash
# Manual check all
docker compose exec Repomancer python manage.py check-updates --all

# Check a single app by ID
docker compose exec Repomancer python manage.py check-updates --app 1
```

### Metadata strategy (optional)
Use this at the App level to scrape fields like description, licence, icon and so on.

```json
{
  "page_url": "https://example.com/project",
  "fields": {
    "description": {"type": "xpath", "expr": "//meta[@name=\"description\"]/@content"},
    "licence": {"type": "regex", "pattern": "License: ([A-Za-z0-9-]+)"},
    "icon_url": {"type": "xpath", "expr": "//link[@rel=\"icon\"]/@href"}
  }
}
```
