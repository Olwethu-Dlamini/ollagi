"""Which code each ticket touches, so tickets are grouped by shared code (docs/decisions/0040).

Two kinds of evidence, strongest first:

  code  the files the ticket's pull requests change (Bitbucket). A pull request belongs to every ticket key
        in its branch name or title: "fix/T-7113-7119-specs" is T-7113 and T-7119.
  page  for a ticket without a pull request yet: an area of the product whose words its title uses, or whose
        epic it sits under, read from a private map (~/.config/ollagi/areas.toml). ollagi is a public repo,
        so no product, page or repository names live in this code.

The map, one [[area]] per area of the product:

    [[area]]
    name = "Calendar"
    words = ["calendar"]                       # whole words or phrases, matched in the lowercase title
    epics = ["EPIC-22"]                        # optional
    code = ["web-app:src/pages/Calendar", "events-api"]   # repository slug, optionally ":path prefix"
    broad = true                               # optional: a cross-cutting area (tests, CI, a shared widget)

A changed file outside every area still counts, as "<repository>:<first folders>", so two pull requests
editing the same folder meet even before the map knows it. Such a folder, like an area marked broad, is
shown but never decides which group a ticket joins (src/ollagi/grouping.py). Changelogs, version and lock files, translation files and
test-only files never count: nearly every pull request touches those.
"""

import base64
import json
from concurrent.futures import ThreadPoolExecutor
import re
import tomllib
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ollagi.jira import Ticket, read_env

AREAS_FILE = Path.home() / ".config" / "ollagi" / "areas.toml"
BITBUCKET_ENV = Path.home() / ".bitbucket.env"
API = "https://api.bitbucket.org/2.0"
FOLDER_DEPTH = 3  # "src/pages/Calendar": deep enough to tell pages apart, shallow enough to meet
NOISE = re.compile(r"(^|/)(changelog(\.md)?|readme(\.md)?|package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml"
                   r"|directory\.build\.props|[^/]+\.csproj|\.gitignore|\.github/.+|locales?/.+)$", re.I)  # translations: every UI change
TEST_ONLY = re.compile(r"(^|/)(cypress|e2e|tests?|__tests__|[^/]+\.tests?)/", re.I)
KEYS = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]*)-(\d+)((?:-\d+)*)")  # Jira keys are uppercase


@dataclass(frozen=True)
class Area:
    name: str
    words: tuple[str, ...] = ()
    epics: tuple[str, ...] = ()
    code: tuple[str, ...] = ()
    broad: bool = False


@dataclass(frozen=True)
class Evidence:
    area: str
    kind: str  # "code" or "page"
    detail: str  # "PR #2374", 'title says "calendar"', "epic EPIC-22"
    broad: bool = False  # a cross-cutting area, or a folder the map does not know


def load_areas(path: Path = AREAS_FILE) -> list[Area]:
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text())
    return [Area(a["name"], tuple(w.lower() for w in a.get("words", ())), tuple(a.get("epics", ())),
                 tuple(a.get("code", ())), bool(a.get("broad", False))) for a in data.get("area", ())]


def keys_in(text: str) -> set[str]:
    """Ticket keys in a branch name or title; "T-7113-7119" names two tickets of the same project."""
    found = set()
    for project, first, more in KEYS.findall(text):
        found.add(f"{project}-{first}")
        found.update(f"{project}-{n}" for n in more.split("-")[1:] if len(n) >= len(first) - 1)
    return found


def path_area(repo: str, path: str, areas: list[Area]) -> str | None:
    """The area a changed file belongs to, or None for files every pull request touches."""
    if NOISE.search(path) or TEST_ONLY.search(path):
        return None
    for area in areas:
        for entry in area.code:
            slug, _, prefix = entry.partition(":")
            prefix = prefix.strip("/")
            if slug.lower() == repo.lower() and (not prefix or path == prefix or path.startswith(prefix + "/")):
                return area.name
    folder = "/".join(path.split("/")[:-1][:FOLDER_DEPTH])
    return f"{repo}:{folder}" if folder else repo


