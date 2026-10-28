# charx-workbench

Bộ công cụ chỉnh sửa **mọi nội dung** trong file thẻ nhân vật PocketRisu `.charx`:
`card.json`, `module.risum`, lorebook, regex, trigger, CJS, HTML nền, asset, `x_meta`,
các entry lạ, và cả layout v2/`charxJpeg`.

Chỉ cần **Python 3.7+**, không cài thêm thư viện. Toàn bộ logic nằm trong
`scripts/charx_core.py`; `scripts/charx.py` là CLI. `scripts/rpack_map.bin` là bảng giải mã
rpack lấy từ PocketRisu (giấy phép trong `LICENSES/`).

## Vì sao dùng work directory

`.charx` là ZIP. Nếu sửa trực tiếp bằng tay rất dễ hỏng các phần nhị phân (`module.risum`),
sai đường dẫn `embeded://`, lệch `x_meta`, hoặc mất entry không nhận diện được. Quy trình ở
đây:

1. `unpack` giải nén archive ra một cây thư mục, giải mã `module.risum` thành `module.json`.
2. Sửa `card.json`, `module.json`, file text, asset… bằng lệnh chuyên dụng.
3. `pack` dựng lại `module.risum` từ JSON rồi đóng gói thành `.charx` **mới**.
4. `diff` chứng minh chỉ đúng các trường yêu cầu thay đổi.

File nguồn không bao giờ bị ghi đè.

## Cấu trúc

```
charx-workbench/
  SKILL.md                     # quy ước vận hành cho agent
  README.md                    # file này
  scripts/charx.py             # CLI
  scripts/charx_core.py        # thư viện lõi
  scripts/rpack_map.bin        # bảng rpack 512 byte (PocketRisu)
  references/charx-format.md   # đặc tả định dạng + nguồn PocketRisu
  references/editing-recipes.md # công thức cho từng loại chỉnh sửa
  references/ui-localization.md # quy trình Việt hóa toàn bộ UI (selector/HUD/panel/log/lệnh)
  references/character-split.md # quy trình tách 1 nhân vật từ card đa nhân vật thành card riêng
  references/validation-codes.md # toàn bộ mã lỗi/cảnh báo
  LICENSES/                    # giấy phép rpack (MIT / AGPL) + NOTICE
  tests/selftest.py            # 25 kiểm thử tổng hợp, không cần card thật
```

## Bắt đầu nhanh

Ví dụ với `C:/path/CharX File (6).charx` (thẻ thật đã dùng để kiểm thử):

```bash
cd "C:/path/to/charx-workbench"
export PYTHONIOENCODING=utf-8          # console cp1258 vẫn in được tiếng Hàn

python scripts/charx.py info "C:/path/CharX File (6).charx"

python scripts/charx.py unpack "C:/path/CharX File (6).charx" "work/CharX File (6)"
python scripts/charx.py validate "work/CharX File (6)"

# sửa một trường ngắn
python scripts/charx.py set "work/CharX File (6)" /data/description --string "Nội dung mới"

# sửa văn bản dài, regex, CJS: xuất ra file rồi nhập lại
python scripts/charx.py text export "work/CharX File (6)"
#    -> text/card/description.md, text/module/lorebook/[FOLDER/]*.md, text/module/regex/*.txt ...
python scripts/charx.py text import "work/CharX File (6)"

# thêm một mục lorebook
python scripts/charx.py book add "work/CharX File (6)" --name "Ghi chú mới" \
  --keys "chia khoa, key phu" --content "Nội dung lore." --order 200

# thay một asset theo index trong data.assets
python scripts/charx.py assets replace "work/CharX File (6)" "#2" "C:/path/anh-moi.webp"

python scripts/charx.py validate "work/CharX File (6)"
python scripts/charx.py pack "work/CharX File (6)" --out "out/"
#    -> out/변유리.charx (tên card đã làm sạch)
python scripts/charx.py diff "C:/path/CharX File (6).charx" "out/변유리.charx"
```

