"""Identifier-friendly terms, so that "b.p.no 5", "B.P. No. 5", "BP No.5" and the file name
"B_P_No_5_CF_No_NF.pdf" all become the same words: "b p no 5". Used at index time and query time."""
import re

_TERM = re.compile(r"[^\W\d_]+|\d+")  # runs of letters, or runs of digits (splits "No5" into "no 5")


def split_terms(text: str) -> str:
    return " ".join(_TERM.findall(text.lower()))


def id_phrases(text: str, before: int = 3) -> list[tuple[str, int]]:
    """For each number in the text, the phrases ending in it with up to `before` words in front,
    longest first, e.g. "the b.p.no 5" -> [("b p no 5", 3), ("p no 5", 2), ("no 5", 1)]."""
    words = split_terms(text).split()
    phrases = []
    for i, w in enumerate(words):
        if w.isdigit():
            for k in range(min(before, i), 0, -1):
                phrases.append((" ".join(words[i - k:i + 1]), k))
    return phrases
