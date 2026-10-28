# Ghi chú định dạng CharX / PocketRisu

Được suy ra từ mã nguồn TypeScript của PocketRisu trong `PocketRisu/src/ts/`. Toolkit bám
đúng các quy tắc này để card sau khi đóng gói lại hành xử giống bản gốc khi import.

Nguồn chính:

- `process/processzip.ts` — `CharXImporter` / `CharXWriter`: layout zip, giới hạn 50 MB,
  cách đặt đường dẫn asset, việc ghi `x_meta`.
- `characterCards.ts` — `exportCharacterCard`, `createBaseV3`, `createBaseV2`,
  `importCharacterCardSpec`, `convertCharbook`: cấu trúc card, đường dẫn asset, chuyển đổi
  lorebook và thứ tự ưu tiên khi import.
- `process/modules.ts` — `RisuModule`, `exportModuleLegacy`, `readModule`: container
  `module.risum`.
- `rpack/rpack_js.js` + `rpack/rpack_map.bin` — codec thay thế từng byte.
- `storage/database.svelte.ts` — hình dạng field của `loreBook`, `customscript`.
- `process/triggers.ts` — hình dạng của `triggerscript`.
- `pngChunk.ts` — cách đọc chunk `tEXt` của PNG, dùng cho `x_meta`.

## 1. Container

`.charx` là một archive ZIP. PocketRisu cũng nhận `charxJpeg`: đúng bytes ZIP đó nhưng có
một ảnh JPEG đứng trước, nên file mở được như một bức ảnh. Không có footer hay bảng offset;
trình đọc sẽ quét tới `PK\x03\x04` đầu tiên parse được thành ZIP. Toolkit giữ prefix trong
`_charx/jpeg_prefix.bin` và mặc định ghi lại nó.

Các entry thường gặp:

| Entry | Vai trò |
| --- | --- |
| `card.json` | JSON Character Card V3 |
| `chara` | JSON V2 kiểu cũ, mã hóa base64 (chỉ có ở layout v2) |
| `module.risum` | Module Risu nhị phân, không bắt buộc |
| `assets/<type>/<itype>/<name>.<ext>` | Asset của card |
| `x_meta/<name>.json` | Metadata từng asset do PocketRisu ghi |
| mọi thứ khác | Toolkit giữ nguyên từng byte |

Có hai layout card:

- **v3**: `card.json` là JSON UTF-8 thuần, `spec: "chara_card_v3"`.
- **v2**: entry `chara` chứa base64 của JSON nén một dòng (`JSON.stringify(card)`, không
  thụt lề), `spec: "chara_card_v2"`; asset là các entry `chara-ext-asset_:<N>` chứa base64
  của ảnh (đã nén), được tham chiếu từ `data.assets[].uri` dưới dạng `__asset:N`.

PocketRisu từ chối nguồn `card.json` trừ khi `spec === "chara_card_v3"`; nguồn `chara` đi
qua luồng import v2.

`unpack` ghi mọi entry của archive vào `_charx/manifest.json` (tên, đường dẫn local, vai
trò, kích thước, SHA-256, kiểu nén, DOS timestamp) cùng các fingerprint baseline của nguồn
(`card_sha256`, `module_sha256`, `prefix_sha256`, `entries_sha256`). `pack` đóng gói các
record trong manifest trước, nên entry lạ vẫn sống sót kể cả khi tên của nó trùng với
đường dẫn do tool sở hữu (`text/`, `_charx/`, `module.json`, dotfile, `*.tmp`); các bản
trùng đó được cất dưới `_charx/original/entries/`. File tạo thêm trong cây work mà không
có trong manifest sẽ được thêm thành entry mới. Nếu một record pack được trong manifest đã
mất file local, gói sẽ báo `ENTRY_E_MISSING` và pack dừng lại trừ khi có `--force`.

