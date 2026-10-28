#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charx-workbench command line interface.

Examples:
  charx.py info card.charx
  charx.py unpack card.charx work/
  charx.py text export work/
  charx.py pack work/ --out card-edited.charx
  charx.py validate card-edited.charx
  charx.py diff card.charx card-edited.charx
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import charx_core as core  # noqa: E402


def _setup_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def print_json(data):
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n")


def preview(value, limit=100):
    if isinstance(value, str):
        text = value.replace("\r", "\\r").replace("\n", "\\n")
        return text[:limit] + ("..." if len(text) > limit else "")
    return value


def cmd_info(args):
    info = core.info_source(args.source)
    if args.json:
        print_json(info)
        return 0
    card = info["card"]
    module = info["module"]
    print("Source: %s" % info["source"])
    print("  archive : %s | entries %d | payload %s | %s"
          % (core.format_size(info["archive_size"]) if info["archive_size"] else "-",
             info["entry_count"],
             core.format_size(info["payload_size"]),
             info["archive_kind"]))
    if info["prefix_size"]:
        print("  prefix  : %d bytes (charxJpeg)" % info["prefix_size"])
    print("Card: %s | %s | creator: %s" % (card.get("name"), card.get("spec"), card.get("creator")))
    fields = card.get("fields") or {}
    if fields:
        print("  text    : " + ", ".join("%s %s" % (key, format(value, ","))
                                        for key, value in fields.items()))
    print("  lorebook: %d entries (source: %s) | alternate greetings: %d"
          % (card.get("lore_count", 0), card.get("lore_source"),
             card.get("alternate_greetings", 0)))
    by_type = card.get("asset_by_type") or {}
    print("  assets  : %d (%s) | %s | x_meta %d | missing meta %d"
          % (card.get("asset_count", 0),
             ", ".join("%s %d" % item for item in sorted(by_type.items())),
             core.format_size(card.get("asset_bytes") or 0),
             card.get("x_meta_count", 0),
             card.get("assets_missing_meta", 0)))
    exts = card.get("extensions_risuai") or {}
    if exts:
        parts = []
        for key in sorted(exts):
            value = exts[key]
            if value.get("type") == "str":
                parts.append("%s %s" % (key, format(value.get("len", 0), ",")))
            elif value.get("type") in ("list", "dict"):
                parts.append("%s[%s]" % (key, value.get("len")))
        if parts:
            print("  risuai  : " + ", ".join(parts))
    print("Module: %s" % ("present" if module.get("present") else "none"))
    if module.get("present"):
        print("  name    : %s | id %s" % (module.get("name"), module.get("id")))
        print("  content : lorebook %d | regex %d | trigger %d | assets %d | cjs %s | "
              "backgroundEmbedding %s"
              % (module.get("lorebook", 0), module.get("regex", 0), module.get("trigger", 0),
                 module.get("assets", 0), format(module.get("cjs_len", 0), ","),
                 format(module.get("backgroundEmbedding_len", 0), ",")))
        flags = []
        if module.get("namespace"):
            flags.append("namespace=%s" % module.get("namespace"))
        if module.get("customModuleToggle_len"):
            flags.append("toggles %s chars" % format(module.get("customModuleToggle_len"), ","))
        if module.get("lowLevelAccess"):
            flags.append("lowLevelAccess")
        if module.get("hideIcon"):
            flags.append("hideIcon")
        if flags:
            print("  flags   : " + ", ".join(flags))
    counts = info["warnings"]
    print("Checks: %d error(s), %d warning(s), %d info"
          % (counts.get("error", 0), counts.get("warn", 0), counts.get("info", 0)))
    shown = 0
    for item in info["issues"]:
        if item["level"] == "info":
            continue
        if shown >= args.max_issues:
            print("  ... (use --json or validate for the full list)")
            break
        print("  [%s] %s: %s" % (item["level"], item["code"], item["message"]))
        shown += 1
    return 0


