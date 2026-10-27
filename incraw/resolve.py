"""Pick the right profile out of LinkedIn people-search results for a name."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

AUTO_PICK = 0.8  # minimum score to check a candidate without asking
MARGIN = 0.25    # ...and how far ahead of the runner-up it must be


@dataclass
class Candidate:
    slug: str
    name: str
    subtitle: str  # headline / location / current company, as shown in search
    score: float

    def as_dict(self) -> dict:
        return {"slug": self.slug, "name": self.name, "subtitle": self.subtitle, "score": round(self.score, 2)}


def fold(s: str) -> str:
    """lowercase, strip accents (ł→l too), collapse punctuation."""
    s = (s or "").replace("ł", "l").replace("Ł", "L")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _clean_name(line: str) -> str:
    # "Jan Kowalski • 2nd" / "Jan Kowalski • 3rd+" / "View Jan Kowalski’s profile"
    line = re.sub(r"\s*•.*$", "", line)
    line = re.sub(r"^View\s+(.*?)[’']s\s+profile$", r"\1", line, flags=re.IGNORECASE)
    return line.strip()


def parse_result(raw: dict) -> tuple[str, str]:
    lines = [l.strip() for l in (raw.get("text") or "").splitlines() if l.strip()]
    lines = [l for l in lines if not re.match(r"^(•\s*)?(1st|2nd|3rd\+?|You)$|^(Connect|Follow|Message)$", l)]
    name = _clean_name(lines[0]) if lines else ""
    rest = [l for l in lines[1:] if _clean_name(l) != name and not l.lower().startswith("view ")]
    return name, " · ".join(rest[:3])


def rank(query_name: str, company: str, raw_results: list[dict]) -> list[Candidate]:
    q_tokens = fold(query_name).split()
    q_company = fold(company)
    out = []
    for raw in raw_results:
        name, subtitle = parse_result(raw)
        if not name or fold(name) == "linkedin member":
            continue
        c_tokens = fold(name).split()
        if not q_tokens or not c_tokens:
            continue
        hits = sum(1 for t in q_tokens if t in c_tokens)
        score = hits / len(q_tokens)
        if fold(name) == " ".join(q_tokens):
            score += 0.1
        if q_company:
            score += 0.3 if q_company in fold(raw.get("text", "")) else -0.2
        out.append(Candidate(slug=raw["slug"], name=name, subtitle=subtitle, score=max(score, 0.0)))
    out.sort(key=lambda c: c.score, reverse=True)
    return out


def choose(candidates: list[Candidate]) -> Candidate | None:
    """The one candidate safe to check automatically, or None (= ask the user)."""
    if not candidates or candidates[0].score < AUTO_PICK:
        return None
    if len(candidates) > 1 and candidates[0].score - candidates[1].score < MARGIN:
        return None
    return candidates[0]
