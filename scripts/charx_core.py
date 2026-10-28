#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Core library for charx-workbench.

Reads, edits, validates and rebuilds PocketRisu .charx character cards.
Python 3.7+, standard library only.

Format facts implemented here were derived from PocketRisu:
  src/ts/process/processzip.ts   (CharX zip layout, 50 MB asset limit)
  src/ts/process/modules.ts      (module.risum container)
  src/ts/rpack/rpack_js.js       (rpack byte substitution)
  src/ts/characterCards.ts       (card.json v2/v3 export + import rules)
  src/ts/storage/database.svelte.ts (Risu lorebook/regex/trigger shapes)
"""

import base64
import binascii
import copy
import hashlib
import io
import json
import os
import re
import shutil
import struct
import sys
import time
import uuid
import zipfile

TOOL_NAME = "charx-workbench"
TOOL_VERSION = "1.0.0"
MANIFEST_VERSION = 1

MODULE_MAGIC = 111
MODULE_VERSION = 0
MAX_ASSET_BYTES = 50 * 1024 * 1024  # PocketRisu skips assets above this
EMBEDED_PREFIX = "embeded://"
MODULE_ASSET_SCHEME = "module-asset://"

RESERVED_TOP_FILES = {"card.json", "module.json", "module.risum"}
RESERVED_TOP_DIRS = {"_charx", "text"}

LORE_MODES = {"normal", "constant", "multiple", "child", "folder"}
MAX_LORE_FOLDER_DEPTH = 32
TRIGGER_TYPES = {"start", "manual", "output", "input", "display", "request"}
REGEX_TYPES = {"editinput", "editoutput", "editprocess", "editdisplay", "editrequest", "disabled", ""}

CARD_TEXT_FIELDS = [
    ("description", "md"),
    ("first_mes", "md"),
    ("mes_example", "md"),
    ("personality", "md"),
    ("scenario", "md"),
    ("system_prompt", "md"),
    ("post_history_instructions", "md"),
    ("creator_notes", "md"),
    ("creator", "txt"),
    ("character_version", "txt"),
    ("nickname", "txt"),
]

RISU_TEXT_FIELDS = [
    ("backgroundHTML", "html"),
    ("additionalText", "txt"),
    ("defaultVariables", "txt"),
    ("prebuiltAssetCommand", "txt"),
    ("prebuiltAssetStyle", "txt"),
    ("toggles", "txt"),
]

MODULE_TEXT_FIELDS = [
    ("name", "txt"),
    ("description", "md"),
    ("cjs", "js"),
    ("backgroundEmbedding", "html"),
    ("customModuleToggle", "txt"),
]

IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "avif", "bmp"}
AUDIO_EXTS = {"mp3", "wav", "ogg", "flac"}
VIDEO_EXTS = {"mp4", "webm", "mov", "avi", "mkv"}
MODEL_EXTS = {"mmd", "obj"}
AI_EXTS = {"safetensors", "cpkt", "onnx"}
FONT_EXTS = {"otf", "ttf", "woff", "woff2"}
CODE_EXTS = {"js", "ts", "lua"}
STORED_EXTS = IMAGE_EXTS | AUDIO_EXTS | VIDEO_EXTS | AI_EXTS | FONT_EXTS | {"zip", "charx", "gz", "7z"}


class CharxError(Exception):
    pass


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json_bytes(doc):
    return json.dumps(doc, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def canonical_json_sha256(doc):
    try:
        return sha256_bytes(canonical_json_bytes(doc))
    except (TypeError, ValueError):
        return None


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def write_bytes(path, data):
    parent = os.path.dirname(path)
    if parent:
        try:
            os.makedirs(parent)
        except OSError:
            if not os.path.isdir(parent):
                raise
    with open(path, "wb") as f:
        f.write(data)


def write_json(path, doc, indent=2):
    text = json.dumps(doc, ensure_ascii=False, indent=indent, default=str)
    write_bytes(path, (text + "\n").encode("utf-8"))


def load_json_bytes(data, label="JSON"):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CharxError("%s is not valid UTF-8: %s" % (label, exc))
    try:
        return json.loads(text)
    except ValueError as exc:
        raise CharxError("%s is not valid JSON: %s" % (label, exc))


def load_json_file(path):
    return load_json_bytes(read_bytes(path), path)


def decode_text_bytes(data, label="file"):
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CharxError("%s is not valid UTF-8: %s" % (label, exc))


def dump_json(doc, indent=2):
    return json.dumps(doc, ensure_ascii=False, indent=indent, default=str)


def issue(level, code, message, path=None):
    item = {"level": level, "code": code, "message": message}
    if path:
        item["path"] = path
    return item


def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def slugify(text, fallback="item", max_len=48):
    text = (text or "").strip()
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._ ")
    if len(text) > max_len:
        text = text[:max_len].rstrip("._ ")
    return text or fallback


WINDOWS_RESERVED_NAMES = ({"CON", "PRN", "AUX", "NUL"}
                          | set("COM%d" % i for i in range(1, 10))
                          | set("LPT%d" % i for i in range(1, 10)))


def clean_filename(text, fallback="lore", max_len=48):
    base = slugify(text, fallback=fallback, max_len=max_len)
    if base.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:
        base = "_" + base
    return base


def unique_filename(base, used, ext):
    candidate = base + ext
    index = 2
    while candidate.lower() in used:
        candidate = "%s_%d%s" % (base, index, ext)
        index += 1
    used.add(candidate.lower())
    return candidate


def format_size(num):
    if num < 1024:
        return "%d B" % num
    if num < 1024 * 1024:
        return "%.1f KB" % (num / 1024.0)
    return "%.2f MB" % (num / (1024.0 * 1024.0))


# --------------------------------------------------------------------------
# rpack + module.risum
# --------------------------------------------------------------------------

class RPack:
    """Risu's byte-substitution codec. rpack_map.bin is 512 bytes: encode|decode."""

    def __init__(self, path=None):
        if path is None:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rpack_map.bin")
        data = read_bytes(path)
        if len(data) != 512:
            raise CharxError("rpack map must be 512 bytes: %s" % path)
        self.encode_table = data[:256]
        self.decode_table = data[256:512]

    def encode(self, data):
        return bytes(data).translate(self.encode_table)

    def decode(self, data):
        return bytes(data).translate(self.decode_table)


RPACK = RPack()


