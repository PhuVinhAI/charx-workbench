# Bản địa hóa UI của card

Quy trình này dùng khi người dùng muốn **mọi thứ card hiển thị dưới dạng UI** sang tiếng
Việt (hoặc hỗ trợ thêm tiếng Việt nếu card đã có cơ chế đa ngôn ngữ). Phạm vi: selector/màn
hình bắt đầu, HUD, side panel, nhật ký lệnh, nhãn trạng thái, nút bấm, tooltip, thông báo hệ
thống do trigger sinh ra. Lorebook, prose và nội dung kể chuyện **không** thuộc phạm vi trừ
khi được yêu cầu riêng.

Quy trình này **làm tay và card-agnostic**. Mỗi card tự đặt marker, tên biến, tên lệnh, cấu
trúc HUD riêng; đừng giả định bất kỳ quy ước nào bên dưới là của card bạn đang sửa. Bước 1
luôn là khảo sát để lấy quy ước của chính card đó.

Nếu card đã có cơ chế đa ngôn ngữ (selector ngôn ngữ, bảng chuỗi i18n), hãy **thêm tiếng
Việt** như một lựa chọn mới thay vì ghi đè ngôn ngữ gốc (mục 8).

## Nguyên tắc tối thiểu

- Chỉ sửa **lớp hiển thị**. Bốn lớp được đụng tới: prompt sinh dữ liệu hiển thị, nhãn tĩnh
  trong regex/CSS/HTML, câu hướng dẫn ngôn ngữ, và bảng ánh xạ tên → hiển thị/avatar.
- Giữ nguyên **marker** và **tên field** của card (bất kể card dùng ký hiệu gì: `◈…◈`,
  `★☆`, `【…】`, `TIME|`, `STAMP|`, `@|`…). Regex của card match theo đúng những chuỗi đó.
- Giữ nguyên **mã trạng thái** (`C/H/N`, `on/away/dnd`, `0/1/2`), ID/class, `risu-trigger`,
  tên biến chat (`getvar`/`setvar`), khóa asset, tên biến trong template.
- **Thêm, đừng thay thế.** Giữ bản gốc trong bảng ánh xạ và thêm alias Latin; giữ token lệnh
  gốc và thêm alias tiếng Việt. Chat cũ, log cũ và dữ liệu cũ vẫn phải hoạt động.
- Không đổi **thứ tự ngày/tháng** nếu script đang parse. Ví dụ Lua đọc `STAMP` bằng
  `(%d+)[%./](%d+)` và hiểu là tháng.ngày: giữ `10.21`, chỉ dịch phần chữ trong ngoặc.
- Không đổi line ending của code không liên quan. File Lua phải giữ LF; nếu ghi qua công cụ
  Windows, kiểm tra `\r\n` trước khi `set`.
- Dịch theo giọng của card: UI hiện đại dùng "Chọn lại", "Bắt đầu", "Đang review"; UI học
  thuật dùng "Họp lab · Biên bản", "Dự án đang triển khai"; UI cổ trang dùng xưng hô phù hợp.
- Không chắc một chuỗi là UI hay lore? Đọc ngữ cảnh của nó. Nếu nó được render ra màn hình
  (nằm trong regex `editdisplay`, trong HTML nền, trong `print`/`addChat` của trigger, hoặc
  trong block ví dụ của prompt HUD) thì đó là UI.

## 1. Khảo sát: lấy quy ước của chính card này

```bash
export PYTHONIOENCODING=utf-8
python scripts/charx.py info "C:/path/card.charx" --json
python scripts/charx.py unpack "C:/path/card.charx" "work/card"
python scripts/charx.py validate "work/card"
python scripts/charx.py text export "work/card"
find "work/card/text" -type f | sort
```

Quét ngôn ngữ nguồn theo dải Unicode (đổi dải theo card):

```bash
# Hangul
grep -rlP '[\x{AC00}-\x{D7A3}]' "work/card/text"
# Hiragana/Katakana
grep -rlP '[\x{3040}-\x{30FF}]' "work/card/text"
# Hán tự
grep -rlP '[\x{4E00}-\x{9FFF}]' "work/card/text"
```

Rồi tự trả lời năm câu sau và ghi lại — mọi bước sau đều dựa vào bảng này:

| Câu hỏi | Cách tìm | Kết quả cần ghi |
| --- | --- | --- |
| Marker của block dữ liệu là gì? | grep ký hiệu lặp lại trong prompt/lore/regex `in` | ví dụ `◈ML … ◈` |
| Tên field trong block? | đọc block ví dụ trong prompt | `TIME|`, `LOC|`, `@|`, `STAMP|`… |
| Biến chat nào điều khiển UI? | grep `getvar::` trong regex/trigger | ví dụ `ml_started`, `ml_tab`… |
| Người dùng gõ lệnh gì? | đọc regex `in` và note nhắc lệnh | ví dụ `/미팅`, `/start`… |
| UI được sinh ra ở đâu? | bảng bề mặt bên dưới | danh sách pointer sẽ sửa |

