# Tách một nhân vật thành card riêng

Dùng khi card gốc là **card đa nhân vật** (một card chứa cả dàn cast: nhiều hồ sơ, nhiều
greeting, nhiều scene, ảnh riêng cho từng người) và người dùng muốn một card chỉ còn **một
nhân vật**, kèm đúng phần prompt/ảnh/code/regex/script phục vụ nhân vật đó.

Quy trình này **làm tay**. Card đa nhân vật có vô tận cách viết: cast có thể nằm trong
lorebook, trong `alternate_greetings`, trong bảng Lua của trigger, trong danh sách `<img
cmd="...">`, trong regex OUT, hoặc trong cả năm chỗ cùng lúc. Không có bộ lọc tự động nào
đọc hiểu được tất cả. Toolkit chỉ cung cấp lệnh nguyên thủy (`text export`, `book`,
`assets`, `get`/`set`, `validate`, `diff`); phần phán đoán là của người làm.

Ba điều phải đúng ở cuối, kiểm cả ba:

- **Đủ về nhân vật**: hồ sơ, greeting, scene, ảnh, avatar, bảng dữ liệu của người đó.
- **Đủ về bối cảnh**: thế giới/setting, địa điểm, tổ chức, luật viết và thể loại,
  engine/format (HUD, selector, lệnh), thuật ngữ, timeline nền, và quan hệ của nhân vật đích
  với những người xung quanh. Mọi thứ **định hình chung** phải đi theo, để card mới tự đứng
  được mà không cần đọc card gốc.
- **Không thừa**: không còn hồ sơ/ảnh/branch/scene/bảng dữ liệu dành riêng cho nhân vật khác.

## 0. Chuẩn bị và giữ mốc so sánh

```bash
export PYTHONIOENCODING=utf-8
python scripts/charx.py info "C:/path/card.charx" --json > info.json
python scripts/charx.py unpack "C:/path/card.charx" "work/base"     # mốc, KHÔNG sửa
python scripts/charx.py unpack "C:/path/card.charx" "work/split"    # bản sẽ sửa
python scripts/charx.py validate "work/split"
python scripts/charx.py text export "work/split"
```

Ghi lại baseline: số entry, số asset, tổng dung lượng, số lore, số regex, số trigger, các
warning có sẵn. Warning có sẵn từ nguồn không phải lỗi do bạn gây ra.

`work/base` là mốc để đối chiếu bất cứ lúc nào (`diff`, hoặc đọc lại văn bản gốc trước khi
quyết định cắt). Không sửa `work/base`.

Trên Git Bash, mọi lệnh có pointer bắt đầu bằng `/` (ví dụ `/data/description`) cần
`MSYS_NO_PATHCONV=1` ở đầu dòng, nếu không `/data/...` bị đổi thành đường dẫn Windows.

## 1. Dựng bảng cast từ bằng chứng

Đừng tin một nguồn duy nhất. Liệt kê bằng chứng rồi mới kết luận.

| Nguồn bằng chứng | Cách xem | Thường cho biết |
| --- | --- | --- |
| `data.name`, `data.description` | `text/card/description.md` | Nhân vật "chính danh" của card, hoặc cả dàn cast |
| `alternate_greetings` | `text/card/alternate_greetings/*.md` | Mỗi greeting thường là một nhân vật hoặc một scene |
| Lorebook | `book list --json`, `text/module/lorebook/**` | Hồ sơ từng nhân vật, folder theo nhân vật, khóa key là tên |
| Regex OUT | `text/module/regex/*.out.txt` | Selector, side panel, HUD, log — nơi in tên nhân vật ra UI |
| Trigger / CJS | `get ... /module/trigger/0/effect/0/code --target module` | Bảng dữ liệu do tác giả tự đặt tên (kiểu `PARTNERS`, `AVATARS`, `BIRTHDAYS`, `POS`), map tên→alias |
| Asset | `assets list` | Họ tên asset (`<prefix>_<alias>`, `<Name>_*`, `av_<alias>`) |
| `{{raw::...}}`, `<img cmd="...">`, `risu-trigger="..."` | grep trong `text/` | Tên asset/lệnh gắn với từng nhân vật |

