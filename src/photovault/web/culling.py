"""Topic-scoped, reversible culling. Originals are never modified."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from urllib.parse import parse_qs

from photovault.database.connection import connect
from photovault.catalog.library import LibraryQuery, list_library_items


def require_topic(db, topic):
    if not db.execute('SELECT 1 FROM events WHERE id=?', (topic,)).fetchone():
        raise ValueError('Topic not found')


def photo_page(db, topic, section='', offset=0, limit=80, picks=False):
    require_topic(db, topic)
    if section and not db.execute('SELECT 1 FROM topic_sections WHERE id=? AND topic_id=?', (section, topic)).fetchone():
        raise ValueError('Section does not belong to this topic')
    where = "ea.event_id=? AND a.media_type='IMAGE' AND al.missing_since IS NULL"
    args = [topic]
    if section:
        where += ' AND EXISTS(SELECT 1 FROM topic_section_assets sa WHERE sa.asset_id=a.id AND sa.section_id=?)'
        args.append(section)
    if picks:
        where += " AND EXISTS(SELECT 1 FROM topic_culling tc WHERE tc.topic_id=? AND tc.asset_id=a.id AND tc.decision='pick')"
        args.append(topic)
    base = f'''FROM event_assets ea JOIN assets a ON a.id=ea.asset_id
        JOIN asset_locations al ON al.asset_id=a.id
        LEFT JOIN media_metadata mm ON mm.asset_id=a.id WHERE {where}'''
    total = db.execute('SELECT COUNT(DISTINCT a.id) '+base, args).fetchone()[0]
    ids = [r[0] for r in db.execute('SELECT a.id '+base+''' GROUP BY a.id
        ORDER BY MAX(COALESCE(mm.capture_datetime,al.capture_date,'')) DESC,a.id LIMIT ? OFFSET ?''', args+[limit, offset])]
    by_id = {}
    if ids:
        # Only a bounded page of asset identities is expanded into display metadata.
        from photovault.web.server import _row_payload
        rows = list_library_items(db, LibraryQuery(asset_ids=tuple(ids), include_rejected=True, limit=100000))
        for row in rows:
            by_id.setdefault(row['asset_id'], _row_payload(row))
    items = []
    for asset in ids:
        if asset not in by_id:
            continue
        item = by_id[asset]
        row = db.execute("SELECT hash_value FROM perceptual_hashes WHERE asset_id=? AND algorithm='dhash64'", (asset,)).fetchone()
        item['dhash'] = row[0] if row else None
        items.append(item)
    return {'items': items, 'total': total, 'next_offset': offset+len(ids) if offset+len(ids)<total else None}


def decisions(db, topic):
    require_topic(db, topic)
    return {r[0]:r[1] for r in db.execute('''SELECT tc.asset_id,tc.decision FROM topic_culling tc
        JOIN event_assets ea ON ea.asset_id=tc.asset_id AND ea.event_id=tc.topic_id WHERE tc.topic_id=?''', (topic,))}


def set_decision(db, topic, asset, decision):
    if decision not in ('pick','reject','clear'):
        raise ValueError('Invalid decision')
    if not db.execute('SELECT 1 FROM event_assets WHERE event_id=? AND asset_id=?', (topic, asset)).fetchone():
        raise ValueError('Photo is not in this topic')
    if decision == 'clear':
        db.execute('DELETE FROM topic_culling WHERE topic_id=? AND asset_id=?', (topic, asset))
    else:
        db.execute('''INSERT INTO topic_culling VALUES(?,?,?,datetime('now'))
            ON CONFLICT(topic_id,asset_id) DO UPDATE SET decision=excluded.decision,updated_at=excluded.updated_at''', (topic, asset, decision))
    db.commit()


def preview(db, asset):
    """Decode only an explicitly inspected image; return a bounded EXIF-oriented JPEG."""
    from PIL import Image, ImageOps
    rows = db.execute('''SELECT v.current_mount_path,al.relative_path FROM asset_locations al
        JOIN volumes v ON v.id=al.volume_id WHERE al.asset_id=? AND al.missing_since IS NULL
        AND v.status='CONNECTED' ''', (asset,)).fetchall()
    for root_text, relative in rows:
        if not root_text:
            continue
        root = Path(root_text).resolve()
        target = (root / relative).resolve()
        if root not in target.parents or not target.is_file():
            continue
        try:
            with Image.open(target) as original:
                original.draft('RGB', (1800, 1800))
                image = ImageOps.exif_transpose(original)
                image.thumbnail((1800, 1800))
                output = io.BytesIO()
                image.convert('RGB').save(output, format='JPEG', quality=90)
                return output.getvalue()
        except (OSError, ValueError):
            continue
    raise ValueError('Detailed preview unavailable. The original may be offline or unsupported.')


def handle(handler, parsed, method):
    if not parsed.path.startswith('/api/culling/'):
        return False
    db = connect(handler.catalog_path)
    try:
        parts = parsed.path.strip('/').split('/')
        topic = parts[2] if len(parts)>2 else ''
        action = parts[3] if len(parts)>3 else ''
        if method == 'GET' and action == 'preview':
            data = preview(db, topic)
            handler._send(data, 'image/jpeg')
        elif method == 'GET' and action == 'photos':
            q = parse_qs(parsed.query)
            result = photo_page(db, topic, q.get('section',[''])[0], max(0,int(q.get('offset',[0])[0])), min(100,max(1,int(q.get('limit',[80])[0]))), q.get('picks',['0'])[0]=='1')
            handler._json(result)
        elif method == 'GET' and action == 'decisions':
            handler._json({'decisions':decisions(db,topic), 'catalog_key':hashlib.sha256(str(handler.catalog_path).encode()).hexdigest()[:16]})
        elif method == 'POST' and action == 'decisions':
            p = handler._read_json()
            set_decision(db,topic,str(p.get('asset_id','')),str(p.get('decision','')))
            handler._json({'ok':True})
        else:
            handler._json({'error':'Not found'},404)
    except (ValueError, TypeError) as error:
        handler._json({'error':str(error)},400)
    finally:
        db.close()
    return True