def decode_module(raw):
    """Return {wrapper, assets:[bytes], trailing:int} from module.risum bytes."""
    if len(raw) < 3:
        raise CharxError("module.risum is too short")
    if raw[0] != MODULE_MAGIC:
        raise CharxError("module.risum: bad magic %d (expected 111)" % raw[0])
    if raw[1] != MODULE_VERSION:
        raise CharxError("module.risum: unsupported version %d" % raw[1])
    pos = 2
    if pos + 4 > len(raw):
        raise CharxError("module.risum: truncated header")
    main_len = struct.unpack_from("<I", raw, pos)[0]
    pos += 4
    if pos + main_len > len(raw):
        raise CharxError("module.risum: truncated main block")
    main_raw = RPACK.decode(raw[pos:pos + main_len])
    pos += main_len
    try:
        wrapper = json.loads(main_raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CharxError("module.risum: main block is not JSON: %s" % exc)
    if not isinstance(wrapper, dict) or wrapper.get("type") != "risuModule":
        raise CharxError("module.risum: main block is not a risuModule wrapper")
    if not isinstance(wrapper.get("module"), dict):
        raise CharxError("module.risum: wrapper has no module object")

    assets = []
    while pos < len(raw):
        tag = raw[pos]
        pos += 1
        if tag == 0:
            break
        if tag != 1:
            raise CharxError("module.risum: unknown block tag %d at offset %d" % (tag, pos - 1))
        if pos + 4 > len(raw):
            raise CharxError("module.risum: truncated asset block header")
        length = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        if pos + length > len(raw):
            raise CharxError("module.risum: truncated asset block")
        assets.append(RPACK.decode(raw[pos:pos + length]))
        pos += length
    return {"wrapper": wrapper, "assets": assets, "trailing": len(raw) - pos}


def encode_module(wrapper, assets):
    """Serialize a risuModule wrapper + raw asset blobs into module.risum bytes.

    Asset URIs are blanked exactly like PocketRisu's exportModuleLegacy.
    """
    if not isinstance(wrapper, dict) or wrapper.get("type") != "risuModule":
        raise CharxError("module.json must be a {\"type\":\"risuModule\",\"module\":{...}} wrapper")
    if not isinstance(wrapper.get("module"), dict):
        raise CharxError("module.json has no module object")
    work = copy.deepcopy(wrapper)
    module = work["module"]
    meta = module.get("assets")
    if meta is None:
        meta = []
        module["assets"] = meta
    if not isinstance(meta, list):
        raise CharxError("module.assets must be a list")
    if len(meta) != len(assets):
        raise CharxError(
            "module.assets has %d entries but %d binaries were resolved"
            % (len(meta), len(assets))
        )
    for index, entry in enumerate(meta):
        if not isinstance(entry, list) or len(entry) < 1:
            raise CharxError("module.assets[%d] must be [name, uri, ext]" % index)
        while len(entry) < 3:
            entry.append("")
        entry[1] = ""

    main = json.dumps(work, ensure_ascii=False, indent=2).encode("utf-8")
    out = bytearray()
    out += bytes(bytearray([MODULE_MAGIC, MODULE_VERSION]))
    out += struct.pack("<I", len(main))
    out += RPACK.encode(main)
    for blob in assets:
        encoded = RPACK.encode(blob)
        out += b"\x01"
        out += struct.pack("<I", len(encoded))
        out += encoded
    out += b"\x00"
    return bytes(out)


# --------------------------------------------------------------------------
# image / file type detection
# --------------------------------------------------------------------------

def detect_image_type(data):
    n = len(data)
    if n >= 2 and data[0] == 0xFF and data[1] == 0xD8:
        return "JPEG"
    if n >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if n >= 6 and data[:4] == b"GIF8" and data[4:6] in (b"7a", b"9a"):
        return "GIF"
    if n >= 2 and data[:2] == b"BM":
        return "BMP"
    if n >= 12 and data[4:12] == b"ftypavif":
        return "AVIF"
    if n >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return "Unknown"


def detect_ext(data):
    image = detect_image_type(data)
    if image != "Unknown":
        return {"JPEG": "jpg", "PNG": "png", "GIF": "gif", "BMP": "bmp", "AVIF": "avif", "WEBP": "webp"}[image]
    if data[:4] == b"riFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"fLaC":
        return "flac"
    if data[:4] == b"ID3 " or (len(data) > 1 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "mp3"
    if len(data) > 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"qt  ",):
            return "mov"
        return "mp4"
    if data[:4] == b"\x1aE\xdf\xa3":
        return "webm" if b"webm" in data[:64] else "mkv"
    if data[:4] == b"PK\x03\x04":
        return "zip"
    return None


def png_text_chunks(data):
    """Extract tEXt chunks the way PocketRisu does for x_meta."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return {}
    out = {}
    pos = 8
    n = len(data)
    while pos + 12 <= n:
        length = struct.unpack_from(">I", data, pos)[0]
        ctype = data[pos + 4:pos + 8]
        if ctype == b"IEND":
            break
        if ctype == b"tEXt":
            chunk = data[pos + 8:pos + 8 + length]
            key, sep, value = chunk.partition(b"\x00")
            if sep:
                out[key.decode("latin-1", "replace")] = value.decode("utf-8", "replace")
        if length > n:
            break
        pos += 12 + length
    return out


def asset_folder(asset_type):
    if asset_type in ("emotion", "background", "user_icon", "icon"):
        return asset_type
    return "other"


def asset_itype(ext):
    ext = (ext or "").lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in MODEL_EXTS:
        return "model"
    if ext in AI_EXTS:
        return "ai"
    if ext in FONT_EXTS:
        return "fonts"
    if ext in CODE_EXTS:
        return "code"
    if ext in ("", "unknown"):
        return "image"
    return "other"


def asset_path_for(asset_type, name, ext):
    ext = (ext or "unknown").lower()
    folder = asset_folder(asset_type)
    itype = asset_itype(ext)
    if ext == "unknown":
        ext = "png"
    return "assets/%s/%s/%s.%s" % (folder, itype, name, ext)


# --------------------------------------------------------------------------
# entry / local path safety
# --------------------------------------------------------------------------

def norm_entry_name(name):
    name = name.replace("\\", "/")
    while "//" in name:
        name = name.replace("//", "/")
    return name


def is_safe_entry_name(name):
    name = norm_entry_name(name)
    if not name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return False
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts:
        return False
    return all(p != ".." for p in parts)


_WIN_INVALID = set('<>:"\\|?*')
_WIN_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.I)


def safe_component(comp):
    out = "".join("_" if (c in _WIN_INVALID or ord(c) < 32) else c for c in comp)
    out = out.rstrip(" .")
    if not out:
        out = "_"
    if _WIN_RESERVED.match(out):
        out = "_" + out
    if len(out) > 100:
        digest = sha256_text(out)[:8]
        stem, dot, ext = out.rpartition(".")
        if dot and len(ext) <= 10:
            out = stem[:80] + "~" + digest + "." + ext
        else:
            out = out[:80] + "~" + digest
    return out


def local_path_for(entry_name, used):
    parts = [safe_component(p) for p in norm_entry_name(entry_name).split("/") if p]
    rel = "/".join(parts)
    if len(rel) > 190:
        digest = sha256_text(rel)[:8]
        rel = rel[:150].rstrip("._/") + "~" + digest
    base = rel
    counter = 1
    while rel.lower() in used:
        root, ext = os.path.splitext(base)
        rel = "%s_%d%s" % (root, counter, ext)
        counter += 1
    used.add(rel.lower())
    return rel


def os_path(work, rel):
    parts = [p for p in rel.split("/") if p]
    return os.path.join(work, *parts)


def work_local_for_entry(entry_name, used):
    """Local path for a source entry, kept out of tool-owned names and skip rules."""
    rel = local_path_for(entry_name, used)
    first = rel.split("/", 1)[0].lower()
    base = rel.rsplit("/", 1)[-1]
    lowered = rel.lower()
    if (first in RESERVED_TOP_DIRS or lowered in RESERVED_TOP_FILES
            or base.startswith(".") or lowered.endswith((".tmp", ".charx"))):
        return local_path_for("_charx/original/entries/" + rel, used)
    return rel


# --------------------------------------------------------------------------
# .charx archive reader (plain ZIP or JPEG-prefixed charxJpeg)
# --------------------------------------------------------------------------

class CharxArchive:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        raw = read_bytes(self.path)
        self.raw = raw
        self.raw_size = len(raw)
        self.prefix = b""
        self._bio = None
        self._zf = None
        offsets = [0]
        if not raw.startswith(b"PK\x03\x04"):
            offsets = []
            idx = raw.find(b"PK\x03\x04")
            while idx != -1 and len(offsets) < 8:
                offsets.append(idx)
                idx = raw.find(b"PK\x03\x04", idx + 1)
            if not offsets:
                raise CharxError("Not a ZIP/CharX archive: %s" % self.path)
        last_err = None
        for off in offsets:
            try:
                bio = io.BytesIO(raw[off:])
                zf = zipfile.ZipFile(bio)
                if not zf.infolist():
                    raise zipfile.BadZipFile("empty archive")
                self._bio = bio
                self._zf = zf
                self.prefix = raw[:off]
                break
            except Exception as exc:  # noqa: BLE001 - report last parse error
                last_err = exc
        if self._zf is None:
            raise CharxError("Cannot read ZIP in %s: %s" % (self.path, last_err))
        self.infos = self._zf.infolist()
        self.names = [i.filename for i in self.infos]
        self.name_set = set(self.names)

    def read(self, name):
        return self._zf.read(name)

    def head(self, name, count=32):
        with self._zf.open(name) as handle:
            return handle.read(count)

    def info(self, name):
        return self._zf.getinfo(name)

    def close(self):
        if self._zf is not None:
            self._zf.close()
            self._zf = None


# --------------------------------------------------------------------------
# card / module JSON helpers
# --------------------------------------------------------------------------

def unwrap_module(wrapper):
    if not isinstance(wrapper, dict):
        raise CharxError("module.json is not an object")
    module = wrapper.get("module")
    if not isinstance(module, dict):
        raise CharxError("module.json has no module object")
    return module


def card_data(card):
    if not isinstance(card, dict):
        raise CharxError("card.json is not an object")
    data = card.get("data")
    if not isinstance(data, dict):
        raise CharxError("card.json has no data object")
    return data


def effective_lore(card, module):
    """Return (source, list) where module wins, exactly like PocketRisu import."""
    if isinstance(module, dict):
        lore = unwrap_module(module).get("lorebook")
        if isinstance(lore, list):
            return "module", lore
    try:
        entries = card_data(card).get("character_book", {}).get("entries")
    except CharxError:
        entries = None
    if isinstance(entries, list):
        return "card", entries
    return None, []


def card_asset_entries(card):
    try:
        assets = card_data(card).get("assets")
    except CharxError:
        return []
    return assets if isinstance(assets, list) else []


def iter_strings(value, pointer=""):
    """Yield (pointer, string) for every string in a JSON document."""
    if isinstance(value, str):
        yield pointer, value
    elif isinstance(value, dict):
        for key, child in value.items():
            child_ptr = pointer + "/" + str(key).replace("~", "~0").replace("/", "~1")
            for item in iter_strings(child, child_ptr):
                yield item
    elif isinstance(value, list):
        for index, child in enumerate(value):
            for item in iter_strings(child, pointer + "/" + str(index)):
                yield item


def asset_references(card, module, target):
    """Find JSON pointers whose string value references target."""
    results = []
    needle = target.replace("\\", "/")
    exact = "/" not in needle
    for label, doc in (("card", card), ("module", module)):
        if not isinstance(doc, dict):
            continue
        for pointer, value in iter_strings(doc):
            text = value.replace("\\", "/")
            hit = (text == needle) if exact else (needle in text)
            if hit:
                results.append({
                    "target": label,
                    "pointer": pointer,
                    "preview": value[:120],
                })
    return results


# --------------------------------------------------------------------------
# lorebook conversion (ported from PocketRisu characterCards.ts)
# --------------------------------------------------------------------------

def charbook_to_lore(book_entry):
    if not isinstance(book_entry, dict):
        raise CharxError("character_book entry is not an object")
    extensions = copy.deepcopy(book_entry.get("extensions") or {})
    content = book_entry.get("content") or ""
    keys = book_entry.get("keys") or []
    secondary = book_entry.get("secondary_keys") or []
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        raise CharxError("character_book entry keys must be a list of strings")
    if not isinstance(secondary, list) or not all(isinstance(k, str) for k in secondary):
        secondary = []

    if extensions.get("useProbability") and extensions.get("probability") not in (None, 100):
        content = "@@probability %s\n%s" % (extensions.get("probability"), content)
        extensions.pop("useProbability", None)
        extensions.pop("probability", None)
    if (extensions.get("position") == 4
            and isinstance(extensions.get("depth"), int)
            and isinstance(extensions.get("role"), int)):
        roles = ["system", "user", "assistant"]
        role_index = extensions.get("role")
        role_name = roles[role_index] if 0 <= role_index < len(roles) else "system"
        content = "@@depth %d\n@@role %s\n%s" % (extensions.get("depth"), role_name, content)
        extensions.pop("position", None)
        extensions.pop("depth", None)
        extensions.pop("role", None)
    if isinstance(extensions.get("selectiveLogic"), int) and secondary:
        logic = extensions.get("selectiveLogic")
        if logic == 1:
            book_entry = dict(book_entry)
            book_entry["selective"] = False
            content = "@@exclude_keys_all %s\n%s" % (",".join(secondary), content)
        elif logic == 2:
            book_entry = dict(book_entry)
            book_entry["selective"] = False
            for key in secondary:
                content = "@@exclude_keys %s\n%s" % (key, content)
        elif logic == 3:
            book_entry = dict(book_entry)
            book_entry["selective"] = False
            for key in secondary:
                content = "@@additional_keys %s\n%s" % (key, content)
    if isinstance(extensions.get("delay"), int) and extensions.get("delay") > 0:
        content = "@@activate_only_after %d\n%s" % (extensions.get("delay"), content)
        extensions.pop("delay", None)
    if extensions.get("match_whole_words") is True:
        content = "@@match_full_word\n" + content
        extensions.pop("match_whole_words", None)
    if extensions.get("match_whole_words") is False:
        content = "@@match_partial_word\n" + content
        extensions.pop("match_whole_words", None)

    use_regex = bool(book_entry.get("use_regex"))
    if use_regex and not (keys and keys[0].startswith("/")):
        use_regex = False

    extensions["risu_case_sensitive"] = bool(book_entry.get("case_sensitive"))
    lore = {
        "key": ", ".join(keys),
        "secondkey": ", ".join(secondary) if book_entry.get("selective") else "",
        "insertorder": book_entry.get("insertion_order", 100),
        "comment": book_entry.get("name") or book_entry.get("comment") or "",
        "content": content,
        "mode": book_entry.get("mode") or "normal",
        "alwaysActive": bool(book_entry.get("constant")),
        "selective": bool(book_entry.get("selective")),
        "extentions": extensions,
        "useRegex": use_regex,
    }
    if book_entry.get("folder") is not None:
        lore["folder"] = book_entry.get("folder")
    activation = extensions.get("risu_activationPercent")
    if activation is not None:
        lore["activationPercent"] = activation
    cache = extensions.get("risu_loreCache")
    if cache:
        lore["loreCache"] = cache
    return lore


def lore_to_charbook(lore, existing_extensions=None):
    if not isinstance(lore, dict):
        raise CharxError("module lorebook entry is not an object")
    keys = [k.strip() for k in str(lore.get("key") or "").split(",")]
    secondkey = [k.strip() for k in str(lore.get("secondkey") or "").split(",")]
    source_ext = lore.get("extentions")
    extensions = copy.deepcopy(source_ext) if isinstance(source_ext, dict) else {}
    if not isinstance(source_ext, dict):
        extensions = copy.deepcopy(existing_extensions or {})
    case_sensitive = bool(extensions.get("risu_case_sensitive"))
    if lore.get("activationPercent") is not None:
        extensions["risu_activationPercent"] = lore.get("activationPercent")
    if lore.get("loreCache") is not None:
        extensions["risu_loreCache"] = lore.get("loreCache")
    entry = {
        "keys": keys,
        "content": lore.get("content") or "",
        "extensions": extensions,
        "enabled": True,
        "insertion_order": lore.get("insertorder", 100),
        "constant": bool(lore.get("alwaysActive")),
        "selective": bool(lore.get("selective")),
        "name": lore.get("comment") or "",
        "comment": lore.get("comment") or "",
        "case_sensitive": case_sensitive,
        "use_regex": bool(lore.get("useRegex")),
    }
    if entry["selective"]:
        entry["secondary_keys"] = secondkey
    entry["mode"] = lore.get("mode") or "normal"
    if lore.get("folder") is not None:
        entry["folder"] = lore.get("folder")
    return entry


def sync_module_book_to_card(card, module):
    """Rebuild card.character_book.entries from module.lorebook (PocketRisu export rule)."""
    module_obj = unwrap_module(module)
    if "lorebook" not in module_obj or not isinstance(module_obj.get("lorebook"), list):
        return 0
    data = card_data(card)
    book = data.get("character_book")
    if not isinstance(book, dict):
        book = {}
    book["entries"] = [lore_to_charbook(entry) for entry in module_obj["lorebook"]]
    data["character_book"] = book
    return len(book["entries"])


def sync_card_book_to_module(card, module):
    module_obj = unwrap_module(module)
    try:
        entries = card_data(card).get("character_book", {}).get("entries")
    except CharxError:
        entries = None
    if not isinstance(entries, list):
        raise CharxError("card.json has no character_book.entries to sync")
    module_obj["lorebook"] = [charbook_to_lore(entry) for entry in entries]
    return len(module_obj["lorebook"])


def _lore_signature(entry):
    keys = [k.strip() for k in str(entry.get("key") or "").split(",") if k.strip()]
    secondary = [k.strip() for k in str(entry.get("secondkey") or "").split(",") if k.strip()]
    extensions = entry.get("extentions") if isinstance(entry.get("extentions"), dict) else {}
    return (
        tuple(keys),
        tuple(secondary) if entry.get("selective") else (),
        entry.get("content") or "",
        entry.get("insertorder", 100),
        entry.get("comment") or "",
        entry.get("mode") or "normal",
        bool(entry.get("alwaysActive")),
        bool(entry.get("selective")),
        bool(entry.get("useRegex")),
        entry.get("folder"),
        bool(extensions.get("risu_case_sensitive")),
        entry.get("activationPercent"),
    )


def book_baseline(card, module):
    """Fingerprint both lorebook copies so pack can tell which side was edited."""
    module_obj = unwrap_module(module) if isinstance(module, dict) else None
    lore = module_obj.get("lorebook") if module_obj else None
    try:
        entries = card_data(card).get("character_book", {}).get("entries")
    except CharxError:
        entries = None
    def digest(value):
        if not isinstance(value, list):
            return None
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256_text(canonical)
    return {
        "module_lore_sha256": digest(lore),
        "card_book_sha256": digest(entries),
    }


def book_divergence(card, module):
    """Compare card.character_book against module.lorebook. Returns None or a report."""
    if not isinstance(module, dict):
        return None
    module_obj = unwrap_module(module)
    lore = module_obj.get("lorebook")
    if not isinstance(lore, list):
        return None
    try:
        entries = card_data(card).get("character_book", {}).get("entries")
    except CharxError:
        entries = None
    if not isinstance(entries, list):
        return {"card_count": 0, "module_count": len(lore), "first_mismatch": None,
                "reason": "card has no character_book.entries"}
    try:
        converted = [charbook_to_lore(entry) for entry in entries]
    except CharxError as exc:
        return {"card_count": len(entries), "module_count": len(lore),
                "first_mismatch": None, "reason": str(exc)}
    if len(converted) != len(lore):
        return {"card_count": len(converted), "module_count": len(lore),
                "first_mismatch": min(len(converted), len(lore)), "reason": "entry count differs"}
    for index, (left, right) in enumerate(zip(converted, lore)):
        if _lore_signature(left) != _lore_signature(right):
            return {"card_count": len(converted), "module_count": len(lore),
                    "first_mismatch": index, "reason": "entry content differs"}
    return None


# --------------------------------------------------------------------------
# work directory: unpack
# --------------------------------------------------------------------------

def _backup_dir(path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    candidate = "%s.old-%s" % (path.rstrip("\\/"), stamp)
    counter = 1
    while os.path.exists(candidate):
        candidate = "%s.old-%s-%d" % (path.rstrip("\\/"), stamp, counter)
        counter += 1
    os.rename(path, candidate)
    return candidate


def _write_work_readme(work, manifest):
    lines = []
    lines.append("# CharX work directory")
    lines.append("")
    lines.append("Source: `%s`" % manifest.get("source", ""))
    lines.append("Tool: %s %s" % (TOOL_NAME, TOOL_VERSION))
    lines.append("")
    lines.append("Source of truth:")
    lines.append("- `card.json` - Character Card JSON (pretty printed, edit freely).")
    if manifest.get("module_decoded"):
        lines.append("- `module.json` - decoded risuModule wrapper; packed back into `module.risum`.")
    else:
        lines.append("- `module.risum` is preserved as raw bytes (no decoded module.json).")
    lines.append("- `assets/**`, `x_meta/**` and any other entry are packed as-is.")
    lines.append("- `text/` (after `text export`) - long prose/code files for easy editing.")
    lines.append("- `_charx/` - tool bookkeeping; never packed.")
    lines.append("")
    lines.append("Do not keep unrelated files in this directory: every file outside")
    lines.append("`_charx/` and `text/` is packed into the .charx.")
    write_bytes(os.path.join(work, "_charx", "README.md"),
                ("\n".join(lines) + "\n").encode("utf-8"))


def unpack(charx_path, work_dir, force=False, quiet=False):
    archive = CharxArchive(charx_path)
    work = os.path.abspath(work_dir)
    if os.path.exists(work) and os.listdir(work):
        if not force:
            raise CharxError(
                "Work directory is not empty: %s\nUse a new directory or pass --force "
                "(the existing directory is renamed, not deleted)." % work
            )
        backup = _backup_dir(work)
        if not quiet:
            print("Existing work directory moved to: %s" % backup)
    if not os.path.exists(work):
        os.makedirs(work)

    used_local = set()
    entries = []
    warnings = []
    card_raw = None
    module_raw = None
    chara_raw = None
    card_entry_name = None

    for info in archive.infos:
        name = info.filename
        if name.endswith("/"):
            entries.append({
                "name": name,
                "role": "dir",
                "local": None,
                "packable": False,
                "size": info.file_size,
                "sha256": None,
            })
            continue
        if not is_safe_entry_name(name):
            warnings.append("Unsafe entry name skipped: %r" % name)
            continue
        data = archive.read(name)
        role = "other"
        if name == "card.json":
            role = "card"
            card_raw = data
            card_entry_name = name
        elif name == "module.risum":
            role = "module"
            module_raw = data
        elif name == "chara":
            role = "card-v2"
            chara_raw = data
            card_entry_name = name
        elif name.startswith("chara-ext-asset_"):
            role = "v2-asset"
        elif name.startswith("assets/"):
            role = "asset"
        elif name.startswith("x_meta/"):
            role = "meta"

        record = {
            "name": name,
            "role": role,
            "size": len(data),
            "sha256": sha256_bytes(data),
            "compress_type": info.compress_type,
            "date_time": list(info.date_time),
        }

        if role == "card":
            local = "_charx/original/card.json"
            write_bytes(os_path(work, local), data)
            record["local"] = local
            record["packable"] = False
        elif role == "module":
            local = "_charx/original/module.risum"
            write_bytes(os_path(work, local), data)
            record["local"] = local
            record["packable"] = False
        elif role == "card-v2":
            local = "_charx/original/chara"
            write_bytes(os_path(work, local), data)
            record["local"] = local
            record["packable"] = False
        elif role == "v2-asset":
            decoded = base64.b64decode(data, validate=False)
            local = local_path_for("legacy_assets/" + safe_component(name), used_local)
            write_bytes(os_path(work, local), decoded)
            record["local"] = local
            record["packable"] = True
            record["encoding"] = "base64"
            record["decoded_size"] = len(decoded)
        else:
            local = work_local_for_entry(name, used_local)
            write_bytes(os_path(work, local), data)
            record["local"] = local
            record["packable"] = True
        entries.append(record)

    # card.json / chara -> card.json
    layout = "unknown"
    card = None
    if card_raw is not None:
        layout = "v3"
        card = load_json_bytes(card_raw, "card.json")
        write_json(os.path.join(work, "card.json"), card, indent=4)
    elif chara_raw is not None:
        layout = "v2"
        try:
            decoded = base64.b64decode(re.sub(rb"\s+", b"", chara_raw), validate=False)
        except (binascii.Error, ValueError) as exc:
            raise CharxError("Cannot decode legacy chara entry: %s" % exc)
        card = load_json_bytes(decoded, "chara")
        write_json(os.path.join(work, "card.json"), card, indent=4)
        write_bytes(os.path.join(work, "_charx", "original", "chara"), chara_raw)
    else:
        raise CharxError("No card.json (or legacy chara entry) found in %s" % charx_path)

    # module.risum -> module.json + module assets
    module_decoded = False
    module_assets = []
    module_error = None
    if module_raw is not None:
        try:
            decoded_module = decode_module(module_raw)
            wrapper = decoded_module["wrapper"]
            blocks = decoded_module["assets"]
            meta = unwrap_module(wrapper).get("assets")
            if meta is None:
                meta = []
                unwrap_module(wrapper)["assets"] = meta
            if not isinstance(meta, list):
                raise CharxError("module.assets is not a list")
            if len(meta) != len(blocks):
                raise CharxError(
                    "module.assets has %d entries but module.risum has %d asset blocks"
                    % (len(meta), len(blocks))
                )
            os.makedirs(os.path.join(work, "_charx", "module_assets"), exist_ok=True)
            for index, blob in enumerate(blocks):
                item = meta[index]
                if not isinstance(item, list) or len(item) < 3:
                    raise CharxError("module.assets[%d] is not [name, uri, ext]" % index)
                name = str(item[0] or ("asset_%d" % index))
                ext = str(item[2] or "bin")
                filename = "%04d_%s.%s" % (index, safe_component(name), safe_component(ext))
                local = "_charx/module_assets/" + filename
                write_bytes(os_path(work, local), blob)
                origin_uri = item[1]
                if origin_uri:
                    item[1] = MODULE_ASSET_SCHEME + str(index)
                module_assets.append({
                    "index": index,
                    "local": local,
                    "name": name,
                    "ext": ext,
                    "original_uri": origin_uri,
                })
            write_json(os.path.join(work, "module.json"), wrapper, indent=2)
            module_decoded = True
            if decoded_module["trailing"]:
                warnings.append("module.risum has %d trailing bytes after the end marker"
                                % decoded_module["trailing"])
        except CharxError as exc:
            module_error = str(exc)
            warnings.append("module.risum could not be decoded: %s" % exc)
            write_bytes(os.path.join(work, "_charx", "module-decode-error.txt"),
                        (str(exc) + "\n").encode("utf-8"))

    prefix_file = None
    if archive.prefix:
        prefix_file = "_charx/jpeg_prefix.bin"
        write_bytes(os_path(work, prefix_file), archive.prefix)

    manifest = {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "manifest_version": MANIFEST_VERSION,
        "source": archive.path,
        "source_size": archive.raw_size,
        "source_sha256": sha256_bytes(archive.raw),
        "archive_kind": "jpeg+zip" if archive.prefix else "zip",
        "prefix_file": prefix_file,
        "prefix_size": len(archive.prefix),
        "layout": layout,
        "card_entry": card_entry_name,
        "card_spec": card.get("spec") if isinstance(card, dict) else None,
        "card_sha256": canonical_json_sha256(card),
        "module_entry": "module.risum" if module_raw is not None else None,
        "module_decoded": module_decoded,
        "module_sha256": canonical_json_sha256(wrapper) if module_decoded else None,
        "module_error": module_error,
        "prefix_sha256": sha256_bytes(archive.prefix),
        "entries_sha256": entries_fingerprint(entries),
        "module_assets": module_assets,
        "baseline_books": book_baseline(card, decoded_module.get("wrapper") if module_decoded else None),
        "entries": entries,
        "warnings": warnings,
        "created_at": int(time.time()),
    }
    write_json(os.path.join(work, "_charx", "manifest.json"), manifest, indent=2)
    _write_work_readme(work, manifest)
    archive.close()
    return manifest


def load_manifest(work):
    path = os.path.join(work, "_charx", "manifest.json")
    if not os.path.isfile(path):
        raise CharxError("Not a charx-workbench directory (missing _charx/manifest.json): %s" % work)
    manifest = load_json_file(path)
    if manifest.get("tool") != TOOL_NAME:
        raise CharxError("Unknown manifest in %s" % work)
    return manifest


def save_manifest(work, manifest):
    write_json(os.path.join(work, "_charx", "manifest.json"), manifest, indent=2)


def load_work(work):
    manifest = load_manifest(work)
    card_path = os.path.join(work, "card.json")
    if not os.path.isfile(card_path):
        raise CharxError("Missing card.json in work directory: %s" % work)
    card = load_json_file(card_path)
    module = None
    module_path = os.path.join(work, "module.json")
    if os.path.isfile(module_path):
        module = load_json_file(module_path)
    return manifest, card, module


def save_card(work, card):
    write_json(os.path.join(work, "card.json"), card, indent=4)


def save_module(work, module):
    write_json(os.path.join(work, "module.json"), module, indent=2)


# --------------------------------------------------------------------------
# pack
# --------------------------------------------------------------------------

def _manifest_by_local(manifest):
    lookup = {}
    for index, entry in enumerate(manifest.get("entries") or []):
        local = entry.get("local")
        if local:
            lookup[local.lower()] = (index, entry)
    return lookup


def _manifest_entry_by_name(manifest, name):
    for record in manifest.get("entries") or []:
        if record.get("name") == name:
            return record
    return None


def entries_fingerprint(entries):
    """Hash of entry names and payload hashes, ignoring card/module copies."""
    lines = []
    for record in entries or []:
        if record.get("role") in ("dir", "card", "module", "card-v2"):
            continue
        lines.append("%s\x00%s" % (record.get("name"), record.get("sha256")))
    lines.sort()
    return sha256_text("\n".join(lines))


def work_matches_source(work, manifest, card, module, prefix, items, missing):
    """True when packing would reproduce the unpacked archive byte-for-byte."""
    if missing:
        return False
    source = manifest.get("source") or ""
    recorded_source = manifest.get("source_sha256")
    if not source or not recorded_source or not os.path.isfile(source):
        return False
    if sha256_file(source) != recorded_source:
        return False
    if manifest.get("card_sha256") != canonical_json_sha256(card):
        return False
    if module is not None:
        if manifest.get("module_sha256") != canonical_json_sha256(module):
            return False
    else:
        record = _manifest_entry_by_name(manifest, "module.risum")
        if record is not None:
            raw_path = os_path(work, record.get("local") or "")
            if not record.get("local") or not os.path.isfile(raw_path):
                return False
            if sha256_file(raw_path) != record.get("sha256"):
                return False
    if sha256_bytes(prefix) != manifest.get("prefix_sha256"):
        return False
    if manifest.get("entries_sha256") != entries_fingerprint(manifest.get("entries")):
        return False
    packable = [
        record for record in manifest.get("entries") or []
        if record.get("packable") is not False
        and record.get("role") not in ("dir", "card", "module", "card-v2")
        and record.get("name") and record.get("local")
        and not record.get("name").endswith("/")
    ]
    if len([item for item in items if item.get("role") not in ("card", "module")]) != len(packable):
        return False
    for record in packable:
        data = read_bytes(os_path(work, record["local"]))
        if record.get("encoding") == "base64":
            data = base64.b64encode(data)
        if sha256_bytes(data) != record.get("sha256"):
            return False
    return True


def manifest_missing_files(work, manifest=None):
    """Packable manifest entries whose local file no longer exists."""
    manifest = manifest or load_manifest(work)
    missing = []
    for record in manifest.get("entries") or []:
        if record.get("packable") is False:
            continue
        if record.get("role") in ("dir", "card", "module", "card-v2"):
            continue
        local = record.get("local")
        if local and not os.path.isfile(os_path(work, local)):
            missing.append({"name": record.get("name"), "local": local,
                            "role": record.get("role")})
    return missing


def collect_pack_entries(work, manifest=None):
    """Return [{entry, local, role, size, ...}] for everything that should be zipped.

    Manifest records are packed first, so original entries survive even when
    their local copy lives under `_charx/` (hidden names, `text/`, `*.tmp`, ...).
    Files created outside the manifest are appended as new entries.
    """
    manifest = manifest or load_manifest(work)
    found = []
    covered = set()
    for order, record in enumerate(manifest.get("entries") or []):
        if record.get("packable") is False:
            continue
        if record.get("role") in ("dir", "card", "module", "card-v2"):
            continue
        entry_name = record.get("name")
        local = record.get("local")
        if not entry_name or not local or entry_name.endswith("/"):
            continue
        if not is_safe_entry_name(entry_name):
            raise CharxError("Unsafe entry name would be packed: %r" % entry_name)
        full = os_path(work, local)
        if not os.path.isfile(full):
            continue  # manifest_missing_files() reports these
        found.append({
            "entry": entry_name,
            "local": local,
            "role": record.get("role", "other"),
            "size": os.path.getsize(full),
            "encoding": record.get("encoding"),
            "compress_type": record.get("compress_type"),
            "date_time": record.get("date_time"),
            "sort_key": (0, order),
        })
        covered.add(local.lower())

    for root, dirs, files in os.walk(work):
        rel_root = os.path.relpath(root, work).replace("\\", "/")
        if rel_root == ".":
            rel_root = ""
        if rel_root == "":
            dirs[:] = [d for d in dirs if d not in RESERVED_TOP_DIRS]
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for filename in files:
            rel = (rel_root + "/" + filename) if rel_root else filename
            if rel.lower() in covered:
                continue
            if rel in RESERVED_TOP_FILES:
                continue
            if rel.startswith("_charx/") or rel.startswith("text/"):
                continue
            if rel.startswith(".") or rel.endswith(".tmp") or rel.endswith(".charx"):
                continue
            local = rel
            full = os_path(work, local)
            if not os.path.isfile(full):
                continue
            if local.startswith("legacy_assets/"):
                raise CharxError(
                    "legacy_assets file has no manifest mapping: %s" % local
                )
            entry_name = local
            if not is_safe_entry_name(entry_name):
                raise CharxError("Unsafe entry name would be packed: %r" % entry_name)
            found.append({
                "entry": entry_name,
                "local": local,
                "role": "other",
                "size": os.path.getsize(full),
                "encoding": None,
                "compress_type": None,
                "date_time": None,
                "sort_key": (1, natural_key(local)),
            })
    found.sort(key=lambda item: item["sort_key"])

    seen = set()
    for item in found:
        if item["entry"] in seen:
            raise CharxError("Duplicate zip entry would be packed: %s" % item["entry"])
        seen.add(item["entry"])
    return found


def _module_asset_blobs(work, module, manifest):
    module_obj = unwrap_module(module)
    meta = module_obj.get("assets") or []
    if not isinstance(meta, list):
        raise CharxError("module.assets must be a list")
    mapping = {}
    for item in manifest.get("module_assets") or []:
        mapping[int(item["index"])] = item
    blobs = []
    for index, entry in enumerate(meta):
        if not isinstance(entry, list) or len(entry) < 2:
            raise CharxError("module.assets[%d] is not [name, uri, ext]" % index)
        uri = entry[1] or ""
        path = None
        if uri.startswith(MODULE_ASSET_SCHEME):
            try:
                source_index = int(uri[len(MODULE_ASSET_SCHEME):])
            except ValueError:
                raise CharxError("module.assets[%d] has a bad module-asset URI: %r" % (index, uri))
            source = mapping.get(source_index)
            if not source:
                raise CharxError("module asset %d has no file mapping" % source_index)
            path = os_path(work, source["local"])
        elif uri == "":
            source = mapping.get(index)
            if source:
                path = os_path(work, source["local"])
        elif uri.startswith(EMBEDED_PREFIX):
            rel = norm_entry_name(uri[len(EMBEDED_PREFIX):])
            if not is_safe_entry_name(rel):
                raise CharxError("module.assets[%d] uses an unsafe path: %r" % (index, uri))
            path = os_path(work, rel)
        elif uri.startswith("data:"):
            raise CharxError("module.assets[%d] uses a data: URI; store it as a file instead" % index)
        else:
            candidate = uri
            if os.path.isabs(candidate):
                path = candidate
            else:
                candidate = norm_entry_name(candidate)
                if not is_safe_entry_name(candidate):
                    raise CharxError("module.assets[%d] uses an unsafe path: %r" % (index, uri))
                path = os_path(work, candidate)
        if not path or not os.path.isfile(path):
            raise CharxError(
                "Cannot resolve bytes for module.assets[%d] (name=%r, uri=%r)"
                % (index, entry[0] if entry else None, uri)
            )
        blobs.append(read_bytes(path))
    return blobs


def _should_store(entry_name, size):
    ext = os.path.splitext(entry_name)[1].lower().lstrip(".")
    if ext in STORED_EXTS:
        return True
    return size > 4 * 1024 * 1024 and ext not in ("json", "txt", "md", "html", "js", "risum")


def card_output_name(card, module, manifest):
    """Sanitized output stem taken from the card name, then its lorebook/module."""
    try:
        data = card_data(card)
    except CharxError:
        data = {}
    book = data.get("character_book")
    module_name = None
    if isinstance(module, dict):
        try:
            module_name = unwrap_module(module).get("name")
        except CharxError:
            module_name = None
    candidates = [
        data.get("name"),
        book.get("name") if isinstance(book, dict) else None,
        module_name,
        os.path.splitext(os.path.basename(manifest.get("source") or ""))[0],
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return clean_filename(value, fallback="card", max_len=80)
    return "card"


def serialized_card_entry(layout, card):
    """Return the virtual (entry name, payload) that pack writes for the card."""
    if layout == "v2":
        compact = json.dumps(card, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return "chara", base64.b64encode(compact)
    return "card.json", json.dumps(card, ensure_ascii=False, indent=4).encode("utf-8")


def pack(work, out_path=None, force=False, sync_book="auto", touch_date=False,
         prefix_mode="keep", jpeg_prefix=None, compression_level=6):
    manifest, card, module = load_work(work)
    if out_path is None or os.path.isdir(str(out_path)) or str(out_path).endswith(("/", "\\")):
        filename = card_output_name(card, module, manifest) + ".charx"
        out_path = filename if out_path is None else os.path.join(str(out_path), filename)
    out_abs = os.path.abspath(out_path)
    if not out_abs.lower().endswith(".charx"):
        out_abs += ".charx"
    source = manifest.get("source") or ""
    if source and os.path.isfile(source):
        if os.path.normcase(os.path.realpath(source)) == os.path.normcase(os.path.realpath(out_abs)):
            raise CharxError("Refusing to overwrite the source archive: %s" % out_abs)
    if os.path.dirname(out_abs) and not os.path.isdir(os.path.dirname(out_abs)):
        os.makedirs(os.path.dirname(out_abs))

    sync_report = None
    if module is not None and sync_book != "off":
        direction = sync_book
        note = None
        if direction == "auto":
            base = manifest.get("baseline_books") or {}
            base_module = base.get("module_lore_sha256")
            base_card = base.get("card_book_sha256")
            current = book_baseline(card, module)
            module_changed = base_module is not None and current["module_lore_sha256"] != base_module
            card_changed = base_card is not None and current["card_book_sha256"] != base_card
            if module_changed and card_changed:
                direction = "module-to-card"
                note = "both lorebook copies changed; module.lorebook wins on PocketRisu import"
            elif module_changed:
                direction = "module-to-card"
            elif card_changed:
                direction = "card-to-module"
            else:
                direction = "off"
        if direction == "module-to-card":
            divergence = book_divergence(card, module)
            count = sync_module_book_to_card(card, module)
            sync_report = {"direction": direction, "entries": count, "was_divergent": bool(divergence)}
            if note or divergence:
                print("NOTE: rebuilt card.character_book from module.lorebook (%d entries)%s"
                      % (count, "; " + note if note else ""))
        elif direction == "card-to-module":
            count = sync_card_book_to_module(card, module)
            sync_report = {"direction": direction, "entries": count, "was_divergent": None}
            print("NOTE: rebuilt module.lorebook from card.character_book (%d entries)" % count)
        elif direction == "off":
            sync_report = {"direction": "off", "entries": 0, "was_divergent": None}
        else:
            raise CharxError("Unknown --sync-book value: %s" % direction)

    if touch_date:
        try:
            card_data(card)["modification_date"] = int(time.time())
        except CharxError:
            pass

    module_bytes = None
    module_entry = None
    module_record = _manifest_entry_by_name(manifest, "module.risum")
    if module is not None:
        module_bytes = encode_module(module, _module_asset_blobs(work, module, manifest))
        module_entry = "module.risum"
    else:
        raw_module = os.path.join(work, "_charx", "original", "module.risum")
        if os.path.isfile(raw_module):
            module_bytes = read_bytes(raw_module)
            module_entry = "module.risum"

    prefix = b""
    if prefix_mode == "keep":
        prefix_file = manifest.get("prefix_file")
        if prefix_file and os.path.isfile(os_path(work, prefix_file)):
            prefix = read_bytes(os_path(work, prefix_file))
    elif prefix_mode == "none":
        prefix = b""
    elif prefix_mode == "file":
        if not jpeg_prefix or not os.path.isfile(jpeg_prefix):
            raise CharxError("--jpeg-prefix file not found: %s" % jpeg_prefix)
        prefix = read_bytes(jpeg_prefix)
    else:
        raise CharxError("Unknown prefix mode: %s" % prefix_mode)

    items = collect_pack_entries(work, manifest)
    missing = manifest_missing_files(work, manifest)
    if module_entry:
        items.append({
            "entry": module_entry,
            "local": os.path.join(work, "_charx", "original", "module.risum"),
            "role": "module",
            "size": len(module_bytes),
            "bytes": module_bytes,
            "encoding": None,
            "compress_type": module_record.get("compress_type") if module_record else None,
            "date_time": module_record.get("date_time") if module_record else None,
            "sort_key": (2, 0),
        })

    layout = manifest.get("layout", "v3")
    virtual = {}
    card_record = _manifest_entry_by_name(manifest, "chara" if layout == "v2" else "card.json")
    card_entry, card_bytes = serialized_card_entry(layout, card)
    virtual[card_entry] = card_bytes
    virtual["_sort"] = (3, 0)

    # Build the exact bundle that will be written, then validate it.
    pending = []
    for order, item in enumerate(items):
        data = item.get("bytes")
        size = item.get("size")
        if data is not None:
            size = len(data)
        elif item.get("role") == "v2-asset" and size is not None:
            size = 4 * ((size + 2) // 3)
        pending.append({
            "entry": item["entry"],
            "local": item.get("local"),
            "role": item.get("role", "other"),
            "data": data,
            "encoding": item.get("encoding"),
            "size": size,
            "date_time": item.get("date_time"),
            "compress_type": item.get("compress_type"),
            "order": order,
        })
    for name, data in virtual.items():
        if name.startswith("_"):
            continue
        pending.append({"entry": name, "local": None, "role": "card", "data": data,
                        "encoding": None, "size": len(data),
                        "date_time": card_record.get("date_time") if card_record else None,
                        "compress_type": card_record.get("compress_type") if card_record else None,
                        "order": len(pending)})
    pending.sort(key=lambda item: (
        3 if item["role"] == "card" else (2 if item["role"] == "module" else 0),
        item["order"],
    ))

    bundle = bundle_from_pending(pending, prefix, card, module, work)
    issues = validate_bundle(bundle)
    for item in missing:
        issues.append(issue("error", "ENTRY_E_MISSING",
                            "manifest entry %r has no local file: %s"
                            % (item["name"], item["local"]), item["name"]))
    errors = [item for item in issues if item["level"] == "error"]
    if errors and not force:
        summary = "\n".join("  [%s] %s" % (item["code"], item["message"]) for item in errors[:20])
        raise CharxError("Validation failed (%d errors), not writing:\n%s" % (len(errors), summary))

    copied_source = False
    if (prefix_mode == "keep" and not touch_date and compression_level == 6
            and (sync_report is None or sync_report.get("direction") == "off")
            and work_matches_source(work, manifest, card, module, prefix, items, missing)):
        tmp_path = out_abs + ".tmp"
        shutil.copyfile(source, tmp_path)
        os.replace(tmp_path, out_abs)
        copied_source = True
    else:
        _write_zip_with_data(out_abs, prefix, pending, compression_level, work)
    return {
        "output": out_abs,
        "entries": len(pending),
        "prefix_size": len(prefix),
        "sync_book": sync_report,
        "copied_source": copied_source,
        "validation": issues,
    }


def _write_zip_with_data(out_path, prefix, items, compression_level, work=None):
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "wb") as handle:
        if prefix:
            handle.write(prefix)
        zf = zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED, allowZip64=True)
        try:
            for item in items:
                info = zipfile.ZipInfo(item["entry"], date_time=item.get("date_time") or time.localtime()[:6])
                info.external_attr = (0o600 & 0xFFFF) << 16
                compress_type = item.get("compress_type")
                if compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    if _should_store(item["entry"], item.get("size") or 0):
                        compress_type = zipfile.ZIP_STORED
                    else:
                        compress_type = zipfile.ZIP_DEFLATED
                info.compress_type = compress_type
                data = item.get("data")
                if data is None:
                    if not item.get("local") or work is None:
                        raise CharxError("No bytes available for entry %s" % item["entry"])
                    data = read_bytes(os_path(work, item["local"]))
                    if item.get("encoding") == "base64":
                        data = base64.b64encode(data)
                try:
                    zf.writestr(info, data, compresslevel=compression_level)
                except TypeError:
                    zf.writestr(info, data)
        finally:
            zf.close()
    os.replace(tmp_path, out_path)


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

class Bundle(object):
    def __init__(self):
        self.names = []
        self.name_set = set()
        self.sizes = {}
        self.card = None
        self.card_error = None
        self.module = None
        self.module_error = None
        self.module_raw_present = False
        self.module_asset_count = 0
        self.prefix = b""
        self.layout = "v3"
        self._read = None
        self._head = None
        self.source = ""

    def read(self, name):
        return self._read(name)

    def head(self, name, count=32):
        return self._head(name, count)


def bundle_from_archive(path, archive=None):
    archive = archive or CharxArchive(path)
    bundle = Bundle()
    bundle.source = archive.path
    bundle.names = [n for n in archive.names if not n.endswith("/")]
    bundle.name_set = set(bundle.names)
    for info in archive.infos:
        bundle.sizes[info.filename] = info.file_size
    bundle.prefix = archive.prefix
    bundle._read = archive.read
    bundle._head = archive.head
    if "card.json" in bundle.name_set:
        try:
            bundle.card = load_json_bytes(archive.read("card.json"), "card.json")
            bundle.layout = "v3"
        except CharxError as exc:
            bundle.card_error = str(exc)
    elif "chara" in bundle.name_set:
        try:
            raw = archive.read("chara")
            decoded = base64.b64decode(re.sub(rb"\s+", b"", raw), validate=False)
            bundle.card = load_json_bytes(decoded, "chara")
            bundle.layout = "v2"
        except (CharxError, binascii.Error, ValueError) as exc:
            bundle.card_error = str(exc)
    else:
        bundle.card_error = "no card.json or chara entry"
    if "module.risum" in bundle.name_set:
        bundle.module_raw_present = True
        try:
            decoded = decode_module(archive.read("module.risum"))
            bundle.module = decoded["wrapper"]
            bundle.module_asset_count = len(decoded["assets"])
        except CharxError as exc:
            bundle.module_error = str(exc)
    bundle._archive = archive
    return bundle


def bundle_from_work(work, manifest=None, card=None, module=None):
    if manifest is None or card is None:
        manifest, card, module = load_work(work)
    bundle = Bundle()
    bundle.source = os.path.abspath(work)
    bundle.card = card
    bundle.module = module
    bundle.layout = manifest.get("layout", "v3")
    prefix_file = manifest.get("prefix_file")
    if prefix_file and os.path.isfile(os_path(work, prefix_file)):
        bundle.prefix = read_bytes(os_path(work, prefix_file))
    entries = collect_pack_entries(work, manifest)
    bundle.missing_files = manifest_missing_files(work, manifest)
    if module is not None:
        module_obj = unwrap_module(module)
        assets = module_obj.get("assets") or []
        bundle.module_asset_count = len(assets) if isinstance(assets, list) else 0
        entries = entries + [{"entry": "module.risum", "local": "_charx/module.risum", "role": "module", "size": 0}]
    else:
        raw_module = os.path.join(work, "_charx", "original", "module.risum")
        if os.path.isfile(raw_module):
            bundle.module_raw_present = True
            entries = entries + [{"entry": "module.risum", "local": "_charx/original/module.risum",
                                  "role": "module", "size": os.path.getsize(raw_module)}]
    if bundle.layout == "v2":
        entries = entries + [{"entry": "chara", "local": "_charx/generated-chara", "role": "card", "size": 0}]
    else:
        entries = entries + [{"entry": "card.json", "local": "card.json", "role": "card",
                              "size": os.path.getsize(os.path.join(work, "card.json"))}]
    bundle.names = [item["entry"] for item in entries if not item["entry"].endswith("/")]
    bundle.name_set = set(bundle.names)
    local_by_entry = {item["entry"]: item["local"] for item in entries}
    encoding_by_entry = {item["entry"]: item.get("encoding") for item in entries}
    bundle.sizes = {item["entry"]: item["size"] for item in entries}

    def _read(name):
        if name in ("card.json", "chara"):
            return read_bytes(os.path.join(work, "card.json"))
        if name == "module.risum" and module is not None:
            return encode_module(module, _module_asset_blobs(work, module, manifest))
        local = local_by_entry.get(name)
        if local is None:
            raise CharxError("No local file for entry %s" % name)
        return read_bytes(os_path(work, local))

    def _head(name, count=32):
        if name in ("card.json", "chara"):
            with open(os.path.join(work, "card.json"), "rb") as handle:
                return handle.read(count)
        if name == "module.risum":
            return _read(name)[:count]
        local = local_by_entry.get(name)
        if local is None:
            raise CharxError("No local file for entry %s" % name)
        path = os_path(work, local)
        if encoding_by_entry.get(name) == "base64":
            with open(path, "rb") as handle:
                data = handle.read(((count + 3) // 4) * 3)
            return base64.b64encode(data)[:count]
        with open(path, "rb") as handle:
            return handle.read(count)

    bundle._read = _read
    bundle._head = _head
    bundle._manifest = manifest
    return bundle


def bundle_from_pending(pending, prefix, card, module, work=None):
    bundle = Bundle()
    bundle.source = "<pack>"
    bundle.prefix = prefix
    bundle.card = card
    bundle.module = module
    by_name = {}
    for item in pending:
        by_name[item["entry"]] = item
        bundle.sizes[item["entry"]] = item.get("size")
    bundle.names = list(by_name.keys())
    bundle.name_set = set(bundle.names)
    bundle.layout = "v2" if ("chara" in bundle.name_set and "card.json" not in bundle.name_set) else "v3"
    bundle.module_raw_present = "module.risum" in bundle.name_set
    if module is not None:
        assets = unwrap_module(module).get("assets") or []
        bundle.module_asset_count = len(assets) if isinstance(assets, list) else 0

    def _load(item):
        data = item.get("data")
        if data is not None:
            return data
        if not item.get("local") or work is None:
            raise CharxError("No bytes available for entry %s" % item["entry"])
        data = read_bytes(os_path(work, item["local"]))
        if item.get("encoding") == "base64":
            data = base64.b64encode(data)
        return data

    def _read(name):
        return _load(by_name[name])

    def _head(name, count=32):
        item = by_name[name]
        if item.get("data") is None and item.get("encoding") != "base64":
            if item.get("local") and work is not None:
                with open(os_path(work, item["local"]), "rb") as handle:
                    return handle.read(count)
        return _load(item)[:count]

    bundle._read = _read
    bundle._head = _head
    return bundle


def _expected_meta_names(asset_names):
    expected = {}
    for path in asset_names:
        base = os.path.splitext(path)[0]
        meta = "x_meta/" + base.split("/")[-1] + ".json"
        expected[meta.lower()] = path
    return expected


def _resolve_card_asset_uri(uri, bundle):
    """Return (kind, resolved_entry_or_None, note)."""
    if not isinstance(uri, str):
        return ("bad", None, "uri is not a string")
    if uri.startswith(EMBEDED_PREFIX):
        path = norm_entry_name(uri[len(EMBEDED_PREFIX):])
        return ("embeded", path, None)
    if uri.startswith("ccdefault:"):
        return ("ccdefault", None, None)
    if uri.startswith("data:"):
        return ("data", None, None)
    if uri.startswith("__asset:"):
        index = uri[len("__asset:"):]
        return ("v2", "chara-ext-asset_:" + index, None)
    if uri.startswith("http://") or uri.startswith("https://"):
        return ("external", None, "external URL is skipped by PocketRisu import")
    if uri == "":
        return ("empty", None, "empty uri")
    return ("other", None, "unknown uri scheme")


def validate_bundle(bundle, deep=False):
    issues = []
    names = bundle.names
    name_set = bundle.name_set

    if len(names) != len(name_set):
        seen = set()
        for name in names:
            if name in seen:
                issues.append(issue("error", "ZIP_E_DUP", "duplicate zip entry: %s" % name, name))
            seen.add(name)
    for name in names:
        if not is_safe_entry_name(name):
            issues.append(issue("error", "ZIP_E_UNSAFE", "unsafe zip entry path: %r" % name, name))
    for item in getattr(bundle, "missing_files", None) or []:
        issues.append(issue("error", "ENTRY_E_MISSING",
                            "manifest entry %r has no local file: %s"
                            % (item["name"], item["local"]), item["name"]))
    if deep:
        for name in names:
            try:
                bundle.read(name)
            except Exception as exc:
                issues.append(issue("error", "ZIP_E_READ",
                                    "cannot read entry %s: %s" % (name, exc), name))

    if bundle.layout == "v2":
        issues.append(issue("info", "LAYOUT_V2",
                            "legacy v2 layout (chara/base64 entries); supported but PocketRisu imports it as v2"))
    if bundle.prefix:
        issues.append(issue("info", "PREFIX_JPEG",
                            "archive has a %d-byte JPEG prefix (charxJpeg)" % len(bundle.prefix)))

    # ---- card ----
    card = bundle.card
    if card is None:
        issues.append(issue("error", "CARD_E_MISSING", "card.json is missing or unreadable: %s"
                            % (bundle.card_error or "unknown")))
        return issues
    spec = card.get("spec") if isinstance(card, dict) else None
    if spec not in ("chara_card_v3", "chara_card_v2"):
        issues.append(issue("error", "CARD_E_SPEC", "unsupported or missing card spec: %r" % spec))
    elif spec == "chara_card_v2":
        issues.append(issue("warn", "CARD_W_SPEC2", "card spec is chara_card_v2; v3 is expected for .charx"))
    try:
        data = card_data(card)
    except CharxError as exc:
        issues.append(issue("error", "CARD_E_DATA", str(exc)))
        return issues
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        issues.append(issue("warn", "CARD_W_NAME", "data.name is empty"))
    for field in ("name", "description", "personality", "scenario", "first_mes", "mes_example",
                  "creator_notes", "system_prompt", "post_history_instructions", "creator",
                  "character_version", "nickname"):
        if field in data and not isinstance(data[field], str):
            issues.append(issue("warn", "CARD_W_TYPE", "data.%s should be a string" % field, field))
    if not isinstance(data.get("alternate_greetings", []), list):
        issues.append(issue("warn", "CARD_W_TYPE", "data.alternate_greetings should be a list"))
    book = data.get("character_book")
    if book is not None and not isinstance(book, dict):
        issues.append(issue("warn", "CARD_W_TYPE", "data.character_book should be an object"))
    ext = data.get("extensions")
    if ext is not None and not isinstance(ext, dict):
        issues.append(issue("warn", "CARD_W_TYPE", "data.extensions should be an object"))
    risu = (ext or {}).get("risuai") if isinstance(ext, dict) else None
    if risu is not None and not isinstance(risu, dict):
        issues.append(issue("warn", "CARD_W_TYPE", "data.extensions.risuai should be an object"))
    if isinstance(risu, dict):
        if "vits" in risu and not isinstance(risu["vits"], dict):
            issues.append(issue("warn", "CARD_W_TYPE", "extensions.risuai.vits should be an object"))
        if "sdData" in risu and not isinstance(risu["sdData"], list):
            issues.append(issue("warn", "CARD_W_TYPE", "extensions.risuai.sdData should be a list"))
        if "backgroundHTML" in risu and not isinstance(risu["backgroundHTML"], str):
            issues.append(issue("warn", "CARD_W_TYPE", "extensions.risuai.backgroundHTML should be a string"))
        if "triggerscript" in risu and bundle.module is not None:
            issues.append(issue("warn", "CARD_W_IGNORED_TRIGGERS",
                                "extensions.risuai.triggerscript in card.json is ignored because "
                                "module.risum supplies triggers on import"))
        if "customScripts" in risu and bundle.module is not None:
            issues.append(issue("warn", "CARD_W_IGNORED_REGEX",
                                "extensions.risuai.customScripts in card.json is ignored because "
                                "module.risum supplies regex on import"))

    # ---- module ----
    module = bundle.module
    if bundle.module_raw_present and module is None:
        issues.append(issue("error", "MOD_E_DECODE", "module.risum cannot be decoded: %s"
                            % (bundle.module_error or "unknown")))
    if isinstance(module, dict):
        try:
            module_obj = unwrap_module(module)
        except CharxError as exc:
            issues.append(issue("error", "MOD_E_SHAPE", str(exc)))
            module_obj = None
        if isinstance(module_obj, dict):
            if not isinstance(module_obj.get("name"), str):
                issues.append(issue("warn", "MOD_W_NAME", "module.name should be a string"))
            if not isinstance(module_obj.get("id"), str):
                issues.append(issue("warn", "MOD_W_ID", "module.id should be a string"))
            lore = module_obj.get("lorebook")
            if lore is not None and not isinstance(lore, list):
                issues.append(issue("error", "MOD_E_LORE", "module.lorebook should be a list"))
            elif isinstance(lore, list):
                for index, entry in enumerate(lore):
                    if not isinstance(entry, dict):
                        issues.append(issue("error", "MOD_E_LORE", "module.lorebook[%d] is not an object" % index))
                        continue
                    if not isinstance(entry.get("key", ""), str):
                        issues.append(issue("error", "MOD_E_LORE", "module.lorebook[%d].key must be a string" % index))
                    if not isinstance(entry.get("content", ""), str):
                        issues.append(issue("error", "MOD_E_LORE", "module.lorebook[%d].content must be a string" % index))
                    if entry.get("mode", "normal") not in LORE_MODES:
                        issues.append(issue("warn", "MOD_W_LORE",
                                            "module.lorebook[%d].mode is unknown: %r"
                                            % (index, entry.get("mode"))))
                    for flag in ("alwaysActive", "selective", "useRegex"):
                        if flag in entry and not isinstance(entry[flag], bool):
                            issues.append(issue("warn", "MOD_W_LORE",
                                                "module.lorebook[%d].%s should be a boolean" % (index, flag)))
                    order = entry.get("insertorder")
                    if order is not None and (not isinstance(order, int) or isinstance(order, bool)):
                        issues.append(issue("warn", "MOD_W_LORE",
                                            "module.lorebook[%d].insertorder should be an integer" % index))
            regex = module_obj.get("regex")
            if regex is not None and not isinstance(regex, list):
                issues.append(issue("error", "MOD_E_REGEX", "module.regex should be a list"))
            elif isinstance(regex, list):
                for index, entry in enumerate(regex):
                    if not isinstance(entry, dict):
                        issues.append(issue("error", "MOD_E_REGEX", "module.regex[%d] is not an object" % index))
                        continue
                    for field in ("comment", "in", "out", "type"):
                        if field in entry and not isinstance(entry[field], str):
                            issues.append(issue("warn", "MOD_W_REGEX",
                                                "module.regex[%d].%s should be a string" % (index, field)))
                    rtype = entry.get("type", "")
                    if rtype not in REGEX_TYPES:
                        issues.append(issue("warn", "MOD_W_REGEX",
                                            "module.regex[%d].type is unknown: %r" % (index, rtype)))
            trigger = module_obj.get("trigger")
            if trigger is not None and not isinstance(trigger, list):
                issues.append(issue("error", "MOD_E_TRIGGER", "module.trigger should be a list"))
            elif isinstance(trigger, list):
                for index, entry in enumerate(trigger):
                    if not isinstance(entry, dict):
                        issues.append(issue("error", "MOD_E_TRIGGER", "module.trigger[%d] is not an object" % index))
                        continue
                    if entry.get("type") not in TRIGGER_TYPES:
                        issues.append(issue("warn", "MOD_W_TRIGGER",
                                            "module.trigger[%d].type is unknown: %r"
                                            % (index, entry.get("type"))))
                    if not isinstance(entry.get("conditions", []), list):
                        issues.append(issue("warn", "MOD_W_TRIGGER",
                                            "module.trigger[%d].conditions should be a list" % index))
                    if not isinstance(entry.get("effect", []), list):
                        issues.append(issue("warn", "MOD_W_TRIGGER",
                                            "module.trigger[%d].effect should be a list" % index))
                    elif not entry.get("effect"):
                        issues.append(issue("warn", "MOD_W_TRIGGER",
                                            "module.trigger[%d].effect is empty" % index))
            module_assets = module_obj.get("assets") or []
            if not isinstance(module_assets, list):
                issues.append(issue("error", "MOD_E_ASSETS", "module.assets should be a list"))
            elif bundle.module_asset_count and len(module_assets) != bundle.module_asset_count:
                issues.append(issue("error", "MOD_E_ASSET_COUNT",
                                    "module.assets has %d entries but module.risum has %d blocks"
                                    % (len(module_assets), bundle.module_asset_count)))
            if module_obj.get("lowLevelAccess"):
                issues.append(issue("info", "MOD_INFO_LOWLEVEL",
                                    "module requests lowLevelAccess (PocketRisu asks the user on import)"))

            # card book vs module lorebook
            divergence = book_divergence(card, module)
            if divergence:
                issues.append(issue("warn", "BOOK_W_DIVERGENT",
                                    "card.character_book and module.lorebook differ (%s; card=%d, module=%d, "
                                    "first mismatch index=%s); PocketRisu import uses module.lorebook"
                                    % (divergence.get("reason"), divergence.get("card_count"),
                                       divergence.get("module_count"), divergence.get("first_mismatch"))))

    # ---- assets ----
    assets = card_asset_entries(card)
    resolved_assets = []
    referenced_names = set()
    asset_names = []
    main_icon = False
    for index, entry in enumerate(assets):
        label = "data.assets[%d]" % index
        if not isinstance(entry, dict):
            issues.append(issue("error", "ASSET_E_SHAPE", "%s is not an object" % label))
            continue
        for field in ("type", "uri", "name", "ext"):
            if not isinstance(entry.get(field), str):
                issues.append(issue("warn", "ASSET_W_SHAPE", "%s.%s should be a string" % (label, field)))
        asset_type = entry.get("type") or ""
        asset_name = entry.get("name") or ""
        ext = (entry.get("ext") or "").lower()
        uri = entry.get("uri") or ""
        if asset_type == "icon" and asset_name == "main":
            main_icon = True
        if asset_name:
            asset_names.append(asset_name)
        kind, target, note = _resolve_card_asset_uri(uri, bundle)
        if kind == "embeded":
            resolved_assets.append(target)
            referenced_names.add(target)
            if target not in name_set:
                issues.append(issue("error", "ASSET_E_MISSING",
                                    "%s points to missing entry: %s" % (label, target), target))
            else:
                size = bundle.sizes.get(target, 0)
                if size > MAX_ASSET_BYTES:
                    issues.append(issue("error", "ASSET_E_TOO_LARGE",
                                        "%s is %s; PocketRisu skips assets over 50 MB"
                                        % (target, format_size(size)), target))
                if ext in IMAGE_EXTS:
                    head = bundle.head(target, 32)
                    actual = detect_image_type(head)
                    expected = {"jpg": "JPEG", "jpeg": "JPEG"}.get(ext, ext.upper())
                    if actual != "Unknown" and actual != expected:
                        issues.append(issue("warn", "ASSET_W_EXT_MISMATCH",
                                            "%s has extension .%s but bytes look like %s"
                                            % (target, ext, actual), target))
        elif kind == "v2":
            referenced_names.add(target)
            if target not in name_set:
                issues.append(issue("error", "ASSET_E_V2_MISSING",
                                    "%s points to missing legacy entry: %s" % (label, target), target))
        elif kind == "data":
            b64 = uri.split(",", 1)[1] if "," in uri else ""
            if len(b64) > MAX_ASSET_BYTES * 4 / 3:
                issues.append(issue("warn", "ASSET_W_DATA_URI",
                                    "%s data URI is larger than the 50 MB import limit" % label))
            elif b64[:4] and not re.match(r"^[A-Za-z0-9+/=\s]+$", b64[:200]):
                issues.append(issue("warn", "ASSET_W_DATA_URI", "%s has an invalid base64 data URI" % label))
        elif kind == "external":
            issues.append(issue("warn", "ASSET_W_EXTERNAL",
                                "%s uses an external URL; PocketRisu import drops it: %s"
                                % (label, uri[:80])))
        elif kind == "ccdefault":
            pass
        else:
            issues.append(issue("warn", "ASSET_W_URI",
                                "%s has an unresolved uri (%s): %r" % (label, kind, uri[:80])))
        if note:
            issues.append(issue("warn", "ASSET_W_NOTE", "%s: %s" % (label, note)))

    if not main_icon and not bundle.prefix:
        issues.append(issue("warn", "ASSET_W_MAIN_ICON",
                            "no icon/main asset and no JPEG prefix; the imported card may have no portrait"))

    duplicates = {}
    for target in resolved_assets:
        duplicates[target] = duplicates.get(target, 0) + 1
    for target, count in duplicates.items():
        if count > 1:
            issues.append(issue("warn", "ASSET_W_DUP_REF",
                                "%d card assets point to the same file: %s" % (count, target), target))
    name_counts = {}
    for asset_name in asset_names:
        name_counts[asset_name] = name_counts.get(asset_name, 0) + 1
    for asset_name, count in name_counts.items():
        if count > 1:
            issues.append(issue("warn", "ASSET_W_DUP_NAME",
                                "%d assets share the name %r" % (count, asset_name)))

    # x_meta alignment
    lower_names = set(name.lower() for name in names)
    expected_meta = _expected_meta_names(set(resolved_assets))
    for meta_name, asset_path in expected_meta.items():
        if meta_name not in lower_names:
            issues.append(issue("warn", "ASSET_W_NO_META",
                                "asset has no x_meta record: %s" % asset_path, asset_path))
    for name in names:
        if name.startswith("x_meta/") and name.lower() not in expected_meta:
            if name.endswith(".json"):
                issues.append(issue("warn", "ASSET_W_ORPHAN_META",
                                    "x_meta record has no matching asset: %s" % name, name))
        if name.startswith("x_meta/") and name.endswith(".json"):
            try:
                meta_doc = load_json_bytes(bundle.read(name), name)
                if not isinstance(meta_doc, dict):
                    issues.append(issue("warn", "ASSET_W_META_SHAPE", "%s is not a JSON object" % name, name))
            except CharxError as exc:
                issues.append(issue("warn", "ASSET_W_META_JSON", str(exc), name))

    # unreferenced asset files
    for name in names:
        if name.startswith("assets/") and name not in referenced_names:
            issues.append(issue("warn", "ASSET_W_ORPHAN",
                                "asset file is not referenced by card.data.assets: %s" % name, name))

    # v2 __asset references anywhere in the card
    if bundle.layout == "v2":
        for pointer, value in iter_strings(card):
            if value.startswith("__asset:"):
                entry = "chara-ext-asset_:" + value[len("__asset:"):]
                if entry not in name_set:
                    issues.append(issue("error", "ASSET_E_V2_MISSING",
                                        "v2 reference at %s points to missing entry %s" % (pointer, entry), entry))

    return issues


# --------------------------------------------------------------------------
# JSON pointer helpers
# --------------------------------------------------------------------------

def pointer_parts(pointer):
    if pointer in ("", "/"):
        return []
    if pointer.startswith("/"):
        raw = pointer[1:].split("/")
    else:
        raw = re.split(r"[./]", pointer)
    return [p.replace("~1", "/").replace("~0", "~") for p in raw if p != ""]


def get_pointer(doc, pointer):
    current = doc
    for part in pointer_parts(pointer):
        if isinstance(current, dict):
            if part not in current:
                raise CharxError("JSON pointer not found: %s (missing key %r)" % (pointer, part))
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                raise CharxError("JSON pointer needs an integer list index: %s" % pointer)
            if index < 0 or index >= len(current):
                raise CharxError("JSON pointer list index out of range: %s" % pointer)
            current = current[index]
        else:
            raise CharxError("JSON pointer traverses a scalar: %s" % pointer)
    return current


def set_pointer(doc, pointer, value):
    parts = pointer_parts(pointer)
    if not parts:
        raise CharxError("Cannot replace the document root")
    current = doc
    for part in parts[:-1]:
        if isinstance(current, dict):
            if part not in current:
                current[part] = {}
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                raise CharxError("JSON pointer list index out of range: %s" % pointer)
        else:
            raise CharxError("JSON pointer traverses a scalar: %s" % pointer)
    last = parts[-1]
    if isinstance(current, dict):
        current[last] = value
    elif isinstance(current, list):
        if last == "-":
            current.append(value)
        else:
            try:
                current[int(last)] = value
            except ValueError:
                raise CharxError("JSON pointer needs an integer list index: %s" % pointer)
            except IndexError:
                raise CharxError("JSON pointer list index out of range: %s" % pointer)
    else:
        raise CharxError("JSON pointer parent is a scalar: %s" % pointer)


def delete_pointer(doc, pointer):
    parts = pointer_parts(pointer)
    if not parts:
        raise CharxError("Cannot delete the document root")
    parent = doc
    for part in parts[:-1]:
        if isinstance(parent, dict):
            if part not in parent:
                raise CharxError("JSON pointer not found: %s (missing key %r)" % (pointer, part))
            parent = parent[part]
        elif isinstance(parent, list):
            try:
                parent = parent[int(part)]
            except ValueError:
                raise CharxError("JSON pointer needs an integer list index: %s" % pointer)
            except IndexError:
                raise CharxError("JSON pointer list index out of range: %s" % pointer)
        else:
            raise CharxError("JSON pointer traverses a scalar: %s" % pointer)
    last = parts[-1]
    if isinstance(parent, dict):
        if last not in parent:
            raise CharxError("JSON pointer not found: %s" % pointer)
        del parent[last]
    elif isinstance(parent, list):
        try:
            del parent[int(last)]
        except (ValueError, IndexError):
            raise CharxError("JSON pointer list index out of range: %s" % pointer)
    else:
        raise CharxError("JSON pointer parent is a scalar: %s" % pointer)


# --------------------------------------------------------------------------
# text export / import
# --------------------------------------------------------------------------

def _lore_label(entry, name_field):
    value = entry.get(name_field)
    if isinstance(value, str) and value.strip():
        return value
    keys = entry.get("keys")
    if not isinstance(keys, list):
        keys = str(entry.get("key") or "").split(",")
    for key in keys:
        if isinstance(key, str) and key.strip():
            return key.strip()
    return "lore"


def _lore_folder_id(entry):
    """Folder entries carry their id in `key` (module) or `keys[0]` (card)."""
    key = entry.get("key")
    if isinstance(key, str) and key.strip():
        return key.strip()
    keys = entry.get("keys")
    if isinstance(keys, list):
        for item in keys:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None


def _lore_folder_ref(entry):
    folder = entry.get("folder")
    if isinstance(folder, str):
        folder = folder.strip()
        if folder:
            return folder
    return None


def _lore_folders(lore):
    """Return ({id: folder entry}, order, {id: parent id or None}) with cycles cut."""
    folders = {}
    order = []
    for entry in lore:
        if not isinstance(entry, dict) or (entry.get("mode") or "normal") != "folder":
            continue
        folder_id = _lore_folder_id(entry)
        if folder_id is None or folder_id in folders:
            continue
        folders[folder_id] = entry
        order.append(folder_id)

    parent = {}
    for folder_id in order:
        raw = _lore_folder_ref(folders[folder_id])
        parent[folder_id] = raw if raw in folders and raw != folder_id else None

    resolved = set()
    for start in order:
        if start in resolved:
            continue
        chain = []
        seen = {}
        node = start
        while node is not None and node not in resolved and node not in seen:
            seen[node] = len(chain)
            chain.append(node)
            node = parent.get(node)
        if node is not None and node in seen:
            parent[chain[-1]] = None
        resolved.update(chain)
    return folders, order, parent


def _lore_folder_name(entry):
    for field in ("comment", "name"):
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _lore_folder_paths(lore):
    """Map each folder id to its exported directory segments (PocketRisu folders)."""
    folders, order, parent = _lore_folders(lore)

    children = {}
    for folder_id in order:
        children.setdefault(parent.get(folder_id), []).append(folder_id)

    segments = {}
    used_by_parent = {None: set()}
    stack = [(None, iter(children.get(None, ())))]
    while stack:
        parent_id, iterator = stack[-1]
        try:
            folder_id = next(iterator)
        except StopIteration:
            stack.pop()
            continue
        entry = folders[folder_id]
        segments[folder_id] = unique_filename(
            clean_filename(_lore_folder_name(entry), fallback="folder"),
            used_by_parent.setdefault(parent_id, set()), "")
        used_by_parent.setdefault(folder_id, set())
        stack.append((folder_id, iter(children.get(folder_id, ()))))

    paths = {}
    for folder_id in order:
        chain = []
        node = folder_id
        while node is not None and node not in paths:
            chain.append(node)
            node = parent.get(node)
        base = paths[node] if node is not None else ()
        for item in reversed(chain):
            base = base + (segments[item],)
            paths[item] = base
        if len(paths[folder_id]) > MAX_LORE_FOLDER_DEPTH:
            raise CharxError(
                "Lorebook folder nesting is deeper than %d levels; export aborted"
                % MAX_LORE_FOLDER_DEPTH)
    return paths


def _lore_folder_display_paths(lore):
    """Map each folder id to its display-name path, root first."""
    folders, order, parent = _lore_folders(lore)
    names = {folder_id: _lore_folder_name(folders[folder_id]) or "folder"
             for folder_id in order}
    paths = {}
    for folder_id in order:
        chain = []
        node = folder_id
        while node is not None and node not in paths:
            chain.append(node)
            node = parent.get(node)
        base = paths[node] if node is not None else ()
        for item in reversed(chain):
            base = base + (names[item],)
            paths[item] = base
        if len(paths[folder_id]) > MAX_LORE_FOLDER_DEPTH:
            raise CharxError(
                "Lorebook folder nesting is deeper than %d levels"
                % MAX_LORE_FOLDER_DEPTH)
    return paths


def _resolve_lore_folder(lore, target):
    """Resolve a folder id, display name or 'A/B' path to a folder id."""
    needle = str(target or "").strip()
    if not needle:
        return None
    folders, order, _parent = _lore_folders(lore)
    if needle in folders:
        return needle
    lowered = needle.replace("\\", "/").strip("/").lower()
    if not lowered:
        return None
    display = _lore_folder_display_paths(lore)
    exported = _lore_folder_paths(lore)
    for paths in (display, exported):
        exact = [folder_id for folder_id in order
                 if "/".join(paths.get(folder_id, ())).lower() == lowered]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise CharxError("Lorebook folder path is ambiguous: %s" % target)
    named = [folder_id for folder_id in order
             if (display.get(folder_id) or ("",))[-1].lower() == lowered]
    if len(named) == 1:
        return named[0]
    if len(named) > 1:
        raise CharxError("Lorebook folder name is ambiguous: %s" % target)
    raise CharxError("Unknown lorebook folder: %s" % target)


def _lore_folder_dir_names(folder_paths):
    """Directory names per parent path, so lore files never shadow a folder."""
    names = {}
    for path in folder_paths.values():
        for depth, segment in enumerate(path):
            names.setdefault(path[:depth], set()).add(segment.lower())
    return names


def _text_targets(card, module, include_empty=False):
    targets = []

    def add(rel_file, target, pointer, label=""):
        targets.append({"file": rel_file, "target": target, "pointer": pointer, "label": label})

    data = card_data(card)
    for field, ext in CARD_TEXT_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and (include_empty or value != ""):
            add("card/%s.%s" % (field, ext), "card", "/data/" + field, field)
    greetings = data.get("alternate_greetings")
    if isinstance(greetings, list):
        for index, value in enumerate(greetings):
            if isinstance(value, str) and (include_empty or value != ""):
                add("card/alternate_greetings/%03d.md" % index, "card",
                    "/data/alternate_greetings/%d" % index, "alt greeting %d" % index)
    extensions = data.get("extensions")
    risu = extensions.get("risuai") if isinstance(extensions, dict) else None
    if isinstance(risu, dict):
        for field, ext in RISU_TEXT_FIELDS:
            value = risu.get(field)
            if isinstance(value, str) and (include_empty or value != ""):
                add("card/extensions/%s.%s" % (field, ext), "card",
                    "/data/extensions/risuai/" + field, field)
    depth = extensions.get("depth_prompt") if isinstance(extensions, dict) else None
    if isinstance(depth, dict) and isinstance(depth.get("prompt"), str) and (include_empty or depth.get("prompt")):
        add("card/extensions/depth_prompt.prompt.md", "card",
            "/data/extensions/depth_prompt/prompt", "depth prompt")

    source, lore = effective_lore(card, module)
    if source in ("module", "card"):
        if source == "module":
            base_dir = "module/lorebook"
            pointer_base = "/module/lorebook/%d/content"
            name_field = "comment"
        else:
            base_dir = "card/character_book"
            pointer_base = "/data/character_book/entries/%d/content"
            name_field = "name"
        folder_paths = _lore_folder_paths(lore)
        folder_names = _lore_folder_dir_names(folder_paths)
        lore_files = {}
        for index, entry in enumerate(lore):
            if not isinstance(entry, dict):
                continue
            if (entry.get("mode") or "normal") == "folder":
                continue
            content = entry.get("content")
            if not isinstance(content, str) or not (include_empty or content != ""):
                continue
            name = _lore_label(entry, name_field)
            dirs = folder_paths.get(_lore_folder_ref(entry), ())
            used = lore_files.setdefault(dirs, set(folder_names.get(dirs, ())))
            filename = "%s/%s" % (
                "/".join((base_dir,) + dirs),
                unique_filename(clean_filename(name), used, ".md"))
            add(filename, source, pointer_base % index,
                "lore: %s" % "/".join(dirs + (name,)))

    if isinstance(module, dict):
        module_obj = unwrap_module(module)
        for field, ext in MODULE_TEXT_FIELDS:
            value = module_obj.get(field)
            if isinstance(value, str) and (include_empty or value != ""):
                add("module/%s.%s" % (field, ext), "module", "/module/" + field, field)
        regex = module_obj.get("regex")
        regex_files = set()
        if isinstance(regex, list):
            for index, entry in enumerate(regex):
                if not isinstance(entry, dict):
                    continue
                fields = [field for field in ("in", "out")
                          if isinstance(entry.get(field), str)
                          and (include_empty or entry.get(field) != "")]
                if not fields:
                    continue
                comment = entry.get("comment")
                base = unique_filename(
                    clean_filename(comment, fallback="regex"), regex_files, "")
                for field in fields:
                    add("module/regex/%s.%s.txt" % (base, field), "module",
                        "/module/regex/%d/%s" % (index, field),
                        "regex %d: %s" % (index, comment or ""))
    return targets


def _prune_empty_dirs(root):
    for current, _dirs, _files in os.walk(root, topdown=False):
        if os.path.abspath(current) == os.path.abspath(root):
            continue
        try:
            os.rmdir(current)
        except OSError:
            pass


def text_export(work, force=False, include_empty=False):
    manifest, card, module = load_work(work)
    text_dir = os.path.join(work, "text")
    map_path = os.path.join(text_dir, "_map.json")
    if os.path.isdir(text_dir) and not force:
        existing = []
        for root, _dirs, files in os.walk(text_dir):
            for filename in files:
                if filename != "_map.json":
                    existing.append(filename)
        if existing and not os.path.isfile(map_path):
            raise CharxError(
                "text/ already exists with %d file(s) but has no _map.json; "
                "pass --force to replace it" % len(existing)
            )
    if os.path.isdir(text_dir) and os.path.isfile(map_path) and not force:
        old = load_json_file(map_path)
        changed = []
        for item in old.get("files") or []:
            path = os.path.join(text_dir, item["file"].replace("/", os.sep))
            if not os.path.isfile(path):
                changed.append(item["file"] + " (missing)")
                continue
            current = read_bytes(path)
            if sha256_bytes(current) != item.get("sha256"):
                changed.append(item["file"])
        if changed:
            raise CharxError(
                "text/ has files edited since the last export (%d). Use --force to "
                "overwrite them, or run `text import` first. First: %s"
                % (len(changed), ", ".join(changed[:5]))
            )
    targets = _text_targets(card, module, include_empty=include_empty)
    if not os.path.isdir(text_dir):
        os.makedirs(text_dir)
    if os.path.isfile(map_path):
        try:
            old_map = load_json_file(map_path)
        except CharxError:
            old_map = {}
        for item in old_map.get("files") or []:
            rel = item.get("file") or ""
            if not rel:
                continue
            old_path = os.path.join(text_dir, rel.replace("/", os.sep))
            if os.path.isfile(old_path):
                os.remove(old_path)
    records = []
    for item in targets:
        doc = card if item["target"] == "card" else module
        if doc is None:
            continue
        try:
            value = get_pointer(doc, item["pointer"])
        except CharxError:
            continue
        if not isinstance(value, str):
            continue
        rel = item["file"]
        full = os.path.join(text_dir, rel.replace("/", os.sep))
        write_bytes(full, value.encode("utf-8"))
        records.append({
            "file": rel,
            "target": item["target"],
            "pointer": item["pointer"],
            "label": item["label"],
            "sha256": sha256_text(value),
            "len": len(value),
        })
    _prune_empty_dirs(text_dir)
    known = set(item["file"] for item in records)
    unmapped = []
    for root, _dirs, files in os.walk(text_dir):
        for filename in files:
            rel = os.path.relpath(os.path.join(root, filename), text_dir).replace(os.sep, "/")
            if rel != "_map.json" and rel not in known:
                unmapped.append(rel)
    mapping = {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "exported_at": int(time.time()),
        "files": records,
        "unmapped": sorted(unmapped),
    }
    write_json(map_path, mapping, indent=2)
    return mapping


def text_import(work, force=False, keep_crlf=False):
    _, card, module = load_work(work)
    text_dir = os.path.join(work, "text")
    map_path = os.path.join(text_dir, "_map.json")
    if not os.path.isfile(map_path):
        raise CharxError("No text/_map.json; run `text export` first: %s" % text_dir)
    mapping = load_json_file(map_path)
    docs = {"card": card, "module": module}
    applied = []
    unchanged = []
    conflicts = []
    missing = []
    known = set()
    for item in mapping.get("files") or []:
        rel = item.get("file")
        known.add(rel)
        target = item.get("target")
        doc = docs.get(target)
        if doc is None:
            conflicts.append({"file": rel, "reason": "target %s is not present" % target})
            continue
        full = os.path.join(text_dir, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            missing.append(rel)
            continue
        try:
            text = decode_text_bytes(read_bytes(full), rel)
        except CharxError as exc:
            conflicts.append({"file": rel, "reason": str(exc)})
            continue
        if not keep_crlf:
            text = text.replace("\r\n", "\n")
        file_hash = sha256_text(text)
        if file_hash == item.get("sha256"):
            unchanged.append(rel)
            continue
        try:
            current = get_pointer(doc, item.get("pointer"))
        except CharxError as exc:
            conflicts.append({"file": rel, "reason": str(exc)})
            continue
        if not isinstance(current, str):
            conflicts.append({"file": rel, "reason": "target is no longer a string"})
            continue
        if sha256_text(current) != item.get("sha256") and not force:
            conflicts.append({
                "file": rel,
                "reason": "JSON value changed since export and the text file also changed",
            })
            continue
        try:
            set_pointer(doc, item.get("pointer"), text)
        except CharxError as exc:
            conflicts.append({"file": rel, "reason": str(exc)})
            continue
        item["sha256"] = file_hash
        item["len"] = len(text)
        applied.append(rel)

    if applied:
        save_card(work, card)
        if module is not None:
            save_module(work, module)
        mapping["exported_at"] = int(time.time())
        write_json(map_path, mapping, indent=2)

    extra = []
    for root, _dirs, files in os.walk(text_dir):
        rel_root = os.path.relpath(root, text_dir).replace("\\", "/")
        for filename in files:
            rel = filename if rel_root == "." else rel_root + "/" + filename
            if rel == "_map.json" or rel in known or filename == "_map.json":
                continue
            extra.append(rel)
    return {
        "applied": applied,
        "unchanged": unchanged,
        "conflicts": conflicts,
        "missing": missing,
        "unmapped_files": extra,
    }


# --------------------------------------------------------------------------
# asset operations
# --------------------------------------------------------------------------

def find_asset(card, manifest, work, target):
    """Resolve #index, name, asset path or URI to a description dict."""
    data = card_data(card)
    assets = data.get("assets")
    if not isinstance(assets, list):
        assets = []
    if target.startswith("#"):
        try:
            index = int(target[1:])
        except ValueError:
            raise CharxError("Asset index must be #<number>")
        if index < 0 or index >= len(assets):
            raise CharxError("Asset index out of range: %s" % target)
        entry = assets[index]
        return _asset_desc(card, manifest, work, index, entry)
    for index, entry in enumerate(assets):
        if isinstance(entry, dict) and entry.get("name") == target:
            return _asset_desc(card, manifest, work, index, entry)
    needle = target.replace("\\", "/")
    if needle.startswith(EMBEDED_PREFIX):
        needle = needle[len(EMBEDED_PREFIX):]
    for index, entry in enumerate(assets):
        if not isinstance(entry, dict):
            continue
        uri = (entry.get("uri") or "")
        if uri.startswith(EMBEDED_PREFIX) and uri[len(EMBEDED_PREFIX):] == needle:
            return _asset_desc(card, manifest, work, index, entry)
    # direct file / entry path
    lookup = _manifest_by_local(manifest)
    for record in manifest.get("entries") or []:
        if record.get("name") == needle or (record.get("local") or "").lower() == needle.lower():
            return {
                "index": None,
                "entry": record["name"],
                "local": record.get("local"),
                "name": os.path.splitext(os.path.basename(record["name"]))[0],
                "type": None,
                "ext": os.path.splitext(record["name"])[1].lstrip("."),
                "uri": None,
                "card_entry": None,
            }
    if is_safe_entry_name(needle) and os.path.isfile(os_path(work, needle)):
        return {
            "index": None,
            "entry": needle,
            "local": needle,
            "name": os.path.splitext(os.path.basename(needle))[0],
            "type": None,
            "ext": os.path.splitext(needle)[1].lstrip("."),
            "uri": None,
            "card_entry": None,
        }
    raise CharxError("Asset not found: %s" % target)


def _asset_desc(card, manifest, work, index, entry):
    uri = entry.get("uri") or ""
    if not uri.startswith(EMBEDED_PREFIX):
        raise CharxError(
            "data.assets[%d] does not use embeded:// (%r); replace its bytes manually"
            % (index, uri[:80])
        )
    path = norm_entry_name(uri[len(EMBEDED_PREFIX):])
    if not is_safe_entry_name(path):
        raise CharxError("Asset URI escapes the work directory: %s" % uri)
    lookup = _manifest_by_local(manifest)
    local = None
    record = lookup.get(path.lower())
    if record:
        local = record[1].get("local")
    if local is None and os.path.isfile(os_path(work, path)):
        local = path
    if local is None:
        raise CharxError("Asset file is missing from work directory: %s" % path)
    return {
        "index": index,
        "entry": path,
        "local": local,
        "name": entry.get("name") or "",
        "type": entry.get("type") or "",
        "ext": (entry.get("ext") or "").lower(),
        "uri": uri,
        "card_entry": entry,
    }


def _meta_record_for_entry(manifest, entry_name):
    base = os.path.splitext(entry_name)[0].split("/")[-1]
    candidate = ("x_meta/" + base + ".json").lower()
    for record in manifest.get("entries") or []:
        if (record.get("name") or "").lower() == candidate:
            return record
    return None


def _meta_for_entry(manifest, work, entry_name):
    record = _meta_record_for_entry(manifest, entry_name)
    if record:
        local = record.get("local")
        if local and os.path.isfile(os_path(work, local)):
            return local
    base = os.path.splitext(entry_name)[0].split("/")[-1]
    candidate = "x_meta/" + base + ".json"
    if os.path.isfile(os_path(work, candidate)):
        return candidate
    return None


def _write_meta(work, manifest, entry_name, data, meta_override=None):
    if meta_override:
        meta_doc = load_json_file(meta_override)
        if not isinstance(meta_doc, dict):
            raise CharxError("Metadata override must be a JSON object")
    else:
        meta_doc = {}
        existing_local = _meta_for_entry(manifest, work, entry_name)
        if existing_local:
            try:
                existing = load_json_file(os_path(work, existing_local))
                if isinstance(existing, dict):
                    meta_doc = existing
            except CharxError:
                meta_doc = {}
        image_type = detect_image_type(data)
        meta_doc["type"] = image_type
        if image_type == "PNG":
            chunks = png_text_chunks(data)
            if chunks:
                meta_doc = chunks
    base = os.path.splitext(entry_name)[0].split("/")[-1]
    meta_entry = "x_meta/" + base + ".json"
    record = _meta_record_for_entry(manifest, entry_name)
    if record:
        local = record.get("local")
    else:
        used = set(_manifest_by_local(manifest).keys())
        local = local_path_for(meta_entry, used)
        manifest.setdefault("entries", []).append({
            "name": meta_entry,
            "role": "meta",
            "local": local,
            "packable": True,
            "size": 0,
            "sha256": None,
        })
    write_json(os_path(work, local), meta_doc, indent=2)
    for item in manifest.get("entries") or []:
        if item.get("local") == local:
            item["size"] = os.path.getsize(os_path(work, local))
            item["sha256"] = sha256_bytes(read_bytes(os_path(work, local)))
    return meta_entry, meta_doc


def asset_replace(work, target, source_file, meta_override=None):
    manifest, card, _module = load_work(work)
    desc = find_asset(card, manifest, work, target)
    data = read_bytes(source_file)
    if not data:
        raise CharxError("Replacement file is empty: %s" % source_file)
    write_bytes(os_path(work, desc["local"]), data)
    if desc["entry"].startswith("chara-ext-asset_") and not meta_override:
        meta_entry = None
        meta_doc = None
    else:
        meta_entry, meta_doc = _write_meta(work, manifest, desc["entry"], data, meta_override)
    entry_ext = (desc.get("ext") or os.path.splitext(desc["entry"])[1].lstrip(".")).lower()
    actual_ext = detect_ext(data[:64])
    warning = None
    if actual_ext and entry_ext and actual_ext != entry_ext:
        warning = ("asset path ends in .%s but replacement bytes look like .%s; "
                   "the path is kept so references stay valid" % (entry_ext, actual_ext))
    save_card(work, card)
    save_manifest(work, manifest)
    return {
        "entry": desc["entry"],
        "local": desc["local"],
        "card_index": desc.get("index"),
        "meta_entry": meta_entry,
        "meta": meta_doc,
        "warning": warning,
        "bytes": len(data),
    }


def asset_add(work, source_file, name=None, asset_type="x-risu-asset", ext=None,
              add_entry=True, meta_override=None):
    manifest, card, _module = load_work(work)
    data = read_bytes(source_file)
    if not data:
        raise CharxError("Asset file is empty: %s" % source_file)
    if not name:
        name = os.path.splitext(os.path.basename(source_file))[0]
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip()
    if not name:
        raise CharxError("Asset name is empty after sanitizing")
    if ext:
        ext = ext.lower().lstrip(".")
    else:
        ext = detect_ext(data[:64]) or "unknown"
    if ext == "unknown":
        ext = "unknown"
    entry_name = asset_path_for(asset_type, name, ext)
    used_entries = set((record.get("name") or "").lower() for record in manifest.get("entries") or [])
    used_locals = set(_manifest_by_local(manifest).keys())
    candidate = entry_name
    counter = 1
    while candidate.lower() in used_entries or os.path.isfile(os_path(work, candidate)):
        candidate = asset_path_for(asset_type, "%s_%d" % (name, counter), ext)
        counter += 1
    entry_name = candidate
    local = local_path_for(entry_name, used_locals)
    write_bytes(os_path(work, local), data)
    manifest.setdefault("entries", []).append({
        "name": entry_name,
        "role": "asset",
        "local": local,
        "packable": True,
        "size": len(data),
        "sha256": sha256_bytes(data),
        "added": True,
    })
    meta_entry, meta_doc = _write_meta(work, manifest, entry_name, data, meta_override)
    result = {
        "entry": entry_name,
        "local": local,
        "name": name,
        "type": asset_type,
        "ext": ext,
        "meta_entry": meta_entry,
        "meta": meta_doc,
        "bytes": len(data),
        "card_index": None,
        "warning": None if ext != "unknown" else
                   "unknown image/file type; PocketRisu stores it as .png metadata type Unknown",
    }
    if add_entry:
        data_doc = card_data(card)
        assets = data_doc.get("assets")
        if not isinstance(assets, list):
            assets = []
            data_doc["assets"] = assets
        assets.append({
            "type": asset_type,
            "uri": EMBEDED_PREFIX + entry_name,
            "name": name,
            "ext": ext,
        })
        result["card_index"] = len(assets) - 1
        save_card(work, card)
    save_manifest(work, manifest)
    return result


def asset_remove(work, target, yes=False, keep_file=False):
    if not yes:
        raise CharxError("Refusing to remove an asset without --yes")
    manifest, card, module = load_work(work)
    desc = find_asset(card, manifest, work, target)
    data_doc = card_data(card)
    assets = data_doc.get("assets")
    removed_entry = None
    if isinstance(assets, list) and desc.get("index") is not None:
        removed_entry = assets.pop(desc["index"])
    refs = []
    if desc.get("entry"):
        refs = asset_references(card, module, desc["entry"])
    stamp = time.strftime("%Y%m%d-%H%M%S")
    moved = []
    to_move = [desc.get("local")]
    meta_local = _meta_for_entry(manifest, work, desc["entry"]) if desc.get("entry") else None
    if meta_local:
        to_move.append(meta_local)
    if not keep_file:
        for local in to_move:
            if not local:
                continue
            src = os_path(work, local)
            if os.path.isfile(src):
                dst = os_path(work, "_charx/removed/%s/%s" % (stamp, local))
                write_bytes(dst, read_bytes(src))
                os.remove(src)
                moved.append(local)
                manifest["entries"] = [e for e in manifest.get("entries") or []
                                       if (e.get("local") or "").lower() != local.lower()]
    save_card(work, card)
    save_manifest(work, manifest)
    return {
        "removed": removed_entry,
        "entry": desc.get("entry"),
        "moved": moved,
        "references": refs,
        "file_kept": bool(keep_file),
    }


def asset_list(work):
    manifest, card, module = load_work(work)
    result = []
    for index, entry in enumerate(card_asset_entries(card)):
        if not isinstance(entry, dict):
            continue
        uri = entry.get("uri") or ""
        path = uri[len(EMBEDED_PREFIX):] if uri.startswith(EMBEDED_PREFIX) else None
        local = None
        size = None
        if path:
            record = _manifest_by_local(manifest).get(path.lower())
            if record:
                local = record[1].get("local")
                if local:
                    full = os_path(work, local)
                    if os.path.isfile(full):
                        size = os.path.getsize(full)
        refs = asset_references(card, module, path) if path else []
        meta_local = _meta_for_entry(manifest, work, path) if path else None
        result.append({
            "index": index,
            "type": entry.get("type"),
            "name": entry.get("name"),
            "ext": entry.get("ext"),
            "entry": path,
            "local": local,
            "size": size,
            "uri_kind": "embeded" if path else uri.split(":", 1)[0],
            "x_meta": meta_local,
            "refs": len(refs),
        })
    return result


def asset_gc(work, move=False, yes=False):
    manifest, card, module = load_work(work)
    referenced = set()
    for entry in card_asset_entries(card):
        if isinstance(entry, dict):
            uri = entry.get("uri") or ""
            if uri.startswith(EMBEDED_PREFIX):
                referenced.add(uri[len(EMBEDED_PREFIX):].lower())
    orphans = []
    meta_expected = set()
    for path in referenced:
        meta_expected.add(("x_meta/" + os.path.splitext(path.split("/")[-1])[0] + ".json").lower())
    for record in manifest.get("entries") or []:
        name = record.get("name") or ""
        if record.get("role") == "asset" and name.lower() not in referenced:
            orphans.append(record)
        if record.get("role") == "meta" and name.lower() not in meta_expected:
            orphans.append(record)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    moved = []
    if move:
        if not yes:
            raise CharxError("Refusing to move orphan assets without --yes")
        for record in orphans:
            local = record.get("local")
            if not local:
                continue
            src = os_path(work, local)
            if os.path.isfile(src):
                write_bytes(os_path(work, "_charx/removed/%s/%s" % (stamp, local)), read_bytes(src))
                os.remove(src)
                moved.append(local)
        keep = {((item.get("local") or "").lower(), (item.get("name") or "")) for item in orphans}
        manifest["entries"] = [e for e in manifest.get("entries") or []
                               if ((e.get("local") or "").lower(), (e.get("name") or "")) not in keep]
        save_manifest(work, manifest)
    return {
        "orphans": [{"entry": r.get("name"), "local": r.get("local"), "role": r.get("role")}
                    for r in orphans],
        "moved": moved,
    }


# --------------------------------------------------------------------------
# lorebook operations
# --------------------------------------------------------------------------

def book_list(work):
    _manifest, card, module = load_work(work)
    source, lore = effective_lore(card, module)
    folders_map, order, parent = _lore_folders(lore)
    display = _lore_folder_display_paths(lore)
    result = []
    for index, entry in enumerate(lore):
        if not isinstance(entry, dict):
            continue
        if source == "module":
            view = {
                "index": index,
                "keys": entry.get("key"),
                "secondkey": entry.get("secondkey"),
                "mode": entry.get("mode"),
                "alwaysActive": entry.get("alwaysActive"),
                "selective": entry.get("selective"),
                "insertorder": entry.get("insertorder"),
                "comment": entry.get("comment"),
                "content_len": len(entry.get("content") or ""),
            }
        else:
            view = {
                "index": index,
                "keys": ", ".join(entry.get("keys") or []),
                "secondkey": ", ".join(entry.get("secondary_keys") or []),
                "mode": entry.get("mode"),
                "alwaysActive": entry.get("constant"),
                "selective": entry.get("selective"),
                "insertorder": entry.get("insertion_order"),
                "comment": entry.get("name") or entry.get("comment"),
                "content_len": len(entry.get("content") or ""),
            }
        if (entry.get("mode") or "normal") == "folder":
            folder_id = _lore_folder_id(entry)
        else:
            folder_id = _lore_folder_ref(entry)
        view["folder"] = folder_id
        view["folder_path"] = "/".join(display.get(folder_id, ()))
        result.append(view)
    folders = []
    for folder_id in order:
        folders.append({
            "id": folder_id,
            "name": _lore_folder_name(folders_map[folder_id]),
            "path": "/".join(display.get(folder_id, ())),
            "parent": parent.get(folder_id),
        })
    return {"source": source, "entries": result, "folders": folders}


def _book_append(work, source, card, module, lore_entry):
    """Append a module-shaped lore entry to the effective lorebook, return its index."""
    if source == "module":
        module_obj = unwrap_module(module)
        lore = module_obj.get("lorebook")
        if not isinstance(lore, list):
            lore = []
            module_obj["lorebook"] = lore
        lore.append(lore_entry)
        save_module(work, module)
        return len(lore) - 1
    data_doc = card_data(card)
    book = data_doc.get("character_book")
    if not isinstance(book, dict):
        book = {}
        data_doc["character_book"] = book
    entries = book.get("entries")
    if not isinstance(entries, list):
        entries = []
        book["entries"] = entries
    entries.append(lore_to_charbook(lore_entry))
    save_card(work, card)
    return len(entries) - 1


def book_add(work, name, keys, content, mode="normal", insertorder=100,
             always_active=False, selective=False, secondkeys=None, folder=None,
             use_regex=False, case_sensitive=False):
    manifest, card, module = load_work(work)
    source, _lore = effective_lore(card, module)
    if source is None:
        raise CharxError("Card has neither module.lorebook nor character_book.entries")
    keys_list = [k.strip() for k in keys.split(",") if k.strip()]
    if not keys_list:
        raise CharxError("At least one lore key is required")
    second_list = [k.strip() for k in (secondkeys or "").split(",") if k.strip()]
    if mode not in LORE_MODES:
        raise CharxError("Unknown lore mode: %s" % mode)
    lore_entry = {
        "key": ", ".join(keys_list),
        "secondkey": ", ".join(second_list),
        "insertorder": int(insertorder),
        "comment": name,
        "content": content,
        "mode": mode,
        "alwaysActive": bool(always_active),
        "selective": bool(selective),
        "extentions": {"risu_case_sensitive": bool(case_sensitive)},
        "useRegex": bool(use_regex),
    }
    if folder:
        parent_id = _resolve_lore_folder(_lore, folder)
        if parent_id is None:
            raise CharxError("Unknown lorebook folder: %s" % folder)
        lore_entry["folder"] = parent_id
    index = _book_append(work, source, card, module, lore_entry)
    return {"source": source, "index": index, "entry": lore_entry}


def book_folder_add(work, name, parent=None, folder_id=None):
    manifest, card, module = load_work(work)
    source, lore = effective_lore(card, module)
    if source is None:
        raise CharxError("Card has neither module.lorebook nor character_book.entries")
    name = (name or "").strip()
    if not name:
        raise CharxError("Folder name is required")
    if folder_id is None:
        folder_id = "\uf000folder:" + str(uuid.uuid4())
    else:
        folder_id = folder_id.strip()
        if not folder_id:
            raise CharxError("Folder id is empty")
    existing = set(_lore_folder_id(entry) for entry in lore if isinstance(entry, dict))
    if folder_id in existing:
        raise CharxError("A lorebook folder with id %r already exists" % folder_id)
    parent_id = _resolve_lore_folder(lore, parent)
    lore_entry = {
        "key": folder_id,
        "secondkey": "",
        "insertorder": 100,
        "comment": name,
        "content": "",
        "mode": "folder",
        "alwaysActive": False,
        "selective": False,
        "extentions": {},
        "useRegex": False,
    }
    if parent_id is not None:
        lore_entry["folder"] = parent_id
    index = _book_append(work, source, card, module, lore_entry)
    return {"source": source, "index": index, "id": folder_id,
            "parent": parent_id, "entry": lore_entry}


def book_move(work, index, target):
    manifest, card, module = load_work(work)
    source, lore = effective_lore(card, module)
    if source is None:
        raise CharxError("Card has no lorebook")
    if index < 0 or index >= len(lore):
        raise CharxError("Lorebook index out of range: %d (count=%d)" % (index, len(lore)))
    entry = lore[index]
    if not isinstance(entry, dict):
        raise CharxError("Lorebook entry %d is not an object" % index)
    target_id = _resolve_lore_folder(lore, target)
    if target_id is not None:
        folder_id = _lore_folder_id(entry)
        if folder_id is not None:
            _folders, _order, parent = _lore_folders(lore)
            node = target_id
            while node is not None:
                if node == folder_id:
                    raise CharxError(
                        "Cannot move a lorebook folder into itself or a descendant")
                node = parent.get(node)
        entry["folder"] = target_id
    else:
        entry.pop("folder", None)
    if source == "module":
        save_module(work, module)
    else:
        save_card(work, card)
    display = _lore_folder_display_paths(lore)
    return {"source": source, "index": index, "folder": target_id,
            "path": list(display.get(target_id, ()))}


def book_remove(work, index, yes=False):
    if not yes:
        raise CharxError("Refusing to remove a lorebook entry without --yes")
    manifest, card, module = load_work(work)
    source, lore = effective_lore(card, module)
    if source is None:
        raise CharxError("Card has no lorebook")
    if index < 0 or index >= len(lore):
        raise CharxError("Lorebook index out of range: %d (count=%d)" % (index, len(lore)))
    removed = lore.pop(index)
    if source == "module":
        save_module(work, module)
    else:
        save_card(work, card)
    return {"source": source, "removed": removed}


# --------------------------------------------------------------------------
# diff / snapshots
# --------------------------------------------------------------------------

def snapshot_source(path):
    if os.path.isdir(path):
        manifest, card, module = load_work(path)
        entries = {}
        for item in collect_pack_entries(path, manifest):
            data = read_bytes(os_path(path, item["local"]))
            if item.get("encoding") == "base64":
                data = base64.b64encode(data)
            entries[item["entry"]] = {
                "size": len(data),
                "sha256": sha256_bytes(data),
            }
        prefix = b""
        if manifest.get("prefix_file") and os.path.isfile(os_path(path, manifest["prefix_file"])):
            prefix = read_bytes(os_path(path, manifest["prefix_file"]))
        return {
            "kind": "work",
            "path": os.path.abspath(path),
            "entries": entries,
            "card": card,
            "module": _normalize_module(module),
            "prefix_size": len(prefix),
            "prefix_sha": sha256_bytes(prefix) if prefix else None,
            "layout": manifest.get("layout", "v3"),
        }
    archive = CharxArchive(path)
    entries = {}
    for info in archive.infos:
        if info.filename.endswith("/"):
            continue
        if info.filename in ("card.json", "module.risum", "chara"):
            continue
        entries[info.filename] = {
            "size": info.file_size,
            "sha256": sha256_bytes(archive.read(info.filename)),
        }
    bundle = bundle_from_archive(path, archive=archive)
    result = {
        "kind": "charx",
        "path": archive.path,
        "entries": entries,
        "card": bundle.card,
        "module": _normalize_module(bundle.module),
        "prefix_size": len(archive.prefix),
        "prefix_sha": sha256_bytes(archive.prefix) if archive.prefix else None,
        "layout": bundle.layout,
    }
    archive.close()
    return result


def _normalize_module(module):
    if not isinstance(module, dict):
        return module
    normalized = copy.deepcopy(module)
    try:
        module_obj = unwrap_module(normalized)
    except CharxError:
        return normalized
    assets = module_obj.get("assets")
    if isinstance(assets, list):
        for index, entry in enumerate(assets):
            if isinstance(entry, list) and len(entry) >= 2:
                entry[1] = MODULE_ASSET_SCHEME + str(index)
    return normalized


def _preview(value, limit=100):
    if isinstance(value, str):
        text = value.replace("\r", "\\r").replace("\n", "\\n")
        return text[:limit] + ("..." if len(text) > limit else "")
    return value


def diff_json(old, new, path="", changes=None, limit=400):
    if changes is None:
        changes = []
    if len(changes) >= limit:
        return changes
    if type(old) is not type(new) and not (isinstance(old, (int, float)) and isinstance(new, (int, float))):
        changes.append({"kind": "type", "path": path or "/", "old_type": type(old).__name__,
                        "new_type": type(new).__name__, "old": _preview(old), "new": _preview(new)})
        return changes
    if isinstance(old, dict):
        old_keys = set(old.keys())
        new_keys = set(new.keys())
        for key in sorted(old_keys - new_keys):
            changes.append({"kind": "removed", "path": (path + "/" + str(key)), "old": _preview(old[key])})
        for key in sorted(new_keys - old_keys):
            changes.append({"kind": "added", "path": (path + "/" + str(key)), "new": _preview(new[key])})
        for key in sorted(old_keys & new_keys):
            if len(changes) >= limit:
                break
            diff_json(old[key], new[key], path + "/" + str(key), changes, limit)
    elif isinstance(old, list):
        if len(old) != len(new):
            changes.append({"kind": "length", "path": path or "/", "old_len": len(old), "new_len": len(new)})
        for index in range(min(len(old), len(new))):
            if len(changes) >= limit:
                break
            diff_json(old[index], new[index], path + "/" + str(index), changes, limit)
        if len(new) > len(old):
            for index in range(len(old), min(len(new), len(old) + 10)):
                changes.append({"kind": "added", "path": path + "/" + str(index), "new": _preview(new[index])})
        if len(old) > len(new):
            for index in range(len(new), min(len(old), len(new) + 10)):
                changes.append({"kind": "removed", "path": path + "/" + str(index), "old": _preview(old[index])})
    else:
        if old != new:
            item = {"kind": "changed", "path": path or "/", "old": _preview(old), "new": _preview(new)}
            if isinstance(old, str) and isinstance(new, str):
                item["old_len"] = len(old)
                item["new_len"] = len(new)
            changes.append(item)
    return changes


def diff_sources(left_path, right_path, ignore_modification_date=True):
    left = snapshot_source(left_path)
    right = snapshot_source(right_path)
    left_entries = left["entries"]
    right_entries = right["entries"]
    added = sorted(set(right_entries) - set(left_entries))
    removed = sorted(set(left_entries) - set(right_entries))
    changed = []
    for name in sorted(set(left_entries) & set(right_entries)):
        if left_entries[name]["sha256"] != right_entries[name]["sha256"]:
            changed.append({
                "entry": name,
                "old_size": left_entries[name]["size"],
                "new_size": right_entries[name]["size"],
            })
    left_card = left["card"]
    right_card = right["card"]
    if ignore_modification_date and isinstance(left_card, dict) and isinstance(right_card, dict):
        left_card = copy.deepcopy(left_card)
        right_card = copy.deepcopy(right_card)
        for doc in (left_card, right_card):
            data = doc.get("data")
            if isinstance(data, dict):
                data.pop("modification_date", None)
    card_changes = diff_json(left_card, right_card, "") if left_card is not None and right_card is not None else []
    module_changes = diff_json(left["module"], right["module"], "") if left["module"] is not None or right["module"] is not None else []
    return {
        "left": {"path": left["path"], "kind": left["kind"]},
        "right": {"path": right["path"], "kind": right["kind"]},
        "entries": {"added": added, "removed": removed, "changed": changed},
        "card_changes": card_changes,
        "module_changes": module_changes,
        "prefix": {
            "left_size": left["prefix_size"],
            "right_size": right["prefix_size"],
            "same": left["prefix_sha"] == right["prefix_sha"],
        },
        "layout": {"left": left["layout"], "right": right["layout"]},
    }


# --------------------------------------------------------------------------
# info
# --------------------------------------------------------------------------

def info_source(path):
    if os.path.isdir(path):
        manifest, card, module = load_work(path)
        pack_items = collect_pack_entries(path)
        names = [item["entry"] for item in pack_items]
        sizes = {}
        for item in pack_items:
            size = item["size"] or 0
            if item.get("encoding") == "base64":
                size = 4 * ((size + 2) // 3)
            sizes[item["entry"]] = size
        card_entry, card_bytes = serialized_card_entry(manifest.get("layout", "v3"), card)
        names.append(card_entry)
        sizes[card_entry] = len(card_bytes)
        raw_module = os.path.join(path, "_charx", "original", "module.risum")
        module_size = os.path.getsize(raw_module) if os.path.isfile(raw_module) else 0
        if module is not None:
            try:
                module_size = len(encode_module(module, _module_asset_blobs(path, module, manifest)))
            except CharxError:
                pass
        if module is not None or os.path.isfile(raw_module):
            names.append("module.risum")
            sizes["module.risum"] = module_size
        prefix_size = 0
        if manifest.get("prefix_file") and os.path.isfile(os_path(path, manifest["prefix_file"])):
            prefix_size = os.path.getsize(os_path(path, manifest["prefix_file"]))
        source_kind = "work"
        source_path = os.path.abspath(path)
        archive_size = None
        bundle = bundle_from_work(path, manifest=manifest, card=card, module=module)
    else:
        archive = CharxArchive(path)
        names = [n for n in archive.names if not n.endswith("/")]
        sizes = {i.filename: i.file_size for i in archive.infos}
        prefix_size = len(archive.prefix)
        source_kind = "charx"
        source_path = archive.path
        archive_size = archive.raw_size
        bundle = bundle_from_archive(path, archive=archive)
        card = bundle.card
        module = bundle.module

    assets = card_asset_entries(card) if isinstance(card, dict) else []
    asset_by_type = {}
    asset_by_ext = {}
    resolved = []
    total_asset_bytes = 0
    for entry in assets:
        if not isinstance(entry, dict):
            continue
        asset_type = entry.get("type") or "(none)"
        ext = (entry.get("ext") or "(none)").lower()
        asset_by_type[asset_type] = asset_by_type.get(asset_type, 0) + 1
        asset_by_ext[ext] = asset_by_ext.get(ext, 0) + 1
        uri = entry.get("uri") or ""
        if uri.startswith(EMBEDED_PREFIX):
            target = uri[len(EMBEDED_PREFIX):]
            resolved.append(target)
            total_asset_bytes += sizes.get(target, 0)

    source, lore = effective_lore(card, module) if isinstance(card, dict) else (None, [])
    module_obj = None
    if isinstance(module, dict):
        try:
            module_obj = unwrap_module(module)
        except CharxError:
            module_obj = None
    meta_count = sum(1 for name in names if name.startswith("x_meta/"))
    expected_meta = _expected_meta_names(set(resolved))
    lower_names = set(name.lower() for name in names)
    missing_meta = [path for meta, path in expected_meta.items() if meta not in lower_names]

    fields = {}
    if isinstance(card, dict):
        data = card.get("data")
        if isinstance(data, dict):
            for key in ("description", "first_mes", "mes_example", "personality", "scenario",
                        "system_prompt", "post_history_instructions", "creator_notes"):
                if isinstance(data.get(key), str):
                    fields[key] = len(data[key])
    extensions = (card.get("data") or {}).get("extensions") if isinstance(card, dict) else None
    risu = extensions.get("risuai") if isinstance(extensions, dict) else None
    ext_fields = {}
    if isinstance(risu, dict):
        for key, value in risu.items():
            if isinstance(value, str):
                ext_fields[key] = {"type": "str", "len": len(value)}
            elif isinstance(value, list):
                ext_fields[key] = {"type": "list", "len": len(value)}
            elif isinstance(value, dict):
                ext_fields[key] = {"type": "dict", "len": len(value)}
            else:
                ext_fields[key] = {"type": type(value).__name__, "value": value}

    issues = validate_bundle(bundle)
    if getattr(bundle, "_archive", None) is not None:
        bundle._archive.close()
    counts = {"error": 0, "warn": 0, "info": 0}
    for item in issues:
        counts[item["level"]] = counts.get(item["level"], 0) + 1

    return {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "source": source_path,
        "source_kind": source_kind,
        "archive_size": archive_size,
        "entry_count": len(names),
        "payload_size": sum(sizes.values()),
        "prefix_size": prefix_size,
        "archive_kind": "jpeg+zip" if prefix_size else "zip",
        "card": {
            "spec": card.get("spec") if isinstance(card, dict) else None,
            "name": (card.get("data") or {}).get("name") if isinstance(card, dict) else None,
            "creator": (card.get("data") or {}).get("creator") if isinstance(card, dict) else None,
            "fields": fields,
            "lore_source": source,
            "lore_count": len(lore),
            "character_book_count": len(((card.get("data") or {}).get("character_book") or {}).get("entries") or [])
            if isinstance(card, dict) else 0,
            "alternate_greetings": len((card.get("data") or {}).get("alternate_greetings") or [])
            if isinstance(card, dict) else 0,
            "extensions_risuai": ext_fields,
            "asset_count": len(assets),
            "asset_by_type": asset_by_type,
            "asset_by_ext": asset_by_ext,
            "asset_bytes": total_asset_bytes,
            "x_meta_count": meta_count,
            "assets_missing_meta": len(missing_meta),
        },
        "module": {
            "present": module_obj is not None,
            "name": module_obj.get("name") if module_obj else None,
            "id": module_obj.get("id") if module_obj else None,
            "lorebook": len(module_obj.get("lorebook") or []) if module_obj else 0,
            "regex": len(module_obj.get("regex") or []) if module_obj else 0,
            "trigger": len(module_obj.get("trigger") or []) if module_obj else 0,
            "assets": len(module_obj.get("assets") or []) if module_obj else 0,
            "cjs_len": len(module_obj.get("cjs") or "") if module_obj else 0,
            "backgroundEmbedding_len": len(module_obj.get("backgroundEmbedding") or "") if module_obj else 0,
            "namespace": module_obj.get("namespace") if module_obj else None,
            "customModuleToggle_len": len(module_obj.get("customModuleToggle") or "") if module_obj else 0,
            "lowLevelAccess": bool(module_obj.get("lowLevelAccess")) if module_obj else False,
            "hideIcon": bool(module_obj.get("hideIcon")) if module_obj else False,
        },
        "warnings": {"error": counts.get("error", 0), "warn": counts.get("warn", 0),
                     "info": counts.get("info", 0)},
        "issues": issues,
    }


# --------------------------------------------------------------------------
# raw entry operations
# --------------------------------------------------------------------------

def raw_get(work, entry):
    manifest = load_manifest(work)
    needle = norm_entry_name(entry)
    for record in manifest.get("entries") or []:
        if record.get("name") == needle or (record.get("local") or "").lower() == needle.lower():
            local = record.get("local")
            if not local:
                raise CharxError("Entry has no local file: %s" % needle)
            full = os_path(work, local)
            if not os.path.isfile(full):
                raise CharxError("Local file is missing: %s" % full)
            return record.get("name"), read_bytes(full)
    full = os_path(work, needle)
    if is_safe_entry_name(needle) and os.path.isfile(full):
        return needle, read_bytes(full)
    raise CharxError("Entry not found: %s" % entry)


def raw_put(work, entry, source_file):
    manifest = load_manifest(work)
    normalized = norm_entry_name(entry)
    lowered = normalized.lower()
    if normalized in RESERVED_TOP_FILES:
        raise CharxError("Use the dedicated command for %s" % entry)
    if lowered.startswith("_charx/") or lowered.startswith("text/"):
        raise CharxError("Entry path is reserved for the work directory: %s" % entry)
    if not is_safe_entry_name(entry):
        raise CharxError("Unsafe entry name: %r" % entry)
    data = read_bytes(source_file)
    lookup = _manifest_by_local(manifest)
    record = None
    for item in manifest.get("entries") or []:
        if item.get("name") == entry:
            record = item
            break
    if record:
        local = record.get("local")
    else:
        used = set(lookup.keys())
        local = work_local_for_entry(entry, used)
        if entry.startswith("assets/"):
            role = "asset"
        elif entry.startswith("x_meta/"):
            role = "meta"
        else:
            role = "other"
        record = {
            "name": entry,
            "role": role,
            "local": local,
            "packable": True,
            "size": len(data),
            "sha256": sha256_bytes(data),
            "added": True,
        }
        manifest.setdefault("entries", []).append(record)
    write_bytes(os_path(work, local), data)
    record["size"] = len(data)
    record["sha256"] = sha256_bytes(data)
    save_manifest(work, manifest)
    return {"entry": entry, "local": local, "bytes": len(data)}


def raw_remove(work, entry, yes=False):
    if not yes:
        raise CharxError("Refusing to remove an entry without --yes")
    manifest = load_manifest(work)
    for record in list(manifest.get("entries") or []):
        if record.get("name") == entry:
            local = record.get("local")
            if local and os.path.isfile(os_path(work, local)):
                stamp = time.strftime("%Y%m%d-%H%M%S")
                dst = os_path(work, "_charx/removed/%s/%s" % (stamp, local))
                write_bytes(dst, read_bytes(os_path(work, local)))
                os.remove(os_path(work, local))
            manifest["entries"] = [item for item in manifest.get("entries") or [] if item is not record]
            save_manifest(work, manifest)
            return {"entry": entry, "local": local}
    raise CharxError("Entry not found in manifest: %s" % entry)


# --------------------------------------------------------------------------
# standalone module commands
# --------------------------------------------------------------------------

def module_decode_file(risum_path, out_json, assets_dir=None):
    decoded = decode_module(read_bytes(risum_path))
    wrapper = decoded["wrapper"]
    module_obj = unwrap_module(wrapper)
    assets = module_obj.get("assets") or []
    module_assets = []
    if assets_dir:
        os.makedirs(assets_dir, exist_ok=True)
    for index, blob in enumerate(decoded["assets"]):
        if index >= len(assets):
            raise CharxError("module asset block %d has no metadata entry" % index)
        entry = assets[index]
        name = str(entry[0] or ("asset_%d" % index))
        ext = str(entry[2] or "bin")
        if assets_dir:
            filename = "%04d_%s.%s" % (index, safe_component(name), safe_component(ext))
            write_bytes(os.path.join(assets_dir, filename), blob)
        if entry[1]:
            entry[1] = MODULE_ASSET_SCHEME + str(index)
        module_assets.append({"index": index, "name": name, "ext": ext, "bytes": len(blob)})
    write_json(out_json, wrapper, indent=2)
    return {"wrapper": wrapper, "assets": module_assets, "trailing": decoded["trailing"]}


def module_encode_file(module_json, out_risum, assets_dir=None):
    wrapper = load_json_file(module_json)
    module_obj = unwrap_module(wrapper)
    assets = module_obj.get("assets") or []
    base = os.path.dirname(os.path.abspath(module_json))
    blobs = []
    for index, entry in enumerate(assets):
        if not isinstance(entry, list) or len(entry) < 2:
            raise CharxError("module.assets[%d] must be [name, uri, ext]" % index)
        uri = entry[1] or ""
        if uri.startswith(MODULE_ASSET_SCHEME):
            try:
                int(uri[len(MODULE_ASSET_SCHEME):])
            except ValueError:
                raise CharxError("module.assets[%d] has a bad module-asset URI: %r"
                                 % (index, uri))
        path = None
        if uri.startswith(EMBEDED_PREFIX):
            rel = norm_entry_name(uri[len(EMBEDED_PREFIX):])
            if not is_safe_entry_name(rel):
                raise CharxError("module.assets[%d] uses an unsafe path: %r" % (index, uri))
            path = os_path(base, rel)
        elif uri and not uri.startswith(MODULE_ASSET_SCHEME):
            if os.path.isabs(uri):
                path = uri
            else:
                rel = norm_entry_name(uri)
                if not is_safe_entry_name(rel):
                    raise CharxError("module.assets[%d] uses an unsafe path: %r" % (index, uri))
                path = os_path(base, rel)
        if path is None or not os.path.isfile(path):
            if assets_dir:
                prefix = "%04d_" % index
                for filename in sorted(os.listdir(assets_dir)):
                    if filename.startswith(prefix):
                        path = os.path.join(assets_dir, filename)
                        break
        if not path or not os.path.isfile(path):
            raise CharxError("Cannot resolve bytes for module.assets[%d] (%r)" % (index, uri))
        blobs.append(read_bytes(path))
    raw = encode_module(wrapper, blobs)
    write_bytes(out_risum, raw)
    return {"bytes": len(raw), "assets": len(blobs)}


# --------------------------------------------------------------------------
# embedded module assets
# --------------------------------------------------------------------------

def _module_assets_meta(module):
    if not isinstance(module, dict):
        raise CharxError("Work directory has no decoded module.json")
    module_obj = unwrap_module(module)
    meta = module_obj.get("assets")
    if meta is None:
        return module_obj, []
    if not isinstance(meta, list):
        raise CharxError("module.assets must be a list")
    return module_obj, meta


def _module_asset_records(manifest):
    records = {}
    for item in manifest.get("module_assets") or []:
        if isinstance(item, dict) and item.get("index") is not None:
            records[int(item["index"])] = item
    return records


def module_asset_list(work):
    manifest, _card, module = load_work(work)
    _module_obj, meta = _module_assets_meta(module)
    records = _module_asset_records(manifest)
    result = []
    for index, entry in enumerate(meta):
        record = records.get(index) or {}
        name = None
        ext = None
        uri = None
        if isinstance(entry, list):
            if entry:
                name = entry[0]
            if len(entry) > 1:
                uri = entry[1]
            if len(entry) > 2:
                ext = entry[2]
        local = record.get("local")
        size = None
        if local and os.path.isfile(os_path(work, local)):
            size = os.path.getsize(os_path(work, local))
        result.append({
            "index": index,
            "name": str(name or record.get("name") or ("asset_%d" % index)),
            "ext": str(ext or record.get("ext") or "bin"),
            "local": local,
            "size": size,
            "uri": uri,
        })
    return {"assets": result}


def _module_asset_target(module, manifest, target):
    _module_obj, meta = _module_assets_meta(module)
    records = _module_asset_records(manifest)
    needle = str(target or "").strip()
    if needle.lower().startswith(MODULE_ASSET_SCHEME):
        needle = needle[len(MODULE_ASSET_SCHEME):]
    if needle.startswith("#"):
        needle = needle[1:]
    index = None
    if needle.isdigit():
        index = int(needle)
    else:
        lowered = needle.lower()
        if not lowered:
            raise CharxError("Module asset target is empty")
        matches = []
        for candidate, entry in enumerate(meta):
            names = set()
            if isinstance(entry, list) and entry and entry[0]:
                names.add(str(entry[0]).lower())
            record = records.get(candidate) or {}
            if record.get("name"):
                names.add(str(record["name"]).lower())
            if record.get("local"):
                names.add(os.path.basename(str(record["local"])).lower())
            if lowered in names:
                matches.append(candidate)
        if not matches:
            raise CharxError("No module asset matches: %s" % target)
        if len(matches) > 1:
            raise CharxError("Module asset target is ambiguous: %s (indexes %s)"
                             % (target, ", ".join(str(m) for m in matches)))
        index = matches[0]
    if index < 0 or index >= len(meta):
        raise CharxError("Module asset index out of range: %d (count=%d)"
                         % (index, len(meta)))
    entry = meta[index]
    if not isinstance(entry, list) or len(entry) < 2:
        raise CharxError("module.assets[%d] is not [name, uri, ext]" % index)
    return index, entry, records.get(index)


def module_asset_replace(work, target, source_file, name=None, ext=None):
    manifest, _card, module = load_work(work)
    index, entry, record = _module_asset_target(module, manifest, target)
    data = read_bytes(source_file)
    if not data:
        raise CharxError("Replacement file is empty: %s" % source_file)
    previous_uri = entry[1] if len(entry) > 1 else None
    new_name = str(name).strip() if name else str(entry[0] or ("asset_%d" % index))
    if not new_name:
        new_name = "asset_%d" % index
    new_ext = (ext or (entry[2] if len(entry) > 2 else "") or "").lower().lstrip(".")
    if not new_ext:
        new_ext = detect_ext(data[:64]) or "bin"
    filename = "%04d_%s.%s" % (index, safe_component(new_name), safe_component(new_ext))
    local = "_charx/module_assets/" + filename
    used = set()
    for item in manifest.get("module_assets") or []:
        if not isinstance(item, dict) or item.get("index") is None:
            continue
        if int(item["index"]) != index and item.get("local"):
            used.add(str(item["local"]).lower())
    candidate = local
    counter = 1
    while candidate.lower() in used:
        candidate = "_charx/module_assets/%04d_%s_%d.%s" % (
            index, safe_component(new_name), counter, safe_component(new_ext))
        counter += 1
    local = candidate
    old_local = record.get("local") if record else None
    write_bytes(os_path(work, local), data)
    if old_local and old_local.lower() != local.lower():
        old_path = os_path(work, old_local)
        if os.path.isfile(old_path):
            os.remove(old_path)
    while len(entry) < 3:
        entry.append("")
    original_uri = record.get("original_uri") if record else previous_uri
    if isinstance(original_uri, str) and original_uri.startswith(MODULE_ASSET_SCHEME):
        original_uri = None
    entry[0] = new_name
    entry[1] = MODULE_ASSET_SCHEME + str(index)
    entry[2] = new_ext
    record = record or {"index": index}
    record.update({"index": index, "local": local, "name": new_name, "ext": new_ext})
    record["original_uri"] = original_uri
    module_assets = [item for item in manifest.get("module_assets") or []
                     if not (isinstance(item, dict)
                             and item.get("index") is not None
                             and int(item["index"]) == index)]
    module_assets.append(record)
    module_assets.sort(key=lambda item: int(item.get("index", 0)))
    manifest["module_assets"] = module_assets
    save_module(work, module)
    save_manifest(work, manifest)
    detected = detect_ext(data[:64])
    warning = None
    if detected and new_ext and detected != new_ext:
        warning = ("module asset is stored as .%s but replacement bytes look like .%s; "
                   "the metadata is kept so references stay valid" % (new_ext, detected))
    return {"index": index, "name": new_name, "ext": new_ext, "local": local,
            "entry": entry, "bytes": len(data), "warning": warning}


# --------------------------------------------------------------------------
# report helpers
# --------------------------------------------------------------------------

def summarize_issues(issues, limit=None):
    counts = {"error": 0, "warn": 0, "info": 0}
    for item in issues:
        counts[item["level"]] = counts.get(item["level"], 0) + 1
    lines = []
    for level in ("error", "warn", "info"):
        subset = [item for item in issues if item["level"] == level]
        if limit:
            subset = subset[:limit]
        for item in subset:
            path = (" (%s)" % item["path"]) if item.get("path") else ""
            lines.append("[%s] %s: %s%s" % (level, item["code"], item["message"], path))
    return counts, lines