```bash
python scripts/charx.py book list "work/split" --json > book.json
python scripts/charx.py assets list "work/split" > assets.txt
grep -rn "{{raw::" "work/split/text" | head -50
```

Kết quả phải là một bảng, mỗi nhân vật một dòng:

| Nhân vật | Alias (gốc + Latin) | Bằng chứng (pointer) | Họ asset |
| --- | --- | --- | --- |
| … | … | … | … |
| *ví dụ:* Park Roa | `박로아`, `Park Roa`, `roa` | `/module/lorebook/7`, `/module/regex/8/out`, bảng avatar trong trigger | `roa_*`, `sp_roa` |

Kèm ba danh sách phụ, quyết định chất lượng của cả lần tách:

- **Lớp bối cảnh chung** (bảng bên dưới): mọi thứ định hình thế giới mà nhân vật đích sống
  trong đó → **kéo theo**.
- **Mục mập mờ**: entry nhắc tới ≥2 nhân vật (roster, quan hệ, timeline chung). Đọc kỹ rồi
  xếp vào "giữ nguyên", "cắt bớt" hoặc "rút thành một dòng bối cảnh", không đoán.
- **Họ asset không có chủ**: nhóm asset cùng tiền tố mà không khớp tên nhân vật nào. Ghi
  vào báo cáo, **giữ nguyên** (thiếu ảnh tệ hơn thừa ảnh).

### Lớp bối cảnh chung phải kéo theo

Tách nhân vật **không** phải là chỉ giữ prompt của riêng người đó. Card mới phải tự đứng
được: người đọc phải biết ngay chuyện xảy ra ở đâu, khi nào, luật chơi là gì, ai đang nói,
và những cái tên được nhắc tới là ai. Lập bảng này **trước khi xóa bất cứ thứ gì**.

| Lớp | Nội dung thường gặp | Xử lý |
| --- | --- | --- |
| Thế giới / bối cảnh | setting, thời đại, địa điểm, tổ chức, phe phái, nghề nghiệp chung | Giữ nguyên |
| Luật viết và thể loại | ngôi kể, độ dài, nhịp cảnh, mức nội dung, quy tắc `@@depth`/`@@role` | Giữ nguyên |
| Engine / format | HUD, selector, side panel, log, marker, field key, CSS, regex render | Giữ nguyên |
| Thuật ngữ | glossary, tên kỹ năng/chức danh, đơn vị, danh xưng, kính ngữ | Giữ nguyên |
| Timeline / sự kiện nền | lịch sử thế giới, sự kiện đã xảy ra, mốc thời gian chung | Giữ; chỉ cắt chi tiết riêng của nhân vật khác |
| Quan hệ của nhân vật đích | "X là chị gái của đích", "đích và Y cùng lab" | **Giữ cả tên người khác** — đó là bối cảnh của đích |
| Lệnh / cơ chế dùng chung | lệnh gõ, trigger chung, bảng dữ liệu engine | Giữ; chỉ cắt phần tử của nhân vật khác |
| Hồ sơ đầy đủ của nhân vật khác | tiểu sử, ngoại hình, tính cách, scene riêng, greeting riêng, ảnh riêng | Xóa |

Khi một entry **vừa** là bối cảnh **vừa** chứa hồ sơ nhân vật khác (roster, bảng quan hệ,
danh sách thành viên, mô tả một nhóm), đừng xóa cả entry: rút phần của người khác thành
**một dòng định danh** đủ để câu chuyện còn nghĩa (tên + vai trò + quan hệ với nhân vật
đích), bỏ tiểu sử, ngoại hình, tính cách, scene và ảnh của họ.

