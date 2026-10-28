# CharX / PocketRisu format notes

Derived from the PocketRisu TypeScript sources in `PocketRisu/src/ts/`. The toolkit mirrors
these rules so that a repacked card behaves like the original on import.

Primary sources:

- `process/processzip.ts` — `CharXImporter` / `CharXWriter`: zip layout, 50 MB limit, asset
  routing, `x_meta` writes.
- `characterCards.ts` — `exportCharacterCard`, `createBaseV3`, `createBaseV2`,
  `importCharacterCardSpec`, `convertCharbook`: card structure, asset paths, lorebook
  conversion and import precedence.
- `process/modules.ts` — `RisuModule`, `exportModuleLegacy`, `readModule`: the `module.risum`
  container.
- `rpack/rpack_js.js` + `rpack/rpack_map.bin` — byte substitution codec.
- `storage/database.svelte.ts` — `loreBook`, `customscript` field shapes.
- `process/triggers.ts` — `triggerscript` shape.
- `pngChunk.ts` — PNG `tEXt` extraction used for `x_meta`.

## 1. Container

A `.charx` is a ZIP archive. PocketRisu also accepts `charxJpeg`: the same ZIP bytes
preceded by a JPEG image, so the file opens as a picture. There is no footer or offset
table; readers scan for the first `PK\x03\x04` that parses as a ZIP. This toolkit keeps the
prefix in `_charx/jpeg_prefix.bin` and writes it back by default.

Typical entries:

| Entry | Role |
| --- | --- |
| `card.json` | Character Card V3 JSON |
| `chara` | Legacy V2 JSON, base64-encoded (v2 layout only) |
| `module.risum` | Optional binary Risu module |
| `assets/<type>/<itype>/<name>.<ext>` | Card assets |
| `x_meta/<name>.json` | Per-asset metadata written by PocketRisu |
| anything else | Preserved byte-for-byte by the toolkit |

There are two card layouts:

- **v3**: `card.json` is plain UTF-8 JSON, `spec: "chara_card_v3"`.
- **v2**: a `chara` entry whose bytes are base64 of compact JSON (`JSON.stringify(card)`,
  no indentation), `spec: "chara_card_v2"`; assets are `chara-ext-asset_:<N>` entries whose
  bytes are base64 of the (compressed) image, referenced from `data.assets[].uri` as
  `__asset:N`.

PocketRisu refuses a `card.json` source unless `spec === "chara_card_v3"`; a `chara` source
goes through the v2 import path.

## 2. `card.json` (V3)

```json
{
  "spec": "chara_card_v3",
  "spec_version": "3.0",
  "data": {
    "name": "...", "description": "...", "personality": "...", "scenario": "...",
    "first_mes": "...", "mes_example": "...", "creator_notes": "...",
    "system_prompt": "...", "post_history_instructions": "...",
    "alternate_greetings": ["..."],
    "character_book": {"name": "...", "entries": [ ... ]},
    "tags": ["..."], "creator": "...", "character_version": "...", "nickname": "...",
    "extensions": {"risuai": { ... }, "depth_prompt": {...}, "...": "..."},
    "assets": [
      {"type": "icon", "uri": "embeded://assets/icon/image/main.png",
       "name": "main", "ext": "png"}
    ],
    "group_only_greetings": [],
    "creation_date": 0, "modification_date": 0
  }
}
```

Notes:

- PocketRisu writes `card.json` with `JSON.stringify(card, null, 4)` — four-space indent,
  UTF-8, **no trailing newline**. The toolkit matches this so a no-op repack is
  byte-identical.
- `data.assets[].type` is one of `icon`, `emotion`, `background`, `user_icon`,
  `x-risu-asset`; unknown values land in the `other` folder on export.
- `data.assets[].uri` may be:
  - `embeded://<zip path>` — PocketRisu's spelling, one `d`; points inside the archive.
  - `ccdefault:` — the card portrait (the JPEG prefix or the card image).
  - `data:<mime>;base64,...` — inline payload (JSON export format).
  - `__asset:<N>` — legacy v2 reference to `chara-ext-asset_:<N>`.
  - `http(s)://...` — PocketRisu drops external URLs on charx import.
- `data.extensions.risuai` carries Risu-specific state: `viewScreen`, `backgroundHTML`,
  `additionalText`, `bias`, `sdData`, `vits`, `triggerscript`, `customScripts`,
  `lowLevelAccess`, `toggles`, etc. `triggerscript` and `customScripts` are overwritten by
  `module.trigger` / `module.regex` when a module is present.

