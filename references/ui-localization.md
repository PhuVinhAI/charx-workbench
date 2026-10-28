# Bản địa hóa UI của card

Quy trình này dùng khi người dùng muốn **mọi thứ card hiển thị dưới dạng UI** sang tiếng Việt
— không chỉ HUD cuối tin nhắn mà cả selector/màn hình bắt đầu, side panel, nhật ký lệnh, nhãn
trạng thái, nút bấm và thông báo hệ thống do trigger sinh ra. Lorebook, prose và nội dung kể
chuyện **không** thuộc phạm vi trừ khi được yêu cầu riêng.

Nếu card đã có cơ chế đa ngôn ngữ (selector ngôn ngữ, bảng chuỗi i18n), hãy **thêm tiếng Việt**
như một lựa chọn mới thay vì ghi đè ngôn ngữ gốc. Nếu không, dịch lớp hiển thị sang tiếng Việt.

## Nguyên tắc tối thiểu

- Giữ nguyên **marker** (`◈YR`, `◈ML`, `☆★`), **tên field** (`TIME|`, `STAMP|`, `@|`...),
  **mã trạng thái** (`C/H/N`, `on/away/dnd`) và cấu trúc HTML/CSS/CBS.
- Giữ nguyên **ID/class**, `risu-trigger`, tên biến chat, khóa asset và tên biến trong template.
- Chỉ sửa bốn lớp: prompt sinh dữ liệu hiển thị, nhãn tĩnh trong regex/CSS, câu hướng dẫn
  ngôn ngữ, và bảng ánh xạ tên → hiển thị/avatar.
- Giữ bản gốc trong bảng ánh xạ, **thêm** alias Latin thay vì thay thế. Chat cũ và dữ liệu cũ
  vẫn hoạt động.
- Giữ **token lệnh cũ** trong regex (`/미팅`, `/시연회`) và thêm alias mới (`/hop`, `/demo`).
  Không đổi tên lệnh cũ thành chữ Latin trong chính regex nếu người dùng vẫn gõ lệnh Hàn.
- Không đổi thứ tự ngày/tháng nếu script đang parse. Ví dụ Lua đọc `STAMP` bằng
  `(%d+)[%./](%d+)` và hiểu là tháng.ngày: giữ `10.21`, chỉ dịch phần thứ trong ngoặc.
- Không đổi line ending của code không liên quan. File Lua phải giữ LF; nếu ghi qua công cụ
  Windows, kiểm tra `\r\n` trước khi `set`.
- Dịch theo giọng của card: UI hiện đại có thể dùng "Chọn lại", "Bắt đầu", "Đang review";
  UI học thuật có thể dùng "Họp lab · Biên bản", "Dự án đang triển khai".

## 1. Kiểm kê toàn bộ bề mặt UI

```bash
python scripts/charx.py text export "work/card"
find "work/card/text" -type f | sort
grep -rlP '[\x{AC00}-\x{D7A3}]' "work/card/text/module/regex" \
  "work/card/text/card/extensions" 2>/dev/null
```

Lập bảng trước khi sửa — mỗi dòng là một bề mặt, không gộp:

| Bề mặt | Nơi thường nằm | Dấu hiệu |
| --- | --- | --- |
| Prompt sinh dữ liệu | `module/lorebook/.../HUD.md` hoặc entry có marker | `◈...◈`, mô tả field, câu "Write ... in Korean" |
| Selector / màn hình bắt đầu | `module/regex/<tên>.out.txt` | `in` là `☆★`; `out` có phòng ban, scene card, nút bắt đầu |
| HUD | regex `HUD` + `card/extensions/backgroundHTML.html` | `in` chứa `◈...`; `out` có `$1...`, class HUD, nhãn tĩnh |
| Side panel | regex `사이드패널`/`sidepanel` + trigger | `{{getvar::...}}`, nhãn "프로젝트", "생일", "채널", "멤버" |
| Nhật ký lệnh | regex `회의록`, `시연 로그`, lệnh `/...` | marker `[ML_MEETING]`, `[ML_DEMO]`, khung chat/Slack |
| Thông báo trigger | trigger Lua/CJS | `print(...)`, `addChat`, biến `ml_ws`, `ml_tab`, trạng thái dự án |
| Lệnh gõ | regex `.in.txt` | `in` chứa `/미팅`, `/시연회`; note nhắc lệnh |
| CSS nhãn tĩnh | `backgroundHTML.html` / `backgroundEmbedding` | `content:"..."`, `::before`, tooltip |

