"""Structure-aware chunking. Prose is packed paragraph by paragraph with a small overlap; tables are
split into row groups with the header repeated, so every chunk is readable on its own."""
import re
from dataclasses import dataclass

from .extractors.base import Segment


@dataclass
class Chunk:
    context: str  # "file > Sheet: X > rows 10-35", stored and shown with the text
    text: str
    location: dict


def est_tokens(text: str) -> int:
    return len(text) // 4 + 1


def _describe(location: dict) -> str:
    parts = []
    if "sheet" in location:
        parts.append(f"Sheet: {location['sheet']}")
    if "page" in location:
        parts.append(f"Page {location['page']}")
    if location.get("section"):
        parts.append(location["section"])
    if "rows" in location:
        parts.append(f"rows {location['rows']}")
    return " > ".join(parts)


def _md_row(cells: list[str]) -> str:
    return "| " + " | ".join(c.replace("|", "/") for c in cells) + " |"


def _split_long(text: str, max_chars: int) -> list[str]:
    """Split one oversized paragraph at sentence ends, then hard-wrap if a sentence is still too long."""
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?;])\s+", text):
        while len(sentence) > max_chars:
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if len(current) + len(sentence) + 1 > max_chars and current:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _chunk_text(text: str, target: int, overlap: int) -> list[str]:
    max_chars, overlap_chars = target * 4, overlap * 4
    paras = []
    for p in re.split(r"\n\s*\n|\n(?=[A-Z0-9•\-*(])", text):
        p = p.strip()
        if p:
            paras.extend(_split_long(p, max_chars) if len(p) > max_chars else [p])
    chunks, current = [], []
    for p in paras:
        if current and sum(len(x) + 1 for x in current) + len(p) > max_chars:
            chunks.append("\n".join(current))
            # Carry the tail paragraphs (up to the overlap size) into the next chunk.
            tail, size = [], 0
            for x in reversed(current):
                if size + len(x) > overlap_chars:
                    break
                tail.insert(0, x)
                size += len(x)
            current = tail
        current.append(p)
    if current:
        chunks.append("\n".join(current))
    return chunks


def _chunk_table(seg: Segment, target: int) -> list[tuple[str, dict]]:
    max_chars = target * 4
    header = _md_row(seg.header) + "\n" + _md_row(["---"] * len(seg.header)) if seg.header else ""
    out, rows, size, start = [], [], len(header), 1
    for i, row in enumerate(seg.rows, start=1):
        line = _md_row(row)
        if rows and size + len(line) > max_chars:
            out.append((header + "\n" + "\n".join(rows), {**seg.location, "rows": f"{start}-{i - 1}"}))
            rows, size, start = [], len(header), i
        rows.append(line[: max_chars])
        size += len(line) + 1
    if rows:
        out.append((header + "\n" + "\n".join(rows), {**seg.location, "rows": f"{start}-{len(seg.rows)}"}))
    elif header:
        out.append((header, seg.location))
    return out


MIN_CHARS = 300  # pieces shorter than this are merged into a neighbour from the same sheet/page/section


def _base(location: dict) -> dict:
    return {k: v for k, v in location.items() if k not in ("rows", "ocr")}


def _merge_small(pieces: list[tuple[str, dict]], max_chars: int) -> list[tuple[str, dict]]:
    merged: list[tuple[str, dict]] = []
    for text, loc in pieces:
        if merged:
            prev_text, prev_loc = merged[-1]
            small = len(prev_text) < MIN_CHARS or len(text) < MIN_CHARS
            if small and _base(prev_loc) == _base(loc) and len(prev_text) + len(text) + 2 <= max_chars:
                rows = [l["rows"] for l in (prev_loc, loc) if "rows" in l]
                new_loc = _base(prev_loc)
                if rows:
                    new_loc["rows"] = f"{rows[0].split('-')[0]}-{rows[-1].split('-')[-1]}"
                if prev_loc.get("ocr") or loc.get("ocr"):
                    new_loc["ocr"] = True
                merged[-1] = (f"{prev_text}\n\n{text}", new_loc)
                continue
        merged.append((text, loc))
    return merged


def chunk_segments(segments: list[Segment], filename: str, target: int = 600, overlap: int = 80) -> list[Chunk]:
    chunks: list[Chunk] = []
    # Merge consecutive prose segments that share a location so small blocks don't become tiny chunks.
    merged: list[Segment] = []
    for seg in segments:
        if (seg.kind == "text" and merged and merged[-1].kind == "text"
                and merged[-1].location == seg.location and merged[-1].ocr == seg.ocr):
            merged[-1] = Segment("text", seg.location, text=merged[-1].text + "\n\n" + seg.text, ocr=seg.ocr)
        else:
            merged.append(seg)

    pieces: list[tuple[str, dict]] = []
    for seg in merged:
        loc = {**seg.location, "ocr": True} if seg.ocr else seg.location
        if seg.kind == "table":
            pieces += [(t, {**l, **({"ocr": True} if seg.ocr else {})}) for t, l in _chunk_table(seg, target)]
        else:
            pieces += [(t, loc) for t in _chunk_text(seg.text, target, overlap)]

    for text, loc in _merge_small(pieces, target * 4):
        if sum(ch.isalnum() for ch in text) < 10:  # e.g. a sheet holding only "INDEX"
            continue
        where = _describe(loc)
        chunks.append(Chunk(context=f"{filename} > {where}" if where else filename, text=text, location=loc))
    return chunks
