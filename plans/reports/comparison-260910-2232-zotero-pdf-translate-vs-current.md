# So sánh: `windingwind/zotero-pdf-translate` vs `pdf-translate-layout`

Ngày: 2026-09-10 · Nhánh: `claude/zotero-pdf-translate-comparison-ab1153`
Bằng chứng: clone `zotero-pdf-translate` @ `eae077e` (2026-08-28), đọc trực tiếp source.

---

## 1. Kết luận một dòng

Hai repo **không cạnh tranh nhau** — chúng giải hai bài toán khác hẳn. Nhưng
`zotero-pdf-translate` (ZPT) đã trưởng thành ở đúng những chỗ repo này còn mỏng:
**lớp trừu tượng nhà cung cấp dịch, bộ nhớ dịch (cache), và làm sạch output của LLM.**

## 2. Hai bài toán khác nhau

Hình dung anh Minh, kỹ sư ESS, có file `LFP-manual-33p.pdf`:

| | ZPT | Repo này |
|---|---|---|
| Anh Minh làm gì | Mở PDF trong Zotero, **bôi đen** một đoạn → bản dịch hiện ở popup bên cạnh | Chạy pipeline → nhận **file PDF mới** 33 trang, tiếng Việt, layout y hệt bản gốc |
| Sản phẩm đầu ra | Text trong panel / comment của annotation / trường metadata | `output/translated-approved.pdf` |
| PDF gốc có bị sửa? | **Không bao giờ** | Có — redact + vẽ lại chữ tại đúng baseline |
| Ai dịch | 46 dịch vụ (Google, DeepL, GPT, Claude…) | Chính agent trong phiên (Claude Code / Codex) |
| Đưa cho khách hàng được? | Không (chỉ đọc tại chỗ) | Có (đó là mục tiêu) |

ZPT là **kính lúp đọc tài liệu**. Repo này là **xưởng in lại tài liệu**.
Phần chồng lấn duy nhất: "lấy chữ ra khỏi PDF rồi dịch".

## 3. Chấm điểm theo trục

| Trục | ZPT | Repo này | Ai hơn |
|---|---|---|---|
| Bảo toàn layout | không có khái niệm | 7 gate + pixel diff 300/600 DPI | **Repo này**, cách biệt lớn |
| Chống dịch giả/dịch sót | không có | `carry_through`, `negation_drop`, `digit_drift`, `symbol_drift`, `address_entity_drift`, authenticity P0 | **Repo này**, hiếm gặp |
| Kiểm chứng & fail-closed | không (là công cụ UI) | máy trạng thái, P0 không waive, audit trail | **Repo này** |
| Đa nhà cung cấp dịch | 46 service sau 1 interface 60 dòng | 1 (agent), luồng thủ công tự ghép | **ZPT** |
| Bộ nhớ dịch / cache | có (queue lookup) | **không có** | **ZPT** |
| Làm sạch output LLM | strip `<think>`, regex hậu xử lý | **không có** | **ZPT** |
| Tự nhận diện ngôn ngữ nguồn | `franc` + trường `language` của item | cứng en→vi | **ZPT** |
| Phân phối / cộng đồng | 11.757 sao, 507 fork, 3 locale, cài 1 click | skill nội bộ, 64 commit | **ZPT** |
| Test | 1 file, 2 assertion | `selftest.py` 2.259 dòng | **Repo này** |

Quy mô: ZPT ~11.009 dòng TypeScript trong `src/`; repo này ~8.494 dòng Python trong
`scripts/`. Cả hai đều **AGPL-3.0** → mượn code hợp lệ về giấy phép.

---

## 4. Năm điều đáng học, xếp theo (giá trị ÷ công sức)

### 4.1. Dùng lại bản dịch cho region trùng nguồn — CAO / RẤT THẤP

**Bằng chứng ZPT:** `src/modules/services/index.ts` — trước khi gọi API, nó tìm ngược
trong queue một task đã `success` có cùng `raw` + `service` + cặp ngôn ngữ, trúng thì
lấy luôn kết quả.

