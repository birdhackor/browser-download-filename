"""The README, the documentation and the sources read as they look.

The ```pycon examples give what they show, and no file hides characters that
display as nothing or reorder the text around them, such as U+202E.
"""

from __future__ import annotations

import doctest
import re
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_PYCON_BLOCK = re.compile(r"^```pycon\n(.*?)^```", re.DOTALL | re.MULTILINE)

# The documentation is not in the sdist; there only the README is checked.
DOCUMENTS = [
    path for path in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*/*.md"))] if path.is_file()
]
TEXT_FILES = [
    *DOCUMENTS,
    *(path for path in [ROOT / "MAINTENANCE.md"] if path.is_file()),
    *sorted(ROOT.glob("src/**/*.py")),
    *sorted(ROOT.glob("tests/**/*.py")),
    *sorted(ROOT.glob("scripts/*.py")),
]


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


@pytest.mark.parametrize("path", DOCUMENTS, ids=_relative)
def test_examples(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    parser = doctest.DocTestParser()
    runner = doctest.DocTestRunner(optionflags=doctest.ELLIPSIS)
    report: list[str] = []
    # Examples later in a document may use names that earlier ones defined.
    namespace: dict[str, object] = {}
    for block in _PYCON_BLOCK.finditer(text):
        line = text.count("\n", 0, block.start(1))
        test = parser.get_doctest(block[1], namespace, path.name, str(path), line)
        runner.run(test, out=report.append, clear_globs=False)
        # The test ran in a copy of the namespace.
        namespace.update(test.globs)
    assert runner.failures == 0, "".join(report)


@pytest.mark.parametrize("path", TEXT_FILES, ids=_relative)
def test_no_hidden_characters(path: Path) -> None:
    hidden = [
        f"line {number}: U+{ord(char):04X} {unicodedata.name(char, '')}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        for char in line
        if char != "\t"
        and (
            unicodedata.category(char) in ("Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp")
            or (unicodedata.category(char) == "Zs" and char != " ")
        )
    ]
    # Write such characters as escapes in code, and by name in prose.
    assert not hidden, "\n".join(hidden)