Kết quả thực tế trên thẻ ví dụ: 660 entry, 30,32 MB, 329 asset (29,98 MB), 36 mục lorebook
lấy từ module, module có 36 lore + 4 regex + 1 trigger. Khi chưa sửa gì, `pack` sao chép
nguyên file nguồn: **hash SHA-256 của cả file đầu ra trùng nguồn** (31.795.982 byte), và
tất nhiên 660/660 entry giống hệt từng byte. Khi có sửa, `pack` dựng lại archive, giữ kiểu
nén (DEFLATE/STORED) và timestamp của từng entry; các entry không sửa vẫn giống hệt từng
byte, còn stream DEFLATE của entry bị đổi được nén lại.

`pack` lấy `_charx/manifest.json` làm nguồn sự thật cho các entry gốc, nên entry lạ, entry
ẩn, tên trùng thư mục dành riêng của tool (`text/`, `_charx/`, `module.json`…) vẫn được
đóng gói lại đúng tên và đúng byte. File mới tạo trong work được tự thêm vào archive. Nếu
một entry có trong manifest mà file local đã bị xóa, `validate` báo `ENTRY_E_MISSING` và
`pack` từ chối chạy (trừ khi `--force`).

## Các lệnh

### Phân tích và đóng gói

| Lệnh | Việc |
| --- | --- |
| `info SOURCE [--json]` | Tổng quan card/module/asset và số cảnh báo |
| `unpack CHARX WORK [--force]` | Giải nén, giải mã module, tạo `_charx/manifest.json` |
| `validate SOURCE [--deep]` | Kiểm tra cấu trúc và tham chiếu |
| `pack WORK [--out OUT]` | Dựng `.charx` mới; bỏ `--out` thì tự đặt tên theo tên card |
| `diff LEFT RIGHT [--fail-on-diff]` | So sánh entry (byte) + JSON card/module (ngữ nghĩa) |

`pack` đặt tên file xuất theo `data.name` của card (làm sạch ký tự cấm, giữ tiếng
Hàn/Việt). Nếu `data.name` trống, lần lượt dùng tên lorebook, tên module, rồi tên archive
nguồn. Bỏ `--out` để ghi `<tên card>.charx` vào thư mục hiện tại; nếu `--out` là thư mục
(hoặc kết thúc bằng `/`), file được ghi vào trong thư mục đó. `pack` từ chối ghi đè chính
file nguồn.

`pack` tự động đồng bộ lorebook theo `--sync-book`:

- `auto` (mặc định): so hash của hai bản lorebook với mốc lúc `unpack`. Chỉ bản nào bị sửa
  thì đồng bộ sang bản kia; cả hai cùng sửa thì module thắng (đúng luật import của
  PocketRisu); không sửa gì thì không đụng vào.
- `module-to-card` / `card-to-module`: ép một chiều.
- `off`: không đồng bộ.

### Đọc và sửa JSON

JSON pointer theo RFC 6901. Card dùng `/data/...`; module dùng `/module/...` vì
`module.json` là wrapper `{"type":"risuModule","module":{...}}`.

```bash
python scripts/charx.py get WORK /data/first_mes --raw
python scripts/charx.py get WORK /module/lorebook/3/content --target module
python scripts/charx.py set WORK /data/personality --string "Điềm tĩnh"
python scripts/charx.py set WORK /module/regex/0/out --file out.txt --target module
python scripts/charx.py del WORK /data/tags --yes
```

- `--string TEXT` đặt nguyên văn chuỗi.
- `--file FILE` đọc UTF-8 thành chuỗi (dùng cho văn bản dài).
- `--json-file FILE` đọc giá trị JSON (số, mảng, object…).
- Không có cờ nào thì giá trị được hiểu là JSON nếu parse được, ngược lại là chuỗi.

### Văn bản dài: `text export` / `text import`

`text export` xuất:

- các trường card: `description`, `first_mes`, `mes_example`, `personality`, `scenario`,
  `system_prompt`, `post_history_instructions`, `creator_notes`, alternate greetings;
- `extensions.risuai.backgroundHTML`, `additionalText`, `defaultVariables`,
  `prebuiltAssetCommand`, `prebuiltAssetStyle`, `toggles`, `depth_prompt.prompt`;
- nội dung lorebook **đang có hiệu lực** (module nếu có module);
- module `name`, `description`, `cjs`, `backgroundEmbedding`, `customModuleToggle`;
- regex `in`/`out`.

