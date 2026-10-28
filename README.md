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
  references/validation-codes.md # toàn bộ mã lỗi/cảnh báo
  LICENSES/                    # giấy phép rpack (MIT / AGPL) + NOTICE
  tests/selftest.py            # 12 kiểm thử tổng hợp, không cần card thật
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
#    -> work/CharX File (6)/text/card/description.md, module/lorebook/*.md, module/regex/*.txt ...
python scripts/charx.py text import "work/CharX File (6)"

# thêm một mục lorebook
python scripts/charx.py book add "work/CharX File (6)" --name "Ghi chú mới" \
  --keys "chia khoa, key phu" --content "Nội dung lore." --order 200

# thay một asset theo index trong data.assets
python scripts/charx.py assets replace "work/CharX File (6)" "#2" "C:/path/anh-moi.webp"

python scripts/charx.py validate "work/CharX File (6)"
python scripts/charx.py pack "work/CharX File (6)" --out "out/CharX File (6)-edited.charx"
python scripts/charx.py diff "C:/path/CharX File (6).charx" "out/CharX File (6)-edited.charx"
```

Kết quả thực tế trên thẻ ví dụ: 660 entry, 30,32 MB, 329 asset (29,98 MB), 36 mục lorebook
lấy từ module, module có 36 lore + 4 regex + 1 trigger. Khi chưa sửa gì, `pack` cho ra file
có **660/660 entry giống hệt từng byte** (kể cả `card.json` và `module.risum`).

## Các lệnh

### Phân tích và đóng gói

| Lệnh | Việc |
| --- | --- |
| `info SOURCE [--json]` | Tổng quan card/module/asset và số cảnh báo |
| `unpack CHARX WORK [--force]` | Giải nén, giải mã module, tạo `_charx/manifest.json` |
| `validate SOURCE [--deep]` | Kiểm tra cấu trúc và tham chiếu |
| `pack WORK --out OUT` | Dựng `.charx` mới; mặc định giữ prefix JPEG |
| `diff LEFT RIGHT [--fail-on-diff]` | So sánh entry (byte) + JSON card/module (ngữ nghĩa) |

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

File lorebook được đặt theo `comment` (module) hoặc `name` (card) đã làm sạch, không còn
tiền tố index; nếu hai mục trùng tên, file sau thêm `_2`, `_3`… Tên không hợp lệ trên
Windows (ký tự cấm, tên thiết bị như `CON`) cũng được làm sạch.

`text/_map.json` lưu hash từng file. `text import` chỉ áp file đã đổi; nếu cả JSON và file
text đều đổi từ lần export thì báo conflict (dùng `--force` để lấy bản text). Mặc định
chuẩn hóa CRLF → LF; giữ CRLF bằng `--keep-crlf`.

### Lorebook

```bash
python scripts/charx.py book list WORK
python scripts/charx.py book add WORK --name "Tên" --keys "a, b" --content-file lore.md \
  --mode normal --order 150 [--selective --secondkeys "c"] [--always-active] [--use-regex]
python scripts/charx.py book remove WORK 12 --yes
python scripts/charx.py book sync WORK --direction module-to-card
```

`book add/remove` tác động lên bản lorebook có hiệu lực (module khi có module). Khi pack,
`auto` sẽ chép thay đổi sang bản còn lại.

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

### Module độc lập

```bash
python scripts/charx.py module decode module.risum --out module.json --assets-dir mod_assets
python scripts/charx.py module encode module.json --out module.risum --assets-dir mod_assets
```

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
- **Windows/Git Bash**: chuỗi bắt đầu bằng `/` bị đổi thành đường dẫn Windows. Thêm
  `MSYS_NO_PATHCONV=1` trước lệnh hoặc viết `//data/description`.
- **Console cp1258**: đặt `PYTHONIOENCODING=utf-8` để in tiếng Hàn/Nhật không lỗi.

## Kiểm thử

```bash
python tests/selftest.py          # 12/12 kiểm thử, tự xóa thư mục tạm
python tests/selftest.py --keep   # giữ tests/.tmp để xem
```

Bộ test dựng card tổng hợp (v3 + module + asset + entry lạ, thêm biến thể charxJpeg và v2)
rồi kiểm tra: round-trip byte-identical, text conflict, sync lorebook, asset add/replace/
remove/gc, raw entry, validate chặn gói hỏng, module decode/encode, và CLI.

## Giấy phép

`scripts/rpack_map.bin` và thuật toán rpack lấy từ PocketRisu (`src/ts/rpack/`), phát hành
theo MIT hoặc AGPL; xem `LICENSES/rpack-NOTICE.md`. Phần còn lại của toolkit dùng tự do
trong phạm vi dự án của bạn.
