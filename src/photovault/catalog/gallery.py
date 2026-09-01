from __future__ import annotations

import html
from pathlib import Path

from .timeline import list_timeline


def write_gallery(connection, output: Path, volume_id: str | None = None, limit: int = 500) -> Path:
    output = output.expanduser().resolve()
    rows = list_timeline(connection, volume_id, limit)
    volume_roots = {
        row[0]: Path(row[1]).expanduser().resolve()
        for row in connection.execute("SELECT id, current_mount_path FROM volumes WHERE current_mount_path IS NOT NULL")
    }
    cards: list[str] = []
    for row in rows:
        # Timeline rows also carry display-time and source provenance. Keep the
        # static gallery interested only in the fields it renders so adding
        # organisation metadata remains backwards-compatible for this export.
        asset_id = row[0]
        filename, relative, row_volume_id = row[1], row[2], row[3]
        captured, make, model = row[4], row[6], row[7]
        thumbnail = row[12]
        original = volume_roots[row_volume_id] / relative
        image_uri = Path(thumbnail).expanduser().resolve().as_uri() if thumbnail else original.as_uri()
        full_uri = original.as_uri()
        caption = " · ".join(str(value) for value in (captured, make, model) if value)
        cards.append(
            '<article class="card">'
            f'<a href="{html.escape(full_uri, quote=True)}"><img loading="lazy" src="{html.escape(image_uri, quote=True)}" alt="{html.escape(filename, quote=True)}"></a>'
            f'<div class="name">{html.escape(filename)}</div><div class="meta">{html.escape(caption)}</div>'
            f'<div class="path">{html.escape(relative)}</div></article>'
        )
    document = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>PhotoVault Gallery</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:24px;background:#f7f5f1;color:#2d2924}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}}.card{{background:white;border:1px solid #e2ddd5;border-radius:12px;padding:10px;overflow:hidden}}img{{width:100%;height:180px;object-fit:cover;border-radius:8px}}.name{{font-weight:600;margin-top:8px;word-break:break-word}}.meta,.path{{font-size:12px;color:#6e665d;margin-top:4px;word-break:break-word}}</style>
</head><body><h1>PhotoVault Gallery</h1><p>{len(cards)} catalogued item(s); originals remain in place.</p><main class="grid">{''.join(cards)}</main></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return output
