# Công thức chỉnh sửa

Mọi lệnh chạy từ thư mục `charx-workbench` (hoặc thay `scripts/charx.py` bằng đường dẫn
đầy đủ). Trên Git Bash, đặt `MSYS_NO_PATHCONV=1` khi dùng pointer bắt đầu bằng `/`.

## 0. Chuẩn bị

```bash
export PYTHONIOENCODING=utf-8
python scripts/charx.py info "C:/path/card.charx" --json > info.json
python scripts/charx.py unpack "C:/path/card.charx" "work/card"
python scripts/charx.py validate "work/card"
```

Xem `info.json` để biết `lore_source` (`module` hay `card`), `module.present`, layout, số
asset và các cảnh báo có sẵn. **Cảnh báo có sẵn từ nguồn không phải lỗi do bạn gây ra** —
ghi lại để báo cáo, đừng cố sửa nếu không được yêu cầu.

## 1. Sửa văn bản của card

Trường ngắn:

```bash
python scripts/charx.py set "work/card" /data/first_mes --string "Xin chào."
python scripts/charx.py set "work/card" /data/creator_notes --file notes.txt
python scripts/charx.py set "work/card" /data/alternate_greetings/0 --string "Lời chào khác."
```

Trường dài (description, first_mes, ví dụ hội thoại, HTML nền, lorebook, regex, CJS):

```bash
python scripts/charx.py text export "work/card"
# sửa trực tiếp work/card/text/... bằng editor
python scripts/charx.py text import "work/card"
```

`text import` chỉ áp file có nội dung đổi; file JSON và file text cùng đổi từ lần export sẽ
báo `conflicts` và **không** ghi đè (trừ khi `--force`). Sau khi import thành công, hash
trong `_map.json` được cập nhật.

Danh sách trường được export nằm trong `references/charx-format.md` (mục `card.json` và
`module.risum`) và hàm `_text_targets`; tóm tắt: 8 trường card, alternate greetings,
risuai text, depth prompt, lorebook hiệu lực, module
name/description/cjs/backgroundEmbedding/customModuleToggle, regex in/out.

## 2. Thêm/xóa/sửa lorebook

Xác định bản hiệu lực:

```bash
python scripts/charx.py book list "work/card"
```

Kết quả có `"source": "module"` hoặc `"card"`. `book list --json` cũng trả về `folder`
(id) và `folder_path` cho từng entry, cùng danh sách `folders`.

### Thêm

```bash
python scripts/charx.py book add "work/card" \
  --name "TÊN MỤC" --keys "từ khóa 1, từ khóa 2" --content-file lore.md \
  --mode normal --order 150 --folder "Tên folder"   # hoặc "Cha/Con"
# tùy chọn: --selective --secondkeys "khóa phụ" --always-active --use-regex --case-sensitive
```

`book add` ghi vào bản hiệu lực. Khi pack, `--sync-book auto` (mặc định) chép sang bản kia.

### Tạo folder và di chuyển mục

```bash
python scripts/charx.py book folder add "work/card" --name "Folder mới"
python scripts/charx.py book folder add "work/card" --name "Con" --parent "Folder mới"
python scripts/charx.py book move "work/card" 12 --folder "Folder mới/Con"
python scripts/charx.py book move "work/card" 12 --folder ""     # đưa về gốc
```

`--parent`/`--folder` nhận id `\uf000folder:...`, tên folder (nếu duy nhất) hoặc đường dẫn
hiển thị `Cha/Con`. `book folder add` tự sinh UUID; có thể truyền id cố định bằng `--id`.
`book move` từ chối đưa folder vào chính nó hoặc folder con của nó.

### Sửa nội dung

Cách 1 — qua text export/import (khuyên dùng cho văn bản dài):

```bash
python scripts/charx.py text export "work/card"
# work/card/text/module/lorebook/[FOLDER/]TÊN_MỤC.md
# hoặc work/card/text/card/character_book/[FOLDER/]TÊN_MỤC.md
python scripts/charx.py text import "work/card"
```

Cách 2 — sửa trực tiếp pointer:

