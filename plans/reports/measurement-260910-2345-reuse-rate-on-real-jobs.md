# Đo tỷ lệ gộp request trên job thật (engine 1.9.48)

Ngày: 2026-09-10 · Nhánh: `claude/zotero-pdf-translate-comparison-ab1153`

**Phương pháp:** chỉ-đọc. Nạp `model/regions.json` + `model/context_graph.json` có sẵn,
chạy CHÍNH các hàm production (`protect`, `classify_action`, `same_source_groups`,
`build_reuse_map`, `reuse_key`) để tính pipeline 1.9.48 SẼ phát bao nhiêu request. Không
gọi stage nào. `mtime` của cả 4 `regions.json` vẫn là 2026-08-28 — job không bị đụng.

**Mẫu:** 4 job có trên máy — Macmillan *Science: A Closer Look* G1–G4, engine 1.9.47,
`prompt_version: req-v1`, status NEEDS_REVIEW. Tổng 349+ trang/quyển.

---

## 1. Kết quả

| Job | region | cần dịch | gộp được | % | request thực phát | nhóm ĐANG lệch bản dịch |
|---|---:|---:|---:|---:|---:|---:|
| G1 | 3.425 | 3.030 | 680 | 22,4% | 2.350 | 29 |
| G2 | 2.997 | 2.639 | 539 | 20,4% | 2.100 | 12 |
| G3 | 5.749 | 5.206 | 1.059 | 20,3% | 4.147 | 31 |
| G4 | 7.045 | 6.473 | 1.404 | 21,7% | 5.069 | 66 |
| **Tổng** | **19.216** | **17.348** | **3.682** | **21,2%** | **13.666** | **138** |

**21,2% region cần dịch không phải gọi model.** Ổn định 20,3–22,4% trên cả bốn quyển.

Chi phí prompt tiết kiệm, đo bằng chính `requests.jsonl` của các job:
**3,1 / 15,9 MB (19,2%) ≈ 763k token đầu vào**, chưa kể 3.682 lượt sinh bản dịch đầu ra.

## 2. Phát hiện đáng giá hơn con số: 138 nhóm ĐANG lệch bản dịch

Đây là `CONSISTENCY_DRIFT` mà lint cũ không bao giờ thấy (nó duyệt một dict rỗng — xem
CHANGELOG 1.9.48 §Fixed). Cùng một chữ nguồn, trong cùng một quyển, ra nhiều bản dịch:

| Nguồn | Các bản dịch cùng tồn tại | Job |
|---|---|---|
| `ENGAGE` | `KHỞI ĐỘNG` · `GẮN KẾT` · `KHƠI GỢI` | G3, G4 |
| `▶ Learn It` | `▶ Học điều này` · `▶ Học nào` · `▶ Học` | G2, G4 |
| `▶ Try It` | `▶ Thử xem` · `▶ Hãy thử` · `▶ Thử nào` | G2, G4 |
| `Draw Conclusions` | `Rút kết luận` · `Rút ra kết luận` | G3 |
| `You need` | `Em cần` · `Bạn cần` | G2 |
| `Earth and Space Sciences` | `Khoa học Trái Đất và vũ trụ` · `… và Không gian` | G2 |
| `EXTEND` | `MỞ RỘNG` · `Mở rộng` | G1 |

Đây là nhãn điều hướng của sách giáo khoa, in ở đầu mỗi bài. Học sinh thấy `KHỞI ĐỘNG` ở
bài 1 và `GẮN KẾT` ở bài 5 cho **cùng một mục**. Từ 1.9.48 chuyện này không xảy ra được nữa
— cả nhóm dùng chung đúng một bản dịch.

## 3. Khoá chặt có đáng không? Có.

`reuse_key` loại 566 lượt gộp so với gộp thô theo chữ (4.248 → 3.682, **13%**). Lý do tách:

| Trường gây tách | Số nhóm |
|---|---:|
| `region_type` | 372 |
| `masked` (bảng placeholder) | 149 |
| `style_roles` | 19 |
| `spec_cells` / `fill_rules` | 0 |

**149 nhóm tách vì `masked`** đúng là ca đã lường trước: `same_source` gộp theo chữ đã
chuẩn hoá khoảng trắng, nên `"Max 48 V"` và `"Max 48  V"` cùng khoá mà mask khác nhau. Gộp
thô ở 149 nhóm này sẽ in ký tự `⟦MEAS_1⟧` lên trang giao khách. Guard không phải lý thuyết.

`spec_cells`/`fill_rules` = 0 vì sách giáo khoa không có bảng thông số hai cột — trường đó
sẽ có việc ở manual/datasheet.

## 4. Rủi ro chênh khung: gần như không có

Thiết kế chọn đại diện là region có **khung chật nhất**, nên bản dịch dùng chung có thể
ngắn hơn mức ô rộng nhất trong nhóm cho phép. Đo trên 839 nhóm:

| | max/min chiều rộng khung |
|---|---|
| trung vị | **1,00×** (khung y hệt nhau) |
| p90 | 1,29× |
| p99 | 2,01× |
| lớn nhất | 5,05× |
| nhóm chênh > 2× | **9 nhóm (1,1%)** |

Một nửa số nhóm có khung giống hệt nhau; 99% chênh dưới 2×. Cái giá của việc lấy khung
chật nhất là gần bằng 0, còn lợi ích (tránh P0 `G4_RATIO_FLOOR` ở mọi ô hẹp) là thật.

## 5. Giới hạn của phép đo

- Cả 4 job là **sách giáo khoa cùng một nhà xuất bản, cùng template**. Nhãn sư phạm
  (`EXPLAIN`, `EXTEND`, `Quick Check`, `Visual Summary`) lặp rất đều — đó chính là lý do
  tỷ lệ 21% ổn định. **Manual pin/datasheet chưa đo** (14 job trong comment code không còn
  trên máy). Dự đoán: manual cũng lặp nhiều (header bảng, `CẢNH BÁO`, nhãn cột) nhưng
  profile khác; cần một job manual thật để xác nhận.
- Bản dịch trong các job này do engine 1.9.47 sinh với `req-v1`, tức chưa có cảnh báo
  `reused_by`. Con số "138 nhóm lệch" vì thế là ảnh chụp lỗi CŨ, không phải dự báo lỗi mới.
- Không đo được token đầu ra tiết kiệm (job không lưu số token).

## 6. Câu hỏi còn treo

1. **Có nên nới `region_type` khỏi khoá gộp không?** Nó tách 372 nhóm — nhiều nhất. Nới ra
   sẽ đưa tỷ lệ gộp từ 21,2% lên ~24,5%. Nhưng khi ấy một `heading` và một `paragraph` cùng
   chữ sẽ dùng chung bản dịch, mà hai loại này có chế độ khung và `style_roles` khác nhau.
   Khuyến nghị: **giữ nguyên** — 3,3 điểm phần trăm không đáng đổi lấy rủi ro sizing.
2. Có job manual/datasheet nào ở máy khác để đo profile thứ hai không?
