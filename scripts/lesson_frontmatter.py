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
        lines = ("".join(source) if isinstance(source, list) else source).splitlines()
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
        text = "\n".join(self.lines) + "\n"
        self.first_cell["source"] = text.splitlines(keepends=True)
        # nbformat writes 1-space JSON; matching it keeps the diff to the changed lines.
        self.path.write_text(json.dumps(self.notebook, indent=1, ensure_ascii=False)
                             + ("\n" if self.raw.endswith("\n") else ""), encoding="utf-8")


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