def cmd_unpack(args):
    manifest = core.unpack(args.charx, args.work, force=args.force, quiet=args.quiet)
    if args.json:
        print_json(manifest)
        return 0
    print("Unpacked: %s" % args.work)
    print("  source  : %s" % manifest["source"])
    print("  layout  : %s | %s | entries %d | prefix %d bytes"
          % (manifest["layout"], manifest["archive_kind"],
             len(manifest["entries"]), manifest["prefix_size"]))
    print("  card    : card.json (spec %s)" % manifest.get("card_spec"))
    print("  module  : %s" % ("module.json (decoded)" if manifest["module_decoded"]
                              else ("raw module.risum" if manifest["module_entry"] else "none")))
    for warning in manifest.get("warnings") or []:
        print("  WARNING : %s" % warning)
    return 0


def _bundle_for(source):
    if os.path.isdir(source):
        return core.bundle_from_work(source), None
    bundle = core.bundle_from_archive(source)
    return bundle, getattr(bundle, "_archive", None)


def cmd_validate(args):
    bundle, archive = _bundle_for(args.source)
    try:
        issues = core.validate_bundle(bundle, deep=args.deep)
    finally:
        if archive is not None:
            archive.close()
    errors = [item for item in issues if item["level"] == "error"]
    if args.json:
        print_json({
            "source": os.path.abspath(args.source),
            "ok": not errors,
            "counts": {
                "error": len(errors),
                "warn": len([item for item in issues if item["level"] == "warn"]),
                "info": len([item for item in issues if item["level"] == "info"]),
            },
            "issues": issues,
        })
    else:
        counts, lines = core.summarize_issues(issues, limit=args.max_issues)
        print("Validation: %s" % ("PASS" if not errors else "FAIL"))
        print("  errors %d | warnings %d | info %d"
              % (counts.get("error", 0), counts.get("warn", 0), counts.get("info", 0)))
        for line in lines:
            print("  " + line)
        if len(issues) > args.max_issues * 3:
            print("  ... (%d issues total; use --json for all)" % len(issues))
    return 1 if errors else 0


def cmd_pack(args):
    prefix_mode = "keep"
    if args.no_prefix:
        prefix_mode = "none"
    elif args.jpeg_prefix:
        prefix_mode = "file"
    result = core.pack(
        args.work,
        args.out,
        force=args.force,
        sync_book=args.sync_book,
        touch_date=args.touch_date,
        prefix_mode=prefix_mode,
        jpeg_prefix=args.jpeg_prefix,
        compression_level=args.compression,
    )
    counts = {"error": 0, "warn": 0, "info": 0}
    for item in result["validation"]:
        counts[item["level"]] = counts.get(item["level"], 0) + 1
    if args.json:
        print_json(result)
        return 0
    print("Packed: %s" % result["output"])
    print("  entries : %d | prefix %d bytes | validation errors %d, warnings %d"
          % (result["entries"], result["prefix_size"], counts.get("error", 0), counts.get("warn", 0)))
    if result["sync_book"]:
        print("  lorebook: synced %d entries (%s)"
              % (result["sync_book"]["entries"], result["sync_book"]["direction"]))
    return 0


def cmd_diff(args):
    result = core.diff_sources(args.left, args.right,
                               ignore_modification_date=not args.strict_date)
    if args.json:
        print_json(result)
    else:
        entries = result["entries"]
        print("Entries: %d added, %d removed, %d changed"
              % (len(entries["added"]), len(entries["removed"]), len(entries["changed"])))
        for name in entries["added"][:args.max_items]:
            print("  + %s" % name)
        for name in entries["removed"][:args.max_items]:
            print("  - %s" % name)
        for item in entries["changed"][:args.max_items]:
            print("  ~ %s (%s -> %s)"
                  % (item["entry"], core.format_size(item["old_size"] or 0),
                     core.format_size(item["new_size"] or 0)))
        print("Card: %d change(s)" % len(result["card_changes"]))
        for item in result["card_changes"][:args.max_items]:
            _print_change(item)
        print("Module: %d change(s)" % len(result["module_changes"]))
        for item in result["module_changes"][:args.max_items]:
            _print_change(item)
        if not result["prefix"]["same"]:
            print("Prefix: %d -> %d bytes (changed)"
                  % (result["prefix"]["left_size"], result["prefix"]["right_size"]))
    total = (len(result["entries"]["added"]) + len(result["entries"]["removed"])
             + len(result["entries"]["changed"]) + len(result["card_changes"])
             + len(result["module_changes"]))
    if not result["prefix"]["same"]:
        total += 1
    if args.fail_on_diff and total:
        return 1
    return 0