```bash
# có module
python scripts/charx.py set "work/card" /module/lorebook/12/content --file lore.md --target module
# không có module
python scripts/charx.py set "work/card" /data/character_book/entries/12/content --file lore.md
```

### Sửa khóa, chế độ, thứ tự

```bash
python scripts/charx.py set "work/card" /module/lorebook/12/key --string "alpha, beta" --target module
python scripts/charx.py set "work/card" /module/lorebook/12/secondkey --string "gamma" --target module
python scripts/charx.py set "work/card" /module/lorebook/12/insertorder 250 --target module
```

Sau đó pack với `auto` để cập nhật bản card. Nếu muốn kiểm soát tay:

```bash
python scripts/charx.py book sync "work/card" --direction module-to-card
# hoặc card-to-module
```

### Xóa

```bash
python scripts/charx.py book remove "work/card" 12 --yes
```

Index là vị trí trong danh sách hiệu lực (đúng như `book list`). Không xóa theo tên để tránh
nhầm khi có mục trùng tên.

### Lưu ý về hai bản lorebook

Khi có module, PocketRisu **bỏ qua** `card.data.character_book`. Nếu sửa trực tiếp card mà
module không đổi, `pack --sync-book auto` sẽ chép card → module. Nếu sửa cả hai, module
thắng và bản card bị ghi đè. Cách an toàn: luôn dùng `book ...` hoặc `--target module`.

## 3. Sửa regex

Xem danh sách:

```bash
python scripts/charx.py get "work/card" /module/regex --target module
```

Sửa pattern/replacement:

```bash
python scripts/charx.py set "work/card" /module/regex/0/in --file pattern.txt --target module
python scripts/charx.py set "work/card" /module/regex/0/out --file replacement.txt --target module
python scripts/charx.py set "work/card" /module/regex/0/type --string "editdisplay" --target module
```

Hoặc dùng `text export`: mỗi regex sinh hai file `<COMMENT>.in.txt` và `<COMMENT>.out.txt`
trong `module/regex/` (tên làm sạch từ `comment`; trùng tên thêm `_2`, `_3`…).

Thêm regex mới — tạo file JSON chứa object rồi append:

```bash
cat > regex.json <<'JSON'
{"comment": "Lọc từ", "in": "foo", "out": "bar", "type": "editdisplay"}
JSON
python scripts/charx.py set "work/card" /module/regex/- --json-file regex.json --target module
```

Lưu ý: `type` phải là một trong `editinput`, `editoutput`, `editprocess`, `editdisplay`,
`editrequest`, `disabled`, `""`. Regex phải giữ cặp phân cách hợp lệ nếu là regex thật.

## 4. Sửa trigger

Trigger là mảng object `{comment, type, conditions, effect}`. Sửa code Lua/JS bên trong:

```bash
python scripts/charx.py set "work/card" /module/trigger/0/effect/0/code --file code.lua --target module
```

Thêm trigger mới:

```bash
cat > trigger.json <<'JSON'
{"comment": "mới", "type": "output", "conditions": [], "effect": [{"type": "triggerlua", "code": "-- code"}]}
JSON
python scripts/charx.py set "work/card" /module/trigger/- --json-file trigger.json --target module
```

`type` hợp lệ: `start`, `manual`, `output`, `input`, `display`, `request`. Không đổi cấu
trúc `conditions`/`effect` nếu không có lý do; mỗi object con được giữ nguyên khi pack.

Nếu card **không có module**, trigger nằm ở
`/data/extensions/risuai/triggerscript` và regex ở `/data/extensions/risuai/customScripts`
(`--target card`). Khi có module, các trường card này bị bỏ qua lúc import.

## 5. Sửa CJS, HTML nền, toggle

```bash
python scripts/charx.py text export "work/card"
# work/card/text/module/cjs.js
# work/card/text/module/backgroundEmbedding.html
# work/card/text/module/customModuleToggle.txt
python scripts/charx.py text import "work/card"
```

Hoặc:

```bash
python scripts/charx.py set "work/card" /module/cjs --file cjs.js --target module
python scripts/charx.py set "work/card" /module/backgroundEmbedding --file bg.html --target module
```

