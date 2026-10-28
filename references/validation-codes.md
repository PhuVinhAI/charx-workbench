# Mã kiểm tra (validation codes)

`validate` soi cấu trúc ZIP, `card.json`, `module.risum` (đã giải mã) và mọi tham chiếu
asset. Mỗi vấn đề là một object:

```json
{"level": "warn", "code": "ASSET_W_NO_META", "message": "...", "path": "assets/icon/main.png"}
```

`path` chỉ có khi vấn đề gắn với một entry cụ thể (`null` nếu không).

## Mức độ và cổng chặn

| Mức | Ý nghĩa | `pack` |
| --- | --- | --- |
| `error` | Gói hỏng hoặc không thể import đúng; phải sửa | Từ chối, trừ khi `--force` |
| `warn` | Gói vẫn dùng được nhưng có rủi ro/khác chuẩn PocketRisu | Cho qua, phải báo lại khi giao |
| `info` | Thông tin về layout/prefix/quyền module | Cho qua |

- `validate SOURCE` trả exit code `1` nếu có ít nhất một `error`, ngược lại `0`.
- `validate SOURCE --json` trả `{"source", "ok", "counts": {"error","warn","info"}, "issues": [...]}`.
- `--deep` đọc toàn bộ payload của từng entry (zipfile kiểm tra CRC khi đọc) và báo
  `ZIP_E_READ` nếu một entry không đọc được. Không có `--deep`, công cụ chỉ đọc phần đầu
  (32 byte) của asset để nhận dạng ảnh, nên hỏng giữa file có thể không bị phát hiện.
- `pack` chạy lại toàn bộ kiểm tra trên gói sẽ ghi; lỗi `error` làm hỏng gói bị chặn trước
  khi ghi file.

## Nhóm ZIP / layout

| Mã | Mức | Điều kiện | Cách xử lý |
| --- | --- | --- | --- |
| `ZIP_E_DUP` | error | Hai entry trùng tên trong ZIP | Dựng lại archive từ bản sạch; không sửa tay ZIP trùng tên |
| `ZIP_E_UNSAFE` | error | Tên tuyệt đối, có ổ đĩa (`C:`), hoặc chứa `..` | `raw put` với đường dẫn tương đối an toàn; không bao giờ giải nén entry này ra ngoài work dir |
| `ZIP_E_READ` | error | `--deep` không đọc được payload (CRC hỏng, entry bị cắt) | Thay entry bằng `raw put` từ file lành, hoặc lấy lại nguồn |
| `LAYOUT_V2` | info | Chỉ có `chara`, không có `card.json` | Bình thường với card v2; PocketRisu vẫn import như v2 |
| `PREFIX_JPEG` | info | Archive có prefix JPEG (`charxJpeg`) | `pack` giữ prefix mặc định; không cần làm gì |

## Card (`card.json` / `chara`)

| Mã | Mức | Điều kiện | Cách xử lý |
| --- | --- | --- | --- |
| `CARD_E_MISSING` | error | Không có `card.json` lẫn `chara`, hoặc JSON không đọc được | Kiểm tra entry `card.json` bằng `raw get`; khôi phục từ nguồn |
| `CARD_E_SPEC` | error | `spec` không phải `chara_card_v3`/`chara_card_v2` | `set /spec --string chara_card_v3` (card phải có `data`) |
| `CARD_E_DATA` | error | `spec` v3 nhưng thiếu/không hợp lệ `data` object | Thêm `data` đúng chuẩn V3 |
| `CARD_W_SPEC2` | warn | `spec` là `chara_card_v2` | Chỉ chuyển sang v3 khi thật sự cần; v2 vẫn dùng được |
| `CARD_W_NAME` | warn | `data.name` rỗng/không phải chuỗi | Điền tên nhân vật |
| `CARD_W_TYPE` | warn | Sai kiểu ở trường đã biết (`description` phải là chuỗi, `alternate_greetings` phải là mảng, `extensions.risuai.vits` phải là object, `sdData` phải là mảng, `backgroundHTML` phải là chuỗi…) | Sửa đúng kiểu; message nêu chính xác trường |
| `CARD_W_IGNORED_TRIGGERS` | warn | Có `extensions.risuai.triggerscript` **và** có `module.risum` | Sửa `module.trigger`; bản trong card sẽ bị PocketRisu bỏ qua |
| `CARD_W_IGNORED_REGEX` | warn | Có `extensions.risuai.customScripts` **và** có `module.risum` | Sửa `module.regex`; bản trong card sẽ bị bỏ qua |

