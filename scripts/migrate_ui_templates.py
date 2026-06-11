"""One-shot UI migration: replace inline styles and wrap tables in table-wrap."""
from __future__ import annotations

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "pharmaconnect" / "templates"
SKIP = {"_macros.html"}

REPLACEMENTS: list[tuple[str, str]] = [
    ('class="grid grid-4" style="margin-bottom:1rem"', 'class="grid grid-4 mb-1"'),
    ('class="grid grid-3" style="margin-bottom:1rem"', 'class="grid grid-3 mb-1"'),
    ('class="grid grid-2" style="margin-bottom:1rem"', 'class="grid grid-2 mb-1"'),
    ('class="form-inline" style="margin-bottom:1rem"', 'class="form-inline filter-bar"'),
    ('style="display:flex;gap:0.5rem;flex-wrap:wrap"', 'class="topbar-actions"'),
    ('style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap"', 'class="topbar-actions"'),
    ('style="display:flex;gap:0.5rem;align-items:center"', 'class="filter-inline"'),
    ('style="display:flex;gap:0.35rem;flex-wrap:wrap;align-items:center"', 'class="inline-actions"'),
    ('style="display:inline-flex;gap:0.25rem;align-items:center"', 'class="inline-actions"'),
    ('style="display:inline-flex;gap:0.35rem;align-items:center"', 'class="inline-actions"'),
    ('style="display:inline"', 'class="inline-form"'),
    ('style="text-align:right"', 'class="text-right"'),
    ('style="color:var(--danger);font-weight:600"', 'class="cell-danger"'),
    ('style="color:var(--muted);font-size:0.85rem;margin:0.5rem 0 0"', 'class="text-sub mt-1"'),
    ('style="color:var(--muted);font-size:0.85rem"', 'class="text-sub"'),
    ('style="color:var(--muted);font-size:0.8rem;margin-top:1rem"', 'class="doc-footer-note"'),
    ('style="color:var(--muted);font-size:0.8rem"', 'class="text-sub"'),
    ('style="color:var(--muted)"', 'class="text-muted"'),
    ('style="color:var(--success)"', 'class="text-success"'),
    ('style="color:var(--accent);font-size:0.85rem"', 'class="scheme-banner"'),
    ('style="margin-top:1.5rem"', 'class="subsection-title"'),
    ('style="margin-top:1rem"', 'class="mt-1"'),
    ('style="margin-top:0.75rem"', 'class="mt-1"'),
    ('style="margin-bottom:1rem"', 'class="mb-1"'),
    ('style="margin-bottom:1.5rem"', 'class="mb-2"'),
    ('style="grid-column:1/-1"', 'class="card-span"'),
    ('style="display:inline-block;margin-bottom:0.5rem"', 'class="invoice-qr"'),
    ('style="text-align:right"', 'class="doc-header-right"'),
    (
        'style="margin-top:1rem;padding:0.75rem;border:1px solid var(--border);border-radius:8px"',
        'class="eway-box mt-1"',
    ),
    (
        'style="display:flex;gap:0.5rem;margin-top:0.5rem;align-items:center"',
        'class="eway-form"',
    ),
    ('<div>', '<div class="topbar-actions">'),  # dangerous - skip
]

# Remove the dangerous last replacement
REPLACEMENTS = [r for r in REPLACEMENTS if r[0] != "<div>"]


def merge_classes(tag: str, extra: str) -> str:
    if not extra:
        return tag
    m = re.search(r'class="([^"]*)"', tag)
    if m:
        classes = m.group(1).split()
        for c in extra.split():
            if c not in classes:
                classes.append(c)
        return tag[: m.start(1)] + " ".join(classes) + tag[m.end(1) :]
    return tag.replace(">", f' class="{extra}">', 1)


def strip_style_add_class(content: str) -> str:
    for old, new in REPLACEMENTS:
        content = content.replace(old, new)
    # kpi-value with inline color
    content = re.sub(
        r'<div class="kpi-value" style="color:var\(--warn\)">',
        '<div class="kpi-value warn">',
        content,
    )
    content = re.sub(
        r'<div class="kpi-value" style="color:var\(--danger\)">',
        '<div class="kpi-value danger">',
        content,
    )
    content = re.sub(
        r'<div class="kpi-value" style="color:var\(--success\)">',
        '<div class="kpi-value success">',
        content,
    )
    content = re.sub(
        r'<div class="kpi-value" style="color:var\(--accent\)">',
        '<div class="kpi-value">',
        content,
    )
    content = re.sub(
        r'<div class="kpi-value" style="font-size:1rem;color:([^"]+)">',
        r'<div class="kpi-value sm">',
        content,
    )
    # h3 with subsection
    content = re.sub(
        r'<h3 style="margin-top:1\.5rem">',
        '<h3 class="subsection-title">',
        content,
    )
    content = re.sub(
        r'<h3 style="color:var\(--danger\)">',
        '<h3 class="subsection-title text-danger">',
        content,
    )
    # topbar bare div -> topbar-actions
    content = re.sub(
        r'(<div class="topbar[^"]*">.*?<h2>.*?</h2>\s*)<div>(\s*(?:<a |<button |<form ))',
        r"\1<div class=\"topbar-actions\">\2",
        content,
        flags=re.DOTALL,
        count=0,
    )
    # card with only table -> list-card + table-wrap
    return content


def wrap_bare_tables(content: str) -> str:
    lines = content.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        if re.search(r'<div class="card(?:\s[^"]*)?">', line) and "list-card" not in line:
            # peek for direct table within card (allow h3/p first)
            j = i + 1
            while j < len(lines):
                s = lines[j].strip()
                if s.startswith("<div class=\"table-wrap\"") or s.startswith("<form"):
                    break
                if s.startswith("<table"):
                    indent = re.match(r"^(\s*)", lines[j]).group(1)
                    out.append(f"{indent}<div class=\"table-wrap\">")
                    out.append(lines[j])
                    i = j
                    # find closing table
                    while i < len(lines):
                        i += 1
                        out.append(lines[i])
                        if lines[i].strip() == "</table>":
                            out.append(f"{indent}</div>")
                            break
                    break
                if s.startswith("</div>"):
                    break
                j += 1
        i += 1
    return "\n".join(out)


def add_list_card(content: str) -> str:
    return re.sub(
        r'<div class="card">(\s*<div class="table-wrap">)',
        r'<div class="card list-card">\1',
        content,
    )


def upgrade_kpi_cards(content: str) -> str:
    return re.sub(
        r'<div class="card">(\s*<h3>[^<]+</h3>\s*<div class="kpi-value)',
        r'<div class="card kpi-card">\1',
        content,
    )


def process_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    updated = original
    updated = strip_style_add_class(updated)
    updated = wrap_bare_tables(updated)
    updated = add_list_card(updated)
    updated = upgrade_kpi_cards(updated)
    if updated != original:
        path.write_text(updated, encoding="utf-8", newline="\n")
        return True
    return False


def main() -> None:
    changed = 0
    for path in sorted(TEMPLATES.glob("*.html")):
        if path.name in SKIP:
            continue
        if process_file(path):
            print(f"updated: {path.name}")
            changed += 1
    print(f"Done. {changed} files changed.")


if __name__ == "__main__":
    main()