"""Guardrails around a question: checks on the question before search, on the sources before Gemini reads them,
on the answer after it is written, and on a document's text before it is indexed. All plain, fast checks
(no extra model calls); what they find is returned with the answer as {"status", "findings"}."""
import re
import threading
import time
from collections import defaultdict, deque

from .config import get_settings

BLOCKED_ANSWER = ("I can only answer questions about your uploaded documents, and I can't change how I work. "
                  "Please rephrase your question.")

SELF_HARM_ANSWER = ("I'm really sorry you're feeling this way. You don't have to face it alone: in India you can call "
                    "Tele-MANAS on 14416 or 1-800-891-4416 (free, 24x7) to talk to a counsellor. If you are in immediate "
                    "danger, please call 112.")
HARM_ANSWER = ("I can't help with harming people or animals. If an animal needs care, please contact a vet or a local "
               "animal welfare helpline; if anyone is in danger, call 112. I can answer questions about your documents.")

# Wanting to hurt oneself.
_SELF_HARM = re.compile(r"""(?ix)
      \b(kill|hurt|harm|cut|hang|poison) \s+ my \s* self\b
    | \bsuicid(e|al)\b | \bself[\s-]*harm
    | \bend \s+ (my \s+ life|it \s+ all)\b
    | \b(want|wanna|going) \s+ (to \s+)? die\b
    | \bdon'?t \s+ want \s+ to \s+ live\b
""")

# Wanting, or asking how, to hurt a person or an animal; making weapons. Written in the first person or as
# "how to", so documents' own words ("wards of personnel killed in action") are not caught.
_HARM_VERB = r"(kill|murder|hurt|harm|poison|stab|torture|abuse|strangle|drown)"
_KILL = r"(kill|murder|poison|stab|strangle|torture|drown)"  # not "hurt"/"harm": "will it hurt my chances?"
_HOW = r"how \s+ (do \s+ i | can \s+ i | should \s+ i | would \s+ i | to) \s+"
_HARM = re.compile(rf"""(?ix)
      \b(i|we) \s* (want|wanna|am \s+ going|'?m \s+ going|plan|am \s+ planning|will|'?ll|feel \s+ like)
          \s+ (to \s+)? {_HARM_VERB}\b
    | \b{_HOW} {_HARM_VERB}\b
    | \b{_HOW} (make|build|buy) \s+ (a \s+)? (bomb|explosive|gun|weapon|poison)\b
    | \b{_KILL} \s+ (my|his|her|their|our|your|him|them|someone|somebody|anyone|a \s+ person|people)\b
    | \b(ideas?|ways?|tips|methods?|steps|plans?|help \s+ me) \s+ (to|for|on) \s+ (how \s+ to \s+)? {_HARM_VERB}
""")

# The answer model's own safety verdict (it is told to reply with one of these instead of an answer).
_MODEL_SAFETY = re.compile(r"^\W*SAFETY\s*:\s*(SELF_HARM|HARM)\b")

# Attempts to override the assistant's rules, in a question or hidden in a document.
_INJECTION = re.compile(r"""(?ix)
      \b(ignore|disregard|forget|override|bypass) \s+ (all \s+ | any \s+ | the \s+ | your \s+ | my \s+)?
          (previous|prior|above|earlier|preceding|existing|your|system|safety) \s+
          (instructions?|rules?|prompts?|guidelines|guardrails|restrictions)\b
    | \b(ignore|disregard|forget) \s+ (all|everything) \s+ (above|before|previous|prior)\b
    | \b(system|developer) \s+ (prompt|message)\b
    | \b(reveal|show|print|repeat) \s+ (me \s+)? your \s+ (instructions|rules|prompt)\b
    | \byou \s+ are \s+ now \s+ (DAN|unrestricted|unfiltered|jailbroken|in \s+ (developer|god) \s+ mode)\b
    | \bjail \s* break
    | \bDAN \s+ mode\b
    | \b(pretend|act) \s+ (to \s+ be|as) \b [^.\n]{0,40} \b(no|without) \s+ (rules|restrictions|limits|filters)\b
    | <\s*/?\s*(system|source|instructions?)\s*>
""")

