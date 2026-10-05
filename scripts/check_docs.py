from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
FENCED_CODE_PATTERN = re.compile(r"(?ms)^\s*(```|~~~).*?^\s*\1\s*$")
INLINE_CODE_PATTERN = re.compile(r"(?<!`)`[^`]*`(?!`)")


def markdown_files(root: Path = ROOT) -> list[Path]:
    paths = [root / "README.md", root / "CONTRIBUTING.md", root / "SECURITY.md"]
    paths.extend((root / "docs").rglob("*.md"))
    workflow_readme = root / "workflows" / "n8n" / "README.md"
    if workflow_readme.is_file():
        paths.append(workflow_readme)
    return sorted({path for path in paths if path.is_file()})


def local_link_errors(path: Path, root: Path = ROOT) -> list[str]:
    text = path.read_text(encoding="utf-8")
    text = FENCED_CODE_PATTERN.sub("", text)
    text = INLINE_CODE_PATTERN.sub("", text)
    errors: list[str] = []

    for match in LINK_PATTERN.finditer(text):
        raw_target = match.group(1).strip()
        if raw_target.startswith("<") and ">" in raw_target:
            raw_target = raw_target[1:raw_target.index(">")]
        else:
            raw_target = raw_target.split(maxsplit=1)[0]
        parsed = urlsplit(raw_target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue

        target = (path.parent / unquote(parsed.path)).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            errors.append(f"{path.relative_to(root)}: link escapes repository: {raw_target}")
            continue
        if not target.exists():
            errors.append(f"{path.relative_to(root)}: missing local link: {raw_target}")
    return errors


def main() -> int:
    paths = markdown_files()
    if not paths:
        print("No project Markdown files found.", file=sys.stderr)
        return 1
    errors = [error for path in paths for error in local_link_errors(path)]
    if errors:
        print("Documentation link check failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print(f"Checked local Markdown links in {len(paths)} files: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
