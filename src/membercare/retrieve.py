"""Lexical retrieval over plan-guide sections. No embedding index is used."""

from __future__ import annotations

import re

_STOP = {
    "a",
    "an",
    "and",
    "are",
    "can",
    "do",
    "for",
    "how",
    "i",
    "is",
    "me",
    "my",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "what",
    "why",
    "you",
    "your",
}


def tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in _STOP}


def search_sections(guide: dict, query: str, limit: int = 3) -> list[dict]:
    wanted = tokens(query)
    ranked: list[tuple[int, str, dict]] = []
    for section in guide["sections"]:
        haystack = tokens(
            " ".join(
                [
                    section["title"],
                    section["text"],
                    " ".join(section.get("keywords") or []),
                ]
            )
        )
        score = len(wanted & haystack)
        if score:
            ranked.append((score, section["id"], section))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    found = []
    for score, _, section in ranked[:limit]:
        row = dict(section)
        row["score"] = score
        row["document_title"] = guide["document_title"]
        row["plan_name"] = guide["plan_name"]
        row["plan_year"] = guide["plan_year"]
        found.append(row)
    return found