Khi không có gì thay đổi — hash nguồn, fingerprint của card/module/prefix, danh sách entry
trong manifest và hash của mọi file local đều còn khớp — `pack` chép archive nguồn nguyên
văn từng byte, nên toàn bộ file output có SHA-256 giống nguồn. Sau bất kỳ chỉnh sửa nào, nó
dựng lại ZIP và tái sử dụng lựa chọn DEFLATE/STORED cùng timestamp gốc cho từng entry:
entry không đổi vẫn giống từng byte, còn entry đã sửa có stream deflate mới.

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

Lưu ý:

- PocketRisu ghi `card.json` bằng `JSON.stringify(card, null, 4)` — thụt lề 4 khoảng
  trắng, UTF-8, **không có newline ở cuối**. Toolkit bám đúng như vậy để một lần đóng gói
  không thay đổi gì vẫn giống từng byte.
- `data.assets[].type` là một trong `icon`, `emotion`, `background`, `user_icon`,
  `x-risu-asset`; giá trị lạ sẽ rơi vào folder `other` khi export.
- `data.assets[].uri` có thể là:
  - `embeded://<zip path>` — đúng chính tả của PocketRisu, một chữ `d`; trỏ vào trong
    archive.
  - `ccdefault:` — ảnh chân dung của card (prefix JPEG hoặc ảnh card).
  - `data:<mime>;base64,...` — payload nhúng trực tiếp (định dạng export JSON).
  - `__asset:<N>` — tham chiếu v2 cũ tới `chara-ext-asset_:<N>`.
  - `http(s)://...` — PocketRisu bỏ URL bên ngoài khi import charx.
- `data.extensions.risuai` chứa trạng thái riêng của Risu: `viewScreen`, `backgroundHTML`,
  `additionalText`, `bias`, `sdData`, `vits`, `triggerscript`, `customScripts`,
  `lowLevelAccess`, `toggles`… Khi có module, `triggerscript` và `customScripts` bị
  `module.trigger` / `module.regex` ghi đè.

## 3. `module.risum`

Layout nhị phân, đúng như `exportModuleLegacy` ghi và `readModule` đọc:

```
byte   111            magic
byte   0              version
uint32 little-endian  độ dài block main
bytes                block main: rpack(UTF-8 JSON)
lặp:
  byte 1             marker của asset
  uint32 little-endian độ dài asset
  bytes              block asset: rpack(bytes của asset)
byte   0              marker kết thúc
```

JSON chính có dạng:

```json
{"type": "risuModule", "module": { ...RisuModule... }}
```

Các field của `RisuModule`:

| Field | Ý nghĩa |
| --- | --- |
| `name`, `description` | Danh tính của module |
| `id` | Chuỗi UUID |
| `lorebook` | `loreBook[]`, lorebook có hiệu lực khi import charx |
| `regex` | `customscript[]` (`{comment, in, out, type}`) |
| `trigger` | `triggerscript[]` (`{comment, type, conditions, effect}`) |
| `cjs` | Chuỗi mã nguồn Cassiopeia JS |
| `backgroundEmbedding` | HTML chèn phía sau khung chat |
| `assets` | `[name, uri, ext][]`, mỗi block asset một entry |
| `assetManifest` | Manifest asset bên ngoài, không bắt buộc (Risu storage) |
| `namespace` | Chuỗi namespace |
| `customModuleToggle` | Text DSL của toggle |
| `lowLevelAccess`, `hideIcon` | Cờ khi import |
| `folderId`, `mcp`, `icon` | Field mới hơn, không bắt buộc |

Số metadata asset và số block phải bằng nhau. Khi export, PocketRisu đặt trắng mỗi `uri`
thành `""` và ghi bytes của ảnh (đã nén) thành một block cho mỗi asset. Khi import, block
`i` được gán cho `assets[i]`. Toolkit lưu mỗi block dưới `_charx/module_assets/` và ghi
lại các URI không rỗng thành `module-asset://<i>`; URI rỗng vẫn giữ rỗng và được phân giải
theo index, nhờ đó một lần đóng gói không thay đổi gì vẫn giống từng byte.

### rpack

