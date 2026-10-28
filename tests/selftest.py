#!/usr/bin/env python3
"""Self-test for charx-workbench. Uses only synthetic fixtures and the stdlib.

Run:  python tests/selftest.py [--keep]
Exit code 0 means every check passed.
"""

import base64
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
CLI = os.path.join(SCRIPTS, "charx.py")
sys.path.insert(0, SCRIPTS)

import charx_core as core  # noqa: E402

RESULTS = []


def check(label, fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - the runner must continue
        RESULTS.append((label, False, "%s: %s" % (type(exc).__name__, exc)))
        print("FAIL  %s\n      %s: %s" % (label, type(exc).__name__, exc))
    else:
        RESULTS.append((label, True, ""))
        print("ok    %s" % label)


def eq(actual, expected, label):
    if actual != expected:
        raise AssertionError("%s: expected %r, got %r" % (label, expected, actual))


def make_png(rgba=(255, 0, 0, 255)):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    raw = b"\x00" + bytes(rgba)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def write_zip(path, entries, prefix=b""):
    """entries: list of (name, bytes) written in that order."""
    with open(path, "wb") as handle:
        if prefix:
            handle.write(prefix)
        with zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in entries:
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.external_attr = (0o600 & 0xFFFF) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, data)


def build_module(lorebook):
    wrapper = {
        "type": "risuModule",
        "module": {
            "name": "Test Module",
            "description": "Module used by the self-test.",
            "id": "11111111-2222-3333-4444-555555555555",
            "lorebook": lorebook,
            "regex": [
                {"comment": "Noise filter", "in": "foo", "out": "bar", "type": "editdisplay"},
            ],
            "trigger": [
                {"comment": "start", "type": "start", "conditions": [],
                 "effect": [{"type": "triggerlua", "code": "-- noop"}]},
            ],
            "cjs": "-- cjs noop",
            "backgroundEmbedding": "<div id=\"module-bg\"></div>",
            "assets": [["mod_asset", "", "png"]],
            "namespace": "selftest",
            "customModuleToggle": "",
            "lowLevelAccess": False,
            "hideIcon": False,
        },
    }
    return wrapper


def build_card(lorebook):
    book = [core.lore_to_charbook(entry) for entry in lorebook]
    return {
        "spec": "chara_card_v3",
        "spec_version": "3.0",
        "data": {
            "name": "Selftest Card",
            "description": "Original description for the self-test.",
            "personality": "Precise.",
            "scenario": "A small laboratory.",
            "first_mes": "Hello from the self-test.",
            "mes_example": "<START>\n{{user}}: ping\n{{char}}: pong",
            "creator_notes": "Synthetic fixture; safe to delete.",
            "system_prompt": "",
            "post_history_instructions": "",
            "alternate_greetings": ["Alternate hello."],
            "character_book": {"name": "Selftest Book", "entries": book},
            "tags": ["selftest", "synthetic"],
            "creator": "charx-workbench",
            "character_version": "1.0",
            "extensions": {
                "talkativeness": "0.5",
                "risuai": {
                    "viewScreen": "none",
                    "backgroundHTML": "<div class=\"card-bg\"></div>",
                    "bias": [],
                    "sdData": [],
                    "utilityBot": False,
                },
            },
            "assets": [
                {"type": "icon", "uri": "embeded://assets/icon/image/main.png",
                 "name": "main", "ext": "png"},
                {"type": "x-risu-asset", "uri": "embeded://assets/other/image/test_bg.png",
                 "name": "test_bg", "ext": "png"},
            ],
            "group_only_greetings": [],
            "creation_date": 1700000000,
            "modification_date": 1700000000,
        },
    }


def build_fixture(path, prefix=b""):
    png = make_png((10, 20, 30, 255))
    lorebook = [
        {"key": "", "secondkey": "", "insertorder": 1000, "comment": "HUD",
         "content": "Constant HUD entry.", "mode": "normal", "alwaysActive": True,
         "selective": False, "extentions": {"risu_case_sensitive": False},
         "useRegex": False, "folder": "\uf000folder:test"},
        {"key": "dragon, wyrm", "secondkey": "cave", "insertorder": 50,
         "comment": "Dragons", "content": "Dragons sleep in caves.", "mode": "normal",
         "alwaysActive": False, "selective": True,
         "extentions": {"risu_case_sensitive": True}, "useRegex": False},
    ]
    card = build_card(lorebook)
    wrapper = build_module(lorebook)
    module_bytes = core.encode_module(wrapper, [png])
    entries = [
        ("card.json", json.dumps(card, ensure_ascii=False, indent=4).encode("utf-8")),
        ("module.risum", module_bytes),
        ("assets/icon/image/main.png", png),
        ("assets/other/image/test_bg.png", png),
        ("x_meta/main.json", b'{"type":"PNG"}'),
        ("x_meta/test_bg.json", b'{"type":"PNG"}'),
        ("notes/readme.txt", "unknown text entry\n".encode("utf-8")),
        ("misc/blob.bin", bytes(range(64))),
    ]
    write_zip(path, entries, prefix=prefix)
    return {"entries": entries, "png": png, "module_bytes": module_bytes, "card": card}