Cẩn thận với tên trùng từ thường: alias phải là **tên người**. Kiểm tra trước khi dùng một
từ làm khóa sở hữu: nó có xuất hiện trong hồ sơ nhân vật, trong bảng avatar, hoặc làm tiền
tố họ asset không? Nếu chỉ xuất hiện trong prose với nghĩa thông thường thì không phải tên.

## 2. Chọn nhân vật đích và quyết định danh tính card

- Nhân vật đích: ghi lại **mọi** dạng tên sẽ dùng để grep (Hangul, Latin, viết tắt, không
  dấu cách, dạng trong asset). Thiếu một dạng là sót nội dung.
- `data.name`: đổi sang tên nhân vật nếu người dùng muốn card mới mang tên đó; nếu không
  được nói rõ, giữ tên gốc và hỏi. `pack` đặt tên file theo `data.name`.
- `data.creator`, `creator_notes`, `tags`: **giữ nguyên** credit tác giả. Có thể thêm một
  dòng ghi chú "tách từ card X, chỉ còn nhân vật Y" vào `creator_notes`.
- Ảnh bìa: nếu là `charxJpeg`, cân nhắc `pack --jpeg-prefix <ảnh của nhân vật đích>`; chỉ
  dùng ảnh **có thật trong card** (lấy từ asset của nhân vật đó), không bịa bytes.

## 3. Lorebook: phân loại rồi mới xóa

Với từng entry, trả lời hai câu: *nó thuộc về ai?* và *bỏ nó thì card còn chạy không?*

| Loại | Xử lý |
| --- | --- |
| Hồ sơ/tiểu sử/scenario riêng của nhân vật khác | Xóa (`book remove`) |
| Hồ sơ của nhân vật đích | Giữ; sửa nếu nó đang viết theo kiểu "một trong số N người" |
| Engine: format HUD, luật viết, quy tắc `@@depth`/`@@role`, Always-On hệ thống | Giữ nguyên |
| Thế giới/bối cảnh: setting, địa điểm, tổ chức, thuật ngữ, timeline nền | **Giữ nguyên** — đây là thứ làm card mới còn hiểu được (mục 1) |
| Roster/danh sách cast, quan hệ giữa các nhân vật | Không xóa cả entry: giữ nhân vật đích, rút người khác thành một dòng định danh |
| Entry theo scene chỉ dùng cho scene của nhân vật khác | Xóa (xem mục 4 về scene id) |
| Folder | Xóa folder khi không còn entry con; dùng `book list --json` để xem `folder_path` |

Sau khi xóa, đọc lại card như người mới: còn trả lời được *ở đâu / khi nào / luật gì / ai
đang nói / người được nhắc tới là ai* không? Nếu một entry bối cảnh bị mất, khôi phục từ
`work/base`.

```bash
python scripts/charx.py book list "work/split" --json
python scripts/charx.py book remove "work/split" 12 --yes
python scripts/charx.py book move "work/split" 5 --folder ""      # đưa về gốc nếu folder đã xóa
```

Index của `book remove` là vị trí trong danh sách hiệu lực; sau mỗi lần xóa index **dịch
lại**, nên xóa từ cuối lên đầu hoặc `book list` lại sau mỗi bước.

Khi có module, mọi sửa đổi phải đi qua bản module (`book ...` tự làm việc này); `pack
--sync-book auto` mirror sang card.

## 4. Greeting, scene và description

**Greeting.** Card đa nhân vật thường có một greeting cho mỗi nhân vật/scene.

- Xác định greeting của nhân vật đích bằng cách đọc: ai nói, ai được `{{char}}` hoá thân,
  scene nào đang bật.
- Giữ greeting đích ở `first_mes`; các greeting còn lại: xóa khỏi `alternate_greetings`
  (hoặc giữ lại nếu người dùng muốn, nhưng khi đó phải cắt phần nhân vật khác bên trong).
- Nếu greeting đích chứa khối chọn scene/chọn nhân vật, cắt theo mục 5.