`rpack_map.bin` dài 512 byte: 256 byte đầu là bảng thay thế khi encode, 256 byte sau là
bảng nghịch đảo. Việc encode là phép dịch từng byte (`bytes.translate`), nên nó thuận
nghịch và không làm tăng kích thước. Toolkit chép bảng này từ PocketRisu và giữ nguyên giấy
phép kép MIT/AGPL trong `LICENSES/`.

## 4. Thứ tự ưu tiên khi import

Từ `characterCards.ts` (nhánh charx) và `importCharacterCardSpec`:

1. `card.json` phải là `chara_card_v3`, nếu không import thất bại.
2. Nếu có `module.risum`, `module.trigger` và `module.regex` được chép vào
   `card.data.extensions.risuai.triggerscript` / `customScripts` (ghi đè chúng).
3. Nếu có `module.lorebook`, nó được truyền làm `overrideLorebook`;
   `importCharacterCardSpec` bắt đầu bằng danh sách đó và, khi nó tồn tại, bỏ qua
   `convertCharbook` trên `data.character_book` (vẫn đọc settings/extensions). Vì vậy
   **lorebook của module thắng lorebook của card**.
4. Không có module thì `data.character_book.entries` được chuyển qua `convertCharbook`.
5. Mọi entry không phải JSON, không phải `card.json`, không phải `module.risum` đều được
   lưu thành asset trong app; entry không được tham chiếu thì chỉ là không dùng tới. Các
   entry JSON khác ngoài `card.json` (kể cả `x_meta/**`) bị trình import bỏ qua.

Hệ quả khi chỉnh sửa:

- Luôn sửa lorebook của module (hoặc dùng lệnh `book`) khi có module.
- `pack --sync-book auto` mirror lorebook đã đổi sang bản còn lại để cả hai trình đọc đều
  thấy cùng dữ liệu.
- Sửa `triggerscript` / `customScripts` ở phía card là vô ích khi còn module; hãy sửa
  `module.trigger` / `module.regex`.

## 5. Quy tắc export asset (`createBaseV3` + `exportCharacterCard`)

- Asset bị bỏ qua khi URI của nó đã là URI nội bộ/đã biết (`ccdefault:`, `data:`,
  `http(s)`, handle asset local).
- Mọi asset khác được đọc, cho qua `compressImage`, rồi ghi vào
  `assets/<type>/<itype>/<uniqueName>.<ext>`.
  - folder (`type`): `icon`, `emotion`, `background`, `user_icon`, còn lại là `other`.
  - itype theo đuôi file: `png/jpg/jpeg/gif/webp/avif` → `image`; `mp3/wav/ogg/flac` →
    `audio`; `mp4/webm/mov/avi/mkv` → `video`; `mmd/obj` → `model`;
    `safetensors/cpkt/onnx` → `ai`; `otf/ttf/woff/woff2` → `fonts`; `js/ts/lua` → `code`;
    còn lại → `other`.
  - `ext === "unknown"` được ghi thành `.png` dưới `assets/<type>/image`.
  - Tên trùng nhau nhận hậu tố `_1`, `_2`…
- `uri` của entry asset được ghi lại thành `embeded://<path>`.
- `x_meta/<uniqueName>.json` được ghi bên cạnh: với PNG là các chunk `tEXt` dưới dạng
  object (hoặc `{"type":"PNG"}` khi không có chunk nào); với kiểu khác là
  `{"type":"WEBP"}`… PocketRisu không bao giờ đọc lại các record này — chúng là tài liệu
  cho công cụ bên ngoài.
- Asset lớn hơn **50 MiB** bị `CharXImporter` loại (`MAX_ASSET_SIZE_BYTES`).

## 6. Chuyển đổi lorebook

Field của entry phía card (`character_book.entries[]`): `keys`, `secondary_keys`,
`content`, `extensions`, `enabled`, `insertion_order`, `constant`, `selective`, `name`,
`comment`, `case_sensitive`, `use_regex`, cùng phần mở rộng của Risu là `mode` và `folder`.