Bảng bề mặt — điền pointer thật của card, không gộp nhiều bề mặt vào một dòng:

| Bề mặt | Nơi thường nằm | Dấu hiệu nhận ra |
| --- | --- | --- |
| Prompt sinh dữ liệu | lorebook entry có marker, entry Always-On | mô tả field, block ví dụ, câu "Write … in Korean" |
| Selector / màn hình bắt đầu | regex có `in` là marker ngắn; hoặc greeting | `out` là HTML lớn: scene card, nút bắt đầu, chọn nhân vật |
| HUD | regex `in` chứa marker + `backgroundHTML`/`backgroundEmbedding` | `out` có `$1…`, class HUD, nhãn tĩnh |
| Side panel | regex + trigger | `{{getvar::…}}`, nhãn mục, danh sách thành viên |
| Nhật ký lệnh | regex cho log, marker log riêng | khung chat/Slack/biên bản, tiêu đề log |
| Thông báo trigger | trigger Lua/CJS | `print(…)`, `addChat`, nhãn trạng thái |
| Lệnh gõ | regex `in` | token `/…`, note nhắc lệnh, regex xóa note |
| CSS nhãn tĩnh | `backgroundHTML`, `backgroundEmbedding` | `content:"…"`, `::before`, tooltip, `aria-label` |
| Nút bấm | HTML trong `out` | `risu-trigger="…"`, `cmd="…"` |

Xem nhanh code trigger:

```bash
MSYS_NO_PATHCONV=1 python scripts/charx.py get "work/card" \
  /module/trigger/0/effect/0/code --target module
```

Nếu card **không có module**, các bề mặt nằm ở `card.json`:
`/data/extensions/risuai/customScripts` (regex), `/triggerscript` (trigger),
`/backgroundHTML`, và lorebook trong `/data/character_book`.

Kết thúc bước 1 phải có: danh sách pointer cần sửa, marker/field/biến/lệnh của card, và
ngôn ngữ nguồn.

## 2. Phân loại từng chuỗi trước khi dịch

Với mỗi chuỗi ngôn ngữ nguồn tìm được, xếp vào một trong bốn nhóm. Đừng dịch hàng loạt.

| Nhóm | Xử lý |
| --- | --- |
| Nhãn hiển thị (tiêu đề, nút, tên mục, tooltip, CSS `content`) | Dịch |
| Giá trị trong block ví dụ của prompt | Dịch |
| Khóa kỹ thuật (marker, field key, mã trạng thái, ID, class, biến, tên asset) | Giữ nguyên |
| Khóa tên người / token lệnh gốc | Giữ nguyên + **thêm** alias Latin / alias tiếng Việt |

Sau khi dịch xong một bề mặt, quét lại ngôn ngữ nguồn trên đúng bề mặt đó: mức mong đợi là
**0**, trừ các khóa gốc đã cố ý giữ.

## 3. Prompt sinh dữ liệu hiển thị

Thêm đúng **một câu** chỉ thị ngôn ngữ, không viết lại entry. Câu mẫu giữ tiếng Anh vì phần
lớn card viết prompt bằng tiếng Anh; chỉ nội dung hiển thị mới cần tiếng Việt:

```text
Write every HUD value in Vietnamese; keep the field names and block markers unchanged.
Do not use Korean anywhere in the HUD block.
```

(Đổi `Korean` thành ngôn ngữ nguồn của card.)

Nếu field dẫn chiếu một bảng gốc trong card (ví dụ field `CALL` phải theo bảng `ADDRESS
TERMS`), thêm yêu cầu render field đó bằng tiếng Việt, nếu không model sẽ chép nguyên kính
ngữ ngôn ngữ nguồn vào HUD:

```text
Render the CALL field in Vietnamese (for example {{user}} ạ or cậu).
```

Với dữ liệu có tên nhân vật, nói rõ dùng chữ Latin đúng như bảng tham chiếu của card:

```text
Write every value in Vietnamese; keep names in Latin script exactly as in QUICK REFERENCE.
```

Dịch **các giá trị trong block ví dụ** (mọi field mà card có). Giữ nguyên tên field, marker,
mã trạng thái và thứ tự field. Không cần dịch phần hướng dẫn kỹ thuật còn lại nếu tác giả
viết bằng tiếng Anh.

Nếu card có nhiều prompt sinh dữ liệu (HUD, log, panel), thêm câu chỉ thị vào **từng** cái.