HTML nền của card (khi không dùng module) ở `/data/extensions/risuai/backgroundHTML`.
Giữ nguyên mọi placeholder `{{...}}`, biến `getvar/setvar`, thẻ HTML và cú pháp template.

## 6. Asset

### Liệt kê và tìm tham chiếu

```bash
python scripts/charx.py assets list "work/card"
python scripts/charx.py assets refs "work/card" "#2"
python scripts/charx.py assets refs "work/card" "bg"
```

`#N` = index trong `data.assets`; `"bg"` = tên asset; cũng nhận đường dẫn
`assets/other/image/bg.webp` hoặc URI.

### Thay bytes, giữ nguyên đường dẫn (khuyên dùng)

```bash
python scripts/charx.py assets replace "work/card" "#2" "C:/path/moi.webp"
```

Đường dẫn entry không đổi nên mọi `embeded://` và `x_meta` vẫn hợp lệ. Nếu đuôi file khai
báo khác loại bytes thật, lệnh trả `warning` và vẫn giữ đường dẫn (đúng hành vi của
PocketRisu); cân nhắc đổi cả `ext` nếu cần.

### Thêm asset mới

```bash
python scripts/charx.py assets add "work/card" "C:/path/nem.png" \
  --name "nem" --type x-risu-asset
```

Lệnh tạo file dưới `assets/<type>/<itype>/`, thêm entry vào `data.assets` với
`embeded://...`, và tạo `x_meta/nem.json`. Đường dẫn trùng tên sẽ được tự động thêm `_1`.
`--no-entry` chỉ chép file, không thêm vào `data.assets` (dùng cho file phụ).

### Xóa asset

```bash
python scripts/charx.py assets remove "work/card" "#2" --yes
python scripts/charx.py assets gc "work/card"          # chỉ liệt kê
python scripts/charx.py assets gc "work/card" --move --yes
```

`remove` gỡ entry khỏi `data.assets` và chuyển file + `x_meta` vào `_charx/removed/<thời
gian>/`, không xóa vĩnh viễn. `gc` tìm file asset không còn được tham chiếu.

### Ảnh chân dung / main icon

- `uri: "ccdefault:"` trỏ tới ảnh chân dung của card (JPEG prefix hoặc ảnh card).
- Asset `type: "icon"`, `name: "main"` là main icon. Thiếu cả hai → cảnh báo
  `ASSET_W_MAIN_ICON`.
- Với charxJpeg, thay ảnh bìa bằng `pack --jpeg-prefix new.jpg`. Không tự bịa bytes.

### Asset trong module

Các block asset của module nằm ở `work/card/_charx/module_assets/<index>_<tên>.<ext>`.
Có thể thay file tại chỗ rồi `pack` (module.risum sẽ chứa bytes mới), hoặc dùng lệnh để
đồng bộ cả metadata:

```bash
python scripts/charx.py module assets list "work/card"
python scripts/charx.py module assets replace "work/card" "#0" new.png
python scripts/charx.py module assets replace "work/card" "mod_asset" new.png \
  --name ten_moi --ext png
```

Target nhận `#index`, số index, tên asset (so khớp cả tên trong `module.json` và tên file
local) hoặc `module-asset://N`. Lệnh cập nhật file local, `module.json` (`assets[i]` =
`[name, module-asset://i, ext]`) và `_charx/manifest.json`; `pack` mới đưa bytes vào
`module.risum`. Không sửa `module.risum` bằng tay.

### Asset v2

Với layout v2, asset nằm ở `legacy_assets/` sau khi unpack và entry gốc là
`chara-ext-asset_:N` (base64). Thay bytes:

```bash
python scripts/charx.py assets replace "work/card" "chara-ext-asset_:0" new.png
```

`pack` sẽ base64-encode lại đúng entry đó. Asset v2 không có `x_meta`; `replace` chỉ đổi
bytes (trừ khi truyền `--meta`), nên `diff` chỉ báo đúng entry vừa thay.

## 7. Entry tùy ý / file lạ

