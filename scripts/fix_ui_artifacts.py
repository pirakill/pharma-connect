"""Fix migration artifacts: escaped quotes and duplicate class attributes."""
from __future__ import annotations

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "pharmaconnect" / "templates"


def fix_content(content: str) -> str:
    content = content.replace('class=\\"topbar-actions\\"', 'class="topbar-actions"')
    while True:
        m = re.search(r'class="([^"]*)" class="([^"]*)"', content)
        if not m:
            break
        content = content[: m.start()] + f'class="{m.group(1)} {m.group(2)}"' + content[m.end() :]
    return content


def main() -> None:
    for path in sorted(TEMPLATES.glob("*.html")):
        original = path.read_text(encoding="utf-8")
        updated = fix_content(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
            print(f"fixed: {path.name}")


if __name__ == "__main__":
    main()