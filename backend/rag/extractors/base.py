import datetime as dt
from dataclasses import asdict, dataclass, field


@dataclass
class Segment:
    """A piece of a document in reading order. Prose has `text`; a table has `header` and `rows`
    so the chunker can repeat the header in every chunk."""
    kind: str  # "text" | "table"
    location: dict  # e.g. {"page": 3}, {"sheet": "S-Curve", "rows": "1-40"}, {"section": "2. Progress"}
    text: str = ""
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    ocr: bool = False


@dataclass
class Extraction:
    segments: list[Segment]
    page_count: int | None = None
    ocr_page_count: int = 0

    def to_json(self) -> dict:
        return {"segments": [asdict(s) for s in self.segments], "page_count": self.page_count,
                "ocr_page_count": self.ocr_page_count}

    @classmethod
    def from_json(cls, data: dict) -> "Extraction":
        return cls([Segment(**s) for s in data["segments"]], data.get("page_count"), data.get("ocr_page_count", 0))


class UnsupportedFile(Exception):
    pass


def clean_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if v != v:
            return ""
        r = round(v, 6)
        v = int(r) if r.is_integer() else r
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d") if v.time() == dt.time() else v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, (dt.date, dt.time)):
        return v.isoformat()
    return " ".join(str(v).split())


def table_from_grid(grid: list[list[str]]) -> tuple[str, list[str], list[list[str]]]:
    """Drop empty rows/columns and choose a header row: the fullest of the first 10 non-empty rows.
    Returns (preamble, header, rows); the preamble is the title lines above the header."""
    grid = [r for r in grid if any(c for c in r)]
    if not grid:
        return "", [], []
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]
    keep = [j for j in range(width) if any(r[j] for r in grid)]
    grid = [[r[j] for j in keep] for r in grid]
    head = max(range(min(10, len(grid))), key=lambda i: sum(1 for c in grid[i] if c))
    preamble = "\n".join(" | ".join(c for c in r if c) for r in grid[:head])
    return preamble, grid[head], grid[head + 1:]