## Module (`module.risum`)

| Mã | Mức | Điều kiện | Cách xử lý |
| --- | --- | --- | --- |
| `MOD_E_DECODE` | error | Có `module.risum` nhưng rpack/khung nhị phân không giải mã được | `module decode` để xem lỗi; nếu bất khả, giữ nguyên byte gốc và chỉ dùng `raw` |
| `MOD_E_SHAPE` | error | JSON giải mã không phải `{"type":"risuModule","module":{...}}` | Sửa `module.json` đúng wrapper; `pack` sẽ từ chối nếu sai |
| `MOD_W_NAME` / `MOD_W_ID` | warn | `module.name` / `module.id` không phải chuỗi | Điền chuỗi; ID nên là duy nhất |
| `MOD_E_LORE` | error | `module.lorebook` không phải mảng, entry không phải object, `key`/`content` không phải chuỗi | Sửa bằng `book` hoặc `set --target module` |
| `MOD_W_LORE` | warn | `mode` lạ (ngoài `normal/constant/multiple/child/folder`), cờ boolean sai kiểu, `insertorder` không phải số nguyên | Sửa đúng kiểu/giá trị; PocketRisu có thể bỏ qua entry sai |
| `MOD_E_REGEX` | error | `module.regex` không phải mảng hoặc entry không phải object | Sửa cấu trúc mảng |
| `MOD_W_REGEX` | warn | `comment/in/out/type` sai kiểu, hoặc `type` ngoài `editinput/editoutput/editprocess/editdisplay/editrequest/disabled/""` | Sửa `type`; sai kiểu chuỗi có thể làm script không chạy |
| `MOD_E_TRIGGER` | error | `module.trigger` không phải mảng hoặc entry không phải object | Sửa cấu trúc mảng |
| `MOD_W_TRIGGER` | warn | `type` ngoài `start/manual/output/input/display/request`; `conditions`/`effect` không phải mảng; `effect` rỗng | Sửa theo đúng shape trigger của Risu |
| `MOD_E_ASSETS` | error | `module.assets` không phải mảng | Sửa thành mảng (có thể rỗng) |
| `MOD_E_ASSET_COUNT` | error | Số phần tử `module.assets` khác số block asset nhị phân trong `module.risum` | Không tự thêm/bớt phần tử; dùng `assets add/remove` hoặc `module decode/encode` với `--assets-dir` |
| `MOD_INFO_LOWLEVEL` | info | `lowLevelAccess` bật | PocketRisu sẽ hỏi người dùng khi import; ghi chú khi giao |
| `BOOK_W_DIVERGENT` | warn | `card.data.character_book.entries` khác `module.lorebook` (khác số lượng hoặc nội dung) | Bình thường khi mới sửa một bên; `pack --sync-book auto` sẽ đồng bộ. Nếu không có module thì không bao giờ báo |

## Asset trong card

`data.assets[N]` được kiểm tra theo từng URI. `#N` trong message là index thực trong mảng.