## 3. `module.risum`

Binary layout, as written by `exportModuleLegacy` and read by `readModule`:

```
byte   111            magic
byte   0              version
uint32 little-endian  main length
bytes                main block: rpack(UTF-8 JSON)
repeat:
  byte 1             asset marker
  uint32 little-endian asset length
  bytes              asset block: rpack(asset bytes)
byte   0              end marker
```

The main JSON is:

```json
{"type": "risuModule", "module": { ...RisuModule... }}
```

`RisuModule` fields:

| Field | Meaning |
| --- | --- |
| `name`, `description` | Module identity |
| `id` | UUID string |
| `lorebook` | `loreBook[]`, the effective lorebook on charx import |
| `regex` | `customscript[]` (`{comment, in, out, type}`) |
| `trigger` | `triggerscript[]` (`{comment, type, conditions, effect}`) |
| `cjs` | Cassiopeia JS source string |
| `backgroundEmbedding` | HTML injected behind the chat |
| `assets` | `[name, uri, ext][]`, one entry per asset block |
| `assetManifest` | Optional external asset manifest (Risu storage) |
| `namespace` | Namespacing string |
| `customModuleToggle` | Toggle DSL text |
| `lowLevelAccess`, `hideIcon` | Import flags |
| `folderId`, `mcp`, `icon` | Optional newer fields |

Asset metadata and blocks must have the same count. On export PocketRisu blanks each
`uri` to `""` and writes the image bytes (already compressed) as one block per asset. On
import, block `i` is assigned to `assets[i]`. The toolkit stores each block under
`_charx/module_assets/` and rewrites non-empty URIs to `module-asset://<i>`; empty URIs stay
empty and are resolved by index, which keeps a no-op repack byte-identical.

### rpack

`rpack_map.bin` is 512 bytes: the first 256 bytes are the encode substitution table, the
last 256 the inverse table. Encoding is a per-byte translation (`bytes.translate`), so it
is reversible and adds no size. The toolkit copies the map from PocketRisu and preserves
the dual MIT/AGPL license in `LICENSES/`.

## 4. Import precedence

From `characterCards.ts` (charx branch) and `importCharacterCardSpec`:

1. `card.json` must be `chara_card_v3`, otherwise import fails.
2. If `module.risum` exists, `module.trigger` and `module.regex` are copied into
   `card.data.extensions.risuai.triggerscript` / `customScripts` (overwriting them).
3. If `module.lorebook` exists, it is passed as `overrideLorebook`; `importCharacterCardSpec`
   starts with that list and, when present, skips `convertCharbook` on
   `data.character_book` (it still reads settings/extensions). So **the module lorebook wins
   over the card lorebook**.
4. Without a module, `data.character_book.entries` is converted through `convertCharbook`.
5. Every non-JSON, non-`card.json`, non-`module.risum` entry is saved as an asset in the
   app; unreferenced ones are simply unused. JSON entries other than `card.json` (including
   `x_meta/**`) are ignored by the importer.

Consequences for editing:

- Always edit the module lorebook (or use `book` commands) when a module is present.
- `pack --sync-book auto` mirrors a changed lorebook to the other copy so both readers see
  the same data.
- Card-side `triggerscript` / `customScripts` edits are useless while a module exists; edit
  `module.trigger` / `module.regex`.

## 5. Asset export rules (`createBaseV3` + `exportCharacterCard`)

- Assets are skipped when their URI is already a known/internal URI (`ccdefault:`, `data:`,
  `http(s)`, local asset handles).
- Every other asset is read, passed through `compressImage`, then written to
  `assets/<type>/<itype>/<uniqueName>.<ext>`.
  - folder (`type`): `icon`, `emotion`, `background`, `user_icon`, otherwise `other`.
  - itype by extension: `png/jpg/jpeg/gif/webp/avif` → `image`; `mp3/wav/ogg/flac` →
    `audio`; `mp4/webm/mov/avi/mkv` → `video`; `mmd/obj` → `model`;
    `safetensors/cpkt/onnx` → `ai`; `otf/ttf/woff/woff2` → `fonts`; `js/ts/lua` → `code`;
    anything else → `other`.
  - `ext === "unknown"` is written as `.png` under `assets/<type>/image`.
  - Duplicate names get `_1`, `_2`, … suffixes.