# A downloaded error page saved as a PDF (e.g. "the page you were trying to reach doesn't exist").
_ERROR_PAGE = re.compile(r"""(?ix)
      page \s+ you \s+ (were \s+ )? (trying \s+ to \s+ reach|requested|are \s+ looking \s+ for) \s+
          (doesn'?t|does \s+ not|no \s+ longer|cannot|can't|could \s+ not)
    | \b404 \b [^\n]{0,20} \bnot \s+ found\b
""")

_CITATION = re.compile(r"\[(\d{1,3})\]")
_NUMBER = re.compile(r"(?<![\d.,])\d[\d,]*(?:\.\d+)?")
_LIST_MARKER = re.compile(r"^\s*(?:[-*]\s+)?\d{1,2}[.)]\s+", re.M)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z*])|\n+")
_NOT_FOUND = re.compile(r"(?i)could not find|couldn't find|no information|not (mentioned|available|provided|found)")


def _finding(check: str, message: str, **extra) -> dict:
    return {"check": check, "message": message, **extra}


def report(findings: list[dict], blocked: bool = False, retried: bool = False) -> dict:
    status = "blocked" if blocked else ("warning" if findings else "passed")
    return {"status": status, "findings": findings, **({"retried": True} if retried else {})}


# ---------- the question ----------

def check_question(question: str) -> dict | None:
    """A finding (with the reply to give) when the question shows intent to cause harm or tries to override the
    assistant's rules; None when it is fine."""
    match = _SELF_HARM.search(question)
    if match:
        return _finding("self_harm", "The question suggests the person may be at risk.",
                        matched=match.group(0)[:80], reply=SELF_HARM_ANSWER)
    match = _HARM.search(question)
    if match:
        return _finding("harmful_intent", "The question asks for help harming a person or an animal.",
                        matched=match.group(0)[:80], reply=HARM_ANSWER)
    match = _INJECTION.search(question)
    if match:
        return _finding("prompt_injection", "The question tries to change the assistant's rules.",
                        matched=match.group(0)[:80], reply=BLOCKED_ANSWER)
    return None


def check_model_reply(reply: str) -> dict | None:
    """The answer model flags harmful questions the patterns above missed; a finding with the reply to give."""
    match = _MODEL_SAFETY.match(reply)
    if not match:
        return None
    if match.group(1) == "SELF_HARM":
        return _finding("self_harm", "The question suggests the person may be at risk (flagged by the model).",
                        matched=match.group(0), reply=SELF_HARM_ANSWER)
    return _finding("harmful_intent", "The question asks for help causing harm (flagged by the model).",
                    matched=match.group(0), reply=HARM_ANSWER)


class RateLimiter:
    """At most `limit` questions per client in any 60 seconds (in memory, per API process)."""

    def __init__(self):
        self._calls: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, client: str) -> bool:
        limit = get_settings().ask_rate_per_minute
        if limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            calls = self._calls[client]
            while calls and now - calls[0] > 60:
                calls.popleft()
            if len(calls) >= limit:
                return False
            calls.append(now)
            return True


rate_limiter = RateLimiter()


# ---------- the sources ----------

def screen_sources(hits: list[dict]) -> tuple[list[dict], list[dict]]:
    """Drop chunks that carry instructions aimed at the assistant (indirect prompt injection).
    Returns (kept hits, findings)."""
    kept, dropped = [], []
    for h in hits:
        if _INJECTION.search(h.get("text", "")):
            dropped.append(h)
        else:
            kept.append(h)
    if not dropped:
        return kept, []
    return kept, [_finding("source_injection", f"{len(dropped)} source(s) contained instructions aimed at the "
                           "assistant and were left out.", files=sorted({h["filename"] for h in dropped}))]


