
from __future__ import annotations
import re
import os
import json
from urllib.parse import urljoin
import requests
from lxml import html
from bs4 import BeautifulSoup
from typing import Tuple, Optional
from flask import current_app

# --- Version normalisation helper -------------------------------------------
_version_re = re.compile(r"(\d+)(?:[._-]\d+)+(?:[A-Za-z0-9._-]*)?")

def normalise_version(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return raw
    m = _version_re.search(raw)
    return m.group(0).replace('_', '.') if m else raw


class HTTPClient:
    def __init__(self, user_agent: str, referrer: str, timeout: int = 15):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': user_agent,
            'Referer': referrer,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
        gh_token = current_app.config.get('GITHUB_TOKEN') if current_app else None
        if gh_token:
            self.session.headers['Authorization'] = f'Bearer {gh_token}'
        self.timeout = timeout

    def _log_rate_headers(self, resp: requests.Response):
        rl = {k: v for k, v in resp.headers.items() if k.lower().startswith('x-ratelimit') or k.lower() in ('retry-after',)}
        if rl:
            current_app.logger.warning(f"Rate headers for {resp.request.method} {resp.url}: {rl}")

    def get(self, url: str) -> requests.Response:
        current_app.logger.info(f"GET {url}")
        resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        self._log_rate_headers(resp)
        resp.raise_for_status()
        current_app.logger.info(f"GET {resp.url} -> {resp.status_code} ({len(resp.content)} bytes)")
        return resp

    def download(self, url: str, dest_path: str) -> int:
        current_app.logger.info(f"DOWNLOAD {url} -> {dest_path}")
        with self.session.get(url, timeout=self.timeout, stream=True) as r:
            self._log_rate_headers(r)
            r.raise_for_status()
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            total = 0
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
        current_app.logger.info(f"DOWNLOADED {total} bytes to {dest_path}")
        return total


def extract_regex(text: str, pattern: str) -> Optional[str]:
    try:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    except re.error as e:
        current_app.logger.error(f"Bad regex '{pattern}': {e}")
        return None
    if not m:
        return None
    return m.group(1) if m.lastindex else m.group(0)


def extract_xpath(text: str, expr: str, base_url: str | None = None) -> Optional[str]:
    try:
        tree = html.fromstring(text)
        res = tree.xpath(expr)
    except Exception as e:
        current_app.logger.error(f"Bad XPath '{expr}': {e}")
        return None
    if not res:
        return None
    val = res[0]
    if isinstance(val, bytes):
        val = val.decode('utf-8', errors='ignore')
    elif not isinstance(val, str):
        val = str(val)
    if base_url and isinstance(val, str) and val.startswith('/'):
        return urljoin(base_url, val)
    return val.strip()


def scrape_generic(cfg: dict, client: HTTPClient) -> Tuple[Optional[str], Optional[str]]:
    page_url = cfg.get('page_url')
    if not page_url:
        current_app.logger.error("Generic strategy missing 'page_url'")
        return None, None
    resp = client.get(page_url)
    text = resp.text
    base = resp.url

    version = None
    vcfg = cfg.get('version') or {}
    if vcfg.get('type') == 'regex' and vcfg.get('pattern'):
        version = extract_regex(text, vcfg['pattern'])
    elif vcfg.get('type') == 'xpath' and vcfg.get('expr'):
        version = extract_xpath(text, vcfg['expr'])
    version = normalise_version(version)

    dl_url = None
    dcfg = cfg.get('download') or {}
    if dcfg.get('type') == 'template' and dcfg.get('template'):
        if version is None:
            current_app.logger.warning("Template download URL requested but version is None")
            return version, None
        dl_url = dcfg['template'].format(version=version)
    elif dcfg.get('type') == 'regex' and dcfg.get('pattern'):
        m = re.search(dcfg['pattern'], text, re.IGNORECASE)
        if m:
            dl_url = m.group(1) if m.lastindex else m.group(0)
    elif dcfg.get('type') == 'xpath' and dcfg.get('expr'):
        dl_url = extract_xpath(text, dcfg['expr'], base)

    if dl_url and dl_url.startswith('/'):
        dl_url = urljoin(base, dl_url)

    current_app.logger.info(f"Generic strategy result: version={version}, url={dl_url}")
    return version, dl_url


def _github_collect_assets_from_release_html(page_html: str) -> list[tuple[str,str]]:
    soup = BeautifulSoup(page_html, 'html.parser')
    links = []
    for a in soup.select('a[href]'):
        href = a.get('href', '')
        if '/releases/download/' in href:
            full = urljoin('https://github.com', href)
            name = full.split('/')[-1]
            links.append((name, full))
    if links:
        return links
    frag = soup.select_one('include-fragment[src*="/releases/expanded_assets/"]')
    if frag and frag.get('src'):
        return [('__EXPANDED_ASSETS__', urljoin('https://github.com', frag['src']))]
    return []


def scrape_github(cfg: dict, client: HTTPClient) -> Tuple[Optional[str], Optional[str]]:
    repo = cfg.get('repo')
    if not repo:
        current_app.logger.error("GitHub strategy missing 'repo'")
        return None, None
    allow_pre = bool(cfg.get('allow_prerelease', False))

    page_url = f"https://github.com/{repo}/releases" if allow_pre else f"https://github.com/{repo}/releases/latest"
    resp = client.get(page_url)
    release_page_url = resp.url

    version = None
    if not allow_pre:
        tag = release_page_url.rstrip('/').split('/')[-1]
        version = normalise_version(tag)
    else:
        soup0 = BeautifulSoup(resp.text, 'html.parser')
        tag_el = soup0.select_one('a[href*="/releases/tag/"]')
        if tag_el and tag_el.get('href'):
            release_page_url = urljoin('https://github.com', tag_el['href'])
            version = normalise_version(tag_el.get_text(strip=True))

    page_html = client.get(release_page_url).text

    links = _github_collect_assets_from_release_html(page_html)
    if links and links[0][0] == '__EXPANDED_ASSETS__':
        expanded_url = links[0][1]
        current_app.logger.info(f"Fetching expanded assets: {expanded_url}")
        fragment_html = client.get(expanded_url).text
        links = []
        frag_soup = BeautifulSoup(fragment_html, 'html.parser')
        for a in frag_soup.select('a[href]'):
            href = a.get('href', '')
            if '/releases/download/' in href:
                full = urljoin('https://github.com', href)
                name = full.split('/')[-1]
                links.append((name, full))

    if links:
        current_app.logger.info(f"GitHub assets found ({len(links)}): {[name for name,_ in links]}")
    else:
        current_app.logger.warning("GitHub: no assets found in release page (and no expanded assets fragment)")

    asset_regex = cfg.get('asset_regex')
    candidate = None
    for name, full in links:
        if asset_regex:
            try:
                if re.search(asset_regex, name, re.IGNORECASE):
                    candidate = full
                    break
            except re.error as e:
                current_app.logger.error(f"Bad asset_regex '{asset_regex}': {e}")
                return version, None
        else:
            if name.lower().endswith(('.exe', '.msi', '.zip', '.7z')) and not name.lower().endswith('.sig'):
                candidate = full
                break

    current_app.logger.info(f"GitHub strategy result for {repo}: version={version}, url={candidate}")
    return version, candidate


def scrape_gitlab(cfg: dict, client: HTTPClient) -> Tuple[Optional[str], Optional[str]]:
    repo = cfg.get('repo')
    if not repo:
        current_app.logger.error("GitLab strategy missing 'repo'")
        return None, None
    releases_url = f"https://gitlab.com/{repo}/-/releases"
    resp = client.get(releases_url)
    soup = BeautifulSoup(resp.text, 'html.parser')
    first = soup.select_one('[data-qa-selector="release_block"]') or soup.select_one('.release')
    if not first:
        current_app.logger.warning("GitLab: no release blocks found")
        return None, None
    ver_el = first.select_one('[data-qa-selector="release_title"], .release-title, .card-title')
    version = normalise_version(ver_el.get_text(strip=True) if ver_el else None)
    asset_regex = cfg.get('asset_regex')
    dl = None
    cand = []
    for a in first.select('a[href]'):
        href = a['href']
        name = a.get_text(strip=True) or href.split('/')[-1]
        cand.append(name)
        if asset_regex:
            try:
                if re.search(asset_regex, name, re.IGNORECASE):
                    dl = href if href.startswith('http') else urljoin('https://gitlab.com', href)
                    break
            except re.error as e:
                current_app.logger.error(f"Bad asset_regex '{asset_regex}': {e}")
                continue
        elif any(ext in href.lower() for ext in ('.exe', '.msi', '.zip')) and not href.lower().endswith('.sig'):
            dl = href if href.startswith('http') else urljoin('https://gitlab.com', href)
            break
    current_app.logger.info(f"GitLab candidates: {cand}")
    current_app.logger.info(f"GitLab strategy result for {repo}: version={version}, url={dl}")
    return version, dl


def scrape_codeberg(cfg: dict, client: HTTPClient) -> Tuple[Optional[str], Optional[str]]:
    repo = cfg.get('repo')
    if not repo:
        current_app.logger.error("Codeberg strategy missing 'repo'")
        return None, None
    releases_url = f"https://codeberg.org/{repo}/releases"
    resp = client.get(releases_url)
    soup = BeautifulSoup(resp.text, 'html.parser')
    first = soup.select_one('.release-list .release') or soup.select_one('.ui.segment.release')
    if not first:
        current_app.logger.warning("Codeberg: no release blocks found")
        return None, None
    tag_el = first.select_one('.tag, .release-tag') or first.select_one('a[href*="/tag/"]')
    version = normalise_version(tag_el.get_text(strip=True) if tag_el else None)
    asset_regex = cfg.get('asset_regex')
    dl = None
    cand = []
    for a in first.select('a[href]'):
        href = a['href']
        name = a.get_text(strip=True) or href.split('/')[-1]
        cand.append(name)
        if '/releases/download/' in href:
            if asset_regex:
                try:
                    if re.search(asset_regex, name, re.IGNORECASE):
                        dl = href if href.startswith('http') else urljoin('https://codeberg.org', href)
                        break
                except re.error as e:
                    current_app.logger.error(f"Bad asset_regex '{asset_regex}': {e}")
                    continue
            else:
                dl = href if href.startswith('http') else urljoin('https://codeberg.org', href)
                break
    current_app.logger.info(f"Codeberg candidates: {cand}")
    current_app.logger.info(f"Codeberg strategy result for {repo}: version={version}, url={dl}")
    return version, dl


def scrape_sourceforge(cfg: dict, client: HTTPClient) -> Tuple[Optional[str], Optional[str]]:
    project = cfg.get('project')
    path = cfg.get('path', '/')
    if not project:
        current_app.logger.error("SourceForge strategy missing 'project'")
        return None, None
    rss_url = f"https://sourceforge.net/projects/{project}/rss?path={path}"
    resp = client.get(rss_url)
    soup = BeautifulSoup(resp.text, 'xml')
    item = soup.find('item')
    if not item:
        current_app.logger.warning("SourceForge RSS: no items")
        return None, None
    title = item.findtext('title') or ''
    link = item.findtext('link') or ''
    m = re.search(r"([0-9]+(?:\.[0-9A-Za-z-]+)+)", title)
    version = normalise_version(m.group(1) if m else None)
    dl = link
    asset_regex = cfg.get('asset_regex')
    if asset_regex and not re.search(asset_regex, link, re.IGNORECASE):
        files_page = f"https://sourceforge.net/projects/{project}/files/{path.strip('/')}/"
        fresp = client.get(files_page)
        fm = re.search(asset_regex, fresp.text, re.IGNORECASE)
        if fm:
            href = fm.group(0)
            dl = href if href.startswith('http') else urljoin('https://sourceforge.net', href)
    current_app.logger.info(f"SourceForge strategy result for {project}: version={version}, url={dl}")
    return version, dl


def run_strategy(strategy_type: str, strategy_config_json: str, user_agent: str, referrer: str, timeout: int) -> tuple[Optional[str], Optional[str]]:
    try:
        cfg = json.loads(strategy_config_json)
    except json.JSONDecodeError as e:
        current_app.logger.error(f"Strategy config JSON error: {e}")
        return None, None
    client = HTTPClient(user_agent=user_agent, referrer=referrer, timeout=timeout)

    try:
        if strategy_type == 'generic':
            return scrape_generic(cfg, client)
        if strategy_type == 'github':
            return scrape_github(cfg, client)
        if strategy_type == 'gitlab':
            return scrape_gitlab(cfg, client)
        if strategy_type == 'codeberg':
            return scrape_codeberg(cfg, client)
        if strategy_type == 'sourceforge':
            return scrape_sourceforge(cfg, client)
        current_app.logger.error(f"Unknown strategy type: {strategy_type}")
        return None, None
    except Exception as e:
        current_app.logger.error(f"Strategy '{strategy_type}' failed: {e}")
        return None, None