- The asset entry's `uri` is rewritten to `embeded://<path>`.
- `x_meta/<uniqueName>.json` is written next to it: for PNG, the `tEXt` chunks as an object
  (or `{"type":"PNG"}` when there are none); for other types `{"type":"WEBP"}` etc.
  PocketRisu never reads these records back — they are documentation for external tools.
- Assets larger than **50 MiB** are excluded by `CharXImporter` (`MAX_ASSET_SIZE_BYTES`).

## 6. Lorebook conversion

Card entry (`character_book.entries[]`) fields: `keys`, `secondary_keys`, `content`,
`extensions`, `enabled`, `insertion_order`, `constant`, `selective`, `name`, `comment`,
`case_sensitive`, `use_regex`, plus Risu extras `mode` and `folder`.

Module entry (`lorebook[]`) fields: `key` (comma-separated string), `secondkey`, `content`,
`insertorder`, `comment`, `mode`, `alwaysActive`, `selective`, `useRegex`, `extentions`
(including `risu_case_sensitive`, `risu_activationPercent`, `risu_loreCache`), `folder`,
optional `activationPercent`, `loreCache`, `id`.

Folders are ordinary entries with `mode: "folder"` and empty `content`. Their id lives in
`key` (module) or `keys[0]` (card), formatted `\uf000folder:<uuid>`; their `comment`/`name`
is the visible folder name. Child entries set `folder` to that id, and a folder entry may
itself set `folder` to a parent id, so folders nest. An entry whose `folder` id does not
match any folder entry is orphaned: PocketRisu hides it from the folder tree, and
`text export` writes it at the lorebook root.

Card → module (`convertCharbook`) also performs these migrations by prepending `@@` lines
to `content` and deleting the old extension keys:

| Card extension | Module content marker |
| --- | --- |
| `useProbability` + `probability` (≠100) | `@@probability N` |
| `position: 4` + `depth` + `role` | `@@depth N`, `@@role system\|user\|assistant` |
| `selectiveLogic: 1` | `@@exclude_keys_all k1,k2` |
| `selectiveLogic: 2` | `@@exclude_keys key` (one line per key) |
| `selectiveLogic: 3` | `@@additional_keys key` (one line per key) |
| `delay > 0` | `@@activate_only_after N` |
| `match_whole_words: true` | `@@match_full_word` |
| `match_whole_words: false` | `@@match_partial_word` |

`use_regex` is forced to `false` unless the first key starts with `/`. `risu_case_sensitive`
is always set from `case_sensitive`.

Module → card (`lore_to_charbook`, and the toolkit's sync) mirrors PocketRisu's V3 export
exactly: `keys = key.split(',').map(trim)` (empty key → `[""]`), `secondary_keys` only when
`selective`, `insertion_order`, `constant`, `selective`, `name`/`comment`, `case_sensitive`,
`use_regex`, `mode`, `folder`, and extensions copied from `extentions` plus
`risu_activationPercent` / `risu_loreCache` when present.

## 7. Regex and trigger shapes

`customscript` (`module.regex[]`):

```json
{"comment": "label", "in": "pattern", "out": "replacement", "type": "editdisplay"}
```

`type`: `editinput`, `editoutput`, `editprocess`, `editdisplay`, `editrequest`,
`disabled`, or `""`.

`triggerscript` (`module.trigger[]`):

```json
{"comment": "label", "type": "start", "conditions": [], "effect": [
  {"type": "triggerlua", "code": "..."}
]}
```

`type`: `start`, `manual`, `output`, `input`, `display`, `request`. Conditions and effects
are arrays of typed objects; the toolkit validates the container shape but preserves each
condition/effect object verbatim.

## 8. Known quirks

- `embeded://` is intentionally misspelled in the format.
- Module lore wins on import even when `card.data.character_book` looks correct.
- `x_meta` is write-only from PocketRisu's perspective.
- Assets > 50 MB disappear silently on import.
- A PNG-named file may contain WEBP bytes (PocketRisu's `compressImage` can re-encode but
  keeps the declared extension); the toolkit warns (`ASSET_W_EXT_MISMATCH`) without
  rewriting the path.
- `module.risum` trailing bytes after the end marker are preserved and reported.
- PocketRisu export creates a module named `<character> Module` whose lorebook is the card's
  `globalLore`; third-party tools may produce archives where the two lorebooks diverge.
