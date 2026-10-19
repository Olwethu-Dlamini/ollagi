"""Read my open Jira tickets. Read only: this module only ever sends GET requests.

It uses the credentials already on this machine, in ~/.jira.env:

    JIRA_SITE=yourcompany.atlassian.net
    JIRA_EMAIL=me@example.com
    JIRA_API_TOKEN=...

Jira Cloud's search endpoint (`/rest/api/3/search/jql`) takes a JQL query and answers in pages;
`nextPageToken` in an answer asks for the next page. The standing rule for SiMedia work is that a
ticket's status is never changed by tooling, so there is no write call here at all.
"""

import base64
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ENV_FILE = Path.home() / ".jira.env"
MY_OPEN_TICKETS = "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
FIELDS = "summary,status,labels,issuetype,parent,updated"


@dataclass(frozen=True)
class Ticket:
    key: str
    summary: str
    status: str
    labels: tuple[str, ...]
    parent: str | None  # the epic or parent issue key
    issue_type: str
    url: str


def read_env(text: str) -> dict[str, str]:
    """KEY=VALUE lines; `export ` prefixes and surrounding quotes are allowed, # starts a comment."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def parse_issue(issue: dict, site: str) -> Ticket:
    f = issue["fields"]
    return Ticket(
        key=issue["key"],
        summary=f.get("summary") or "",
        status=(f.get("status") or {}).get("name", "?"),
        labels=tuple(f.get("labels") or ()),
        parent=(f.get("parent") or {}).get("key"),
        issue_type=(f.get("issuetype") or {}).get("name", "?"),
        url=f"https://{site}/browse/{issue['key']}",
    )


class Jira:
    def __init__(self, env_file: Path = ENV_FILE):
        env = read_env(env_file.read_text())
        self.site = env["JIRA_SITE"].removeprefix("https://").rstrip("/")
        token = base64.b64encode(f"{env['JIRA_EMAIL']}:{env['JIRA_API_TOKEN']}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}

    def get(self, path: str, params: dict) -> dict:
        url = f"https://{self.site}{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers=self.headers, method="GET")
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def my_open_tickets(self, limit: int = 200) -> list[Ticket]:
        tickets, token = [], None
        while len(tickets) < limit:
            params = {"jql": MY_OPEN_TICKETS, "fields": FIELDS, "maxResults": 100}
            if token:
                params["nextPageToken"] = token
            page = self.get("/rest/api/3/search/jql", params)
            tickets += [parse_issue(i, self.site) for i in page.get("issues", [])]
            token = page.get("nextPageToken")
            if page.get("isLast", True) or not token:
                break
        return tickets[:limit]