**Tình trạng ở đây:** `build_context_graph.py` **đã dựng sẵn** nhóm `same_source`, và
`validate_responses.py:441-454` dùng nó để *báo* `CONSISTENCY_DRIFT` (P2) khi một nguồn
ra nhiều bản dịch khác nhau. Tức là ta đã có dữ liệu, nhưng chỉ dùng để **phát hiện lỗi
sau khi đã tốn token**.

**Đề xuất:** trong `translate_prep.py`, mỗi nhóm `same_source` chỉ phát **một** request;
`validate_responses.py` fan-out target cho các region còn lại. Tài liệu kỹ thuật lặp rất
nhiều ("CẢNH BÁO", "Battery Module", header bảng, nhãn cột) — với job 1947 region, phần
lặp là thật.

Lợi ích kép: giảm token, **và** biến `CONSISTENCY_DRIFT` từ "lỗi phải bắt" thành
"không thể xảy ra". Sửa nguyên nhân, không phải sửa triệu chứng.

⚠️ Bẫy: cùng chữ nhưng khác ngữ cảnh có thể cần khác bản dịch (ví dụ "Cell" trong bảng
thông số vs "Cell" trong sơ đồ). Nên khoá khoá gộp theo `(source_masked, region_type)`
và chỉ gộp region ngắn dạng nhãn; đoạn văn dài để nguyên.

### 4.2. Chặn rác suy luận của LLM lọt vào bản in — CAO / RẤT THẤP

**Bằng chứng ZPT:** `src/utils/str.ts` → `stripEmptyLines()` xoá `<think>…</think>`.
Đây là bug thật họ gặp trong production khi người dùng cắm model suy luận.

**Tình trạng ở đây:** `validate_responses.py` kiểm schema, placeholder round-trip, NFC,
glossary, authenticity — **nhưng không có luật nào bắt `<think>`, ```` ```json ````,
hay câu mở đầu kiểu "Here is the translation:"**. Nếu agent rò rỉ, chuỗi đó sẽ đi thẳng
qua `fit_paint.py` và **được vẽ lên PDF giao cho khách**.

Gate 3 (`rendered-text coverage`) cũng không bắt được: nó kiểm target *có mặt* trong
output, mà rác thì đúng là có mặt.

**Đề xuất:** thêm luật reject P1 trong `validate_responses.py`, cùng chỗ với
`EMPTY_TARGET`:

```python
# Rác suy luận / bao bọc markdown của model lọt vào target. Không tự gỡ:
# gỡ ngầm là che dấu việc provider không tuân prompt (§1 fail-closed).
LLM_ARTIFACT_RE = re.compile(
    r"</?think\b|```|^\s*(?:Here(?:'s| is)|Bản dịch|Translation)\s*:",
    re.IGNORECASE | re.MULTILINE)
```

**Khác biệt triết lý quan trọng:** ZPT **gỡ thầm**, repo này phải **từ chối**. Gỡ thầm
hợp với công cụ đọc (người dùng thấy ngay và tự đánh giá); không hợp với đường ra file
giao khách, nơi nguyên tắc là fail-closed.

### 4.3. Interface nhà cung cấp dịch cho luồng thủ công — TRUNG BÌNH / TRUNG BÌNH

**Bằng chứng ZPT:** `src/modules/services/base.ts` — interface chỉ 6 trường
(`id`, `type`, `translate`, `defaultSecret?`, `secretValidator?`, `config?`), đủ chứa
46 dịch vụ. `_template.ts` là file mẫu 80 dòng comment hướng dẫn 8 bước thêm dịch vụ mới.

**Tình trạng ở đây:** README hứa "For sensitive documents, run the manual flow with a
private translation source instead" — nhưng thực tế người dùng phải **tự viết glue** để
đọc `requests.jsonl` → gọi API riêng → ghi `responses.jsonl`. Lời hứa riêng tư trong
README hiện chưa có code đỡ.

**Đề xuất:** một `scripts/translate_provider.py` nhỏ với Protocol:

```python
class TranslateProvider(Protocol):
    id: str
    def translate(self, batch: list[dict], langfrom: str, langto: str) -> list[dict]:
        """batch = request objects; trả responses đúng schema responses.jsonl."""
