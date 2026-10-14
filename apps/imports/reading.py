"""Reading an uploaded CSV: encoding, delimiter, headings and rows."""

import csv
import io

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
DELIMITERS = [",", ";", "\t", "|"]


class FileProblem(ValueError):
    """The file as a whole cannot be read. The message is shown to the owner."""


def decode(raw: bytes) -> tuple[str, str]:
    """(text, encoding name). UTF-8 with or without a byte order mark, else Windows-1252."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace"), "UTF-8 (with BOM)"
    try:
        return raw.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1252"), "Windows-1252"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "Latin-1"


def detect_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters="".join(DELIMITERS)).delimiter
    except csv.Error:
        first = text.splitlines()[0] if text else ""
        return max(DELIMITERS, key=first.count)


def _headings(row: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for i, cell in enumerate(row, start=1):
        name = " ".join(cell.split()) or f"Column {i}"
        seen[name] = seen.get(name, 0) + 1
        result.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return result


def read(raw: bytes) -> dict:
    """{"encoding", "delimiter", "headers", "rows"}. Rows are padded to the headings."""
    if len(raw) > MAX_BYTES:
        raise FileProblem("The file is larger than 5 MB. Split it into smaller files.")
    text, encoding = decode(raw)
    if not text.strip():
        raise FileProblem("The file is empty.")
    if "\x00" in text:
        raise FileProblem(
            "This does not look like a CSV file. Save it from the spreadsheet as CSV."
        )
    delimiter = detect_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        rows = list(reader)
    except csv.Error as error:
        raise FileProblem(f"The file could not be read as CSV ({error}).") from None
    # Blank lines at the end are dropped. Ones in the middle stay, so row numbers
    # match the spreadsheet; the check passes over them.
    while rows and not any(c.strip() for c in rows[-1]):
        rows.pop()
    if not rows:
        raise FileProblem("The file is empty.")
    headers = _headings(rows[0])
    body = [(r + [""] * len(headers))[: len(headers)] for r in rows[1:]]
    if not any(any(c.strip() for c in r) for r in body):
        raise FileProblem("The file has headings but no rows.")
    if len(body) > MAX_ROWS:
        raise FileProblem(f"The file has more than {MAX_ROWS} rows. Split it into smaller files.")
    return {"encoding": encoding, "delimiter": delimiter, "headers": headers, "rows": body}