**Scene id.** Nhiều card đánh số scene (`{{setvar::scn::2}}`, gate `{{equal::{{getvar::
scn}}::2}}`). Phải lập bảng *scene id → nhân vật* trước khi cắt:

| Scene id | Thuộc về | Bằng chứng |
| --- | --- | --- |
| 1, 4 | nhân vật đích | greeting 1 mô tả scene 4; lore `SCENE 4` |
| 2, 3 | nhân vật khác | greeting 2/3, lore scene 2/3 |

Bỏ block gate theo scene id của nhân vật khác; **giữ** block gate theo trạng thái card
(đã bắt đầu hay chưa, panel đang mở, vị trí, chiều rộng màn hình) vì đó là layout chứ không
phải một mục cast.

**Description.** Card đa nhân vật thường có `description` = cast overview + engine/format.
Khi tách:

1. Đọc và tách đôi nội dung: phần *engine/format/luật* và phần *danh sách nhân vật*.
2. Phần engine **không được mất**. Nếu không còn chỗ cho nó trong description mới, chuyển
   nó thành một lore entry Always-On (ví dụ `ENGINE (from card description)`). Kèm theo đó
   là phần **bối cảnh chung** từng nằm trong description: thế giới, địa điểm, tổ chức, thời
   gian, luật chơi — giữ lại, đừng để mất theo danh sách cast.
3. Phần description mới: hồ sơ của nhân vật đích (lấy từ lore entry hồ sơ của người đó,
   hoặc viết lại từ các phần của entry đó) **cộng với bối cảnh** đủ để một người chưa đọc
   card gốc hiểu được hoàn cảnh: ở đâu, khi nào, quan hệ của đích với những người được nhắc
   tới, đích đang ở tình huống nào.
4. Xóa trong description mọi đoạn hồ sơ riêng của nhân vật khác và mọi "chọn ai để bắt
   đầu". Người khác chỉ còn lại dưới dạng một dòng định danh khi họ có ý nghĩa với bối cảnh
   của nhân vật đích.

```bash
python scripts/charx.py set "work/split" /data/description --file description.md
python scripts/charx.py book add "work/split" --name "ENGINE (from card description)" \
  --content-file engine.md --always-active --order 10
```

## 5. Cắt bên trong một khối văn bản

Đây là phần dễ phá card nhất. Quy tắc chung: **chỉ cắt một đơn vị khi đơn vị đó là một mục
dành riêng cho nhân vật khác**, không cắt vì nó có nhắc tới tên người khác.

Thứ tự kiểm tra cho mỗi đơn vị:

1. **Wrapper.** Nếu block chiếm gần như toàn bộ văn bản (≥ ~90%), đó là điều kiện chạy cả
   engine (`{{#when {{not::{{equal::{{getvar::started}}::1}}}}}}`, `{{#if chat_index…}}`) →
   **giữ**. Cắt wrapper là hỏng cả card. Đây là lỗi over-trim phổ biến nhất.
2. **Gate theo trạng thái** (`getvar` không phải tên người, không phải scene id) → **giữ**.
3. **Gate theo scene id của nhân vật khác** → cắt (dùng bảng scene ở mục 4).
4. **Gate theo tên nhân vật khác** (`{{equal::{{getvar::next}}::Tên}}`) → cắt.
5. **Nhắc tới tên nhân vật khác trong prose/lời thoại/ghi chú quan hệ/bối cảnh thế giới của
   nhân vật đích** → **giữ**. Đó là nội dung và bối cảnh, không phải cast list.
6. **Dòng/mục liệt kê cast** (một dòng một người, một thẻ một người, một nút một người) →
   giữ dòng của nhân vật đích. Với người khác: cắt hẳn nếu dòng đó chỉ để chọn/hiển thị họ;
   rút thành **một dòng định danh** nếu nó mang thông tin bối cảnh mà nhân vật đích cần
   (quan hệ, vai trò trong tổ chức, sự kiện chung).

Kỹ thuật theo loại văn bản:

