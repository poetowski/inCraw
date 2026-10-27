"""Turn pasted text / files into normalized lookup requests."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from urllib.parse import unquote

PROFILE_RE = re.compile(r"linkedin\.com/in/([^/?#\s]+)", re.IGNORECASE)


@dataclass
class Request:
    raw: str
    kind: str  # "url" | "name"
    slug: str = ""
    name: str = ""
    company: str = ""

    @property
    def url(self) -> str:
        return profile_url(self.slug) if self.slug else ""


def profile_url(slug: str) -> str:
    return f"https://www.linkedin.com/in/{slug}/"


def slug_from_url(text: str) -> str:
    m = PROFILE_RE.search(text)
    return unquote(m.group(1)).strip().lower() if m else ""


def parse_line(line: str) -> Request | None:
    line = line.strip().strip("﻿")
    if not line or line.startswith("#"):
        return None
    slug = slug_from_url(line)
    if slug:
        return Request(raw=line, kind="url", slug=slug)
    # "Name, Company" / "Name | Company" / "Name; Company" / "Name<TAB>Company"
    parts = [p.strip() for p in re.split(r"[,|;\t]", line, maxsplit=1)]
    name = parts[0]
    if len(name) < 3 or not re.search(r"[^\W\d_]", name):
        return None
    return Request(raw=line, kind="name", name=name, company=parts[1] if len(parts) > 1 else "")


def parse_text(text: str) -> tuple[list[Request], list[str]]:
    """Parse free text, one person per line. Returns (requests, rejected lines)."""
    if _looks_like_csv_with_header(text):
        return _parse_csv(text)
    requests, rejected, seen = [], [], set()
    for line in text.splitlines():
        req = parse_line(line)
        if req is None:
            if line.strip() and not line.strip().startswith("#"):
                rejected.append(line.strip())
            continue
        key = req.slug or (req.name.lower(), req.company.lower())
        if key in seen:
            continue
        seen.add(key)
        requests.append(req)
    return requests, rejected


def _looks_like_csv_with_header(text: str) -> bool:
    first = text.lstrip("﻿").split("\n", 1)[0].lower()
    cols = [c.strip() for c in re.split(r"[,;\t]", first)]
    return any(c in ("url", "linkedin", "profile", "linkedin_url") for c in cols) or (
        "name" in cols and len(cols) > 1
    )


def _parse_csv(text: str) -> tuple[list[Request], list[str]]:
    text = text.lstrip("﻿")
    dialect = csv.Sniffer().sniff(text.split("\n", 1)[0], delimiters=",;\t")
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    fields = {f.strip().lower(): f for f in reader.fieldnames or []}

    def col(row, *names):
        for n in names:
            if n in fields and row.get(fields[n]):
                return row[fields[n]].strip()
        return ""

    requests, rejected, seen = [], [], set()
    for row in reader:
        url = col(row, "url", "linkedin", "linkedin_url", "profile")
        name = col(row, "name", "full name", "full_name")
        company = col(row, "company", "employer", "organization")
        slug = slug_from_url(url)
        raw = url or ", ".join(p for p in (name, company) if p)
        if slug:
            req = Request(raw=raw, kind="url", slug=slug, name=name, company=company)
        elif len(name) >= 3:
            req = Request(raw=raw, kind="name", name=name, company=company)
        else:
            if any(v for v in row.values()):
                rejected.append(raw or str(list(row.values())))
            continue
        key = req.slug or (req.name.lower(), req.company.lower())
        if key not in seen:
            seen.add(key)
            requests.append(req)
    return requests, rejected
