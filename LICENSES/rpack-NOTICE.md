# Ghi chú giấy phép rpack

## Nguồn

`scripts/rpack_map.bin` là bản sao nguyên văn của bảng rpack trong PocketRisu:

| Mục | Giá trị |
| --- | --- |
| Dự án | PocketRisu (phái sinh từ RisuAI của Kwaroran) |
| Repository | https://github.com/PocketRisu/PocketRisu |
| Phiên bản | 1.16.1 |
| Commit | `5da95f713a610219ddcf6c13de8779c52018196d` (2026-10-24) |
| Đường dẫn gốc | `src/ts/rpack/rpack_map.bin` |
| SHA-256 | `428e939c41617140ef2fad0420d9163cc80ce7c9b2f5e620223a25acc8afd498` (512 byte) |

Thuật toán encode/decode trong `scripts/charx_core.py` (`rpack_decode`, `rpack_encode`) là
bản cài đặt lại bằng Python của `src/ts/rpack/rpack_js.js` (dùng `bytes.translate` thay vì
vòng lặp JS). Không có mã nguồn JavaScript nào được sao chép.

## Giấy phép kép

Theo `src/ts/rpack/LICENSE` của PocketRisu, Rpack.js được phát hành **đồng thời** theo
MIT License và GNU AGPL-3.0:

> Rpack.js is dual-licensed under the MIT License and AGPL-3.0 License.
>
> - If you are using Rpack.js in other applications rather than Risuai, or you are trying
>   to embed Risuai inside your own application, you must follow the AGPL-3.0 License.
> - If you are using Rpack.js only within Risuai, you may use it under the MIT License.

Bản sao đầy đủ:

- `rpack-LICENSE-MIT.txt` — MIT License, Copyright (c) 2026 Kwaroran
- `rpack-LICENSE-AGPL.txt` — GNU AGPL-3.0

`rpack_map.bin` được dùng ở đây cho mục đích **tương thích định dạng**: đọc và ghi module
của thẻ PocketRisu/RisuAI. Nếu bạn phân phối toolkit này như một phần của ứng dụng khác
(không phải RisuAI/PocketRisu), hãy tuân theo AGPL-3.0 như điều khoản trên; nếu chỉ dùng
nội bộ trong RisuAI/PocketRisu, MIT là đủ.

Phần còn lại của charx-workbench (CLI, thư viện, tài liệu, test) không ràng buộc theo hai
giấy phép trên; dùng tự do trong phạm vi dự án của bạn. Mã nguồn PocketRisu khác (không
nằm trong thư mục này) vẫn theo giấy phép riêng của nó — xem `LICENSE` tại repository gốc.