```bash
python scripts/charx.py raw get "work/card" notes/readme.txt --out readme.txt
python scripts/charx.py raw put "work/card" extras/data.bin data.bin
python scripts/charx.py raw rm "work/card" extras/data.bin --yes
```

`raw put` vào đường dẫn mới sẽ thêm entry; vào đường dẫn đã có sẽ thay bytes. Entry không
nằm trong manifest vẫn được giữ khi pack. Không dùng `raw` cho `card.json`,
`module.json`, `module.risum` (lệnh sẽ từ chối; `raw put` cũng từ chối các đường dẫn thuộc
`_charx/` và `text/`). Entry gốc có tên trùng thư mục dành riêng của tool (`text/`,
`_charx/`, file ẩn, `*.tmp`, `module.json`…) được cất dưới
`_charx/original/entries/` nhưng vẫn được pack lại đúng tên gốc.

## 8. Chỉnh sửa module.risum khi không có module.json

```bash
python scripts/charx.py module decode "work/card/_charx/original/module.risum" \
  --out module.json --assets-dir module_assets
# sửa module.json (hoặc chép vào work/card/module.json rồi pack)
python scripts/charx.py module encode module.json --out module.risum --assets-dir module_assets
```

Nếu `unpack` báo `module.risum could not be decoded`, file gốc vẫn được giữ nguyên và pack
sẽ ghi lại đúng bytes đó; mọi thay đổi cấu trúc module phải chờ giải mã thành công.

## 9. CharxJpeg và layout

```bash
python scripts/charx.py pack "work/card" --out out/                       # giữ prefix
python scripts/charx.py pack "work/card" --no-prefix                      # bỏ prefix
python scripts/charx.py pack "work/card" --out out/ --jpeg-prefix new.jpg
```

Không có `--out`, file được ghi thành `<tên card>.charx` trong thư mục hiện tại; nếu `--out`
là thư mục (hoặc kết thúc bằng `/`), file nằm trong thư mục đó. Tên lấy từ `data.name` của
card và được làm sạch; nếu trống thì dùng tên lorebook/module/archive nguồn. `pack` từ chối
ghi đè chính file nguồn.

Với v2, pack ghi entry `chara` (base64 compact JSON) và các `chara-ext-asset_:N`; không tự
chuyển v2 → v3. Muốn chuyển đổi cấu trúc, phải viết lại card theo chuẩn đích và cập nhật
asset reference tương ứng — ngoài phạm vi các lệnh hiện có.

## 10. Kiểm tra trước khi giao

```bash
python scripts/charx.py validate "work/card"
python scripts/charx.py pack "work/card" --out "out/"   # -> out/<tên card>.charx
python scripts/charx.py diff "C:/path/card.charx" "out/<tên card>.charx"
```

- `validate` phải 0 error. Warning có sẵn từ nguồn thì ghi lại, không cần sửa.
- `diff` phải chỉ ra đúng các pointer đã sửa. Với bản không sửa, `pack` phát hiện work
  chưa đổi (manifest, card, module, prefix và mọi file local đều khớp baseline) nên **sao
  chép nguyên file nguồn** — hash SHA-256 của cả archive giống hệt và `diff` rỗng. Khi có
  sửa, `pack` dựng lại archive: entry không sửa giống hệt từng byte, entry bị đổi được nén
  lại (giữ `compress_type`/timestamp), nên chỉ so `diff` theo entry; hash cả file có thể
  khác dù nội dung đúng.
- File người dùng đặt trong `text/` mà không do `text export` tạo ra sẽ được giữ nguyên và
  báo ở `unmapped`; đừng dựa vào export để dọn chúng.
- Không ghi đè file nguồn; luôn xuất ra đường dẫn mới.
- Báo cáo: file/pointer đã đổi, kết quả validate, cảnh báo tồn tại trước đó, phần chưa giải
  mã được (nếu có).

## 11. Lỗi thường gặp