Xem nhanh trigger:

```bash
MSYS_NO_PATHCONV=1 python scripts/charx.py get "work/card" \
  /module/trigger/0/effect/0/code --target module
```

## 2. Dịch selector và nhãn tĩnh

Trong `<selector>.out.txt`, chỉ thay chữ hiển thị:

- tiêu đề/kicker, tên phòng ban, tên và mô tả scene card, nhãn kiến thức/thời tiết;
- chữ trên nút (`Bắt đầu`, `Chọn lại`), `Lv.3` → `Cấp 3`, địa danh trong caption;
- tên nhân vật trong caption và chữ cái đầu avatar → Latin.

Giữ `$1...`, `{{...}}`, class, `risu-trigger`, `data-*`. Nếu selector dùng ảnh asset, không đổi
`src`/`{{raw::...}}`. Kiểm tra cân bằng `<div>`/`</div>` sau khi dịch.

Với side panel, dịch nhãn mục (`Dự án đang triển khai`, `Sinh nhật`, `Kênh`, `Thành viên`) và
nhãn trạng thái; tên thành viên lấy từ biến trigger nên phải xử lý ở bước 4.

## 3. Prompt sinh HUD/dữ liệu

Thêm đúng một câu chỉ thị ngôn ngữ, không viết lại toàn bộ entry. Câu mẫu giữ tiếng Anh vì nó
nằm trong prompt của card (phần lớn card viết prompt bằng tiếng Anh); chỉ nội dung hiển thị
mới cần tiếng Việt:

```text
Write every HUD value in Vietnamese; keep the field names and block markers unchanged.
Do not use Korean anywhere in the HUD block.
```

Nếu field dẫn chiếu bảng gốc (ví dụ `CALL` theo `ADDRESS TERMS`), thêm yêu cầu render field đó
bằng tiếng Việt (`rendered in Vietnamese (for example {{user}} ạ or cậu)`), nếu không model có
thể chép nguyên kính ngữ tiếng Hàn vào HUD.

Với dữ liệu có tên nhân vật, nói rõ dùng chữ Latin đúng như bảng tham chiếu:

```text
Write every value in Vietnamese; keep names in Latin script exactly as in QUICK REFERENCE.
Do not use Korean anywhere in the HUD block.
```

Dịch **các giá trị trong block ví dụ** (TIME, LOC, OUTER, INNER, NEXT, CALL, LEGEND, STAMP,
PIN, status...). Giữ nguyên tên field, marker và mã. Không cần dịch phần hướng dẫn kỹ thuật
còn lại nếu tác giả viết tiếng Anh.

## 4. Trigger: tên hiển thị, trạng thái, thông báo

Đây là nơi UI Việt hóa dễ sót nhất. Xử lý từng nhóm:

**Tên hiển thị.** Giữ nguyên bảng khóa Hàn (dùng để khớp dữ liệu và avatar), thêm bảng dịch:

```lua
local DISPLAY_NAMES = {
  ["차예린"] = "Cha Yerin", ["남지훈"] = "Nam Jihoon",
  ["박로아"] = "Park Roa", ["신민규"] = "Shin Mingyu",
}
local function displayName(name) return DISPLAY_NAMES[name] or name end
```

Áp dụng `displayName()` ở mọi chỗ đưa tên vào UI: side panel, `bday_today`/`bday_soon`, log,
thông báo. Tên trong HUD do model sinh sẽ là Latin; bảng alias avatar phải khớp chính xác
chuỗi đó (xem bước 5).