**CBS / template (`{{#when}}`, `{{#if}}`, `{{#each}}`).** Tìm cặp mở/đóng của block, cắt cả
block kể cả dấu đóng. Sau khi cắt, kiểm tra không còn `{{/when}}` hoặc `{{/if}}` mồ côi.
Xóa các dòng trống dồn lại và tiêu đề mục đã rỗng.

**HTML.** Cắt theo **phần tử**: từ thẻ mở tới thẻ đóng tương ứng. Chỉ cắt phần tử khi nó là
một đơn vị lặp (có phần tử anh em cùng tag+class — một hàng trong danh sách, một thẻ trong
dãy) hoặc là lá. Phần tử bọc ngoài độc nhất (container, panel, wrapper) thì giữ. Sau khi
cắt: đếm lại `<div>`/`</div>`, xóa nhãn nhóm đã rỗng.

**Văn bản dòng.** Cắt nguyên dòng liệt kê nhân vật khác; giữ tiêu đề và cấu trúc.

**Lua/CJS.** Chỉ cắt **phần tử trong bảng dữ liệu**, không cắt code:

```lua
local PARTNERS = { "A", "B", "TARGET" }            -- cắt "A", "B"
local AVATARS  = { { "A", "a" }, { "TARGET", "t" } }
local BIRTHDAYS = { { "A", 8, 17 }, { "TARGET", 7, 28 } }
```

Giữ nguyên hàm, vòng lặp, `setvar`, `roll`, logic render. Sau khi cắt, kiểm tra code còn an
toàn: `#PARTNERS` ≥ 1, không truy cập index đã mất, không chia cho số phần tử bằng 0. Khi
chỉ còn một nhân vật, logic "chọn ngẫu nhiên đối tác" vẫn hợp lệ (luôn trả về người đó) —
không cần viết lại, chỉ cần ghi chú trong báo cáo. Giữ line ending gốc (Lua thường LF).

**Regex.** Với từng regex, quyết định ba mức: giữ nguyên / cắt trong `out` / xóa.

| Regex | Quyết định thường đúng |
| --- | --- |
| Render HUD, render selector, xóa note, đổi hiển thị | Giữ; chỉ cắt hàng/branch của nhân vật khác trong `out` |
| Lệnh dành riêng cho nhân vật khác (`/ten_nguoi_khac`) | Xóa cả cặp `in`/`out` |
| Lệnh dùng chung (`/hop`, `/demo`, `/start`) | Giữ nguyên cả lệnh và alias |

Không đổi `$1...`, nhóm capture, marker, field key. Nếu `out` có nhánh theo tên, cắt nhánh
của người khác và giữ nhánh mặc định.

## 6. Asset: phần tiết kiệm dung lượng lớn nhất

Asset của nhân vật khác thường chiếm phần lớn dung lượng card. Làm theo thứ tự:

1. Lập bảng sở hữu từ **họ tên asset** (tiền tố trước `_`/`-`/`.`) đối chiếu alias đã có ở
   mục 1. Họ nào khớp alias của nhân vật đích → giữ. Họ nào khớp alias nhân vật khác → xóa.
2. Kiểm tra từng asset trước khi xóa bằng tham chiếu:

```bash
python scripts/charx.py assets refs "work/split" "sp_roa"
grep -rn "sp_yerin\|{{raw::yerin" "work/split/text"
```

3. **Giữ** asset dùng chung: icon/main, ảnh nền, sprite HUD, logo, font, audio chung, asset
   mà selector/HUD/panel của engine dùng.
4. **Giữ** asset không xác định được chủ (không khớp alias nào) và ghi vào báo cáo.
5. Xóa bằng lệnh để `x_meta` và `data.assets` được cập nhật nhất quán; file bị xóa được
   chuyển vào `_charx/removed/<thời gian>/` nên có thể khôi phục:

```bash
python scripts/charx.py assets remove "work/split" "#123" --yes
python scripts/charx.py assets gc "work/split"            # liệt kê asset mồ côi
python scripts/charx.py assets gc "work/split" --move --yes
```

