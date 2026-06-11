"""Second UI pass: remaining inline styles."""
from __future__ import annotations

from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "pharmaconnect" / "templates"

REPLACEMENTS = [
    ('<div class="card" style="max-width:500px">', '<div class="card form-page-narrow">'),
    ('<div class="card" style="max-width:480px">', '<div class="card form-page-narrow">'),
    ('<div class="card" style="max-width:520px">', '<div class="card form-page-narrow">'),
    ('<div class="card" style="max-width:640px">', '<div class="card form-page">'),
    ('<p class="page-meta" style="margin-bottom:1.25rem">', '<p class="page-meta mb-2">'),
    ('style="width:4rem"', 'class="input-narrow"'),
    ('style="width:100px"', 'class="input-qty"'),
    ('style="width:100px"', 'class="input-limit"'),
    ('style="width:5rem"', 'class="input-xs"'),
    ('style="width:6rem"', 'class="input-sm-field"'),
    ('style="width:7rem"', 'class="input-sm-field"'),
    ('style="flex:2"', 'class="flex-2"'),
    ('<div class="form-row" style="flex:2">', '<div class="form-row flex-2">'),
    ('style="color:var(--muted);margin:0"', 'class="text-muted no-margin"'),
    ('style="color:var(--muted);margin-bottom:1rem"', 'class="text-muted mb-1"'),
    ('style="color:var(--muted);font-size:0.85rem;margin-top:0.75rem"', 'class="hint-box"'),
    ('style="color:var(--muted);font-size:0.9rem"', 'class="text-sub"'),
    ('style="color:var(--muted);font-size:0.9rem;margin-top:1rem"', 'class="text-sub mt-1"'),
    ('style="color:var(--muted);font-size:0.8rem;margin-top:1.5rem"', 'class="doc-footer-note"'),
    ('style="color:var(--danger)"', 'class="text-danger"'),
    ('style="color:var(--danger);font-size:0.85rem;max-height:200px;overflow:auto"', 'class="error-list"'),
    ('<ul style="color:var(--danger)"', '<ul class="error-list"'),
    ('<pre style="background:var(--bg);padding:1rem;border-radius:8px;font-size:0.8rem;overflow:auto"', '<pre class="pre-block"'),
    ('<div class="grid grid-2" style="margin-top:2rem"', '<div class="grid grid-2 sign-grid"'),
    ('style="border-top:1px solid var(--border);margin-top:2.5rem;padding-top:0.5rem"', 'class="sign-line"'),
    ('style="display:flex;gap:0.35rem;align-items:center"', 'class="inline-actions"'),
    ('style="margin:1rem 0"', 'class="my-1"'),
    ('style="margin-left:0.5rem"', 'class="ml-1"'),
    ('<div class="card" style="margin-bottom:1rem;display:flex;gap:0.5rem;flex-wrap:wrap;align-items:flex-end"', '<div class="card toolbar-card"'),
    ('<form method="post" style="display:flex;gap:0.5rem;align-items:flex-end"', '<form method="post" class="inline-actions"'),
    ('<td style="max-width:360px"', '<td class="cell-wrap"'),
    ('<label style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem;color:var(--muted)"', '<label class="checkbox-row mb-1"'),
    ('style="margin:0"', 'class="no-margin"'),
    ('placeholder="A1" style="width:4rem;text-transform:uppercase"', 'placeholder="A1" class="input-narrow" style="text-transform:uppercase"'),
]


def main() -> None:
    for path in sorted(TEMPLATES.glob("*.html")):
        content = path.read_text(encoding="utf-8")
        updated = content
        for old, new in REPLACEMENTS:
            updated = updated.replace(old, new)
        if updated != content:
            path.write_text(updated, encoding="utf-8", newline="\n")
            print(f"updated: {path.name}")


if __name__ == "__main__":
    main()