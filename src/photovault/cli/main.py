from __future__ import annotations

import argparse
from pathlib import Path

from photovault.catalog.scanner import register_volume, scan_volume
from photovault.backup.audit import audit_backup_set
from photovault.backup.copy import build_copy_plan, execute_copy_plan
from photovault.backup.folder_audit import audit_folder
from photovault.backup.quarantine import build_quarantine_plan, execute_quarantine_plan, undo_quarantine
from photovault.backup.reconcile import reconcile_backup_set
from photovault.backup.sets import add_member, create_backup_set
from photovault.database.connection import connect


def _default_android_helper() -> Path:
    import sys

    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root) / "native" / "macos" / "android_mtp" / "photovault-android-mtp"
    return Path("native/macos/android_mtp/photovault-android-mtp")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="photovault")
    p.add_argument("--catalog", type=Path, default=Path("~/.photovault/catalog.db"))
    sub = p.add_subparsers(dest="command", required=True)
    register = sub.add_parser("register", help="register a folder as a Phase 1 volume")
    register.add_argument("root", type=Path)
    scan = sub.add_parser("scan", help="scan a registered folder read-only")
    scan.add_argument("volume_id")
    scan.add_argument("root", type=Path)
    scan.add_argument("--thumbnail-root", type=Path)
    sub.add_parser("volumes", help="list registered volumes")
    sub.add_parser("volume-refresh", help="refresh connected/offline status from mount paths")
    timeline = sub.add_parser("timeline", help="list catalogued media by capture time")
    timeline.add_argument("--volume-id")
    timeline.add_argument("--limit", type=int, default=100)
    gallery = sub.add_parser("gallery", help="export a local static gallery without copying originals")
    gallery.add_argument("output", type=Path)
    gallery.add_argument("--volume-id")
    gallery.add_argument("--limit", type=int, default=500)
    perceptual = sub.add_parser("perceptual-index", help="compute persisted dHash/pHash values")
    perceptual.add_argument("--volume-id")
    perceptual.add_argument("--algorithm", choices=["dhash64", "phash64", "all"], default="all")
    perceptual.add_argument("--limit", type=int, default=0)
    visual = sub.add_parser("visual-duplicates", help="find advisory visual-similarity groups")
    visual.add_argument("--algorithm", choices=["dhash64", "phash64"], default="phash64")
    visual.add_argument("--threshold", type=int, default=8)
    visual.add_argument("--volume-id")
    places = sub.add_parser("places", help="cluster catalogued GPS metadata")
    places.add_argument("--radius-meters", type=float, default=100.0)
    embedding_index = sub.add_parser("embedding-index", help="index images with a user-supplied ONNX model")
    embedding_index.add_argument("--model", type=Path, required=True)
    embedding_index.add_argument("--model-name")
    embedding_index.add_argument("--image-size", type=int, default=224)
    embedding_index.add_argument("--volume-id")
    embedding_index.add_argument("--limit", type=int, default=0)
    embedding_search = sub.add_parser("embedding-search", help="search persisted embeddings by vector")
    embedding_search.add_argument("model")
    embedding_search.add_argument("--vector", required=True, help="comma-separated query vector")
    embedding_search.add_argument("--limit", type=int, default=20)
    create_set = sub.add_parser("backup-set-create", help="create a backup set")
    create_set.add_argument("name")
    create_set.add_argument("--required-copies", type=int, default=2)
    create_set.add_argument("--scope", default="")
    add = sub.add_parser("backup-set-add", help="add a primary or backup volume to a set")
    add.add_argument("backup_set_id")
    add.add_argument("volume_id")
    add.add_argument("role", choices=["PRIMARY", "BACKUP"])
    add.add_argument("--relative-root", default="")
    audit = sub.add_parser("backup-audit", help="run a read-only redundancy audit")
    audit.add_argument("backup_set_id")
    reconcile = sub.add_parser("reconcile", help="compare a primary and backup read-only")
    reconcile.add_argument("backup_set_id")
    reconcile.add_argument("--backup-volume")
    reconcile.add_argument("--csv", type=Path)
    copy_plan = sub.add_parser("copy-plan", help="create a dry-run copy plan")
    copy_plan.add_argument("backup_set_id")
    copy_plan.add_argument("--backup-volume")
    execute = sub.add_parser("execute-copy", help="execute and verify a copy plan")
    execute.add_argument("backup_set_id")
    execute.add_argument("--backup-volume")
    folder = sub.add_parser("audit-folder", help="audit whether a folder is redundant")
    folder.add_argument("path", type=Path)
    quarantine = sub.add_parser("quarantine", help="move selected catalogued files to reversible quarantine")
    quarantine.add_argument("paths", nargs="+", type=Path)
    quarantine.add_argument("--reason", default="user-requested quarantine")
    quarantine.add_argument("--dry-run", action="store_true")
    undo = sub.add_parser("undo-quarantine", help="restore a completed quarantine operation")
    undo.add_argument("operation_id")
    android = sub.add_parser("android", help="inspect an Android MTP source on macOS")
    android_sub = android.add_subparsers(dest="android_command", required=True)
    devices = android_sub.add_parser("devices", help="list connected Android devices")
    devices.add_argument("--helper", type=Path, default=_default_android_helper())
    storages = android_sub.add_parser("storages", help="list Android storage roots")
    storages.add_argument("--helper", type=Path, default=_default_android_helper())
    listing = android_sub.add_parser("list", help="list a logical Android MTP path")
    listing.add_argument("logical_path", nargs="?", default="")
    listing.add_argument("--offset", type=int, default=0)
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--helper", type=Path, default=_default_android_helper())
    stream = android_sub.add_parser("stream", help="stream one object to a discard sink")
    stream.add_argument("object_id")
    stream.add_argument("--helper", type=Path, default=_default_android_helper())
    stream_test = android_sub.add_parser("stream-test", help="resolve and stream one JPEG in a single MTP session")
    stream_test.add_argument("logical_path", nargs="?", default="DCIM/Camera")
    stream_test.add_argument("--mtp-mode", choices=["full", "partial"], default="full")
    stream_test.add_argument("--partial-size", type=int, default=65536)
    stream_test.add_argument("--transport", choices=["synchronous", "async-pingpong"], default="synchronous")
    stream_test.add_argument("--read-size", choices=["16k", "max-packet"], default="16k")
    stream_test.add_argument("--helper", type=Path, default=_default_android_helper())
    import_one = android_sub.add_parser("import-one", help="copy one Android object with verification")
    import_one.add_argument("object_id")
    import_one.add_argument("destination_root", type=Path)
    import_one.add_argument("--destination-volume", required=True)
    import_one.add_argument("--relative-path")
    import_one.add_argument("--helper", type=Path, default=_default_android_helper())
    import_folder = android_sub.add_parser("import-folder", help="review and import media from one Android folder")
    import_folder.add_argument("logical_path")
    import_folder.add_argument("destination_root", type=Path)
    import_folder.add_argument("--destination-volume", required=True)
    import_folder.add_argument("--helper", type=Path, default=_default_android_helper())
    wifi = sub.add_parser("android-wifi", help="inspect the Android Companion Wi-Fi POC")
    wifi.add_argument("--url", required=True)
    wifi.add_argument("--token", required=True)
    wifi_sub = wifi.add_subparsers(dest="wifi_command", required=True)
    wifi_sub.add_parser("devices")
    wifi_sub.add_parser("folders", help="list read-only Android MediaStore folder summaries")
    wifi_folder = wifi_sub.add_parser("folder", help="show one folder's exact item count")
    wifi_folder.add_argument("relative_path")
    wifi_list = wifi_sub.add_parser("list")
    wifi_list.add_argument("--limit", type=int, default=100)
    wifi_list.add_argument("--offset", type=int, default=0)
    wifi_list.add_argument("--folder", dest="relative_path")
    wifi_stream = wifi_sub.add_parser("stream")
    wifi_stream.add_argument("object_id")
    wifi_benchmark = wifi_sub.add_parser("benchmark-folder", help="read a folder to a discard sink and report payload throughput")
    wifi_benchmark.add_argument("relative_path")
    wifi_benchmark.add_argument("--limit", type=int, default=0, help="maximum files to read; 0 means every file")
    wifi_benchmark.add_argument("--oldest-first", action="store_true")
    wifi_benchmark.add_argument("--images-only", action="store_true")
    wifi_copy = wifi_sub.add_parser("copy-folder", help="review or verified-copy one Android folder to an external destination")
    wifi_copy.add_argument("relative_path")
    wifi_copy.add_argument("destination_root", type=Path, help="an existing directory under /Volumes")
    wifi_copy.add_argument("--limit", type=int, default=0, help="maximum files to copy; 0 means every matching file")
    wifi_copy.add_argument("--oldest-first", action="store_true")
    wifi_copy.add_argument("--images-only", action="store_true")
    wifi_copy.add_argument("--confirm-copy", action="store_true", help="perform the reviewed copy; omission is a read-only plan")
    sub.add_parser("gui", help="launch the optional PySide6 desktop UI")
    return p