6. Với asset nhúng trong module (`_charx/module_assets/`), dùng `module assets list` để xem;
   xóa/sửa phải đi kèm cập nhật `module.json` để số metadata khớp số block
   (`MOD_E_ASSET_COUNT`). Nếu không chắc, giữ nguyên.
7. Nếu card có nhiều greeting/scene và mỗi scene dùng một ảnh, kiểm tra lại ánh xạ
   `cmd="..."` → asset sau khi cắt scene.

## 7. Kiểm chứng: đủ (nhân vật + bối cảnh) và không thừa

**Đủ** — mọi tham chiếu trong văn bản còn lại phải trỏ tới thứ còn tồn tại:

```bash
grep -rhoP '\{\{raw::[^}]+' "work/split/text" | sort -u
grep -rhoP 'embeded://\S+' "work/split/text" | sort -u
grep -rhoP 'getvar::av_[^}]+' "work/split/text" | sort -u
grep -rhoP 'risu-trigger="[^"]+' "work/split/text" | sort -u
python scripts/charx.py validate "work/split"
```

Mỗi tên trong danh sách phải khớp một asset/trigger/biến còn lại. `validate` phải không có
`ASSET_E_MISSING`, `ENTRY_E_MISSING`, `MOD_E_*`.

**Đủ về bối cảnh** — phần dễ thiếu nhất, vì không có lệnh nào báo lỗi cho nó. Mở
`description` + `first_mes` + các lore đã giữ và trả lời như một người chưa từng đọc card
gốc:

| Câu hỏi | Nếu không trả lời được |
| --- | --- |
| Chuyện xảy ra ở đâu, thời điểm nào, thế giới loại gì? | Thiếu entry thế giới/bối cảnh — lấy lại từ `work/base` |
| Luật viết/thể loại/mức nội dung là gì? | Thiếu entry luật viết hoặc `@@depth`/`@@role` |
| Nhân vật đích là ai, đang ở tình huống nào, quan hệ gì với `{{user}}`? | Hồ sơ đích chưa đủ hoặc greeting bị cắt mất phần mở |
| Mỗi cái tên còn xuất hiện là ai? | Thiếu dòng định danh — thêm một dòng, không thêm cả hồ sơ |
| HUD/lệnh/cơ chế của card dùng thế nào? | Thiếu engine/format — kiểm tra entry Always-On đã chuyển |

**Không thừa** — quét tên nhân vật khác trên toàn bộ văn bản:

```bash
for n in "TênKhác1" "TenKhac2"; do
  echo "== $n"; grep -rn "$n" "work/split/text" | head -20
done
python scripts/charx.py assets gc "work/split"
```

Với mỗi chỗ còn nhắc tên nhân vật khác, phải giải thích được và ghi vào báo cáo:

- prose/lời thoại/quan hệ của nhân vật đích → **giữ**, đúng;
- một dòng định danh bối cảnh (tên + vai trò + quan hệ với đích) → **giữ**, đúng;
- comment trong code, credit tác giả → giữ;
- alias gốc trong bảng ánh xạ (đã thêm alias Latin) → giữ;
- một mục trong danh sách cast, một branch, một nút, một hàng HTML, một phần tử bảng Lua,
  một họ asset, hoặc cả một hồ sơ/tiểu sử/scene của người khác → **phải cắt**, đây là sót.

**Kiểm tra logic còn chạy.** Mô phỏng regex bằng mẫu thật (Node dùng cùng cú pháp `$1`):

```bash
node - <<'JS'
const fs = require('fs');
const mod = (JSON.parse(fs.readFileSync('work/split/module.json','utf8'))).module;
const find = n => mod.regex.find(x => x.comment === n);
const apply = (r, s) => s.replace(new RegExp(r.in, 'g'), r.out);
// thay bằng marker + dữ liệu mẫu của CHÍNH card này
const out = apply(find('<tên regex HUD>'), '<block HUD mẫu>');
console.log(out);
if (/\$[0-9]+/.test(out)) { console.error('CÒN $n CHƯA THAY'); process.exit(1); }
JS
```