def _print_change(item):
    kind = item["kind"]
    path = item.get("path") or "/"
    if kind == "changed":
        suffix = ""
        if "old_len" in item:
            suffix = " (%d -> %d chars)" % (item["old_len"], item["new_len"])
        print("  ~ %s%s" % (path, suffix))
        print("      - %s" % preview(item.get("old")))
        print("      + %s" % preview(item.get("new")))
    elif kind == "added":
        print("  + %s = %s" % (path, preview(item.get("new"))))
    elif kind == "removed":
        print("  - %s (was %s)" % (path, preview(item.get("old"))))
    elif kind == "length":
        print("  ~ %s length %d -> %d" % (path, item.get("old_len"), item.get("new_len")))
    elif kind == "type":
        print("  ~ %s type %s -> %s" % (path, item.get("old_type"), item.get("new_type")))


def _load_target(work, target):
    _, card, module = core.load_work(work)
    if target == "card":
        return card, "card"
    if target == "module":
        if module is None:
            raise core.CharxError("Work directory has no module.json")
        return module, "module"
    raise core.CharxError("Unknown target: %s" % target)


def cmd_get(args):
    doc, _target = _load_target(args.work, args.target)
    value = core.get_pointer(doc, args.pointer)
    if args.json:
        print_json(value)
    elif isinstance(value, str):
        if args.raw:
            sys.stdout.buffer.write(value.encode("utf-8"))
            sys.stdout.buffer.flush()
        else:
            sys.stdout.write(value + "\n")
    else:
        sys.stdout.write(core.dump_json(value) + "\n")
    return 0


def cmd_set(args):
    if args.file and args.json_file:
        raise core.CharxError("Use only one of --file or --json-file")
    if args.json_file:
        value = core.load_json_file(args.json_file)
    elif args.file:
        value = core.decode_text_bytes(core.read_bytes(args.file), args.file)
    elif isinstance(args.string, str):
        value = args.string
    else:
        if not args.value:
            raise core.CharxError("Provide a value, --file, --json-file or --string")
        if args.string:
            value = args.value
        else:
            try:
                value = json.loads(args.value)
            except ValueError:
                value = args.value
    doc, target = _load_target(args.work, args.target)
    try:
        old = core.get_pointer(doc, args.pointer)
    except core.CharxError:
        old = None
    core.set_pointer(doc, args.pointer, value)
    if target == "card":
        core.save_card(args.work, doc)
    else:
        core.save_module(args.work, doc)
    old_len = len(old) if isinstance(old, str) else None
    new_len = len(value) if isinstance(value, str) else None
    if args.json:
        print_json({"target": target, "pointer": args.pointer, "old": old, "new": value})
    else:
        if old_len is not None and new_len is not None:
            print("Set %s %s (%d -> %d chars)" % (target, args.pointer, old_len, new_len))
        else:
            print("Set %s %s" % (target, args.pointer))
    return 0


def cmd_del(args):
    if not args.yes:
        raise core.CharxError("Refusing to delete a JSON value without --yes")
    doc, target = _load_target(args.work, args.target)
    old = core.get_pointer(doc, args.pointer)
    core.delete_pointer(doc, args.pointer)
    if target == "card":
        core.save_card(args.work, doc)
    else:
        core.save_module(args.work, doc)
    if args.json:
        print_json({"target": target, "pointer": args.pointer, "removed": old})
    else:
        print("Deleted %s %s" % (target, args.pointer))
    return 0