**Nhãn hệ thống.** Dịch workspace/tab/bot (`ml_ws`, `ml_tab`, `ml_bot`, `ml_ic`), trạng thái
dự án (`Kế hoạch`, `Demo: ...`), thông báo lệnh (`Đã lưu biên bản`, `Đã ghi nhật ký demo`).

**Lệnh.** Mở rộng regex đầu vào, giữ token cũ:

```text
/(?:미팅|hop)[ \t]*([^\n]*)
/(?:시연회|demo)[ \t]*([^\n]*)
```

Cập nhật note nhắc lệnh và regex xóa note (`── (?:위|Nhập)...`) để cả lệnh cũ và mới đều sạch.
Không đổi nhóm capture hoặc thứ tự `$1...` trong output.

**Dữ liệu parse.** Nếu trigger đọc marker/ngày từ HUD, giữ nguyên định dạng. Nếu tên trong
`ml_next` là khóa Hàn, chỉ dịch lúc hiển thị, không đổi giá trị lưu.

## 5. Bắt tên Latin để hiện avatar/UI

Nếu regex chỉ capture tên rồi dùng làm khóa (`{{getvar::av_$4}}`), regex thường **không cần
sửa**: nhóm `((\S)[^|\n]*?)` đã nhận cả tên có dấu cách. Vấn đề nằm ở bảng ánh xạ.

Thêm alias Latin vào bảng gốc, trỏ cùng asset:

```lua
local AVATARS = {
  { "차예린", "yerin" }, ...,
  -- Latin-script HUD names → the same avatar asset
  { "Cha Yerin", "yerin" }, { "Nam Jihoon", "jihoon" }, ...,
}
```

Yêu cầu:

- Alias phải **khớp chính xác** chuỗi UI sẽ in, kể cả dấu cách và hoa/thường. PocketRisu
  truyền thẳng tham số `getvar`, không trim, nên `av_Cha Yerin` là khóa hợp lệ và khớp
  `setChatVar(id, "av_Cha Yerin", ...)`.
- Chỉ thêm alias, không xóa khóa Hàn. Chat cũ, log cũ và regex khác vẫn dùng được.
- Nếu regex/trigger có nhánh `if name == "..."` hoặc `equal::{{...}}::Tên`, thêm nhánh Latin
  tương ứng; không đổi điều kiện cũ.
- Xác nhận asset đích tồn tại, ví dụ `assets/other/image/sp_yerin.png`.

## 6. Card có nhiều ngôn ngữ sẵn

Nếu card có selector ngôn ngữ hoặc bảng chuỗi i18n, **không** thay chuỗi gốc. Thêm nhánh `vi`:

- thêm lựa chọn `Tiếng Việt` vào selector;
- thêm bảng chuỗi `vi` bên cạnh `ko`/`en`, giữ khóa;
- trỏ các nhãn UI sang bảng theo ngôn ngữ đang chọn;
- giữ mặc định cũ nếu người dùng chưa chọn.

Nếu cấu trúc i18n quá phức tạp để thêm an toàn, dừng lại và báo rõ thay vì phá cơ chế gốc.

## 7. Áp dụng và kiểm chứng

```bash
python scripts/charx.py text import "work/card"
# nếu sửa Lua:
python scripts/charx.py set "work/card" /module/trigger/0/effect/0/code \
  --target module --file trigger_vi.lua

python scripts/charx.py validate "work/card"
python scripts/charx.py pack "work/card" --out "out/"
python scripts/charx.py diff "C:/path/source.charx" "out/<tên card>.charx"
```

Kỳ vọng của `diff`:

- `entries`: 0 added/removed/changed.
- `Card`: các entry UI trong bản card book + `backgroundHTML` (nếu có).
- `Module`: lorebook prompt, các regex UI, trigger code đã sửa.
- Bản card book và module lorebook cùng đổi vì `pack --sync-book auto` chép bản module
  (module thắng khi import). Đây là thay đổi dẫn xuất, không phải sửa thêm.