```

Kèm 1-2 provider tham chiếu (OpenAI-compatible endpoint, LibreTranslate self-host).
Đây là điều duy nhất trong danh sách này làm **mở rộng phạm vi** repo — cân nhắc có
thật sự muốn không (xem câu hỏi treo §6).

### 4.4. Kiểm tra ngôn ngữ nguồn ở preflight — TRUNG BÌNH / THẤP

**Bằng chứng ZPT:** `src/utils/config.ts:1-6` dùng `franc` suy ra ngôn ngữ khi trường
`language` của item trống; `task.ts:autoDetectLanguage()` cache kết quả theo item.

**Tình trạng ở đây:** `engine_config_default.yaml` cứng `source: en`. Nếu ai đó đưa PDF
tiếng Trung, `preflight.py` vẫn cho qua; lỗi chỉ lộ ở gate authenticity rất muộn — sau
khi đã đốt toàn bộ token dịch.

**Đề xuất:** thêm một check nhẹ ở `preflight.py` — tỷ lệ ký tự ASCII + tỷ lệ stopword
tiếng Anh trên text đã trích. Lệch ngưỡng → P1 "nguồn có vẻ không phải `languages.source`".
Không cần thêm dependency; tránh cả một job hỏng.

### 4.5. Công thức toán như thực thể được bảo vệ — THẤP / THẤP

**Bằng chứng ZPT:** `src/utils/mathRenderer.ts` — regex bắt `$$…$$`, `\[…\]`, `$…$`,
`\(…\)` rồi render bằng KaTeX.

**Tình trạng ở đây:** không có khái niệm công thức. Với manual pin thì hiếm, với
datasheet thì có (công thức tính SOC, dung lượng).

**Đề xuất (tuỳ chọn):** không cần render — chỉ cần thêm một **kiểu protected token**
`FORMULA` trong `translate_prep.py:protect()` để công thức đi qua nguyên vẹn và được
round-trip verify như `MEAS`/`MODEL`. Tái dùng regex của ZPT làm điểm khởi đầu.

---

## 5. Ba thứ KHÔNG nên bê về

1. **Rừng 46 service.** ZPT phải tự ký request cho Aliyun/Tencent/Baidu, tự cài
   `jsencrypt` (`src/utils/crypto.ts`, 208 dòng). Đó là chi phí họ trả vì có 11.757 sao
   người dùng. Repo này không có nhu cầu đó — nếu làm §4.3 thì làm **một** Protocol,
   không phải 46 file.

2. **`resultRegex` hậu xử lý do người dùng cấu hình** (`services/index.ts`). Cho phép
   người dùng gõ regex xoá bất kỳ thứ gì khỏi bản dịch — trực tiếp mâu thuẫn với
   "no silent fallbacks" trong CONTRIBUTING của repo này.

3. **Cache chỉ khoá theo raw text.** ZPT khoá cache bằng `raw + service + langpair`,
   không có ngữ cảnh. Chấp nhận được cho popup đọc tạm; không chấp nhận được khi bản
   dịch được in ra và đóng dấu duyệt (xem bẫy ở §4.1).

4. **Không có retry/backoff.** Kiểm tra toàn bộ `src/`: chỉ đúng MyMemory xử lý 429
   (`services/mymemory.ts:23,33`). Đây là **điểm yếu** của ZPT, không phải bài học.

---

## 6. Câu hỏi còn treo

1. **§4.3 có nằm trong phạm vi không?** Thêm provider interface = repo tự nhận trách
   nhiệm với chất lượng của MT bên thứ ba, trong khi toàn bộ gate authenticity hiện
   được thiết kế quanh giả định "người dịch là một model có suy luận". Giữ nguyên
   "agent-only" và sửa README cho khớp cũng là một lựa chọn hợp lệ.
2. **§4.1 ngưỡng gộp:** chỉ gộp region `≤ N từ`? N bao nhiêu? Cần đo trên job thật
   (14 job đã có sẵn số liệu) trước khi chốt.
3. **§4.2 nên P1 hay P0?** Rác `<think>` lọt vào file giao khách là lỗi nghiêm trọng,
   nhưng khác với pseudo-translation ở chỗ nó *dễ thấy* khi review. P1 có vẻ đủ.