Field của entry phía module (`lorebook[]`): `key` (chuỗi phân cách bằng dấu phẩy),
`secondkey`, `content`, `insertorder`, `comment`, `mode`, `alwaysActive`, `selective`,
`useRegex`, `extentions` (gồm `risu_case_sensitive`, `risu_activationPercent`,
`risu_loreCache`), `folder`, và tùy chọn `activationPercent`, `loreCache`, `id`.

Folder là entry bình thường có `mode: "folder"` và `content` rỗng. Id của nó nằm trong
`key` (module) hoặc `keys[0]` (card), dạng `\uf000folder:<uuid>`; `comment`/`name` của nó
là tên folder hiển thị. Entry con đặt `folder` bằng id đó, và bản thân entry folder cũng có
thể đặt `folder` bằng id của cha, nên folder lồng nhau được. Entry có id `folder` không
khớp folder nào là entry mồ côi: PocketRisu ẩn nó khỏi cây folder, còn `text export` ghi nó
ở gốc lorebook.

Chiều card → module (`convertCharbook`) còn thực hiện các migration sau bằng cách thêm
dòng `@@` vào đầu `content` và xóa khóa extension cũ:

| Extension phía card | Marker trong content phía module |
| --- | --- |
| `useProbability` + `probability` (≠100) | `@@probability N` |
| `position: 4` + `depth` + `role` | `@@depth N`, `@@role system\|user\|assistant` |
| `selectiveLogic: 1` | `@@exclude_keys_all k1,k2` |
| `selectiveLogic: 2` | `@@exclude_keys key` (mỗi key một dòng) |
| `selectiveLogic: 3` | `@@additional_keys key` (mỗi key một dòng) |
| `delay > 0` | `@@activate_only_after N` |
| `match_whole_words: true` | `@@match_full_word` |
| `match_whole_words: false` | `@@match_partial_word` |

`use_regex` bị ép về `false` trừ khi key đầu tiên bắt đầu bằng `/`. `risu_case_sensitive`
luôn được lấy từ `case_sensitive`.

Chiều module → card (`lore_to_charbook`, và phần sync của toolkit) mirror đúng bản export
V3 của PocketRisu: `keys = key.split(',').map(trim)` (key rỗng → `[""]`),
`secondary_keys` chỉ khi `selective`, `insertion_order`, `constant`, `selective`,
`name`/`comment`, `case_sensitive`, `use_regex`, `mode`, `folder`, và các extension được
chép từ `extentions` cộng thêm `risu_activationPercent` / `risu_loreCache` khi có.

## 7. Hình dạng của regex và trigger

`customscript` (`module.regex[]`):

```json
{"comment": "label", "in": "pattern", "out": "replacement", "type": "editdisplay"}
```

`type`: `editinput`, `editoutput`, `editprocess`, `editdisplay`, `editrequest`, `disabled`,
hoặc `""`.

`triggerscript` (`module.trigger[]`):

```json
{"comment": "label", "type": "start", "conditions": [], "effect": [
  {"type": "triggerlua", "code": "..."}
]}
```

`type`: `start`, `manual`, `output`, `input`, `display`, `request`. Conditions và effect là
mảng các object có kiểu; toolkit validate hình dạng container nhưng giữ nguyên từng object
condition/effect.

## 8. Các điểm dị thường đã biết

- `embeded://` bị viết sai chính tả một cách có chủ đích trong định dạng.
- Lorebook của module thắng khi import kể cả khi `card.data.character_book` trông đúng.
- Với PocketRisu, `x_meta` chỉ được ghi chứ không đọc.
- Asset lớn hơn 50 MB biến mất âm thầm khi import.
- File có tên PNG có thể chứa bytes WEBP (`compressImage` của PocketRisu có thể mã hóa lại
  nhưng vẫn giữ đuôi đã khai báo); toolkit chỉ cảnh báo (`ASSET_W_EXT_MISMATCH`) chứ không
  ghi lại đường dẫn.
- Bytes thừa sau marker kết thúc của `module.risum` được giữ nguyên và được báo cáo.
- Bản export của PocketRisu tạo module tên `<character> Module` với lorebook là
  `globalLore` của card; công cụ bên thứ ba có thể tạo archive mà hai lorebook lệch nhau.