| Hiện tượng | Nguyên nhân / cách xử lý |
| --- | --- |
| `ENTRY_E_MISSING` / `pack` báo entry không có file local | File gốc đã bị xóa khỏi work. Khôi phục file (hoặc unpack lại vào thư mục mới) thay vì `--force` để tránh mất entry. |
| `JSON pointer not found: C:/Program Files/Git/data/...` | Git Bash đổi `/data/...` thành đường dẫn. Dùng `MSYS_NO_PATHCONV=1` hoặc `//data/...`. |
| `UnicodeEncodeError` khi in tiếng Hàn | Đặt `PYTHONIOENCODING=utf-8`. |
| `pack` báo `ASSET_E_MISSING` | `data.assets` trỏ tới entry không có trong work. Khôi phục file hoặc sửa URI. |
| `MOD_E_ASSET_COUNT` | Số `module.assets` khác số block trong `module.risum`. Không sửa tay; dùng `module decode`/`encode` hoặc `pack` từ work nhất quán. |
| `BOOK_W_DIVERGENT` | Hai bản lorebook khác nhau. Import dùng module; dùng `book sync` nếu muốn thống nhất. |
| `text import` báo conflict | JSON và file text cùng đổi. Xem lại, hoặc `--force` để lấy bản text. |
| `pack` từ chối vì validation | Đọc danh sách lỗi; sửa work rồi pack lại. `--force` chỉ dùng khi thật sự hiểu rủi ro. |
| `Refusing to overwrite the source archive` | `--out` trỏ đúng file nguồn. Đổi sang thư mục khác hoặc bỏ `--out` để dùng tên card. |

## 12. Việt hóa toàn bộ UI của card

Với yêu cầu "mọi thứ card hiển thị dạng UI sang tiếng Việt", chỉ sửa lớp hiển thị; không dịch
lore/prose. Kiểm kê đủ bề mặt trước khi sửa:

1. `text export`; quét Hangul trong `module/regex`, `card/extensions`; đọc trigger để tìm
   `print`, biến `ml_*`/`*_ws`/`*_tab`, bảng `AVATARS`, trạng thái dự án.
2. Selector/màn hình bắt đầu: dịch kicker, phòng ban, scene card, caption, nút, chữ cái đầu
   avatar trong `<selector>.out.txt`; giữ `$1...`, `{{...}}`, class, `risu-trigger`.
3. Side panel + nhật ký lệnh: dịch nhãn tĩnh trong regex OUT; thêm bảng `DISPLAY_NAMES` và
   gọi `displayName()` ở mọi chỗ đưa tên vào UI; dịch `ml_ws`/`ml_tab`/`ml_bot`, trạng thái.
4. HUD: thêm một câu `Write every HUD value in Vietnamese...`; dịch block ví dụ; giữ marker
   (`◈YR`, `◈ML`), field key (`TIME|`, `STAMP|`), mã (`C/H/N`, `on/away/dnd`) và thứ tự ngày
   mà script parse (`MM.DD`). Dịch nhãn tĩnh trong HUD OUT và `content:"..."` của CSS.
5. Tên → avatar: thêm alias Latin vào bảng `AVATARS`/`av_` (giữ khóa gốc); regex capture tên
   thường không cần đổi. Alias phải khớp đúng chuỗi UI in ra (PocketRisu không trim `getvar`).
6. Lệnh: mở rộng regex IN `/(?:미팅|hop)...`, `/(?:시연회|demo)...`; giữ token cũ; cập nhật
   note nhắc lệnh và regex xóa note cho cả `── 위` và `── Nhập`.
7. Card có đa ngôn ngữ sẵn: thêm lựa chọn/bảng chuỗi `vi`, không ghi đè ngôn ngữ gốc.
8. `text import` (Lua thì `set ... --file`, giữ LF), `validate`, `pack` ra file mới. `diff`
   phải chỉ thấy các pointer UI + bản card book đồng bộ, `entries` 0 thay đổi.
9. Mô phỏng từng regex bằng mẫu tiếng Việt: marker bị thay, `$n` không sót, nhãn đúng,
   `<div>` cân bằng, `av_<Tên>`/asset `sp_*` tồn tại; thử cả lệnh cũ và mới.

Chi tiết đầy đủ, mẫu lệnh và lỗi thường gặp: [ui-localization.md](ui-localization.md).
