# Hướng dẫn sử dụng skill "Bản đồ quy hoạch overlay"

**Tác giả:** [thieprealtor](https://github.com/thieprealtor) · **Phiên bản:** 1.1 · **Cập nhật:** 30/09/2026

Skill giúp Claude biến bản đồ quy hoạch do cơ quan nhà nước công bố (quy hoạch phân khu 1/2000, quy hoạch sử dụng đất…) thành **lớp phủ đặt đúng vị trí trên Google Earth**, để xem quy hoạch chồng lên ảnh vệ tinh của một phường, xã hay khu vực.

---

## 1. Skill làm được gì

| Bạn đưa vào | Bạn nhận về |
|---|---|
| Tên khu vực (phường/xã/phân khu), hoặc | File `.kmz` lớp phủ quy hoạch, mỗi phân khu một file |
| link bài báo, link ảnh, file PDF hay file ảnh bản đồ | File `.kml` ranh giới phường/xã (nếu hỏi theo phường/xã) |
| | Ảnh kiểm tra: lớp phủ chồng lên ảnh vệ tinh |
| | (Tùy chọn) một dự án Google Earth web có sẵn các lớp phủ |

Ví dụ thực tế: hỏi "làm map quy hoạch phường An Khánh" → skill tìm bản đồ Phân khu 1 và Phân khu 7 (TP Thủ Đức cũ) do UBND công bố ngày 23/6/2025, đặt lên Google Earth, kèm ranh giới phường An Khánh mới (sau sắp xếp 1/7/2025).

Nguyên tắc: chỉ dùng bản đồ **công bố chính thức** (cơ quan nhà nước, hoặc báo chí đăng lại nguyên bản); không sao chép bản đồ My Maps/KML của cá nhân khác; luôn ghi nguồn và số quyết định.

## 2. Cài đặt

### Trên Claude (web / ứng dụng máy tính)

1. Tải file [`dist/ban-do-quy-hoach-overlay.skill`](dist/ban-do-quy-hoach-overlay.skill) trong repo này.
2. Mở Claude → **Settings** → **Capabilities** → mục **Skills** → tải file `.skill` lên.
   Nếu ai đó gửi file `.skill` trong cuộc trò chuyện, chỉ cần bấm **Save skill** trên thẻ file.
3. Cần bật tính năng **chạy code / tạo file** (Code execution). Skill chạy script Python và cần truy cập mạng tới:
   `overpass-api.de`, `server.arcgisonline.com`, `nominatim.openstreetmap.org` và trang chứa ảnh bản đồ.
   Nếu môi trường chặn mạng, skill tự chuyển sang chạy trong trình duyệt (cần tiện ích **Claude in Chrome**).

### Trên Claude Code

```bash
git clone https://github.com/thieprealtor/ban-do-quy-hoach-overlay.git
```

```bash
cp -R ban-do-quy-hoach-overlay/skills/ban-do-quy-hoach-overlay ~/.claude/skills/
```

Skill sẽ có mặt ở các phiên Claude Code mới.

## 3. Cách dùng

### Câu hỏi mẫu

- "Làm map quy hoạch phường An Khánh"
- "Đưa bản đồ quy hoạch phân khu số 7 Thủ Đức lên Google Earth"
- "Làm lớp phủ quy hoạch từ file PDF này" (đính kèm file)
- "Làm KMZ quy hoạch xã …, tỉnh … rồi tạo dự án Google Earth và up lên"

### Claude sẽ làm gì

1. **Hỏi nguồn**: bạn có sẵn link/PDF/ảnh bản đồ không. Có thì gửi; chưa có thì Claude tự tìm trên cổng thông tin nhà nước và báo chí uy tín.
2. **Báo nguồn đã chọn** (cơ quan/báo + số quyết định), và các điều chỉnh quy hoạch mới hơn nếu có.
3. **Định vị bản đồ**: tự khớp theo sông, kênh và đường chính của OpenStreetMap.
4. **Kiểm tra** bằng ảnh vệ tinh (bờ sông, cầu, nút giao phải trùng).
5. **Gửi file** `.kmz`, `.kml` ranh giới và ảnh kiểm tra; nếu bạn yêu cầu thì tải thẳng vào một dự án Google Earth web.
6. **Báo kết quả**: nguồn, số quyết định, độ chính xác, lưu ý khi sử dụng.

### Mẹo

- Ghi rõ tỉnh/thành phố (nhiều nơi trùng tên phường/xã).
- Đã có nguồn chính thức thì gửi ngay trong câu đầu để bỏ qua bước hỏi.
- Muốn đưa thẳng lên Google Earth web thì nói rõ "tạo dự án rồi up lên" (dùng tài khoản Google của bạn trong Chrome).

## 4. Mở kết quả trong Google Earth

**Google Earth Pro (máy tính)**
- *File → Open*, chọn file `.kmz` / `.kml` (hoặc bấm đúp vào file).
- Bật/tắt từng lớp bằng ô tick trong khung *Places*.
- Chỉnh độ trong suốt: chọn lớp trong *Places* rồi kéo thanh trượt ở dưới khung, hoặc chuột phải lớp → *Properties* (macOS: *Get Info*).

**Google Earth web** (earth.google.com)
- *Dự án → Mới → Dự án bản đồ mới* → *Tệp → Nhập tệp → Tải lên từ thiết bị* → chọn file → *Đối tượng trên bản đồ* → *Hoàn tất*.
- Dự án lưu vào Google Drive và xem được trên ứng dụng Google Earth điện thoại.

## 5. Dùng script không cần Claude

Script `skills/ban-do-quy-hoach-overlay/scripts/qh_overlay.py` chạy độc lập với Python ≥ 3.9 và các thư viện `numpy scipy shapely pillow`:

```bash
python3 -m pip install numpy scipy shapely pillow
```

Hoặc dùng `uv run qh_overlay.py …` (script khai báo sẵn thư viện, uv tự cài).

### Các lệnh

| Lệnh | Việc làm |
|---|---|
| `geocode "<địa danh>"` | Tìm tọa độ và gợi ý khung bbox |
| `grid <ảnh>` | Ảnh lưới tọa độ pixel để chọn vùng cần che |
| `masks <ảnh> --exclude …` | Xem phân loại nước/đất sau khi che |
| `fetch-osm --bbox S,W,N,E` | Tải đường chính và mặt nước OpenStreetMap |
| `boundary --bbox … --name "<phường>"` | Ranh giới phường/xã → KML |
| `intersect --road1 … --road2 …` | Tọa độ giao lộ (làm điểm khống chế) |
| `align <ảnh> --exclude …` | Tự khớp bản đồ; hoặc `--gcp` theo điểm khống chế |
| `export --params … --out X.kmz` | Xuất lớp phủ KMZ |
| `verify --kmz … --kml …` | Ảnh kiểm tra trên nền vệ tinh |

### Ví dụ đầy đủ (phường An Khánh, bản đồ Phân khu 1 lưu thành `pk1.jpg`)

```bash
S=skills/ban-do-quy-hoach-overlay/scripts/qh_overlay.py
python3 $S geocode "phường An Khánh, Thành phố Hồ Chí Minh" --margin-km 4
python3 $S fetch-osm --bbox 10.735,106.690,10.835,106.820 --out osm.json
python3 $S boundary --bbox 10.735,106.690,10.835,106.820 --name "An Khánh" --out RanhGioi_PhuongAnKhanh.kml
python3 $S grid pk1.jpg --out grid1.jpg
python3 $S align pk1.jpg --osm osm.json \
  --exclude "39,178,727,1188;1840,1757,2560,2501;1079,2659,2560,3620;0,2787,1083,3620" \
  --out p1.json --check check1.jpg --boundary RanhGioi_PhuongAnKhanh.kml
python3 $S export --params p1.json --osm osm.json \
  --name "QHPK 1/2000 Phân khu số 1 – TP Thủ Đức" \
  --desc "Phê duyệt: QĐ 8248/QĐ-UBND ngày 15/6/2025; công bố 23/6/2025" \
  --out QHPK1_AnKhanh_overlay.kmz
python3 $S verify --kmz QHPK1_AnKhanh_overlay.kmz --kml RanhGioi_PhuongAnKhanh.kml --out kiemtra.jpg
```

### Chọn vùng che (`--exclude`)

Bản đồ công bố thường có tiêu đề, bảng biểu, chú giải, khung tên và sơ đồ phụ nằm cạnh bản vẽ. Các vùng này phải che đi để không làm sai phép khớp:

1. Chạy `grid` rồi đọc tọa độ góc từng khung trên lưới (tọa độ pixel ảnh gốc, dạng `x0,y0,x1,y1`, các khung cách nhau bằng dấu `;`).
2. Soi kỹ mép bằng `grid <ảnh> --crop x0,y0,x1,y1`.
3. Chạy `masks` để xem lại: xám là vùng che, xanh là nước, cam là đất quy hoạch. Che **vừa khít** khung, không lấn vào bản đồ.

### Khi không có sông lớn: dùng điểm khống chế

1. `intersect --road1 "Tên đường A" --road2 "Tên đường B"` để lấy tọa độ giao lộ.
2. Tìm pixel của đúng giao lộ đó trên ảnh bằng `grid --crop`.
3. `align <ảnh> --gcp "u,v,lat,lon;u,v,lat,lon;u,v,lat,lon"` với 3–5 điểm trải đều; thêm `--refine` nếu khu vực có kênh/hồ.

## 6. Độ chính xác và giới hạn

- Sai số định vị thường **20–50 m**; chỉ để tham khảo.
- Ảnh bản đồ do báo đăng thường chỉ rộng khoảng 2.560 pixel, tương đương 2–3,5 m mỗi pixel: xem được tổng thể, không đọc được chi tiết từng lô.
- Quy hoạch có thể đã **điều chỉnh cục bộ** sau khi công bố; skill cố tìm tin điều chỉnh mới nhất nhưng không đảm bảo đủ.
- Ranh giới phường/xã lấy từ OpenStreetMap; skill so diện tích với số liệu chính thức để phát hiện ranh cũ.
- **Khi tư vấn một lô đất cụ thể, luôn đối chiếu thông tin quy hoạch chính thức** (tra cứu tại cơ quan có thẩm quyền).

## 7. Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| Lớp phủ lệch rõ, `score` < 0.5 | Kiểm tra vùng che; thêm `--scale-range` nếu biết thước tỉ lệ; hoặc dùng `--gcp` |
| Mất một dải bản đồ, có mép thẳng | Vùng che lấn vào bản đồ → thu hẹp khung che |
| Báo lỗi Overpass (406/429/timeout) | Đợi vài phút rồi chạy lại; script tự thử máy chủ khác |
| Báo thiếu thư viện | Cài `numpy scipy shapely pillow` hoặc chạy bằng `uv run` |
| Môi trường chặn mạng (403) | Mở quyền mạng cho tính năng chạy code, hoặc để skill chạy trong trình duyệt (Claude in Chrome) |
| Diện tích ranh giới phường lệch nhiều | OpenStreetMap có thể chưa cập nhật ranh mới; dùng nguồn chính thức |

## 8. Nguồn dữ liệu và bản quyền

- Bản đồ quy hoạch thuộc cơ quan ban hành / báo đăng lại; repo không chứa ảnh bản đồ.
- OpenStreetMap: © OpenStreetMap contributors, giấy phép ODbL (dùng để định vị và vẽ ranh giới).
- Ảnh vệ tinh Esri World Imagery chỉ dùng để tạo ảnh kiểm tra, không đưa vào file KMZ.

## 9. Tác giả và góp ý

- Tác giả: **thieprealtor** — <https://github.com/thieprealtor>
- Báo lỗi, góp ý: mở *Issue* tại <https://github.com/thieprealtor/ban-do-quy-hoach-overlay/issues>
- Giấy phép [MIT](LICENSE) © 2026 thieprealtor: được dùng, sửa, chia sẻ (kể cả thương mại), với điều kiện giữ nguyên ghi chú bản quyền và giấy phép trong mọi bản sao.

### Lịch sử phiên bản

- **1.1** (30/09/2026): hỏi nguồn trước khi tìm; script Python tự khớp theo mặt nước và điểm khống chế; ranh giới phường; ảnh kiểm tra vệ tinh; KMZ gọn hơn; tra số quyết định và điều chỉnh mới.
- **1.0** (30/09/2026): bản đầu, chạy hoàn toàn trong trình duyệt (Claude in Chrome).