def cmd_text_export(args):
    mapping = core.text_export(args.work, force=args.force, include_empty=args.include_empty)
    if args.json:
        print_json(mapping)
    else:
        print("Exported %d text file(s) to %s"
              % (len(mapping.get("files") or []), os.path.join(args.work, "text")))
        for item in (mapping.get("files") or [])[:args.max_items]:
            print("  %s  (%d chars)" % (item["file"], item.get("len", 0)))
    return 0


def cmd_text_import(args):
    result = core.text_import(args.work, force=args.force, keep_crlf=args.keep_crlf)
    if args.json:
        print_json(result)
    else:
        print("Applied %d file(s); unchanged %d; conflicts %d; missing %d"
              % (len(result["applied"]), len(result["unchanged"]),
                 len(result["conflicts"]), len(result["missing"])))
        for name in result["applied"]:
            print("  applied  %s" % name)
        for item in result["conflicts"]:
            print("  CONFLICT %s: %s" % (item["file"], item["reason"]))
        for name in result["missing"]:
            print("  missing  %s" % name)
        for name in result["unmapped_files"][:args.max_items]:
            print("  unmapped %s (not in _map.json, ignored)" % name)
    return 2 if result["conflicts"] else 0


def cmd_book_list(args):
    result = core.book_list(args.work)
    if args.json:
        print_json(result)
        return 0
    print("Effective lorebook source: %s (%d entries)" % (result["source"], len(result["entries"])))
    print("  idx  mode      order  active keys                          comment")
    for item in result["entries"]:
        keys = (item.get("keys") or "").replace("\n", " ")
        if len(keys) > 30:
            keys = keys[:27] + "..."
        comment = (item.get("comment") or "").replace("\n", " ")
        if len(comment) > 40:
            comment = comment[:37] + "..."
        print("  %3d  %-8s  %5s  %-6s %-29s %s"
              % (item["index"], item.get("mode"), item.get("insertorder"),
                 "yes" if item.get("alwaysActive") else "-", keys, comment))
    return 0


def cmd_book_add(args):
    if args.content_file:
        content = core.decode_text_bytes(core.read_bytes(args.content_file), args.content_file)
    elif args.content is not None:
        content = args.content
    else:
        raise core.CharxError("Provide --content or --content-file")
    result = core.book_add(
        args.work,
        name=args.name,
        keys=args.keys,
        content=content,
        mode=args.mode,
        insertorder=args.order,
        always_active=args.always_active,
        selective=args.selective,
        secondkeys=args.secondkeys,
        folder=args.folder,
        use_regex=args.use_regex,
        case_sensitive=args.case_sensitive,
    )
    if args.json:
        print_json(result)
    else:
        print("Added lore entry #%d to %s" % (result["index"], result["source"]))
    return 0


def cmd_book_remove(args):
    result = core.book_remove(args.work, args.index, yes=args.yes)
    if args.json:
        print_json(result)
    else:
        print("Removed lore entry #%d from %s" % (args.index, result["source"]))
    return 0


def cmd_book_sync(args):
    manifest, card, module = core.load_work(args.work)
    if module is None:
        raise core.CharxError("Work directory has no module.json")
    if args.direction == "module-to-card":
        count = core.sync_module_book_to_card(card, module)
        core.save_card(args.work, card)
    elif args.direction == "card-to-module":
        count = core.sync_card_book_to_module(card, module)
        core.save_module(args.work, module)
    else:
        raise core.CharxError("Unknown direction: %s" % args.direction)
    result = {"direction": args.direction, "entries": count}
    if args.json:
        print_json(result)
    else:
        print("Synced %d lorebook entries (%s)" % (count, args.direction))
    return 0