Lorebook của PocketRisu có hệ thống thư mục: entry `mode: "folder"` giữ tên folder, entry
con trỏ tới folder qua trường `folder`. `text export` dựng lại đúng cây đó, nên mục nằm
trong folder `⚙️ SYSTEM` sẽ thành `module/lorebook/⚙️_SYSTEM/TÊN_MỤC.md`; folder lồng nhau
tạo thư mục lồng nhau. Tên folder và tên file lấy từ `comment` (module) hoặc `name` (card)
đã làm sạch, không còn tiền tố index. Trùng tên trong **cùng một thư mục** thì file/folder
sau thêm `_2`, `_3`…; entry trỏ tới folder không tồn tại được xuất ở gốc. File regex cũng
đặt theo `comment`: `<tên>.in.txt` và `<tên>.out.txt`. Tên không hợp lệ trên Windows (ký tự
cấm, tên thiết bị như `CON`) cũng được làm sạch.

`text/_map.json` lưu hash từng file. `text import` chỉ áp file đã đổi; nếu cả JSON và file
text đều đổi từ lần export thì báo conflict (dùng `--force` để lấy bản text). Mặc định
chuẩn hóa CRLF → LF; giữ CRLF bằng `--keep-crlf`. File do người dùng tự đặt trong `text/`
không nằm trong `_map.json` sẽ **không bị xóa** khi export lại; chúng được liệt kê ở
`unmapped` trong mapping và trong kết quả `text import`.

### Lorebook

```bash
python scripts/charx.py book list WORK
python scripts/charx.py book add WORK --name "Tên" --keys "a, b" --content-file lore.md \
  --mode normal --order 150 [--selective --secondkeys "c"] [--always-active] [--use-regex] \
  [--folder "Tên folder" hoặc "Cha/Con"]
python scripts/charx.py book folder add WORK --name "Folder mới" [--parent "Cha/Con"]
python scripts/charx.py book move WORK 12 --folder "Cha/Con"   # --folder "" để đưa về gốc
python scripts/charx.py book remove WORK 12 --yes
python scripts/charx.py book sync WORK --direction module-to-card
```

`book add/remove/move` tác động lên bản lorebook có hiệu lực (module khi có module). Khi
pack, `auto` sẽ chép thay đổi sang bản còn lại. `book list` hiển thị thêm đường dẫn folder;
`--json` trả về `folder` (id) và `folder_path` cho từng entry, cùng danh sách `folders`.
`book folder add` sinh id `\uf000folder:<uuid>`; `--parent`/`--folder` nhận id, tên folder
hoặc đường dẫn `Cha/Con`, và lệnh move từ chối tạo vòng lặp folder.

### Asset

```bash
python scripts/charx.py assets list WORK
python scripts/charx.py assets refs WORK "#2"        # tìm mọi tham chiếu tới asset
python scripts/charx.py assets add WORK new.png --name bg --type x-risu-asset
python scripts/charx.py assets replace WORK "bg" new.webp
python scripts/charx.py assets remove WORK "#2" --yes  # file được chuyển vào _charx/removed/
python scripts/charx.py assets gc WORK [--move --yes]  # tìm asset không còn được tham chiếu
```

`#N` là index trong `data.assets`; cũng có thể dùng tên asset, đường dẫn entry
(`assets/...`) hoặc URI `embeded://...`. Mỗi asset embed có `x_meta/<tên>.json`; lệnh
add/replace tự cập nhật (PNG có tEXt chunk sẽ được trích xuất).

### Entry tùy ý

```bash
python scripts/charx.py raw get WORK notes/readme.txt --out readme.txt
python scripts/charx.py raw put WORK extras/new.bin new.bin
python scripts/charx.py raw rm WORK extras/old.bin --yes
```

Entry lạ được giữ nguyên tự động khi pack, không cần thao tác gì.

### Module độc lập và asset nhúng trong module

```bash
python scripts/charx.py module decode module.risum --out module.json --assets-dir mod_assets
python scripts/charx.py module encode module.json --out module.risum --assets-dir mod_assets

python scripts/charx.py module assets list WORK
python scripts/charx.py module assets replace WORK "#0" new.png [--name ten] [--ext png]
```