def quote_source(n: int, hit: dict) -> str:
    """One source for the prompt, fenced so its text cannot pose as the prompt's own structure."""
    def clean(s: str) -> str:
        return re.sub(r"(?i)<\s*/?\s*source\b[^>]*>", "", s)
    return f'<source n="{n}">\n{clean(hit["context"])}\n{clean(hit["text"])}\n</source>'


# ---------- the answer ----------

def _numbers(text: str) -> set[str]:
    """Numbers as plain digits: "₹ 56,100/-" -> "56100", "02 Jul 2001" -> {"2", "2001"}."""
    out = set()
    for raw in _NUMBER.findall(text):
        value = raw.replace(",", "").rstrip(".")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        out.add(value.lstrip("0") or "0")
    return out


def fix_citations(answer: str, source_count: int) -> tuple[str, list[dict]]:
    """Remove citations to sources that do not exist (e.g. [9] when 8 were given)."""
    bad = sorted({int(n) for n in _CITATION.findall(answer) if not 1 <= int(n) <= source_count})
    if not bad:
        return answer, []
    fixed = _CITATION.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= source_count else "", answer)
    return fixed, [_finding("invalid_citations", "The answer cited sources that do not exist; they were removed.",
                            values=bad)]


def unsupported_numbers(answer: str, sources: list[dict], question: str = "") -> list[str]:
    """Numbers in the answer that appear neither in the sources each sentence cites (all sources when a sentence
    cites none) nor in the question."""
    texts = [f"{s['context']}\n{s['text']}" for s in sources]
    every = set().union(*(_numbers(t) for t in texts)) if texts else set()
    allowed_extra = _numbers(question)
    missing: list[str] = []
    body = _LIST_MARKER.sub("", answer)
    for sentence in _SENTENCE.split(body):
        cited = {int(n) for n in _CITATION.findall(sentence) if 1 <= int(n) <= len(texts)}
        pool = set().union(*(_numbers(texts[n - 1]) for n in cited)) if cited else every
        for num in _numbers(_CITATION.sub("", sentence)):
            if num not in pool and num not in allowed_extra and num not in missing:
                missing.append(num)
    return missing


def check_answer(answer: str, sources: list[dict], question: str = "") -> tuple[str, list[dict]]:
    """Validate citations and numbers. Returns (answer with bad citations removed, findings)."""
    answer, findings = fix_citations(answer, len(sources))
    if _NOT_FOUND.search(answer) and not _CITATION.search(answer):
        return answer, findings  # an honest "not found" has nothing to verify
    if not _CITATION.search(answer):
        findings.append(_finding("no_citations", "The answer does not cite any source."))
    missing = unsupported_numbers(answer, sources, question)
    if missing:
        findings.append(_finding("unsupported_numbers", "Some numbers in the answer were not found in the sources "
                                 "it cites (they may be calculated). Check them before use.", values=missing))
    return answer, findings


def unsupported_count(findings: list[dict]) -> int:
    return sum(len(f["values"]) for f in findings if f["check"] == "unsupported_numbers")


def retry_instruction(findings: list[dict]) -> str | None:
    """A correction to send back to the model when the answer has numbers the sources do not contain."""
    for f in findings:
        if f["check"] == "unsupported_numbers":
            return ("Your previous answer contained these numbers that do not appear in the cited sources: "
                    + ", ".join(f["values"]) + ". Answer again using only figures written in the sources, each with "
                    "the citation of the source that contains it. If you add or calculate a figure, say so.")
    return None


# ---------- a document ----------

def check_document(text: str) -> str | None:
    """Why a document should not be indexed (an error page saved as a PDF, or no readable text); None if fine."""
    words = re.findall(r"[^\W\d_]{2,}", text)
    if len(words) < get_settings().min_document_words:
        return f"Only {len(words)} readable words found; the file may be empty, blank or unreadable."
    if len(text) < 3000 and _ERROR_PAGE.search(text):
        return "The file looks like a web error page (e.g. 'page not found'), not a real document."
    return None