def cmd_assets_list(args):
    result = core.asset_list(args.work)
    if args.json:
        print_json(result)
        return 0
    print("  idx  type            ext   size       refs  name / entry")
    for item in result:
        size = core.format_size(item["size"]) if item["size"] is not None else "-"
        print("  %3d  %-14s  %-4s  %-9s  %4d  %s"
              % (item["index"], (item["type"] or "")[:14], (item["ext"] or "")[:4], size,
                 item["refs"], item["entry"] or item["name"]))
    return 0


def cmd_assets_add(args):
    result = core.asset_add(
        args.work, args.file,
        name=args.name,
        asset_type=args.type,
        ext=args.ext,
        add_entry=not args.no_entry,
        meta_override=args.meta,
    )
    if args.json:
        print_json(result)
    else:
        print("Added %s (%s, %s)" % (result["entry"], core.format_size(result["bytes"]), result["type"]))
        if result["card_index"] is not None:
            print("  data.assets[%d] -> %s" % (result["card_index"], result["entry"]))
        print("  x_meta: %s" % result["meta_entry"])
        if result.get("warning"):
            print("  WARNING: %s" % result["warning"])
    return 0


def cmd_assets_replace(args):
    result = core.asset_replace(args.work, args.target, args.file, meta_override=args.meta)
    if args.json:
        print_json(result)
    else:
        print("Replaced %s (%s)" % (result["entry"], core.format_size(result["bytes"])))
        if result["meta_entry"]:
            print("  x_meta: %s" % result["meta_entry"])
        if result.get("warning"):
            print("  WARNING: %s" % result["warning"])
    return 0


def cmd_assets_remove(args):
    result = core.asset_remove(args.work, args.target, yes=args.yes, keep_file=args.keep_file)
    if args.json:
        print_json(result)
    else:
        print("Removed asset: %s" % result.get("entry"))
        if result["moved"]:
            print("  moved to _charx/removed/: %s" % ", ".join(result["moved"]))
        if result["references"]:
            print("  WARNING: %d remaining reference(s) to this asset:" % len(result["references"]))
            for item in result["references"][:10]:
                print("    %s %s" % (item["target"], item["pointer"]))
    return 0


def cmd_assets_refs(args):
    manifest, card, module = core.load_work(args.work)
    desc = core.find_asset(card, manifest, args.work, args.target)
    refs = core.asset_references(card, module, desc.get("entry") or args.target)
    result = {"asset": desc, "references": refs}
    if args.json:
        print_json(result)
    else:
        print("References to %s (%d):" % (desc.get("entry"), len(refs)))
        for item in refs:
            print("  %s %s  %s" % (item["target"], item["pointer"], item["preview"]))
    return 0


def cmd_assets_gc(args):
    result = core.asset_gc(args.work, move=args.move, yes=args.yes)
    if args.json:
        print_json(result)
    else:
        print("Orphan assets: %d" % len(result["orphans"]))
        for item in result["orphans"]:
            print("  %s (%s)" % (item["entry"], item["local"]))
        if result["moved"]:
            print("Moved %d file(s) to _charx/removed/" % len(result["moved"]))
    return 0


def cmd_module_decode(args):
    result = core.module_decode_file(args.risum, args.out, args.assets_dir)
    if args.json:
        print_json({"assets": result["assets"], "trailing": result["trailing"]})
    else:
        print("Decoded module to %s (%d assets, trailing %d bytes)"
              % (args.out, len(result["assets"]), result["trailing"]))
    return 0


def cmd_module_encode(args):
    result = core.module_encode_file(args.module_json, args.out, args.assets_dir)
    if args.json:
        print_json(result)
    else:
        print("Encoded %s (%d bytes, %d assets)"
              % (args.out, result["bytes"], result["assets"]))
    return 0


def cmd_raw_get(args):
    name, data = core.raw_get(args.work, args.entry)
    if args.out:
        core.write_bytes(args.out, data)
        print("Wrote %s (%s) to %s" % (name, core.format_size(len(data)), args.out))
        return 0
    if args.hex:
        sys.stdout.write(data.hex() + "\n")
        return 0
    try:
        text = data.decode("utf-8")
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    except UnicodeDecodeError:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    return 0