## 4. Nhãn tĩnh trong regex OUT, HTML và CSS

Trong `out` của selector/HUD/side panel/log, chỉ thay chữ hiển thị:

- tiêu đề/kicker, tên nhóm/phòng ban, tên và mô tả scene card, nhãn trạng thái;
- chữ trên nút (`Bắt đầu`, `Chọn lại`), cấp độ (`Lv.3` → `Cấp 3`), địa danh trong caption;
- tên nhân vật trong caption và chữ cái đầu avatar → Latin.

Giữ `$1…`, `{{…}}`, class, `risu-trigger`, `data-*`, `src`, `{{raw::…}}`. Kiểm tra cân bằng
`<div>`/`</div>` sau khi dịch.

Với CSS trong `backgroundHTML`/`backgroundEmbedding`: dịch chuỗi trong `content:"…"`,
`aria-label`, `title`, `placeholder`, và text trong thẻ. Giữ selector, tên class, giá trị
màu/kích thước.

## 5. Tên nhân vật: hiển thị và avatar

Đây là nơi dễ sót nhất, vì tên thường đi qua hai chặng: model sinh tên → script/regex dùng
tên làm khóa → UI in tên ra.

**Chặng hiển thị.** Nếu script đưa khóa tên gốc vào UI, thêm bảng dịch và một hàm, không đổi
khóa (tên trong ví dụ là của card MUSE Lab; thay bằng bảng của card bạn đang sửa):

```lua
local DISPLAY_NAMES = {
  ["차예린"] = "Cha Yerin", ["박로아"] = "Park Roa",
}
local function displayName(name) return DISPLAY_NAMES[name] or name end
```

Gọi `displayName()` ở **mọi** chỗ đưa tên vào UI: side panel, sinh nhật, log, thông báo.

**Chặng khóa.** Nếu UI đã in tên Latin (do prompt ở mục 3) mà bảng ánh xạ avatar chỉ có khóa
gốc, avatar sẽ trắng. Thêm alias Latin trỏ cùng asset, giữ khóa cũ:

```lua
local AVATARS = {
  { "차예린", "yerin" },
  { "Cha Yerin", "yerin" },   -- alias Latin, cùng asset
}
```

Yêu cầu:

- Alias phải **khớp chính xác** chuỗi UI sẽ in, kể cả dấu cách và hoa/thường. PocketRisu
  truyền thẳng tham số `getvar`, không trim, nên `av_Cha Yerin` là khóa hợp lệ.
- Chỉ thêm alias, không xóa khóa gốc. Chat cũ, log cũ và regex khác vẫn dùng được.
- Nếu regex/trigger có nhánh `if name == "…"` hoặc `{{equal::{{getvar::…}}::Tên}}`, thêm
  nhánh Latin tương ứng; không sửa điều kiện cũ.
- Xác nhận asset đích tồn tại: `assets refs` hoặc `ls work/card/assets/**/<tên>.*`.
- Nếu regex chỉ capture tên rồi dùng làm khóa (`{{getvar::av_$4}}`), regex thường **không
  cần sửa**: nhóm kiểu `((\S)[^|\n]*?)` đã nhận cả tên có dấu cách. Vấn đề nằm ở bảng ánh xạ.

## 6. Lệnh gõ và note nhắc lệnh

Mở rộng regex đầu vào, giữ token gốc (ví dụ với lệnh tiếng Hàn):

```text
/(?:미팅|hop)[ \t]*([^\n]*)
/(?:시연회|demo)[ \t]*([^\n]*)
```

- Không đổi nhóm capture và thứ tự `$1…` trong output.
- Cập nhật note nhắc lệnh (thêm lệnh mới bên cạnh lệnh cũ).
- Nếu card có regex **xóa note** sau khi dùng, mở rộng nó cho cả note mới, ví dụ
  `── (?:위|Nhập)…`.
- Kiểm tra cả hai dạng khi test: token gốc và token mới, có dấu `/` và không.

## 7. Nhãn hệ thống và thông báo do trigger sinh

Dịch: tên workspace/tab/kênh/bot, nhãn trạng thái dự án, thông báo lệnh ("Đã lưu biên bản",
"Đã ghi nhật ký"), tiêu đề log, nhãn mục trong side panel.

Giữ nguyên: tên biến, giá trị mã, khóa bảng dữ liệu, định dạng ngày mà script parse, và chuỗi
dùng để match đầu vào.

Nếu trigger đọc marker/field từ HUD, giữ nguyên định dạng block. Nếu biến lưu khóa tên gốc
(ví dụ `next = "차예린"`), chỉ dịch lúc hiển thị, không đổi giá trị lưu.