def page_evidence(ticket: Ticket, areas: list[Area]) -> list[Evidence]:
    title = ticket.summary.lower()
    found = []
    for area in areas:
        word = next((w for w in area.words if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", title)), None)
        if word:
            found.append(Evidence(area.name, "page", f'title says "{word}"', area.broad))
        elif ticket.parent and ticket.parent in area.epics:
            found.append(Evidence(area.name, "page", f"epic {ticket.parent}", area.broad))
    return found


def evidence_for(tickets: list[Ticket], areas: list[Area], code=None) -> dict[str, list[Evidence]]:
    """Each ticket's areas. `code` is a Bitbucket (or a stand-in) or None to use the map alone."""
    found: dict[str, dict[str, list[str]]] = {t.key: {} for t in tickets}  # key -> code area -> PRs
    if code is not None:
        mine = [(pr, keys_in(f"{pr['branch']} {pr['title']}") & found.keys()) for pr in code.my_pull_requests(sorted(found))]
        mine = [(pr, keys) for pr, keys in mine if keys]
        # Each pull request's files are one request of a few seconds: ask for them side by side.
        with ThreadPoolExecutor(max_workers=8) as pool:
            files = list(pool.map(code.changed_paths, [pr for pr, _ in mine]))
        for (pr, keys), paths in zip(mine, files):
            hit = {path_area(pr["repo"], p, areas) for p in paths} - {None}
            for key in keys:
                for area in hit:
                    found[key].setdefault(area, []).append(f"#{pr['id']}")
    mapped = {a.name: a.broad for a in areas}
    result = {}
    for t in tickets:
        evidence = [Evidence(area, "code", "PR " + ", ".join(sorted(prs)), mapped.get(area, True))
                    for area, prs in sorted(found[t.key].items(), key=lambda item: -len(item[1]))]
        evidence += [e for e in page_evidence(t, areas) if e.area not in found[t.key]]
        result[t.key] = evidence
    return result


class Bitbucket:
    """My pull requests in one workspace and the files each changes, read only. ~/.bitbucket.env holds
    BITBUCKET_EMAIL, BITBUCKET_API_TOKEN and BITBUCKET_WORKSPACE."""

    MAX_PAGES = 4  # 200 pull requests: months of work, and the first load stays a few seconds

    def __init__(self, env_file: Path = BITBUCKET_ENV):
        env = read_env(env_file.read_text())
        token = f"{env['BITBUCKET_EMAIL']}:{env['BITBUCKET_API_TOKEN']}".encode()
        self.auth = "Basic " + base64.b64encode(token).decode()
        self.workspace = env["BITBUCKET_WORKSPACE"]
        self.paths: dict[tuple[str, int, str], list[str]] = {}  # (repo, id, updated) -> files: never re-read

    def get(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={"Authorization": self.auth, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:  # follows Bitbucket's redirects
            return json.load(response)

    def pages(self, url: str):
        for _ in range(self.MAX_PAGES):
            page = self.get(url)
            yield from page.get("values", ())
            if not page.get("next"):
                return
            url = page["next"]

    def my_pull_requests(self, keys: list[str]) -> list[dict]:
        """My pull requests that may belong to these tickets. Bitbucket filters by the ticket NUMBER, so a
        branch naming two tickets ("T-7113-7119") is found for both; keys_in drops any false match after."""
        me = urllib.parse.quote(self.get(f"{API}/user")["uuid"])
        found = {}
        for start in range(0, len(keys), 15):  # a short query string per request
            terms = [f'source.branch.name ~ "{k.split("-")[-1]}" OR title ~ "{k}"' for k in keys[start:start + 15]]
            url = (f"{API}/workspaces/{self.workspace}/pullrequests/{me}?state=OPEN&state=MERGED&pagelen=50"
                   f"&q={urllib.parse.quote(' OR '.join(terms))}")
            for p in self.pages(url):
                found[(p["destination"]["repository"]["full_name"], p["id"])] = {
                    "id": p["id"], "repo": p["destination"]["repository"]["full_name"].split("/")[-1],
                    "branch": p["source"]["branch"]["name"], "title": p["title"], "updated": p["updated_on"]}
        return list(found.values())

    def changed_paths(self, pr: dict) -> list[str]:
        cached = (pr["repo"], pr["id"], pr["updated"])
        if cached not in self.paths:
            url = f"{API}/repositories/{self.workspace}/{pr['repo']}/pullrequests/{pr['id']}/diffstat?pagelen=100"
            self.paths[cached] = [(f.get("new") or f.get("old"))["path"] for f in self.pages(url)]
        return self.paths[cached]