def cmd_raw_put(args):
    result = core.raw_put(args.work, args.entry, args.file)
    if args.json:
        print_json(result)
    else:
        print("Wrote entry %s (%s) -> %s"
              % (result["entry"], core.format_size(result["bytes"]), result["local"]))
    return 0


def cmd_raw_rm(args):
    result = core.raw_remove(args.work, args.entry, yes=args.yes)
    if args.json:
        print_json(result)
    else:
        print("Removed entry %s (moved to _charx/removed/)" % result["entry"])
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="charx",
        description="Inspect, edit, validate and rebuild PocketRisu .charx character cards.",
    )
    parser.add_argument("--version", action="version",
                        version="%s %s" % (core.TOOL_NAME, core.TOOL_VERSION))
    parser.add_argument("--debug", action="store_true", help="show tracebacks for unexpected errors")
    sub = parser.add_subparsers(dest="command")

    info = sub.add_parser("info", help="summarize an archive or work directory")
    info.add_argument("source")
    info.add_argument("--json", action="store_true")
    info.add_argument("--max-issues", type=int, default=12)
    info.set_defaults(func=cmd_info)

    unpack = sub.add_parser("unpack", help="extract a .charx into an editable work directory")
    unpack.add_argument("charx")
    unpack.add_argument("work")
    unpack.add_argument("--force", action="store_true",
                        help="rename an existing work directory and unpack fresh")
    unpack.add_argument("--quiet", action="store_true")
    unpack.add_argument("--json", action="store_true")
    unpack.set_defaults(func=cmd_unpack)

    validate = sub.add_parser("validate", help="validate an archive or work directory")
    validate.add_argument("source")
    validate.add_argument("--json", action="store_true")
    validate.add_argument("--deep", action="store_true", help="read full asset payloads")
    validate.add_argument("--max-issues", type=int, default=100)
    validate.set_defaults(func=cmd_validate)

    pack = sub.add_parser("pack", help="rebuild a .charx from a work directory")
    pack.add_argument("work")
    pack.add_argument("--out", "-o",
                      help="output .charx path or directory; default: '<card name>.charx'")
    pack.add_argument("--force", action="store_true", help="write even when validation has errors")
    pack.add_argument("--sync-book", choices=["auto", "module-to-card", "card-to-module", "off"],
                      default="auto")
    pack.add_argument("--touch-date", action="store_true",
                      help="update data.modification_date to the current time")
    pack.add_argument("--no-prefix", action="store_true", help="drop the JPEG prefix (charxJpeg)")
    pack.add_argument("--jpeg-prefix", help="use this JPEG file as the charxJpeg prefix")
    pack.add_argument("--compression", type=int, default=6, choices=range(0, 10))
    pack.add_argument("--json", action="store_true")
    pack.set_defaults(func=cmd_pack)

    diff = sub.add_parser("diff", help="compare two archives or work directories")
    diff.add_argument("left")
    diff.add_argument("right")
    diff.add_argument("--json", action="store_true")
    diff.add_argument("--strict-date", action="store_true",
                      help="include data.modification_date in the diff")
    diff.add_argument("--fail-on-diff", action="store_true",
                      help="exit 1 when any difference is found")
    diff.add_argument("--max-items", type=int, default=20)
    diff.set_defaults(func=cmd_diff)

    get = sub.add_parser("get", help="read a JSON value by RFC 6901 pointer")
    get.add_argument("work")
    get.add_argument("pointer")
    get.add_argument("--target", choices=["card", "module"], default="card")
    get.add_argument("--json", action="store_true")
    get.add_argument("--raw", action="store_true", help="write string bytes exactly, no newline")
    get.set_defaults(func=cmd_get)

    set_cmd = sub.add_parser("set", help="set a JSON value by RFC 6901 pointer")
    set_cmd.add_argument("work")
    set_cmd.add_argument("pointer")
    set_cmd.add_argument("value", nargs="?")
    set_cmd.add_argument("--target", choices=["card", "module"], default="card")
    set_cmd.add_argument("--file", help="read a UTF-8 string from this file")
    set_cmd.add_argument("--json-file", help="parse this file as JSON")
    set_cmd.add_argument("--string", nargs="?", const=True, metavar="TEXT",
                         help="set a literal string; accepts the text directly or forces the positional value")
    set_cmd.add_argument("--json", action="store_true")
    set_cmd.set_defaults(func=cmd_set)

    del_cmd = sub.add_parser("del", help="delete a JSON value by RFC 6901 pointer")
    del_cmd.add_argument("work")
    del_cmd.add_argument("pointer")
    del_cmd.add_argument("--target", choices=["card", "module"], default="card")
    del_cmd.add_argument("--yes", action="store_true")
    del_cmd.add_argument("--json", action="store_true")
    del_cmd.set_defaults(func=cmd_del)

    text = sub.add_parser("text", help="export/import long text values as files")
    text_sub = text.add_subparsers(dest="text_command")
    text_export = text_sub.add_parser("export")
    text_export.add_argument("work")
    text_export.add_argument("--force", action="store_true")
    text_export.add_argument("--include-empty", action="store_true")
    text_export.add_argument("--max-items", type=int, default=200)
    text_export.add_argument("--json", action="store_true")
    text_export.set_defaults(func=cmd_text_export)
    text_import = text_sub.add_parser("import")
    text_import.add_argument("work")
    text_import.add_argument("--force", action="store_true",
                             help="apply even when the JSON and the text file both changed")
    text_import.add_argument("--keep-crlf", action="store_true",
                             help="do not normalize CRLF to LF")
    text_import.add_argument("--max-items", type=int, default=100)
    text_import.add_argument("--json", action="store_true")
    text_import.set_defaults(func=cmd_text_import)

    book = sub.add_parser("book", help="inspect or edit the effective lorebook")
    book_sub = book.add_subparsers(dest="book_command")
    book_list = book_sub.add_parser("list")
    book_list.add_argument("work")
    book_list.add_argument("--json", action="store_true")
    book_list.set_defaults(func=cmd_book_list)
    book_add = book_sub.add_parser("add")
    book_add.add_argument("work")
    book_add.add_argument("--name", required=True)
    book_add.add_argument("--keys", required=True, help="comma separated trigger keys")
    book_add.add_argument("--content")
    book_add.add_argument("--content-file")
    book_add.add_argument("--mode", default="normal", choices=sorted(core.LORE_MODES))
    book_add.add_argument("--order", type=int, default=100)
    book_add.add_argument("--always-active", action="store_true")
    book_add.add_argument("--selective", action="store_true")
    book_add.add_argument("--secondkeys")
    book_add.add_argument("--folder")
    book_add.add_argument("--use-regex", action="store_true")
    book_add.add_argument("--case-sensitive", action="store_true")
    book_add.add_argument("--json", action="store_true")
    book_add.set_defaults(func=cmd_book_add)
    book_remove = book_sub.add_parser("remove")
    book_remove.add_argument("work")
    book_remove.add_argument("index", type=int)
    book_remove.add_argument("--yes", action="store_true")
    book_remove.add_argument("--json", action="store_true")
    book_remove.set_defaults(func=cmd_book_remove)
    book_sync = book_sub.add_parser("sync")
    book_sync.add_argument("work")
    book_sync.add_argument("--direction", required=True,
                           choices=["module-to-card", "card-to-module"])
    book_sync.add_argument("--json", action="store_true")
    book_sync.set_defaults(func=cmd_book_sync)

    assets = sub.add_parser("assets", help="inspect or edit card assets")
    assets_sub = assets.add_subparsers(dest="assets_command")
    assets_list = assets_sub.add_parser("list")
    assets_list.add_argument("work")
    assets_list.add_argument("--json", action="store_true")
    assets_list.set_defaults(func=cmd_assets_list)
    assets_add = assets_sub.add_parser("add")
    assets_add.add_argument("work")
    assets_add.add_argument("file")
    assets_add.add_argument("--name")
    assets_add.add_argument("--type", default="x-risu-asset")
    assets_add.add_argument("--ext")
    assets_add.add_argument("--no-entry", action="store_true",
                            help="copy the file but do not add data.assets entry")
    assets_add.add_argument("--meta", help="JSON file to use as x_meta")
    assets_add.add_argument("--json", action="store_true")
    assets_add.set_defaults(func=cmd_assets_add)
    assets_replace = assets_sub.add_parser("replace")
    assets_replace.add_argument("work")
    assets_replace.add_argument("target", help="#index, asset name, entry path or embeded:// URI")
    assets_replace.add_argument("file")
    assets_replace.add_argument("--meta", help="JSON file to use as x_meta")
    assets_replace.add_argument("--json", action="store_true")
    assets_replace.set_defaults(func=cmd_assets_replace)
    assets_remove = assets_sub.add_parser("remove")
    assets_remove.add_argument("work")
    assets_remove.add_argument("target")
    assets_remove.add_argument("--yes", action="store_true")
    assets_remove.add_argument("--keep-file", action="store_true")
    assets_remove.add_argument("--json", action="store_true")
    assets_remove.set_defaults(func=cmd_assets_remove)
    assets_refs = assets_sub.add_parser("refs")
    assets_refs.add_argument("work")
    assets_refs.add_argument("target")
    assets_refs.add_argument("--json", action="store_true")
    assets_refs.set_defaults(func=cmd_assets_refs)
    assets_gc = assets_sub.add_parser("gc")
    assets_gc.add_argument("work")
    assets_gc.add_argument("--move", action="store_true")
    assets_gc.add_argument("--yes", action="store_true")
    assets_gc.add_argument("--json", action="store_true")
    assets_gc.set_defaults(func=cmd_assets_gc)

    module = sub.add_parser("module", help="decode/encode a standalone module.risum")
    module_sub = module.add_subparsers(dest="module_command")
    module_decode = module_sub.add_parser("decode")
    module_decode.add_argument("risum")
    module_decode.add_argument("--out", "-o", required=True)
    module_decode.add_argument("--assets-dir")
    module_decode.add_argument("--json", action="store_true")
    module_decode.set_defaults(func=cmd_module_decode)
    module_encode = module_sub.add_parser("encode")
    module_encode.add_argument("module_json")
    module_encode.add_argument("--out", "-o", required=True)
    module_encode.add_argument("--assets-dir")
    module_encode.add_argument("--json", action="store_true")
    module_encode.set_defaults(func=cmd_module_encode)

    raw = sub.add_parser("raw", help="get/put/remove arbitrary archive entries")
    raw_sub = raw.add_subparsers(dest="raw_command")
    raw_get = raw_sub.add_parser("get")
    raw_get.add_argument("work")
    raw_get.add_argument("entry")
    raw_get.add_argument("--out", "-o")
    raw_get.add_argument("--hex", action="store_true")
    raw_get.set_defaults(func=cmd_raw_get)
    raw_put = raw_sub.add_parser("put")
    raw_put.add_argument("work")
    raw_put.add_argument("entry")
    raw_put.add_argument("file")
    raw_put.add_argument("--json", action="store_true")
    raw_put.set_defaults(func=cmd_raw_put)
    raw_rm = raw_sub.add_parser("rm")
    raw_rm.add_argument("work")
    raw_rm.add_argument("entry")
    raw_rm.add_argument("--yes", action="store_true")
    raw_rm.add_argument("--json", action="store_true")
    raw_rm.set_defaults(func=cmd_raw_rm)
    return parser


def main(argv=None):
    _setup_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except core.CharxError as exc:
        sys.stderr.write("ERROR: %s\n" % exc)
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("Interrupted\n")
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        if getattr(args, "debug", False):
            raise
        sys.stderr.write("ERROR (unexpected): %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