| Mã | Mức | Điều kiện | Cách xử lý |
| --- | --- | --- | --- |
| `ASSET_E_SHAPE` | error | Phần tử `data.assets[N]` không phải object | Sửa thành object có `type/uri/name/ext` |
| `ASSET_W_SHAPE` | warn | Thiếu hoặc sai kiểu một trong `type/uri/name/ext` | Điền chuỗi; PocketRisu dùng các trường này để đặt tên/đường dẫn |
| `ASSET_E_MISSING` | error | `embeded://<path>` trỏ tới entry không tồn tại | Thêm file đúng đường dẫn hoặc sửa URI; đây là lỗi hay gặp nhất khi đổi tên asset bằng tay |
| `ASSET_E_TOO_LARGE` | error | File embed > 50 MiB | Nén/giảm kích thước; PocketRisu bỏ qua asset quá giới hạn |
| `ASSET_W_EXT_MISMATCH` | warn | Đuôi ảnh không khớp magic bytes (ví dụ `.png` nhưng là WEBP) | Đổi `ext`/đuôi entry cho đúng, hoặc convert ảnh |
| `ASSET_E_V2_MISSING` | error | URI `__asset:N` (card v2) hoặc chuỗi `__asset:N` bất kỳ trỏ tới `chara-ext-asset_:N` không tồn tại | Thêm entry tương ứng hoặc sửa index |
| `ASSET_W_DATA_URI` | warn | `data:` URI lớn hơn giới hạn 50 MB, hoặc base64 không hợp lệ | Chuyển sang file embed; data URI làm phình `card.json` |
| `ASSET_W_EXTERNAL` | warn | URI `http(s)://` | Tải file về và thay bằng `embeded://`; PocketRisu bỏ URL ngoài khi import |
| `ASSET_W_URI` | warn | URI không thuộc `embeded://`, `ccdefault:`, `data:`, `__asset:N`, http(s) (kể cả URI rỗng) | Sửa về một dạng hợp lệ |
| `ASSET_W_NOTE` | warn | Ghi chú thêm từ bộ phân giải (ví dụ URI rỗng, URL ngoài) | Đọc message; thường đi kèm mã khác |
| `ASSET_W_MAIN_ICON` | warn | Không có asset `type=icon, name=main` và archive không có prefix JPEG | Thêm icon chính để card có chân dung |
| `ASSET_W_DUP_REF` | warn | Nhiều asset cùng trỏ một file | Giữ nếu chủ ý; nếu không, tách file để tránh sửa nhầm |
| `ASSET_W_DUP_NAME` | warn | Nhiều asset cùng `name` (ví dụ 4 asset `iconx` trên thẻ mẫu) | Đổi tên nếu cần thao tác theo tên; thao tác theo `#N` vẫn chính xác |
| `ASSET_W_NO_META` | warn | Asset embed không có `x_meta/<basename>.json` | `assets replace/add` tự tạo; với file có sẵn, thêm meta nếu muốn giữ đúng chuẩn PocketRisu |
| `ASSET_W_ORPHAN_META` | warn | Có `x_meta/*.json` nhưng không còn asset tương ứng | Xóa meta thừa bằng `raw rm` |
| `ASSET_W_META_SHAPE` | warn | `x_meta/*.json` không phải JSON object | Sửa hoặc xóa; PocketRisu không đọc meta khi import |
| `ASSET_W_META_JSON` | warn | `x_meta/*.json` không parse được | Như trên |
| `ASSET_W_ORPHAN` | warn | File dưới `assets/` không được `data.assets` tham chiếu | `assets gc` để dọn (chuyển vào `_charx/removed/`), hoặc thêm asset trỏ tới file |

Lưu ý: tên `x_meta` được so **không phân biệt hoa/thường** vì PocketRisu ghi meta theo
basename gốc, còn entry ZIP có thể khác case. Vì vậy `ASSET_W_NO_META` không còn báo sai
trên thẻ thật. Với layout v2, `x_meta` gắn với `chara-ext-asset_:N` có thể bị báo
`ASSET_W_ORPHAN_META` (bộ kiểm tra chỉ kỳ vọng meta cho asset `embeded://`); đây chỉ là
cảnh báo, không ảnh hưởng import.

## Đọc kết quả trên thẻ mẫu

`CharX File (6).charx` sau khi sửa lỗi so khớp meta còn **6 cảnh báo có sẵn**, không có lỗi:

- 5 × `ASSET_W_EXT_MISMATCH`: file `.png` nhưng bytes là WEBP.
- 1 × `ASSET_W_DUP_NAME`: 4 asset cùng tên `iconx`.

Đây là đặc điểm của thẻ nguồn, không phải do toolkit tạo ra. Khi giao card đã sửa, giữ
nguyên các cảnh báo này và ghi rõ chúng có từ trước.

## Liên quan

- Đặc tả đầy đủ: [charx-format.md](charx-format.md)
- Công thức sửa theo từng loại nội dung: [editing-recipes.md](editing-recipes.md)
