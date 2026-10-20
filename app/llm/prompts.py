"""A versioned prompt store: files named `<name>@v<N>.md` in one directory.

Prompts live in files, not code, so a change is a reviewable diff, and every run_steps row can
record exactly which version produced it. A published version is never edited; a change is
a new file. The content hash is kept too, so a silent edit to an old file is still noticed.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_FILE = re.compile(r"^(?P<name>[a-z][a-z0-9_]*)@v(?P<version>[0-9]+)\.md$")


class PromptNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    version: int
    text: str
    sha256: str

    @property
    def label(self) -> str:
        """The value stored in run_steps.prompt_version, e.g. 'intake@v2'."""
        return f"{self.name}@v{self.version}"

    def render(self, **values: str) -> str:
        """Fill `$placeholders`. A missing value raises, so a typo never ships as literal text."""
        return Template(self.text).substitute(values)


class PromptStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def load(self, name: str, version: int | None = None) -> Prompt:
        # The name becomes part of a file path, so it must be a plain identifier.
        if not _NAME.match(name):
            raise ValueError(f"invalid prompt name: {name!r}")
        if version is None:
            version = self._latest(name)
        path = self._root / f"{name}@v{version}.md"
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise PromptNotFound(f"{name}@v{version}") from None
        return Prompt(name, version, text, hashlib.sha256(text.encode()).hexdigest())

    def _latest(self, name: str) -> int:
        versions = []
        for path in self._root.glob(f"{name}@v*.md"):
            match = _FILE.match(path.name)
            if match and match["name"] == name:
                versions.append(int(match["version"]))
        if not versions:
            raise PromptNotFound(name)
        # Numeric, not alphabetical: v10 is newer than v2.
        return max(versions)
