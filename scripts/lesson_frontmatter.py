"""
Edit one notebook lesson's frontmatter in place, line by line.

Lines are changed individually instead of re-dumping the YAML, so untouched keys
keep their exact formatting (flow maps like `courses: { csse: { week: 6 } }`,
quoting, comments) and diffs stay one line per change.
"""

import json
import re
from pathlib import Path

import yaml

KEY_LINE = re.compile(r"^([A-Za-z_][\w-]*)\s*:")


class FrontmatterEditError(Exception):
    pass


class NotebookFrontmatter:
    """The frontmatter lines of a notebook's first cell, editable by top-level key."""

    def __init__(self, path: Path):
        self.path = path
        self.raw = path.read_text(encoding="utf-8")
        self.notebook = json.loads(self.raw)
        cells = self.notebook.get("cells") or []
        if not cells:
            raise FrontmatterEditError(f"{path} has no cells")
        source = cells[0].get("source", "")
        text = "".join(source) if isinstance(source, list) else source
        self.ends_with_newline = text.endswith("\n")  # kept on save, so the diff is only the edit
        lines = text.splitlines()
        if len(lines) < 2 or lines[0].strip() != "---" or "---" not in (line.strip() for line in lines[1:]):
            raise FrontmatterEditError(f"{path} first cell is not --- delimited frontmatter")
        self.closing = next(i for i, line in enumerate(lines) if i > 0 and line.strip() == "---")
        self.lines = lines

    @property
    def first_cell(self):
        return self.notebook["cells"][0]

    def data(self) -> dict:
        try:
            return yaml.safe_load("\n".join(self.lines[1:self.closing])) or {}
        except yaml.YAMLError as error:
            raise FrontmatterEditError(f"{self.path} frontmatter is not valid YAML: {error}") from error

    def _key_span(self, key):
        """(start, end) line range of a top-level key, including its indented continuation lines."""
        for index in range(1, self.closing):
            match = KEY_LINE.match(self.lines[index])
            if match and match.group(1) == key:
                end = index + 1
                while end < self.closing and (self.lines[end].startswith((" ", "\t")) or not self.lines[end].strip()):
                    end += 1
                return index, end
        return None

    def set(self, key: str, value_text: str):
        """Set `key: value_text`; value_text is YAML (a list is written as a block)."""
        replacement = _render(key, value_text)
        span = self._key_span(key)
        if span:
            self.lines[span[0]:span[1]] = replacement
        else:
            self.lines[self.closing:self.closing] = replacement
        self._refresh_closing()

    def unset(self, key: str):
        span = self._key_span(key)
        if not span:
            raise FrontmatterEditError(f"{self.path.name} has no `{key}` to remove")
        del self.lines[span[0]:span[1]]
        self._refresh_closing()

    def rename(self, old: str, new: str):
        span = self._key_span(old)
        if not span:
            raise FrontmatterEditError(f"{self.path.name} has no `{old}` to rename")
        if self._key_span(new):
            raise FrontmatterEditError(f"{self.path.name} already has `{new}`; merge it by hand")
        self.lines[span[0]] = re.sub(rf"^{re.escape(old)}(\s*:)", rf"{new}\1", self.lines[span[0]])

    def _refresh_closing(self):
        self.closing = next(i for i, line in enumerate(self.lines) if i > 0 and line.strip() == "---")

    def save(self):
        self.data()  # fail before writing if an edit broke the YAML
        text = "\n".join(self.lines) + ("\n" if self.ends_with_newline else "")
        # nbformat allows a source to be one string or a list of lines; keep whichever the file used.
        was_string = isinstance(json.loads(self.raw)["cells"][0].get("source"), str)
        self.first_cell["source"] = text if was_string else text.splitlines(keepends=True)
        self.path.write_text(self._serialize(), encoding="utf-8")

    def _serialize(self):
        # Hand-edited notebooks often indent a cell differently from the rest of the file, and
        # re-dumping would re-indent it. So when only the frontmatter text changed, replace just
        # that array. Other edits (lesson-fix changing the cell type) re-dump with the file's indent.
        original = json.loads(self.raw)
        original["cells"][0]["source"] = self.first_cell["source"]
        if original == self.notebook:
            spliced = _splice_first_source(self.raw, self.first_cell["source"], self.notebook)
            if spliced is not None:
                return spliced
        return (json.dumps(self.notebook, indent=_json_indent(self.raw), ensure_ascii=False)
                + ("\n" if self.raw.endswith("\n") else ""))


FIRST_CELL_SOURCE = re.compile(r'"cells"\s*:\s*\[\s*\{.*?"source"\s*:\s*', re.S)


def _splice_first_source(raw, source_lines, expected):
    """`raw` with only the first cell's source rewritten in its own indentation, or None if unsafe."""
    match = FIRST_CELL_SOURCE.search(raw)
    if not match or not source_lines:
        return None
    start = match.end()
    _, length = json.JSONDecoder().raw_decode(raw[start:])
    if isinstance(source_lines, str):
        spliced = f"{raw[:start]}{json.dumps(source_lines, ensure_ascii=False)}{raw[start + length:]}"
        return spliced if json.loads(spliced) == expected else None
    old = raw[start:start + length]
    if not old.startswith("["):
        return None
    item_indent = re.match(r"\[\n([ \t]*)\S", old)
    close_indent = re.search(r"\n([ \t]*)\]$", old)
    if not (item_indent and close_indent):
        return None
    items = ",\n".join(item_indent.group(1) + json.dumps(line, ensure_ascii=False) for line in source_lines)
    spliced = f"{raw[:start]}[\n{items}\n{close_indent.group(1)}]{raw[start + length:]}"
    # Guard against matching the wrong array: the result must be exactly the edited notebook.
    return spliced if json.loads(spliced) == expected else None


def _json_indent(raw):
    second_line = raw.split("\n", 2)[1] if raw.count("\n") >= 2 else ""
    return (len(second_line) - len(second_line.lstrip(" "))) or 1


def _render(key, value_text):
    try:
        value = yaml.safe_load(value_text)
    except yaml.YAMLError as error:
        raise FrontmatterEditError(f"value for `{key}` is not valid YAML: {value_text!r}") from error
    if isinstance(value, list):
        return [f"{key}:"] + [f"    - {json.dumps(item) if isinstance(item, str) else item}" for item in value]
    text = value_text.strip()
    # An unquoted ` #` starts a YAML comment, so `AP FRQ #1` would silently become `AP FRQ`.
    if isinstance(value, str) and not text.startswith(("'", '"')) and value != text:
        raise FrontmatterEditError(f"`{key}: {text}` would be read as {value!r}; quote the value")
    return [f"{key}: {text}"]