Kiểm tra từng regex bằng mẫu thật (Node dùng cùng cú pháp `$1`):

```bash
node - <<'JS'
const fs = require('fs');
const raw = JSON.parse(fs.readFileSync('work/card/module.json', 'utf8'));
const mod = raw.module || raw;
const find = (name) => mod.regex.find(x => x.comment === name);
const apply = (r, s) => s.replace(new RegExp(r.in, 'g'), r.out);

let html = apply(find('셀렉터'), '☆★');
if (html.includes('☆★') || /[\uac00-\ud7a3]/.test(html)) process.exit(1);
if (!html.includes('Bắt đầu')) process.exit(1);

const hud = apply(find('HUD'), `◈ML
STAMP|10.21 (Thứ Ba) · 15:40
LOC|Tòa Công trình, tầng 4, phòng 409
@|Cha Yerin|dnd|📝|Đang review.
◈`);
if (!hud.includes('Cha Yerin') || /\$[0-9]+\b/.test(hud)) process.exit(1);
console.log('UI regex OK');
JS
```

Rà soát cuối:

- Quét Hangul theo từng lớp. Mức mong đợi: **0** ở prompt UI, regex OUT, `backgroundHTML`,
  thông báo trigger. Hangul còn lại chỉ được phép ở khóa gốc trong bảng ánh xạ, comment CSS,
  token lệnh cũ trong regex IN, và ví dụ ngôn ngữ Hàn có chủ đích.
- Đếm `<div>`/`</div>` trong OUT của selector/side panel/HUD.
- Mọi alias Latin có asset `sp_*` tương ứng.
- Lệnh cũ và mới đều match; note cũ và mới đều bị xóa.
- `validate` 0 error; warning tồn tại trước đó được ghi lại.
- Không thể chạy PocketRisu trong môi trường hiện tại thì nói rõ: đã kiểm tra tĩnh
  (regex + dữ liệu + pack/diff), chưa xem render thực tế.

## 8. Lỗi thường gặp

| Hiện tượng | Nguyên nhân / xử lý |
| --- | --- |
| Diff trigger đổi toàn bộ file vì `\r\n` | File Lua tạm bị ghi CRLF. Chuyển về LF (`data.replace(b"\r\n", b"\n")`) rồi `set` lại. |
| Avatar trắng hoặc sai người | Tên UI không khớp alias `av_...` (khoảng trắng/hoa-thường) hoặc thiếu asset `sp_*`. |
| HUD vẫn ra tiếng Hàn | Prompt chưa có câu bắt buộc; ví dụ trong prompt vẫn là tiếng Hàn; hoặc model đang bám ví dụ cũ. |
| Selector còn tiếng Hàn | Còn nhãn trong OUT, caption scene, chữ cái đầu avatar hoặc CSS `content:"..."`. |
| Side panel hiện tên Hàn | Trigger đưa khóa gốc vào UI mà không gọi `displayName()`; hoặc biến `ml_*` chưa dịch. |
| Lệnh mới không chạy | Regex IN thiếu alias, hoặc PocketRisu đã trim mất dấu `/`; kiểm tra bằng mẫu `"/hop abc"`. |
| Note lệnh còn sót | Regex xóa note chỉ khớp `── 위`, chưa thêm `── Nhập`. |
| Regex không match block | Đã đổi marker/field key/thứ tự field. Giữ nguyên marker và thứ tự. |
| Sinh nhật/ngày sai sau khi Việt hóa | Đã đổi `MM.DD` thành `DD.MM` trong khi Lua parse tháng.ngày. Giữ `MM.DD`. |
| `BOOK_W_DIVERGENT` trước khi pack | Bình thường khi mới sửa module; `pack --sync-book auto` sẽ đồng bộ card book. |
| Dịch nhầm lore/prose | Ngoài phạm vi UI; hoàn nguyên và chỉ sửa bề mặt hiển thị được yêu cầu. |
