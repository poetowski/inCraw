"""Decide "open to work" from what a profile page shows.

Works on a plain snapshot dict (see linkedin.EXTRACT_PROFILE_JS) so it can be
tested without a browser:
    {"name", "headline", "imgAlts": [...], "topText": "...", "url"}
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Statuses a finished check can end in.
OPEN = "open"                  # LinkedIn's own Open-to-Work signal is public
LIKELY = "likely"              # only self-declared in the headline
NOT_DETECTED = "not_detected"  # nothing public (could still be "recruiters only")

FRAME_RE = re.compile(r"#\s*open\s*to\s*work", re.IGNORECASE)
HIRING_RE = re.compile(r"#\s*hiring", re.IGNORECASE)
CARD_LINE_RE = re.compile(r"^open to work$", re.IGNORECASE)

HEADLINE_PATTERNS = [
    # English
    r"#?\s*open\s*(to|for)\s*work",
    r"open\s+to\s+(new\s+)?(opportunities|roles|positions|offers)",
    r"(actively\s+)?(looking|searching)\s+for\s+(a\s+)?(new\s+)?(job|role|position|opportunit\w+|work|challenge)",
    r"seeking\s+(a\s+)?(new\s+)?(job|role|position|opportunit\w+|employment)",
    r"available\s+(for|to)\s+(hire|work|new\s+opportunities)",
    r"actively\s+looking",
    r"job\s*seek(er|ing)",
    r"in\s+transition",
    # Polish
    r"otwart[ya]\s+na\s+(now[eąa]\s+)?(prac[eę]|ofert[ya]|propozycj[ea]|wyzwani[ae]|możliwości|mozliwosci)",
    r"(szukam|poszukuj[eę])\s+(nowej\s+)?(pracy|zatrudnienia|wyzwa[nń])",
    r"dost[eę]pn[ya]\s+od\s+zaraz",
]
HEADLINE_RE = re.compile("|".join(f"(?:{p})" for p in HEADLINE_PATTERNS), re.IGNORECASE)


@dataclass
class Signal:
    kind: str      # photo_frame | profile_card | headline | hiring
    strength: str  # strong | weak | info
    evidence: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "strength": self.strength, "evidence": self.evidence}


@dataclass
class Detection:
    status: str
    signals: list[Signal] = field(default_factory=list)
    roles: str = ""  # job titles from the Open-to-work card, when shown


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").replace("’", "'").strip()


def detect(snapshot: dict) -> Detection:
    signals: list[Signal] = []
    roles = ""

    for alt in snapshot.get("imgAlts") or []:
        alt = _norm(alt)
        if FRAME_RE.search(alt):
            signals.append(Signal("photo_frame", "strong", alt[:200]))
            break

    lines = [_norm(l) for l in (snapshot.get("topText") or "").splitlines()]
    lines = [l for l in lines if l]
    for i, line in enumerate(lines):
        if CARD_LINE_RE.match(line):
            roles = lines[i + 1] if i + 1 < len(lines) else ""
            if roles.lower().startswith(("show details", "see all details")):
                roles = ""
            signals.append(Signal("profile_card", "strong", f"Open to work: {roles}".strip(": ")))
            break

    headline = _norm(snapshot.get("headline", ""))
    m = HEADLINE_RE.search(headline)
    if m:
        signals.append(Signal("headline", "weak", f"“{m.group(0).strip()}” in headline"))

    for alt in snapshot.get("imgAlts") or []:
        if HIRING_RE.search(alt or ""):
            signals.append(Signal("hiring", "info", "#HIRING photo frame (recruiting, not job-seeking)"))
            break

    if any(s.strength == "strong" for s in signals):
        status = OPEN
    elif any(s.strength == "weak" for s in signals):
        status = LIKELY
    else:
        status = NOT_DETECTED
    return Detection(status=status, signals=signals, roles=roles)