Nếu có Lua, chạy thử bằng `lua`/`luajit` khi máy có sẵn, hoặc đọc kỹ các vòng lặp và index
đã bị ảnh hưởng bởi việc cắt bảng. Nếu không chạy được, nói rõ trong báo cáo là mới kiểm tra
tĩnh.

**Kiểm tra cân bằng cú pháp** với mọi file đã cắt: `{{#when}}`/`{{/when}}`,
`{{#if}}`/`{{/if}}`, `<div>`/`</div>`, `{`/`}` trong bảng Lua, ngoặc trong regex.

## 8. Đóng gói và báo cáo

```bash
python scripts/charx.py validate "work/split"
python scripts/charx.py pack "work/split" --out "out/"
python scripts/charx.py diff "C:/path/card.charx" "out/<tên card>.charx"
```

`diff` lần này **sẽ rất lớn** (đó là bản chất của việc tách): entry asset bị xóa hàng loạt,
lorebook và card book đổi, regex/trigger đổi. Điều phải kiểm tra trong `diff`:

- không có entry **lạ** nào bị xóa (entry không phải asset của nhân vật khác);
- prefix JPEG, entry tùy ý, `x_meta` của asset còn lại vẫn nguyên;
- các pointer đổi đều nằm trong kế hoạch đã ghi ở các mục trên.

Báo cáo giao:

- nhân vật được chọn, alias đã dùng để grep;
- bảng cast đã dựng và bằng chứng của từng người;
- **lớp bối cảnh chung đã kéo theo**: thế giới/setting, luật viết, engine/format, thuật ngữ,
  timeline, quan hệ của nhân vật đích (kèm pointer của từng entry);
- lore: xóa bao nhiêu, giữ bao nhiêu, cắt bao nhiêu, entry nào được rút thành một dòng định
  danh, folder nào bị xóa;
- greeting/description: greeting nào được chọn, phần engine và bối cảnh cũ được chuyển đi đâu;
- scene id nào bị bỏ, scene id nào giữ;
- regex/trigger: cái nào giữ nguyên, cái nào cắt, cái nào xóa;
- asset: giữ/xóa bao nhiêu, giải phóng bao nhiêu dung lượng, họ asset nào không xác định
  được chủ;
- phần còn nhắc tên nhân vật khác và lý do giữ;
- kết quả `validate`, warning có sẵn, và những gì **chưa** test được lúc chạy thật.

## 9. Lỗi thường gặp

| Hiện tượng | Nguyên nhân / xử lý |
| --- | --- |
| Selector/HUD biến mất, output chỉ còn vài ký tự | Đã cắt block wrapper (điều kiện chạy cả engine). Khôi phục từ `work/base`, giữ block chiếm gần hết văn bản. |
| Card mở lên không bắt đầu được | Cắt mất block gate theo trạng thái (`started`, `chat_index`) hoặc scene mặc định của nhân vật đích. |
| Ảnh trắng / thiếu ảnh | Đã xóa asset dùng chung hoặc alias asset không khớp tên mới. `assets refs` + `validate` để tìm. |
| `MOD_E_ASSET_COUNT` | Sửa asset nhúng của module mà không cập nhật `module.json`. |
| `ASSET_E_MISSING` | Xóa file asset mà không dùng `assets remove`, hoặc `{{raw::}}` còn trỏ tới asset đã xóa. |
| Lua lỗi runtime | Cắt phần tử bảng nhưng code còn truy cập index cũ, hoặc `#TABLE` thành 0. |
| Regex không match | Đã đổi marker/field key/nhóm capture khi cắt. Chỉ cắt nội dung, không đổi cú pháp. |
| Vẫn còn tên nhân vật khác trong UI | Quên cắt hàng HTML / nhánh CBS / phần tử bảng dữ liệu; grep lại từng alias. |
| Mất engine sau khi thay description | Không chuyển phần format/luật cũ sang lore Always-On. |
| Card mới đọc không hiểu bối cảnh | Chỉ giữ prompt riêng của nhân vật, quên lớp thế giới/setting/thuật ngữ/timeline. Đối chiếu bảng "lớp bối cảnh chung" ở mục 1 và khôi phục từ `work/base`. |
| Tên người khác xuất hiện mà không ai biết họ là ai | Đã xóa hồ sơ của họ nhưng prose của nhân vật đích vẫn nhắc. Thêm một dòng định danh (tên + vai trò + quan hệ), không thêm cả hồ sơ. |
| Xóa nhầm entry mập mờ | Entry roster/quan hệ/timeline là **dùng chung**: cắt bớt hoặc rút thành một dòng, đừng xóa cả entry. |
| Không mở được trong PocketRisu | Kiểm tra lại `validate`, `data.name`, và `pack` có giữ prefix JPEG hay không. |