def read_entries(path):
    archive = core.CharxArchive(path)
    try:
        return {name: archive.read(name) for name in archive.names if not name.endswith("/")}
    finally:
        archive.close()


def validate_work(work):
    bundle = core.bundle_from_work(work)
    return core.validate_bundle(bundle)


def errors_of(issues):
    return [item for item in issues if item["level"] == "error"]


def main():
    keep = "--keep" in sys.argv
    tmp = os.path.join(HERE, ".tmp")
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    fixture = os.path.join(tmp, "fixture.charx")
    info = build_fixture(fixture)
    work = os.path.join(tmp, "work")

    def t_unpack_validate():
        core.unpack(fixture, work, quiet=True)
        eq(os.path.isfile(os.path.join(work, "card.json")), True, "card.json extracted")
        eq(os.path.isfile(os.path.join(work, "module.json")), True, "module.json decoded")
        eq(os.path.isdir(os.path.join(work, "_charx", "module_assets")), True,
           "module assets extracted")
        issues = validate_work(work)
        eq(len(errors_of(issues)), 0, "validation errors: %s"
           % [(i["code"], i["message"]) for i in errors_of(issues)])
        eq([i["code"] for i in issues if i["code"] == "BOOK_W_DIVERGENT"], [],
           "synthetic card/module books agree")
        manifest, card, module = core.load_work(work)
        eq(manifest["layout"], "v3", "layout")
        eq(len(manifest["entries"]), len(info["entries"]), "manifest entries")
        eq(core.unwrap_module(module)["assets"][0][1], "",
           "empty module asset URI preserved")

    def t_noop_roundtrip():
        out = os.path.join(tmp, "roundtrip.charx")
        report = core.pack(work, out, sync_book="auto")
        eq(len(errors_of(report["validation"])), 0, "pack validation")
        eq(report["sync_book"]["direction"], "off", "pack auto did not rewrite lorebooks")
        left = read_entries(fixture)
        right = read_entries(out)
        eq(sorted(left), sorted(right), "entry name set")
        eq(len(left), len(right), "entry count")
        damaged = [name for name in left if left[name] != right[name]]
        eq(damaged, [], "byte-identical entries")
        eq(len(right), len(info["entries"]), "roundtrip entry count")

    def t_jpeg_prefix():
        prefix = b"\xff\xd8\xff\xe0" + b"JFIF-selftest-prefix" + b"\x00" * 8
        jpeg_fixture = os.path.join(tmp, "jpeg.charx")
        build_fixture(jpeg_fixture, prefix=prefix)
        jpeg_work = os.path.join(tmp, "work_jpeg")
        core.unpack(jpeg_fixture, jpeg_work, quiet=True)
        issues = validate_work(jpeg_work)
        eq([i["code"] for i in issues if i["level"] == "error"], [], "jpeg validate")
        out = os.path.join(tmp, "jpeg_out.charx")
        core.pack(jpeg_work, out, sync_book="auto")
        raw = core.read_bytes(out)
        eq(raw[:len(prefix)], prefix, "jpeg prefix preserved")
        left = read_entries(jpeg_fixture)
        right = read_entries(out)
        eq([n for n in left if left[n] != right[n]], [], "jpeg payload entries identical")
        no_prefix = os.path.join(tmp, "noprefix.charx")
        core.pack(jpeg_work, no_prefix, prefix_mode="none", sync_book="auto")
        eq(core.read_bytes(no_prefix)[:2], b"PK", "--no-prefix writes a plain zip")

    def t_text_edit():
        mapping = core.text_export(work)
        eq(len(mapping["files"]) > 5, True, "text targets exported")
        lore_files = sorted(item["file"] for item in mapping["files"]
                            if "/lorebook/" in item["file"])
        eq(lore_files, ["module/lorebook/Dragons.md", "module/lorebook/HUD.md"],
           "lorebook files use clean names")
        regex_files = sorted(item["file"] for item in mapping["files"]
                             if "/regex/" in item["file"])
        eq(regex_files, ["module/regex/Noise_filter.in.txt",
                         "module/regex/Noise_filter.out.txt"],
           "regex files use clean names")
        used = set()
        eq([core.unique_filename("Same", used, ".md") for _ in range(2)],
           ["Same.md", "Same_2.md"], "duplicate lore names get a suffix")
        eq(core.clean_filename("CON"), "_CON", "reserved device name is sanitized")
        path = os.path.join(work, "text", "card", "description.md")
        text = open(path, "r", encoding="utf-8").read()
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n\nEdited by selftest.")
        report = core.text_import(work)
        eq(report["applied"], ["card/description.md"], "text import applied")
        _, card, _module = core.load_work(work)
        eq(card["data"]["description"].endswith("Edited by selftest."), True,
           "description updated")
        again = core.text_import(work)
        eq(again["applied"], [], "second import is a no-op")
        # conflict: JSON and text both changed
        core.save_card(work, card)
        card["data"]["description"] += " [json edit]"
        core.save_card(work, card)
        current_text = open(path, "r", encoding="utf-8").read()
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(current_text + " [text edit]")
        conflicted = core.text_import(work)
        eq(len(conflicted["conflicts"]), 1, "conflict detected")
        forced = core.text_import(work, force=True)
        eq(forced["applied"], ["card/description.md"], "forced import")
        _, card, _module = core.load_work(work)
        eq(card["data"]["description"].endswith("Edited by selftest. [text edit]"), True,
           "forced text wins")

    def t_lore_folder_export():
        folder_work = os.path.join(tmp, "work_folders")
        if os.path.isdir(folder_work):
            shutil.rmtree(folder_work)
        shutil.copytree(work, folder_work)
        _manifest, card, module = core.load_work(folder_work)
        lore = core.unwrap_module(module)["lorebook"]
        top_id = "\uf000folder:test"
        nested_id = "\uf000folder:nested"
        lore.insert(0, {"key": top_id, "comment": "Test Folder", "content": "",
                        "mode": "folder", "insertorder": 100, "alwaysActive": False,
                        "secondkey": "", "selective": False})
        lore.insert(1, {"key": nested_id, "comment": "Nested", "content": "",
                        "mode": "folder", "insertorder": 100, "alwaysActive": False,
                        "secondkey": "", "selective": False, "folder": top_id})
        lore.append({"key": "", "secondkey": "", "insertorder": 1000, "comment": "HUD",
                     "content": "Second HUD entry.", "mode": "normal",
                     "alwaysActive": True, "selective": False,
                     "extentions": {}, "useRegex": False, "folder": top_id})
        lore.append({"key": "", "secondkey": "", "insertorder": 1000, "comment": "Deep",
                     "content": "Deep lore content.", "mode": "normal",
                     "alwaysActive": False, "selective": False,
                     "extentions": {}, "useRegex": False, "folder": nested_id})
        lore.append({"key": "", "secondkey": "", "insertorder": 1000, "comment": "Loose",
                     "content": "Orphan folder reference.", "mode": "normal",
                     "alwaysActive": False, "selective": False,
                     "extentions": {}, "useRegex": False, "folder": "folder:missing"})
        core.save_module(folder_work, module)
        mapping = core.text_export(folder_work, force=True)
        lore_files = sorted(item["file"] for item in mapping["files"]
                            if "/lorebook/" in item["file"])
        eq(lore_files, [
            "module/lorebook/Dragons.md",
            "module/lorebook/Loose.md",
            "module/lorebook/Test_Folder/HUD.md",
            "module/lorebook/Test_Folder/HUD_2.md",
            "module/lorebook/Test_Folder/Nested/Deep.md",
        ], "lorebook export mirrors folders")
        deep = os.path.join(folder_work, "text", "module", "lorebook",
                            "Test_Folder", "Nested", "Deep.md")
        eq(os.path.isfile(deep), True, "nested folder file written")
        with open(deep, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("Edited nested lore.")
        applied = core.text_import(folder_work)
        eq(applied["applied"], ["module/lorebook/Test_Folder/Nested/Deep.md"],
           "nested import applied")
        _manifest, _card, module = core.load_work(folder_work)
        contents = [entry.get("content") for entry in core.unwrap_module(module)["lorebook"]]
        eq("Edited nested lore." in contents, True, "nested lore content updated")

        card["data"]["character_book"] = {
            "name": "Selftest Book",
            "entries": [core.lore_to_charbook(entry) for entry in lore],
        }
        card_files = sorted(item["file"] for item in core._text_targets(card, None)
                            if "/character_book/" in item["file"])
        eq(card_files, [
            "card/character_book/Dragons.md",
            "card/character_book/Loose.md",
            "card/character_book/Test_Folder/HUD.md",
            "card/character_book/Test_Folder/HUD_2.md",
            "card/character_book/Test_Folder/Nested/Deep.md",
        ], "card lorebook export mirrors folders")

        collision_card = {"data": {"character_book": {"entries": [
            core.lore_to_charbook({
                "key": "\uf000folder:md", "comment": "Notes.md", "content": "",
                "mode": "folder", "insertorder": 100, "alwaysActive": False,
                "secondkey": "", "selective": False}),
            core.lore_to_charbook({
                "key": "", "comment": "Notes", "content": "Body.",
                "mode": "normal", "insertorder": 100, "alwaysActive": False,
                "secondkey": "", "selective": False}),
        ]}}}
        collision_files = [item["file"] for item in core._text_targets(collision_card, None)
                           if "/character_book/" in item["file"]]
        eq(collision_files, ["card/character_book/Notes_2.md"],
           "lore file avoids folder name collision")

    def t_lorebook_edit():
        added = core.book_add(work, "Synthetic Entry", "alpha, beta",
                              "Synthetic lore content.", insertorder=200)
        eq(added["source"], "module", "book add target")
        out = os.path.join(tmp, "lore_edit.charx")
        report = core.pack(work, out, sync_book="auto")
        eq(report["sync_book"]["direction"], "module-to-card", "auto sync direction")
        eq(report["sync_book"]["entries"], 3, "synced entry count")
        eq(len(errors_of(report["validation"])), 0, "lore edit validation")
        archive = core.CharxArchive(out)
        card = json.loads(archive.read("card.json"))
        module = core.unwrap_module(core.decode_module(archive.read("module.risum"))["wrapper"])
        archive.close()
        eq(len(module["lorebook"]), 3, "module lorebook count")
        entries = card["data"]["character_book"]["entries"]
        eq(len(entries), 3, "card book count")
        eq(entries[2]["keys"], ["alpha", "beta"], "card keys")
        eq(entries[2]["content"], "Synthetic lore content.", "card content")
        eq(entries[2], core.lore_to_charbook(module["lorebook"][2]), "card entry shape")
        diff = core.diff_sources(fixture, out)
        eq(diff["entries"]["added"] + diff["entries"]["removed"] + diff["entries"]["changed"],
           [], "no file-level changes from a lore edit")
        eq(any(change["path"] == "/data/assets" for change in diff["card_changes"]), False,
           "asset list untouched")
        listed = core.book_list(work)
        eq(len(listed["entries"]) if isinstance(listed, dict) else len(listed), 3,
           "book list count")

    def t_module_asset_edit():
        # change a module asset blob and confirm it reaches module.risum
        manifest, _card, module = core.load_work(work)
        png2 = make_png((0, 255, 0, 255))
        core.write_bytes(os.path.join(work, "_charx", "module_assets",
                                      manifest["module_assets"][0]["local"].split("/")[-1]), png2)
        out = os.path.join(tmp, "module_asset.charx")
        core.pack(work, out, sync_book="off")
        decoded = core.decode_module(read_entries(out)["module.risum"])
        eq(decoded["assets"][0], png2, "module asset blob updated")

    def t_asset_ops():
        added_png = os.path.join(tmp, "added.png")
        with open(added_png, "wb") as handle:
            handle.write(make_png((1, 2, 3, 255)))
        added = core.asset_add(work, added_png, name="added", asset_type="x-risu-asset")
        eq(added["name"], "added", "asset name")
        eq(os.path.isfile(core.os_path(work, added["entry"])), True, "asset file written")
        eq(os.path.isfile(core.os_path(work, added["meta_entry"])), True, "x_meta written")
        _, card, _module = core.load_work(work)
        eq(len(card["data"]["assets"]), 3, "card asset count after add")
        eq([i["code"] for i in validate_work(work) if i["level"] == "error"], [],
           "asset add validation")
        replacement = os.path.join(tmp, "replacement.png")
        with open(replacement, "wb") as handle:
            handle.write(make_png((4, 5, 6, 255)))
        replaced = core.asset_replace(work, "added", replacement)
        eq(replaced["bytes"], len(make_png((4, 5, 6, 255))), "replace bytes")
        eq(replaced["warning"], None, "replace ext warning")
        copy = core.asset_add(work, added_png, name="added", asset_type="x-risu-asset")
        eq(copy["entry"], "assets/other/image/added_1.png", "duplicate name deduplicated")
        core.asset_remove(work, "#3", yes=True)
        removed = core.asset_remove(work, "#2", yes=True)
        eq(removed["entry"], "assets/other/image/added.png", "removed entry")
        _, card, _module = core.load_work(work)
        eq(len(card["data"]["assets"]), 2, "card asset count after remove")
        eq(os.path.isfile(core.os_path(work, "assets/other/image/added.png")), False,
           "asset file moved out")
        orphans = core.asset_gc(work)
        eq(orphans["orphans"] if isinstance(orphans, dict) else orphans, [],
           "no orphans after remove")
        # an unreferenced file is reported and collected
        core.raw_put(work, "assets/other/image/orphan.png", added_png)
        found = core.asset_gc(work)
        names = [item["entry"] for item in (found["orphans"] if isinstance(found, dict) else found)]
        eq("assets/other/image/orphan.png" in names, True, "orphan detected")
        core.asset_gc(work, move=True, yes=True)
        eq(os.path.isfile(core.os_path(work, "assets/other/image/orphan.png")), False,
           "orphan moved out")

    def t_raw_ops():
        source = os.path.join(tmp, "raw.txt")
        with open(source, "wb") as handle:
            handle.write(b"raw entry body")
        core.raw_put(work, "notes/extra.txt", source)
        name, data = core.raw_get(work, "notes/extra.txt")
        eq(name, "notes/extra.txt", "raw entry name")
        eq(data, b"raw entry body", "raw entry body")
        core.raw_remove(work, "notes/extra.txt", yes=True)
        try:
            core.raw_get(work, "notes/extra.txt")
        except core.CharxError:
            pass
        else:
            raise AssertionError("raw entry still readable after remove")

    def t_validation_failure():
        bad = os.path.join(tmp, "work_bad")
        if os.path.isdir(bad):
            shutil.rmtree(bad)
        shutil.copytree(work, bad)
        os.remove(os.path.join(bad, "assets", "icon", "image", "main.png"))
        codes = [item["code"] for item in errors_of(validate_work(bad))]
        eq("ASSET_E_MISSING" in codes, True, "missing asset detected: %s" % codes)
        out = os.path.join(tmp, "bad.charx")
        try:
            core.pack(bad, out, sync_book="off")
        except core.CharxError as exc:
            eq("Validation failed" in str(exc), True, "pack refuses invalid bundle")
        else:
            raise AssertionError("pack accepted an invalid bundle")
        eq(os.path.exists(out), False, "no output written for invalid bundle")

    def t_module_standalone():
        risum = os.path.join(tmp, "standalone.risum")
        with open(risum, "wb") as handle:
            handle.write(info["module_bytes"])
        out_json = os.path.join(tmp, "standalone.json")
        assets_dir = os.path.join(tmp, "standalone_assets")
        decoded = core.module_decode_file(risum, out_json, assets_dir)
        eq(len(decoded["assets"]), 1, "standalone asset count")
        wrapper = core.load_json_file(out_json)
        module = core.unwrap_module(wrapper)
        eq(module["assets"][0][1], "", "empty module asset uri kept")
        reencoded = os.path.join(tmp, "standalone_out.risum")
        core.module_encode_file(out_json, reencoded, assets_dir)
        eq(core.read_bytes(reencoded), info["module_bytes"], "module decode/encode roundtrip")

    def t_v2_roundtrip():
        png = make_png((9, 9, 9, 255))
        card = {
            "spec": "chara_card_v2",
            "spec_version": "2.0",
            "data": {
                "name": "Legacy",
                "description": "Legacy v2 card.",
                "first_mes": "Hi.",
                "character_book": {"entries": []},
                "extensions": {"risuai": {"viewScreen": "none"}},
                "assets": [{"type": "x-risu-asset", "uri": "__asset:0",
                            "name": "pic", "ext": "png"}],
            },
        }
        compact = json.dumps(card, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        v2_path = os.path.join(tmp, "legacy.charx")
        write_zip(v2_path, [
            ("chara", base64.b64encode(compact)),
            ("chara-ext-asset_:0", base64.b64encode(png)),
            ("x_meta/chara-ext-asset_:0.json", b'{"type":"PNG"}'),
        ])
        v2_work = os.path.join(tmp, "work_v2")
        core.unpack(v2_path, v2_work, quiet=True)
        manifest, current, module = core.load_work(v2_work)
        eq(manifest["layout"], "v2", "v2 layout")
        eq(module, None, "v2 has no module")
        eq(current, card, "v2 card decoded")
        eq(os.path.isfile(os.path.join(v2_work, "legacy_assets",
                                       "chara-ext-asset__0")), True, "v2 asset decoded")
        errors = [i for i in validate_work(v2_work) if i["level"] == "error"]
        eq(errors, [], "v2 validation")
        out = os.path.join(tmp, "legacy_out.charx")
        core.pack(v2_work, out, sync_book="auto")
        names = sorted(read_entries(out))
        eq(names, ["chara", "chara-ext-asset_:0", "x_meta/chara-ext-asset_:0.json"],
           "v2 entry set")
        repacked = read_entries(out)
        eq(base64.b64decode(repacked["chara"]), compact, "v2 card bytes")
        eq(base64.b64decode(repacked["chara-ext-asset_:0"]), png, "v2 asset bytes")

    def t_cli():
        cli_work = os.path.join(tmp, "work_cli")
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["MSYS_NO_PATHCONV"] = "1"

        def run(*args, cwd=ROOT):
            proc = subprocess.run([sys.executable, CLI] + list(args),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  env=env, cwd=cwd)
            output = (proc.stdout + proc.stderr).decode("utf-8", "replace")
            if proc.returncode != 0:
                raise AssertionError("CLI %s failed (%d): %s"
                                     % (" ".join(args), proc.returncode, output[:500]))
            return output

        data = json.loads(run("info", fixture, "--json"))
        eq(data["entry_count"], len(info["entries"]), "CLI info entry count")
        run("unpack", fixture, cli_work)
        validate = json.loads(run("validate", cli_work, "--json"))
        eq(validate["counts"]["error"], 0, "CLI validate errors")
        out = os.path.join(tmp, "cli_out.charx")
        run("pack", cli_work, "--out", out)
        diff = json.loads(run("diff", fixture, out, "--fail-on-diff", "--json"))
        eq(diff["entries"]["added"], [], "CLI diff added")
        eq(diff["card_changes"], [], "CLI diff card")
        auto_dir = os.path.join(tmp, "cli_auto")
        os.makedirs(auto_dir)
        run("pack", cli_work, cwd=auto_dir)
        auto_out = os.path.join(auto_dir, "Selftest_Card.charx")
        eq(os.path.isfile(auto_out), True, "pack default output uses card name")
        out_dir = os.path.join(tmp, "cli_out_dir")
        run("pack", cli_work, "--out", out_dir + os.sep, cwd=auto_dir)
        eq(os.path.isfile(os.path.join(out_dir, "Selftest_Card.charx")), True,
           "pack directory output uses card name")
        try:
            core.pack(cli_work, fixture, sync_book="off")
        except core.CharxError as exc:
            eq("Refusing to overwrite" in str(exc), True, "pack refuses source overwrite")
        else:
            raise AssertionError("pack accepted the source archive as output")
        run("set", cli_work, "/data/description", "--string", "CLI description")
        got = run("get", cli_work, "/data/description", "--raw")
        eq(got, "CLI description", "CLI get/set")
        run("del", cli_work, "/data/tags", "--yes")
        try:
            run("get", cli_work, "/data/tags", "--raw")
        except AssertionError:
            pass
        else:
            raise AssertionError("CLI del did not remove the pointer")

    check("unpack + validate a synthetic v3 card", t_unpack_validate)
    check("no-op pack is byte-identical", t_noop_roundtrip)
    check("charxJpeg prefix handling", t_jpeg_prefix)
    check("text export/import with conflict detection", t_text_edit)
    check("lorebook export mirrors folders", t_lore_folder_export)
    check("lorebook add and module->card sync", t_lorebook_edit)
    check("module asset blob edit", t_module_asset_edit)
    check("asset add/replace/remove/gc", t_asset_ops)
    check("raw entry put/get/remove", t_raw_ops)
    check("validation blocks a broken bundle", t_validation_failure)
    check("standalone module decode/encode", t_module_standalone)
    check("legacy v2 chara roundtrip", t_v2_roundtrip)
    check("CLI smoke test", t_cli)

    failed = [item for item in RESULTS if not item[1]]
    print("\n%d checks, %d passed, %d failed" % (len(RESULTS), len(RESULTS) - len(failed),
                                                 len(failed)))
    if not keep:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