## 8. Card đã có sẵn đa ngôn ngữ

Nếu card có selector ngôn ngữ hoặc bảng chuỗi i18n, **không** thay chuỗi gốc:

- thêm lựa chọn `Tiếng Việt` vào selector, giữ các lựa chọn cũ;
- thêm bảng chuỗi `vi` bên cạnh `ko`/`en`/`ja`, giữ nguyên khóa;
- trỏ nhãn UI sang bảng theo ngôn ngữ đang chọn, không hardcode;
- giữ ngôn ngữ mặc định cũ khi người dùng chưa chọn;
- thêm nhánh i18n cho cả lệnh gõ và note nếu cơ chế đó có i18n.

Nếu cấu trúc i18n quá phức tạp để thêm an toàn, dừng lại và báo rõ thay vì phá cơ chế gốc.

## 9. Áp dụng và kiểm chứng

```bash
python scripts/charx.py text import "work/card"
# nếu sửa Lua/CJS:
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

Mô phỏng từng regex bằng mẫu **do chính card này sinh ra** (lấy mẫu thật từ greeting/log cũ,
rồi thay giá trị bằng bản tiếng Việt):

```bash
node - <<'JS'
const fs = require('fs');
const mod = (JSON.parse(fs.readFileSync('work/card/module.json','utf8'))).module;
const find = n => mod.regex.find(x => x.comment === n);
const apply = (r, s) => s.replace(new RegExp(r.in, 'g'), r.out);

// ví dụ (card MUSE Lab): selector + HUD
let html = apply(find('셀렉터'), '☆★');
if (html.includes('☆★') || /[\uac00-\ud7a3]/.test(html)) process.exit(1);

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

- Quét ngôn ngữ nguồn theo từng lớp. Mức mong đợi: **0** ở prompt UI, regex OUT, HTML nền,
  thông báo trigger. Còn lại chỉ được phép ở: khóa gốc trong bảng ánh xạ, token lệnh gốc
  trong regex IN, comment CSS, ví dụ ngôn ngữ có chủ đích.
- Đếm `<div>`/`</div>` trong OUT của selector/side panel/HUD; đếm cặp `{{#…}}`/`{{/…}}`.
- Mọi alias Latin có asset avatar tương ứng.
- Lệnh cũ và lệnh mới đều match; note cũ và note mới đều bị xóa.
- `validate` 0 error; warning tồn tại trước đó được ghi lại.
- Không chạy được PocketRisu trong môi trường hiện tại thì nói rõ: đã kiểm tra tĩnh (regex +
  dữ liệu + pack/diff), chưa xem render thực tế.

## 10. Lỗi thường gặp

| Hiện tượng | Nguyên nhân / xử lý |
| --- | --- |
| Diff trigger đổi toàn bộ file vì `\r\n` | File tạm bị ghi CRLF. Chuyển về LF (`data.replace(b"\r\n", b"\n")`) rồi `set` lại. |
| Avatar trắng hoặc sai người | Tên UI không khớp alias khóa (khoảng trắng/hoa-thường) hoặc thiếu asset avatar. |
| HUD vẫn ra ngôn ngữ nguồn | Prompt thiếu câu bắt buộc; block ví dụ trong prompt chưa dịch; model đang bám ví dụ cũ. |
| Regex HUD không match nữa | Đã đổi marker, tên field hoặc thứ tự field. Khôi phục từ bản gốc. |
| Selector còn nhãn chưa dịch | Còn chữ trong OUT, caption scene, chữ cái đầu avatar, hoặc CSS `content:"…"`. |
| Side panel hiện tên ngôn ngữ nguồn | Trigger đưa khóa gốc vào UI mà không gọi hàm hiển thị; hoặc biến trạng thái chưa dịch. |
| Lệnh mới không chạy | Regex IN thiếu alias; PocketRisu đã trim mất dấu `/`; test bằng mẫu `"/hop abc"`. |
| Note lệnh còn sót | Regex xóa note chỉ khớp dạng cũ, chưa thêm dạng mới. |
| Sinh nhật/ngày sai sau khi dịch | Đã đổi `MM.DD` thành `DD.MM` trong khi script parse tháng.ngày. Giữ nguyên thứ tự số. |
| `BOOK_W_DIVERGENT` trước khi pack | Bình thường khi mới sửa module; `pack --sync-book auto` sẽ đồng bộ card book. |
| Dịch nhầm lore/prose | Ngoài phạm vi UI; hoàn nguyên và chỉ sửa bề mặt hiển thị được yêu cầu. |
| Ghi đè ngôn ngữ gốc của card đa ngôn ngữ | Phải thêm nhánh `vi`, giữ nguyên chuỗi cũ (mục 8). |