Trong work directory, asset nhúng của module nằm ở
`_charx/module_assets/<index>_<tên>.<ext>`. `module assets replace` nhận `#index`, số
index, tên asset hoặc URI `module-asset://N`, ghi file mới và cập nhật `module.json` +
manifest; `pack` sẽ đưa byte mới vào `module.risum`. Có thể thay byte trực tiếp trong
`_charx/module_assets/` cũng được, nhưng dùng lệnh để tên/đuôi file khớp metadata.

## Những điểm phải nhớ

- **Module thắng card khi import.** Nếu có `module.risum`, PocketRisu dùng
  `module.lorebook`, `module.regex`, `module.trigger`; các bản trong `card.json` bị bỏ qua.
  Vì vậy hãy sửa module (hoặc dùng `book ...`), rồi để `pack` đồng bộ.
- **Không sửa tay `module.risum`.** Sửa `module.json`; `pack` mã hóa lại bằng rpack và giữ
  nguyên các block asset. `module.risum` không giải mã được sẽ được giữ nguyên byte gốc và
  bị chặn sửa cấu trúc cho tới khi `module decode` thành công.
- **Giới hạn 50 MB/asset.** PocketRisu bỏ qua asset lớn hơn khi import.
- **URI asset**: `embeded://` (đúng chính tả của PocketRisu), `ccdefault:` cho ảnh chân dung,
  `__asset:N` cho v2; URL `http(s)` bị bỏ khi import.
- **charxJpeg**: file có prefix JPEG trước ZIP. `pack` giữ prefix; `--no-prefix` để bỏ,
  `--jpeg-prefix file.jpg` để thay.
- **v2**: archive chỉ có `chara` (base64 JSON) và `chara-ext-asset_:N`; công cụ hỗ trợ giải
  nén, sửa và đóng gói lại, nhưng khi import PocketRisu vẫn coi là card v2.
- **UI riêng của card**: Việt hóa mọi bề mặt hiển thị — selector, HUD, side panel, nhật ký
  lệnh, thông báo trigger — bằng prompt ví dụ, nhãn tĩnh trong regex/CSS, alias tên→avatar và
  alias lệnh; giữ marker/field key/mã trạng thái/thứ tự ngày/khóa gốc, thêm tiếng Việt nếu
  card có sẵn đa ngôn ngữ. Mỗi card một quy ước riêng nên bước đầu luôn là khảo sát;
  xem `references/ui-localization.md`.
- **Tách nhân vật khỏi card đa nhân vật**: làm tay theo bằng chứng (hồ sơ lore, greeting,
  bảng dữ liệu trong trigger, họ tên asset). Giữ engine/HUD/selector, asset dùng chung,
  block wrapper và prose; chỉ cắt đơn vị dành riêng cho nhân vật khác; kiểm cả "đủ" lẫn
  "không thừa"; xem `references/character-split.md`.
- **Windows/Git Bash**: chuỗi bắt đầu bằng `/` bị đổi thành đường dẫn Windows. Thêm
  `MSYS_NO_PATHCONV=1` trước lệnh hoặc viết `//data/description`.
- **Console cp1258**: đặt `PYTHONIOENCODING=utf-8` để in tiếng Hàn/Nhật không lỗi.

## Kiểm thử

```bash
python tests/selftest.py          # 25/25 kiểm thử, tự xóa thư mục tạm
python tests/selftest.py --keep   # giữ tests/.tmp để xem
```

Bộ test dựng card tổng hợp (v3 + module + asset + entry lạ, thêm biến thể charxJpeg và v2)
rồi kiểm tra: no-op pack sao chép nguồn byte-identical và tự tắt khi có sửa, `info` của
work khớp archive về số entry/kích thước payload, text conflict, giữ file người dùng trong
`text/`, chặn pack khi thiếu file local, entry ẩn/trùng tên được bảo toàn, diff work↔archive
không báo thay đổi giả, JSON pointer escaping, giới hạn độ sâu/vòng lặp folder, thao tác
folder lorebook, asset nhúng module list/replace, raw path safety, sync lorebook, asset
add/replace/remove/gc, validate gói hỏng, module decode/encode, và CLI.

## Giấy phép

`scripts/rpack_map.bin` và thuật toán rpack lấy từ PocketRisu (`src/ts/rpack/`), phát hành
theo MIT hoặc AGPL; xem `LICENSES/rpack-NOTICE.md`. Phần còn lại của toolkit dùng tự do
trong phạm vi dự án của bạn.
