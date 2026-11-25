# Bản đồ khổ lớn (cấp tỉnh/thành, vùng > 50 km) — `scripts/qh_bigmap.py`

Dùng cho quy hoạch tổng thể/quy hoạch chung/quy hoạch tỉnh: một tờ phủ cả trăm km. Rút ra từ lần làm Quy hoạch tổng thể TP.HCM 2025–2050, tầm nhìn 100 năm (pano 14042×9933 px, ~270 km bề ngang).

## Vì sao không dùng `qh_overlay.py` như bản phân khu

- **Phép chiếu**: hệ mét cục bộ (equirectangular) sai hàng trăm mét ở mép tờ 200 km. Bản vẽ VN thường ở UTM 48N hoặc VN-2000 TM-3 (KTT 105°45' cho TP.HCM) → dùng UTM + affine; độ xoay khớp được (~0,15°) cho biết lớp nào theo VN-2000.
- **Gốc tọa độ** phải ở tâm bản đồ; gốc xa hàng trăm km làm bước tinh chỉnh tỉ lệ/góc bị kẹt.
- **So phép chiếu bằng trường điểm khống chế**, không bằng điểm số chồng nước toàn ảnh (biển, hồ lớn chi phối và đánh lừa — lần đầu Web Mercator "thắng" nhưng sai).
- **Pano ghép lớp**: lớp quy hoạch (nội dung trong ranh) có thể bị đặt lệch so với lớp nền vùng xung quanh (TP.HCM: lệch 260–800 m) và mỗi tờ trong bộ lệch khác nhau (QH33 lệch thêm ~500 m so với QH32). → luôn khớp bằng tín hiệu TRONG ranh quy hoạch (`--plan-kml`), và định vị từng tờ.
- **Khung phụ** (đảo xa như Côn Đảo, sơ đồ vị trí) không ở vị trí thật → che khỏi lớp chính, định vị riêng.

## Quy trình

```bash
B="<thư mục skill>/scripts/qh_bigmap.py"; O="<thư mục skill>/scripts/qh_overlay.py"
# cần thêm pyproj: pip install numpy scipy shapely pillow pyproj  (hoặc uv run)
```

1. **Lấy bản vẽ gốc độ phân giải cao nhất** (JPG/PDF của Sở). Trang Sở QH-KT TP.HCM tải nội dung bài qua `POST /ajaxnews/<đường dẫn bài>`; thư mục Viettel Drive (Nextcloud) liệt kê bằng `PROPFIND /public.php/webdav/` (user = mã chia sẻ, mật khẩu rỗng) và tải bằng `GET` cùng đường dẫn — **bắt buộc có User-Agent trình duyệt** (thiếu → 403). Tra phụ lục danh mục bản vẽ trong Quyết định để biết ký hiệu (QH32…) và tỷ lệ.
2. **Ảnh làm việc**: thu nhỏ ½ bằng `Image.draft('RGB', (W//2, H//2))` (nhanh, không giải mã đủ) → ~7000 px.
3. **Vùng che** (`grid`/`masks` của `qh_overlay.py` dùng được trên ảnh làm việc): tiêu đề, ghi chú, chú giải, logo, **khung phụ**.
4. **Ranh quy hoạch**: `qh_overlay.py boundary --name "<tỉnh/thành>"` (admin_level=4). Ranh tỉnh trên OSM thường gồm cả vùng biển → so diện tích phần đất (trừ biển) với số trong Quyết định.
5. **Dữ liệu nước + biển**: bbox phủ CẢ tờ (kể cả vùng xung quanh):
   `python3 $B fetch --bbox S,W,N,E --sea-point "lat,lon;lat,lon" --out osm_big.json` (điểm ngoài khơi trong bbox; lọc bỏ ao/đầm nuôi).
6. **Khớp**: `python3 $B fit anh_q2.png --osm osm_big.json --exclude "..." --plan-kml RanhGioi.kml --center lat,lon --out model.json --check check.jpg`
   - In ra 2 giai đoạn: `[toàn ảnh]` (nền) rồi `[trong ranh QH]`. Nếu trung vị toàn ảnh lớn (>100 m) mà trong ranh nhỏ (~10 m) → pano lệch lớp, kết quả trong ranh là đúng.
   - Đạt: trung vị ≲ 20 m, p90 ≲ 40 m.
7. **Tờ khác cùng bộ**: `python3 $B register anh2_q2.png --model model.json --exclude "..." --plan-kml RanhGioi.kml --out model2.json` (ghép qua mặt nước chung; lệch ghép ~0,5 px).
8. **Khung phụ (đảo)**: cắt khung từ ảnh làm việc → `fetch` bbox quanh đảo với `--sea-point` → `fit khung.png --osm osm_dao.json --scale-range 0.01,0.08 --rot-range=-6,6 --win 180` (ít điểm khống chế → giữ kết quả tìm sơ bộ, vẫn chính xác) → `export` riêng với `--scale 1` (hoặc tỉ lệ ảnh gốc/khung nếu cắt từ ảnh gốc) và KML khung bao quanh đảo.
9. **Xuất**: `python3 $B export anh_goc.jpg --model model.json --scale 2 --clip-kml RanhGioi.kml --exclude-world "<khung phụ, px ảnh làm việc>" --osm osm_big.json --legend "<khung chú giải>" [--drop-gray] --name "..." --desc "QĐ..., nguồn..." --tag qh32 --out QHxx.kmz`
   - Nắn bằng lưới MESH sang lưới kinh/vĩ độ, ô 2048 px (Google Earth không làm mờ ảnh quá lớn), PNG 256 màu → vài MB.
   - `--drop-gray` cho bản vẽ tô xám vùng không thuộc chủ đề (vd "sử dụng đất khu vực đô thị").
   - Ranh hiển thị: muốn giữ khu **lấn biển** quy hoạch thì dùng ranh hành chính có vùng biển cắt trong ~4 km tính từ bờ (nước vẽ trùng biển thật tự trong suốt).
   - Chú giải thành ScreenOverlay (Google Earth Pro) + ảnh trong mô tả (Earth web có thể không hiện ScreenOverlay).
10. **Kiểm tra**: `qh_overlay.py verify --kmz ... --kml RanhGioi.kml --zoom 11` (toàn cảnh) và `--zoom 15` ở 3–4 điểm (lõi đô thị, cửa sông, bờ biển, đảo).

## Bẫy

- Màu nước trên bản đồ tổng thể: quy tắc cũ (`b>r+50`) nhận nhầm khu công nghiệp tím là nước → dùng `g-r>35 & b-g>12 & b>150` (đã có trong `qh_bigmap.py`).
- Đo độ lệch ở ô toàn biển/hồ lớn không tin cậy (đỉnh tương quan phẳng); script chỉ lấy ô có 0,4–35% nước và độ nhọn đỉnh ≥ 5.
- Ô sát ranh lẫn sông của lớp nền → lùi vào trong ranh (`--plan-shrink`, mặc định ~200 m).
- Ghi chú "hồ sơ đang rà soát, hoàn thiện để đóng dấu" trên bản vẽ → ghi vào mô tả và báo người dùng có thể phải làm lại khi có bản đóng dấu.