def main() -> int:
    args = parser().parse_args()
    if args.command == "android":
        connection = connect(args.catalog)
        try:
            return _dispatch(args, connection)
        finally:
            connection.close()
    if args.command == "android-wifi" and args.wifi_command != "copy-folder":
        return _dispatch(args, None)
    if args.command == "android-wifi" and args.wifi_command == "copy-folder":
        if not str(args.catalog.expanduser().resolve()).startswith("/Volumes/"):
            parser().error("android-wifi copy-folder requires --catalog on an external /Volumes drive")
    connection = connect(args.catalog)

    try:
        return _dispatch(args, connection)
    finally:
        connection.close()


def _dispatch(args: argparse.Namespace, connection) -> int:
    if args.command == "android-wifi":
        import os
        import time
        from photovault.sources.android_wifi import AndroidCompanionUnavailable, AndroidCompanionWifiSource

        source = AndroidCompanionWifiSource(args.url, args.token)
        try:
            if args.wifi_command == "devices":
                item = source.identity()
                print(f"DEVICE\t{item.display_name}\t{item.model}\t{item.adapter}")
            elif args.wifi_command == "folders":
                for folder in source.folders():
                    print(f"FOLDER\t{folder.relative_path}\t{folder.count}\t{folder.size_bytes}\t{folder.image_count}\t{folder.video_count}")
            elif args.wifi_command == "folder":
                print(f"FOLDER_COUNT\t{args.relative_path}\t{source.folder_count(args.relative_path)}")
            elif args.wifi_command == "list":
                items = source.list_folder_page(args.relative_path, offset=args.offset, limit=args.limit) if args.relative_path else list(source.list_children(None))[args.offset:args.offset + args.limit]
                for item in items:
                    print(f"ITEM\t{item.object_id}\t{item.name}\t{item.media_type}\t{item.size_bytes}")
            elif args.wifi_command == "stream":
                with open(os.devnull, "wb") as sink:
                    metrics = source.stream_object(args.object_id, sink)
                print(f"STREAM\t{args.object_id}\t{metrics['bytes_received']}\t{metrics['elapsed_seconds']:.3f}\t{metrics['bytes_per_second']:.0f}")
            elif args.wifi_command == "benchmark-folder":
                started = time.monotonic(); files = 0; received = 0
                with open(os.devnull, "wb") as sink:
                    for item in source.iter_folder(args.relative_path, oldest_first=args.oldest_first):
                        if args.images_only and item.media_type != "IMAGE": continue
                        if args.limit and files >= args.limit: break
                        metrics = source.stream_object(item.object_id, sink)
                        files += 1; received += int(metrics["bytes_received"])
                elapsed = time.monotonic() - started
                print(f"FOLDER_BENCHMARK\t{args.relative_path}\t{files}\t{received}\t{elapsed:.3f}\t{received / elapsed if elapsed else 0:.0f}")
            else:
                from photovault.backup.source_import import SourceImportItem, import_source_items, plan_source_import
                from photovault.catalog.scanner import register_volume

                destination = args.destination_root.expanduser().resolve()
                if not destination.is_dir() or not str(destination).startswith("/Volumes/"):
                    raise AndroidCompanionUnavailable("copy destination must be an existing directory on an external /Volumes drive")
                items = [item for item in source.iter_folder(args.relative_path, oldest_first=args.oldest_first) if not args.images_only or item.media_type == "IMAGE"]
                if args.limit:
                    items = items[:args.limit]
                import_items = [SourceImportItem(
                    item.object_id, f"{args.relative_path.strip('/')}/{item.name}", item.size_bytes,
                    media_type=item.media_type, modified_at=item.modified_at,
                ) for item in items]
                if len({item.relative_path for item in import_items}) != len(import_items):
                    raise AndroidCompanionUnavailable("selected items contain duplicate destination names; no copy was started")
                destination_volume = register_volume(connection, destination)
                plan = plan_source_import(connection, source, import_items, destination, destination_volume)
                conflicts = sum(1 for decision in plan if decision.status.value == "CONFLICT")
                bytes_total = sum(item.size_bytes or 0 for item in items)
                print(f"FOLDER_COPY_PLAN\t{args.relative_path}\t{len(items)}\t{bytes_total}\t{destination}\tconflicts={conflicts}")
                if not args.confirm_copy:
                    print("COPY_NOT_STARTED\tPass --confirm-copy only after reviewing this plan; no phone or destination files were changed.")
                    return 0
                if conflicts:
                    print("COPY_NOT_STARTED\tDestination conflicts must be resolved first.")
                    return 2
                started = time.monotonic(); checkpoint = started; checkpoint_files = 0; checkpoint_bytes = 0; completed_files = 0; completed_bytes = 0
                def progress(row):
                    nonlocal checkpoint, checkpoint_files, checkpoint_bytes, completed_files, completed_bytes
                    now = time.monotonic(); written = int(row["bytes_written"])
                    completed_files += 1; completed_bytes += written; checkpoint_files += 1; checkpoint_bytes += written
                    if now - checkpoint >= 60:
                        elapsed_checkpoint = now - checkpoint; elapsed_total = now - started
                        print(f"FOLDER_COPY_PROGRESS\t{completed_files}\t{len(import_items)}\t{completed_bytes}\t{elapsed_total:.3f}\t{completed_bytes / elapsed_total if elapsed_total else 0:.0f}\t{checkpoint_files}\t{checkpoint_bytes}\t{elapsed_checkpoint:.3f}\t{checkpoint_bytes / elapsed_checkpoint if elapsed_checkpoint else 0:.0f}", flush=True)
                        checkpoint = now; checkpoint_files = 0; checkpoint_bytes = 0
                result = import_source_items(connection, source, import_items, destination, destination_volume, progress_callback=progress)
                elapsed = time.monotonic() - started
                bytes_written = sum(int(row["bytes_written"]) for row in result["results"])
                print(f"FOLDER_COPY\t{args.relative_path}\t{result['imported']}\t{result['already_imported']}\t{bytes_written}\t{elapsed:.3f}\t{bytes_written / elapsed if elapsed else 0:.0f}")
            return 0
        except AndroidCompanionUnavailable as exc:
            print(f"ANDROID_COMPANION_UNAVAILABLE\t{exc}")
            return 2
    if args.command == "android":
        from photovault.sources.android import AndroidMacMtpSource, AndroidSourceUnavailable, stream_test_folder
        from photovault.catalog.sources import record_source_items, register_source

        if args.android_command == "stream-test":
            import os

            try:
                with open(os.devnull, "wb") as sink:
                    metrics = stream_test_folder(args.helper, args.logical_path, sink, read_size=args.read_size, transport=args.transport, mtp_mode=args.mtp_mode, partial_size=args.partial_size)
                print(f"STREAM_TEST\t{args.logical_path}\t{args.mtp_mode}\t{args.partial_size}\t{args.transport}\t{args.read_size}\t{metrics['bytes_received']}\t{metrics['elapsed_seconds']:.3f}\t{metrics['bytes_per_second']:.0f}")
                return 0
            except AndroidSourceUnavailable as exc:
                print(f"ANDROID_UNAVAILABLE\t{exc}")
                return 2
        try:
            source = AndroidMacMtpSource.from_helper(args.helper)
        except AndroidSourceUnavailable as exc:
            print(f"ANDROID_UNAVAILABLE\t{exc}")
            return 2
        try:
            register_source(connection, source.identity())
            if args.android_command == "devices":
                identity = source.identity()
                print(f"DEVICE\t{identity.display_name}\t{identity.model}\t{identity.adapter}")
            elif args.android_command == "storages":
                for storage in source.list_storages():
                    print(f"STORAGE\t{storage.storage_id}\t{storage.name}\t{storage.capacity_bytes}\t{storage.free_bytes}")
            elif args.android_command == "stream":
                import os

                item = source.stat_item(args.object_id)
                with open(os.devnull, "wb") as sink:
                    metrics = source.stream_object(args.object_id, sink)
                print(f"STREAM\t{item.object_id}\t{item.name}\t{metrics['bytes_received']}\t{metrics['elapsed_seconds']:.3f}\t{metrics['bytes_per_second']:.0f}")
            elif args.android_command == "import-one":
                from photovault.backup.source_import import SourceImportItem, import_source_item

                item = source.stat_item(args.object_id)
                relative_path = args.relative_path or item.name
                result = import_source_item(
                    connection,
                    source,
                    SourceImportItem(item.object_id, relative_path, item.size_bytes, media_type=item.media_type, modified_at=item.modified_at),
                    args.destination_root,
                    args.destination_volume,
                )
                print(f"IMPORT\t{result['operation_id']}\t{result['asset_id']}\t{result['bytes_written']}\t{result['sha256']}")
            elif args.android_command == "import-folder":
                from photovault.backup.source_import import (
                    SourceImportItem,
                    SourceImportStatus,
                    import_source_items,
                    plan_source_import,
                )

                parent_id = None
                for component in [part for part in args.logical_path.split("/") if part]:
                    match = source.find_child(parent_id, component)
                    if match is None:
                        print(f"NOT_FOUND\t{args.logical_path}")
                        return 1
                    parent_id = match.object_id
                source_items = [item for item in source.list_children(parent_id) if not item.is_collection]
                import_items = [SourceImportItem(
                    item.object_id,
                    f"{args.logical_path}/{item.name}",
                    item.size_bytes,
                    media_type=item.media_type,
                    modified_at=item.modified_at,
                ) for item in source_items]
                decisions = plan_source_import(connection, source, import_items, args.destination_root, args.destination_volume)
                for decision in decisions:
                    print(f"PLAN\t{decision.status}\t{decision.item.object_id}\t{decision.item.relative_path}\t{decision.reason}")
                if any(decision.status == SourceImportStatus.CONFLICT for decision in decisions):
                    return 2
                result = import_source_items(connection, source, import_items, args.destination_root, args.destination_volume)
                print(f"IMPORT_SUMMARY\t{result['planned']}\t{result['imported']}\t{result['already_imported']}")
            else:
                parent_id = None
                for component in [part for part in args.logical_path.split("/") if part]:
                    match = source.find_child(parent_id, component)
                    if match is None:
                        print(f"NOT_FOUND\t{args.logical_path}")
                        return 1
                    parent_id = match.object_id
                items, total, next_offset = source.list_children_page(
                    parent_id, offset=args.offset, limit=args.limit
                )
                print(f"PAGE\t{args.offset}\t{len(items)}\t{total}\t{'' if next_offset is None else next_offset}")
                for item in items:
                    print(f"ITEM\t{item.object_id}\t{item.name}\t{item.media_type}\t{item.size_bytes}\t{item.modified_at}")
                record_source_items(connection, source.identity().source_id, items, args.logical_path)
            return 0
        except AndroidSourceUnavailable as exc:
            print(f"ANDROID_UNAVAILABLE\t{exc}")
            return 2
        finally:
            source.close()
    if args.command == "register":
        print(register_volume(connection, args.root))
    elif args.command == "scan":
        print(scan_volume(connection, args.volume_id, args.root, args.thumbnail_root))
    elif args.command == "volumes":
        from photovault.catalog.volume_state import refresh_volume_statuses

        refresh_volume_statuses(connection)
        for row in connection.execute("SELECT id, display_name, status, current_mount_path FROM volumes ORDER BY display_name"):
            print(f"{row['id']}\t{row['status']}\t{row['display_name']}\t{row['current_mount_path']}")
    elif args.command == "volume-refresh":
        from photovault.catalog.volume_state import refresh_volume_statuses

        print(refresh_volume_statuses(connection))
    elif args.command == "timeline":
        from photovault.catalog.timeline import list_timeline

        for row in list_timeline(connection, args.volume_id, args.limit):
            print("\t".join("" if value is None else str(value) for value in row))
    elif args.command == "gallery":
        from photovault.catalog.gallery import write_gallery

        print(write_gallery(connection, args.output, args.volume_id, args.limit))
    elif args.command == "perceptual-index":
        from photovault.catalog.perceptual import index_perceptual_hashes

        algorithms = ("dhash64", "phash64") if args.algorithm == "all" else (args.algorithm,)
        print(index_perceptual_hashes(connection, args.volume_id, algorithms, args.limit))
    elif args.command == "visual-duplicates":
        from photovault.catalog.perceptual import find_visual_duplicate_groups

        groups = find_visual_duplicate_groups(connection, args.algorithm, args.threshold, args.volume_id)
        print("WARNING\tvisual similarity is advisory only; no file is safe to delete automatically")
        print(f"GROUPS\t{len(groups)}")
        for group in groups:
            print(f"GROUP\t{group['id']}\t{group['group_type']}\t{group['algorithm']}\tthreshold={group['threshold']}")
            for member in group["members"]:
                print(f"MEMBER\t{member['asset_id']}\tdistance={member['distance']}")
    elif args.command == "places":
        from photovault.catalog.places import cluster_places

        clusters = cluster_places(connection, args.radius_meters)
        print(f"CLUSTERS\t{len(clusters)}")
        for cluster in clusters:
            label = cluster.label or "(coordinates only)"
            print(f"PLACE\t{cluster.id}\t{label}\t{cluster.latitude:.6f},{cluster.longitude:.6f}\tassets={len(cluster.asset_ids)}")
    elif args.command == "embedding-index":
        from photovault.catalog.semantic import OnnxEmbeddingEngine, index_embeddings

        engine = OnnxEmbeddingEngine(args.model, args.model_name, args.image_size)
        print(index_embeddings(connection, engine, args.volume_id, args.limit))
    elif args.command == "embedding-search":
        from photovault.catalog.semantic import search_embeddings

        vector = [float(value.strip()) for value in args.vector.split(",") if value.strip()]
        for asset_id, score in search_embeddings(connection, args.model, vector, args.limit):
            print(f"{asset_id}\t{score:.6f}")
    elif args.command == "backup-set-create":
        print(create_backup_set(connection, args.name, args.required_copies, args.scope))
    elif args.command == "backup-set-add":
        add_member(connection, args.backup_set_id, args.volume_id, args.role, args.relative_root)
    elif args.command == "backup-audit":
        report = audit_backup_set(connection, args.backup_set_id)
        print(f"{report.name}: {report.protected_count}/{report.total_assets} protected ({report.protection_percent:.1f}%)")
        for status, count in report.counts.items():
            if count:
                print(f"{status}\t{count}")
    elif args.command == "reconcile":
        report = reconcile_backup_set(connection, args.backup_set_id, args.backup_volume)
        print(f"{report.name}: {report.primary_volume_id} ↔ {report.backup_volume_id}")
        for status, count in report.counts.items():
            if count:
                print(f"{status}\t{count}")
        if args.csv:
            report.write_csv(args.csv)
            print(f"CSV\t{args.csv}")
    elif args.command == "copy-plan":
        plan = build_copy_plan(connection, args.backup_set_id, args.backup_volume)
        print(f"PLAN\t{plan.operation_id}")
        print(f"FILES\t{len(plan.items)}")
        print(f"BYTES\t{plan.total_bytes}")
        for item in plan.items:
            print(f"COPY\t{item.source_path}\t{item.destination_path}\t{item.size_bytes}")
    elif args.command == "execute-copy":
        plan = build_copy_plan(connection, args.backup_set_id, args.backup_volume)
        print(execute_copy_plan(connection, plan))
    elif args.command == "audit-folder":
        report = audit_folder(connection, args.path)
        status = "SAFE_CANDIDATE_FOR_REMOVAL" if report.safe_candidate else "NOT_SAFE_TO_DELETE"
        print(status)
        print(f"FILES_SCANNED\t{report.files_scanned}")
        print(f"VERIFIED_ELSEWHERE\t{report.verified_elsewhere}")
        print(f"UNIQUE\t{report.unique_files}")
        print(f"CONFLICTS\t{report.conflicts}")
        print(f"OFFLINE_UNKNOWN\t{report.offline_unknown}")
        print(f"UNCATALOGUED\t{report.uncatalogued}")
        for item in report.items:
            if item.status not in {"VERIFIED_ELSEWHERE"}:
                print(f"{item.status}\t{item.relative_path}\t{item.reason}")
    elif args.command == "quarantine":
        plan = build_quarantine_plan(connection, args.paths, args.reason)
        print(f"PLAN\t{plan.operation_id}")
        print(f"FILES\t{len(plan.items)}")
        if not args.dry_run:
            print(execute_quarantine_plan(connection, plan))
    elif args.command == "undo-quarantine":
        print(undo_quarantine(connection, args.operation_id))
    elif args.command == "gui":
        from photovault.ui.main_window import run_gui

        return run_gui(connection)
    return 0
