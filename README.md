# ban-do-quy-hoach-overlay

**Tác giả:** [thieprealtor](https://github.com/thieprealtor) · **Hướng dẫn sử dụng:** [HUONG-DAN-SU-DUNG.md](HUONG-DAN-SU-DUNG.md)

Skill cho Claude: biến ảnh/PDF bản đồ quy hoạch (QHPK 1/2000, QH sử dụng đất…) do cơ quan nhà nước công bố thành **lớp phủ KMZ đặt đúng tọa độ trên Google Earth**, kèm ranh giới phường/xã và ảnh kiểm tra trên nền vệ tinh.

- Hỏi nguồn trước; người dùng không có thì tự tìm trên cổng thông tin nhà nước và báo chí uy tín.
- Tự khớp bản đồ theo sông/kênh và đường chính của OpenStreetMap; sai số thường ~20–50 m.
- Chỉ dùng nguồn công bố chính thức; ghi nguồn + số quyết định vào lớp phủ.
- Có thể tải thẳng các lớp phủ vào một dự án Google Earth web (qua Claude in Chrome).

## Cài vào Claude

Tải [`dist/ban-do-quy-hoach-overlay.skill`](dist/ban-do-quy-hoach-overlay.skill) rồi tải lên mục Skills trong phần cài đặt của Claude (hoặc bấm **Save skill** khi file được gửi trong cuộc trò chuyện).

Gọi bằng các câu như: "làm map quy hoạch phường An Khánh", "đưa bản đồ quy hoạch lên Google Earth", "làm lớp phủ quy hoạch phân khu số 7". Cài trên Claude Code, cách mở kết quả trong Google Earth và xử lý sự cố: xem [hướng dẫn sử dụng](HUONG-DAN-SU-DUNG.md).

## Dùng script độc lập

`skills/ban-do-quy-hoach-overlay/scripts/qh_overlay.py` chạy được không cần Claude: Python ≥ 3.9 với `numpy scipy shapely pillow`, hoặc `uv run` (script khai báo sẵn thư viện).

Ví dụ phường An Khánh (TP.HCM), bản đồ Phân khu 1 do Tuổi Trẻ đăng lại ngày 23/6/2025 lưu thành `pk1.jpg`:

```bash
S=skills/ban-do-quy-hoach-overlay/scripts/qh_overlay.py
python3 $S geocode "phường An Khánh, Thành phố Hồ Chí Minh" --margin-km 4
python3 $S fetch-osm --bbox 10.735,106.690,10.835,106.820 --out osm.json
python3 $S boundary --bbox 10.735,106.690,10.835,106.820 --name "An Khánh" --out RanhGioi_PhuongAnKhanh.kml
python3 $S grid pk1.jpg --out grid1.jpg          # đọc tọa độ bảng biểu/chú giải cần che
python3 $S align pk1.jpg --osm osm.json \
  --exclude "39,178,727,1188;1840,1757,2560,2501;1079,2659,2560,3620;0,2787,1083,3620" \
  --out p1.json --check check1.jpg
python3 $S export --params p1.json --osm osm.json \
  --name "QHPK 1/2000 Phân khu số 1 – TP Thủ Đức" --desc "QĐ 8248/QĐ-UBND ngày 15/6/2025" \
  --out QHPK1_AnKhanh_overlay.kmz
python3 $S verify --kmz QHPK1_AnKhanh_overlay.kmz --kml RanhGioi_PhuongAnKhanh.kml --out kiemtra.jpg
```

Kết quả thử nghiệm với bản đồ này: khớp tự động khoảng 20 giây/tờ, score 0.74 (PK1) và 0.85 (PK7), lệch so với ảnh vệ tinh trong khoảng 20–50 m.

Các lệnh con: `geocode`, `grid`, `masks`, `fetch-osm`, `boundary`, `intersect`, `align` (tự động hoặc `--gcp` theo điểm khống chế), `export`, `verify`. Xem `python3 $S <lệnh> -h`.

## Cấu trúc

```
skills/ban-do-quy-hoach-overlay/
├── SKILL.md                    # quy trình cho Claude
├── scripts/qh_overlay.py       # định vị + xuất KMZ + kiểm tra vệ tinh
└── references/browser-mode.md  # quy trình thay thế khi sandbox bị chặn mạng
dist/ban-do-quy-hoach-overlay.skill   # gói cài đặt
```

## Dữ liệu và bản quyền

- Bản đồ quy hoạch thuộc cơ quan ban hành / báo đăng lại; repo không chứa ảnh bản đồ, tự tải theo link nguồn.
- OpenStreetMap: © OpenStreetMap contributors, ODbL (dùng để định vị và vẽ ranh giới).
- Ảnh vệ tinh Esri World Imagery chỉ dùng để tạo ảnh kiểm tra, không đưa vào KMZ.
- Lớp phủ chỉ để tham khảo; khi tư vấn lô cụ thể phải đối chiếu thông tin quy hoạch chính thức.

## Tác giả

**thieprealtor** — <https://github.com/thieprealtor>. Khi chia sẻ hoặc dùng lại, vui lòng ghi nguồn tác giả. Báo lỗi, góp ý: mở [Issue](https://github.com/thieprealtor/ban-do-quy-hoach-overlay/issues).