## 10. Ví dụ đã làm (để hình dung quy mô)

Card MUSE Lab (`CharX File (7).charx`, 149 MB, 13 nhân vật, module lorebook thắng):

- Bảng cast dựng từ hồ sơ lore (`PROFILE`), khóa entry, bảng `PARTNERS`/`AVATARS`/
  `BIRTHDAYS` trong Lua trigger, họ asset `sp_*` và `<First>_*`.
- Tách nhân vật `박로아`: scene id 2 và 3 thuộc nhân vật khác → bỏ; scene 1, 4, 5, 6 giữ.
- Lore: xóa 12 entry hồ sơ nhân vật khác, giữ 26 entry, cắt 12 entry roster.
- 26 entry được giữ chính là **lớp bối cảnh chung**: engine/format HUD, luật viết, setting
  lab và các địa điểm, thuật ngữ dự án, timeline nền, cùng các entry quan hệ mà 박로아 là
  một đầu mối. 12 entry roster chỉ bị cắt phần hồ sơ của người khác, giữ lại vai trò và quan
  hệ của họ với 박로아.
- `first_mes`: 18590 → 4277 ký tự sau khi bỏ block scene 2/3 và hàng cast của người khác;
  block wrapper `{{#when {{not::{{equal::{{getvar::ml_started}}::1}}}}}}` (9577 ký tự, 81%
  văn bản selector) phải **giữ** — lần chạy đầu cắt nhầm và selector chỉ còn 1592 ký tự.
- `description` cast-overview (2365 ký tự) → hồ sơ của 박로아 (6373 ký tự); phần engine cũ
  chuyển thành lore Always-On `STORY ENGINE (from card description)`.
- Asset: giữ 253, xóa 2068, giải phóng 122 MB — trong 253 asset giữ lại có ảnh dùng chung
  của engine (icon, nền, sprite HUD) chứ không chỉ ảnh của 박로아. Họ asset không xác định
  được chủ: giữ và ghi báo cáo.
- Regex: `/미팅` và `/시연회` (lệnh dùng chung) giữ nguyên chức năng, chỉ cắt phần cast;
  selector và side panel cắt hàng nhân vật khác.
- Lua: cắt phần tử trong `PARTNERS`/`AVATARS`/`BIRTHDAYS`, giữ toàn bộ hàm `roll`/`set`/
  render; `ml_next` khi chỉ còn một người vẫn hợp lệ.
- Còn 152 pointer nhắc tên nhân vật khác, phần lớn là prose/quan hệ trong hồ sơ của nhân
  vật đích → giữ, có ghi chú.

Con số chỉ để tham khảo tỷ lệ: asset là phần nặng nhất, engine/HUD/selector là phần phải giữ
cẩn thận nhất, còn **lớp bối cảnh chung là phần dễ bỏ sót nhất** — nó không nằm trong hồ sơ
của nhân vật nên rất dễ bị xếp nhầm vào "của người khác".
