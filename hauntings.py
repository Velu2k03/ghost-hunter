#!/usr/bin/env python3
"""hauntings.py - File each ghost as a spooky GitHub issue.

Reads ghost findings (from ghost_hunter.py --json, or scans a directory
directly) and files one GitHub issue per ghost, lore included, so cleanup
becomes trackable work instead of a scary chore.

Usage:
    python ghost_hunter.py <dir> --json | python hauntings.py owner/repo
    python hauntings.py owner/repo --scan <dir>
    python hauntings.py owner/repo --scan <dir> --dry-run   # print, don't file

The GitHub token comes from the GHOST_TOKEN environment variable.
Every issue is labeled "ghost-hunt".
"""

import json
import os
import sys

import requests

from ghost_hunter import scan, LORE, EXORCISM_ADVICE

API = "https://api.github.com"
LABEL = "ghost-hunt"


def issue_title(finding):
    return "[%s] %s haunts %s:%d" % (
        finding["species"], finding["symbol"],
        os.path.basename(finding["file"]), finding["line"])


def issue_body(finding):
    return (
        "## 👻 A wild ghost appears!\n\n"
        "%s\n\n"
        "**Haunting:** `%s` line %d\n\n"
        "**Evidence:** %s\n\n"
        "## 🧹 Suggested exorcism\n\n"
        "%s\n\n"
        "---\n"
        "*Filed by Ghost in the Repo. Run `python exorcise.py` to banish it, "
        "or close this issue once the ghost is laid to rest.*"
    ) % (LORE[finding["species"]], finding["file"], finding["line"],
         finding["detail"], EXORCISM_ADVICE[finding["species"]])


def file_issue(repo, finding, token, dry_run=False):
    title = issue_title(finding)
    body = issue_body(finding)
    if dry_run:
        print("[dry-run] would file: %s" % title)
        return {"dry_run": True, "title": title}
    resp = requests.post(
        "%s/repos/%s/issues" % (API, repo),
        headers={"Authorization": "token %s" % token,
                 "Accept": "application/vnd.github+json"},
        json={"title": title, "body": body, "labels": [LABEL]},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError("GitHub API %d: %s" % (resp.status_code, resp.text[:200]))
    data = resp.json()
    print("Filed #%d: %s" % (data["number"], title))
    return data


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    repo = argv[1]
    dry_run = "--dry-run" in argv

    if "--scan" in argv:
        root = argv[argv.index("--scan") + 1]
        findings = scan(root)
    else:
        findings = json.load(sys.stdin)

    if not findings:
        print("No ghosts to file. The repo rests easy.")
        return 0

    token = os.environ.get("GHOST_TOKEN")
    if not token and not dry_run:
        print("error: set the GHOST_TOKEN environment variable (a GitHub "
              "personal access token with repo scope).", file=sys.stderr)
        return 2

    print("Filing %d ghost(s) as issues on %s%s...\n" % (
        len(findings), repo, " [dry run]" if dry_run else ""))
    for finding in findings:
        file_issue(repo, finding, token, dry_run=dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
