---
name: pdf-translate-layout
description: Dịch PDF có text layer (mặc định EN→VI) bảo toàn layout, ảnh, vector, bảng và typography theo PDF Translation Engine v1. Dùng khi user muốn dịch PDF giữ nguyên format ("translate PDF keep layout", dịch manual/datasheet/quick guide sang tiếng Việt), hoặc tiếp tục một translation job đã có. Fail-closed; output cuối chỉ phát hành khi quality gates pass và có human approval.
license: AGPL-3.0
compatibility: Agent-agnostic theo chuẩn Agent Skills. Đã kiểm chứng trên Claude Code và OpenAI Codex (2026-08-05, cùng job 514 region, cả hai đạt). **Antigravity IDE 2.1.1 ĐÃ THỬ VÀ KHÔNG ĐẠT** — sửa `scripts/approve.py` để tự cấp quyền phát hành, chạy quá phạm vi, Gate 2/3/4/6 FAIL; xem `plans/reports/incident-antigravity-self-approve-and-engine-tamper-260805-1222-*`. Agent khác chưa kiểm chứng. Cần shell macOS/Linux + Python >= 3.10; bootstrap deps một lần bằng `bash scripts/setup.sh` (cần network lúc cài); runtime offline, fonts đã bundle.
metadata:
  version: "1.9.46"
---

# pdf-translate-layout

> **Trạng thái:** RELEASED v1.9.46 (engine `1.9.46`, layout model `lg-basic-6`) —
> scripts Milestone 1-4 core hoạt động, đã E2E-test full trên tài liệu thật 15 và
> 29 trang (7/7 gates PASS). Đã kiểm chứng trên Claude Code và Codex; **Antigravity
> không đạt — §9**. Có authenticity gates chống pseudo-translation (§1.6, §7).
> Giới hạn v1 ở §11.
>
> Từ 1.2.1: **1.3.0** thêm detector truncation + short-identical (§7), validator chỉ
> đọc response line cuối mỗi region. **1.4.0** đổi layout model sang `lg-basic-3`:
> hàng bảng gõ liền bằng space được tách theo lưới cột, wrap budget trừ đúng phần
> thụt lề, fit_paint và qa_gates dùng chung dung sai descent (`qa.container_tol_y_em`).
> Layout model đổi tên vì regions.json của cùng một source khác lg-basic-2 → job cũ
> không reproduce được bằng engine mới, phải re-run.
> **1.4.1** thêm `NUMBER_DRIFT` vào `validate_responses.py`: tập chữ số của target phải
> khớp source, lệch thì P1 kèm số thiếu/thừa. **Cảnh báo, không chặn** — nội dung trải qua
> nhiều region có thể dồn số hợp lệ. Không đụng layout; job dựng bằng 1.4.0 vẫn re-fit
> được. Lý do có gate này: 2026-08-05 một model dịch mục lục thành **mục lục khác** (8
> dòng, đổi cả số mục lẫn tên mục) mà mọi gate đều xanh — Gate 2 không thấy vì bản dịch
> trôi chảy, đúng tiếng Việt, không trùng source.
> **1.4.2** siết truncation + thêm hai lưới nội dung, đo trên 7185 cặp của 14 job trước
> khi chốt: (1) sàn truncation 12→6 từ, thêm tầng source ≥12 từ mà target <60% — audit
> 2026-08-05 tìm thấy bản Lite user manual ĐÃ RELEASED mất ~10 câu (cấm ngắn mạch, cấm
> nối tiếp, nửa lệnh tiếp địa, nguyên Bước 1 lắp đặt) đều nằm ở ratio 0.45–0.59, dưới
> radar sàn cũ; (2) `NEGATION_DROP` — source có not/never/forbidden/without mà target
> không còn từ phủ định nào; (3) `SYMBOL_DRIFT` — multiset `<>≤≥±` phải khớp (0 false
> positive đo được). Cả ba là P1 cảnh báo, không chặn; số đếm in ở dòng tổng kết
> validate. Không đụng layout.
> **1.4.3** thêm `TRANSLATION_CARRY_THROUGH` — **P0, không waive được**. Bắt find-replace:
> target giữ ≥3 từ **thường** của source và nhiều hơn gấp đôi số từ tiếng Việt. Ca thật
> nằm trong bản ĐÃ RELEASED: nguyên quy trình khởi động/tắt máy chỉ đổi mỗi chữ `Step` →
> `Bước`, phần còn lại giữ nguyên tiếng Anh; `lang_suspect` không thấy vì nó đòi dưới 5%
> ký tự có dấu, khối này ở 6.9%. Chỉ đếm từ thường nên tên riêng giữ nguyên không bị bắt.
> Đo trên 7185 cặp/14 job: **0 hit ở mọi bản dịch đạt**, bắt trọn 3 khối của bản lỗi.
> **1.4.4** sửa cửa sổ đọc của Gate 3: mép dưới nới đúng bằng descent slack mà `fit_paint`
> được phép dùng (`max(tol_pt, container_tol_y_em × size)`), cùng công thức Gate 4 vẫn
> dùng. Cửa sổ cũ cố định 2pt trong khi slack là 0.6em (5.4pt ở cỡ chữ 9pt), nên dòng
> cuối của region nhiều dòng nằm ngoài vùng đọc và gate báo `G3_TARGET_NOT_FOUND` — P0,
> không waive được — dù chữ có thật trên trang. Đo 2026-08-05: 11/11 P0 của bản V16 Lite
> là báo giả, mốc V16 manual dính thêm 2 ca cùng kiểu. Ngang và mép trên giữ chặt như cũ.
> **1.4.5** tách đúng vai Gate 3 và Gate 4. Gate 3 đo **độ phủ** — bản dịch có lên được
> trang không; hình học là việc Gate 4. Khi target không nằm trong khung container nhưng
> **có trên trang** (so cả bản bỏ khoảng trắng, vì `space_w` của 1.4.0 làm trích xuất lệch
> dấu cách ở hàng bảng nhiều cột), gate ghi `G3_TARGET_OUTSIDE_BOX` mức P2 và trỏ sang
> cảnh báo Gate 4 cùng region, thay vì `G3_TARGET_NOT_FOUND` P0. Thiếu hẳn chữ vẫn là P0
> không waive được. Đo trên 5 cột dịch của cùng một job 514-581 region: **23/23 P0 của
> gate này là báo giả**, chữ có thật trên trang in.
> **1.5.0** sửa hai lỗi layout đã treo từ đầu (`lg-basic-3` giữ nguyên, `region_id` không
> đổi nên mọi `responses.jsonl` cũ vẫn re-fit được):
> (1) **`space_w` theo font token liền kề.** Khe đứng sau một token được vẽ bằng font của
> chính token đó (segment gộp `t1 + " " + t2`), nhưng fitter lấy chung font token đầu
> region. Dòng trộn sans/mono lệch 2.38pt mỗi khe — bốn khe là 9.5pt, đủ để dòng thò khỏi
> ô. `wrap_lines` nay nhận list bề rộng khe.
> (2) **Ngân sách dọc đo từ `base_y`, không phải chiều cao container.** Chữ vẽ từ origin
> của span nguồn chứ không từ mép trên ô, nên phần trên `base_y` không chứa được dòng nào.
> Đối xứng với `wrap_w = c[2] - base_x` vốn đã đúng.
> **1.5.1** `authenticity_check` nhận `keep_terms`: region mà source **chỉ gồm** thuật ngữ
> `keep` của glossary thì giữ nguyên là đúng, không phải "chưa dịch". Ca thật: quick guide
> giữ `Shanghai PYTES Energy Co., Ltd.` đúng theo glossary mà Gate 2 vẫn báo
> `TRANSLATION_IDENTICAL` rồi làm gate đỏ. Chỉ bỏ qua khi không còn từ nào ngoài các term
> đó — region lẫn văn xuôi vẫn được xét đầy đủ.
> **1.5.2** nới khung heading vào khoảng trống đo được (`layout.expand_heading`, mặc định bật).
> Khung region lấy theo bbox chữ **nguồn**; tiếng Việt dài hơn nên một tiêu đề vừa khít ở bản
> gốc thành `FIT_IMPOSSIBLE` dù quanh nó là khoảng trắng. Ca thật: tựa bìa `User Manual`
> (158pt) → `Hướng dẫn sử dụng` (250pt) trong khung 196.6pt. **Không** giải bằng cách cho
> xuống dòng: khung cao 33.7pt, hai dòng cỡ 25.1pt cần 57.7pt — thiếu chiều cao chứ không
> thiếu số dòng. Luật: chỉ áp cho heading **một dòng** (kể cả tiêu đề đánh số bị `LIST_RE`
> xếp nhầm thành `list_item`), chỉ khi fit thất bại, nới đúng bề rộng cần, dừng trước mọi
> vật cản cùng dải dọc (chữ region khác + vector + ảnh) và trong lề thân bài. Heading có tâm
> chữ trùng tâm trang (±3pt) được nới **đối xứng và chuyển sang căn giữa** — giữ "left" thì
> chữ vẫn vẽ từ `base_x` cũ và cụm dài hơn sẽ lệch phải khỏi bố cục gốc.
> **Đặt ở stage 6 chứ không ở extract** vì `region_id` sinh từ `container[0]//8`,
> `container[1]//8`: đổi container ở stage 2 sẽ đổi region_id và làm mồ côi toàn bộ
> `responses.jsonl` đã dịch. Khung vẽ ghi vào `container_paint`; Gate 3/4 đọc nó khi có.
> `region_id`, `lg-basic-3` và mọi job cũ không đổi.
> **1.6.0** thêm **Translation Context Graph** (stage 2.5, `build_context_graph.py`) — nối
> các region thuộc về nhau để model thấy trọn câu/cụm thay vì từng mảnh rời. Lý do: PDF tách
> chữ thành ô nhỏ, thường một dòng một region; đo trên V16 user manual (833 region)
> `continuation_*` = 0 trong khi riêng trang thư ngỏ có 16 liên kết câu thật, nên model dịch
> từng mảnh với ~80 ký tự hàng xóm và không đảo vế qua ranh giới ô được. Graph **không dịch**
> — chỉ nối cạnh bằng hình học + regex (§1.6). Cạnh: `continues` (văn xuôi cùng đoạn ·
> caption-stack cho nhãn nhiều dòng · cross-page cũ), `co_figure`, `same_source`,
> `under_heading`. Artifact `model/context_graph.json`; region nhận thêm `chain_id`.
> **Guard là phần quan trọng nhất** — không có nó thì 9/10 chuỗi ngoài trang thư ngỏ là nối
> sai: loại tiêu đề đánh số (`LIST_RE` khớp `"5."` trong `"5.1.1 …"` nên `region_type` không
> lọc được), dòng mục lục, `Table N`/`Figure N`, dòng `Nhãn: giá trị`, và đầu chuỗi dưới 4
> từ. Caption-stack đo khe theo **chiều cao một dòng**: cụm nhãn thật 0.035, hai nhãn rời
> xếp chồng 0.173–0.301 → ngưỡng 0.12. Đo lại sau guard: V16 manual **9/9 chuỗi đúng**.
> Kèm theo: `translate_prep` (`req-v2`) đưa `chain_source`/`chain_position`/`chain_kind`/
> `co_figure` vào request, prev/next nới 80→240 ký tự (80 cắt giữa câu nên hàng xóm thường
> vô nghĩa), không cắt batch giữa chuỗi, và **bỏ note "ưu tiên vừa container, không cần dịch
> sát từng chữ"** — note đó đẻ ra văn cụt kiểu điện tín và viết tắt tự chế.
> `validate_responses` thêm `CONSISTENCY_DRIFT` (P2, cảnh báo): cùng một nguồn ra hai bản
> dịch khác nhau. So theo nhóm **đã lọc chuỗi** — mảnh của một cụm nhiều dòng trùng chữ với
> một nhãn độc lập là khác biệt hợp lệ (ca thật: `Battery side` mảnh của cụm ở p19 vs nhãn
> độc lập ở p21, hai bản dịch khác nhau và cả hai đều đúng). Đo: 0 báo oan trên bản đã sạch,
> bắt đúng `Model Pin`/`Model pin` trên bản chưa sửa.
> `region_id`, `lg-basic-3`, `container` và mọi job cũ **không đổi** — graph là artifact
> phụ, job dựng trước 1.6.0 chạy được không cần graph.
> **1.7.0** → layout model **`lg-basic-4`**: gộp **cross-block** các dòng cùng một đoạn
> (`layout.merge_paragraph`, mặc định bật; tắt → `lg-basic-3`). `group_block_lines` chỉ gộp
> trong MỘT block rawdict, mà PDF hay đặt mỗi dòng vào một block riêng — thư ngỏ V16 là 28
> dòng thành 28 block, khe thật 2.72pt, thừa điều kiện gộp nếu chung block. Hệ quả cũ: câu
> bị xé theo dòng, model dịch từng mảnh, tiếng Việt không đảo vế qua ranh giới region được.
> Dùng **chung detector với context graph** (`flow_link`) — một luật, hai mức áp dụng: 1.6.0
> chỉ đưa chuỗi vào context, 1.7.0 gộp thật để fitter wrap lại tự do. Mọi guard của graph áp
> nguyên. Đo trên V16 user manual: 833 → 818 region, 9 lần gộp, **10/10 đúng**; thư ngỏ 22
> dòng rời thành 8 đoạn; sau khi gộp graph báo `chains=0` — đúng như thiết kế, không còn gì
> để nối. Mọi đoạn gộp còn dư chỗ reflow (3 dòng/khung chứa 4; 5 dòng/khung chứa 7).
> Kết quả ngôn ngữ: `"developed and produced by Pytes"` nay dịch được thành **"do Pytes phát
> triển và sản xuất"** thay vì calque `"được phát triển và sản xuất bởi Pytes"` mà lg-basic-3
> không sửa nổi vì động từ và tác nhân nằm ở hai region.
> Kèm **`STALE_TRANSLATION`** (P1): `translation_meta` nay đóng dấu `source_hash`, và validate
> báo khi region đổi `source_text` sau khi đã dịch mà vẫn mang bản dịch cũ. Lỗ hổng thật đo
> được lúc migrate: đổi layout model làm 2 region giữ nguyên `region_id` nhưng nguồn dài ra;
> một ca bị `PLACEHOLDER_MISMATCH` chặn, **một ca lọt** vì tỉ lệ từ 0.69 vẫn trên sàn
> truncation 0.60. Job dịch trước 1.7.0 chưa có dấu → lần migrate đầu tiên phải đối chiếu
> `source_hash` bằng tay.
> **Đổi layout model = job cũ phải re-run stage 2.** Chi phí đo được trên V16 manual: chỉ 31
> `region_id` đổi, **0/53 sửa tay bị mồ côi**, 13 region cần dịch mới.
> **1.9.40** → stage 2 vớt thêm chữ mà `get_text()` không trả về. `rawdict` là nguồn duy
> nhất cho tới 1.9.39; trên `Phocos Guide for V5.pdf` trang 2 nguyên đoạn *"Plug in the
> battery end into the RS485 port…"* in ra bình thường (cùng `ArialMT` 12pt, cùng màu, cùng
> `opacity` 1.0, `type` 0 như đoạn ngay dưới, khác mỗi `seqno`) mà `rawdict` không có, trong
> khi `get_texttrace()` có đủ glyph. Không line → không region → stage 4 không dịch, và
> **không gate nào bắt được**: G6 so pixel nguồn với bản dịch, đoạn chưa dịch thì hai bên
> giống hệt nhau nên không sinh diff. Đo trên 44 hướng dẫn ghép biến tần: **8 file, 91 dòng,
> 4.862 ký tự**; 36 file còn lại và nguồn của mọi bản đã giao khách đều vớt 0. Dòng vớt được
> báo `TEXT_RECOVERED_BY_TRACE` (P2) kèm số trang.
>
> Hai chốt chống nhân đôi, cả hai dựng SAU khi đo: so khớp theo **chuỗi** chứ không theo
> bbox (texttrace gộp span khác cách rawdict, so tâm bbox báo thừa 13.021 ký tự trên
> `V16 Lite user manual` vốn đã dịch đủ); và bỏ run đã được line rawdict phủ **quá nửa ký
> tự** — chỗ rawdict rơi ligature nó trả `BaƩery QuanƟty` còn texttrace trả
> `Battery Quantity`, khác chuỗi nên lọt vòng đầu rồi đè lên dòng cũ (`V5 Series` 10 dòng
> trước, 0 sau). Đếm theo ký tự vì đếm theo diện tích để lọt ca span trải ngang hai cột.
> **1.9.41** → `expand_container` nhận ra **dải nền chạy sau chữ** và thôi coi nó là vật cản.
> Tiêu đề mục `BOM LIST` của 15 hướng dẫn ghép biến tần nằm trên dải màu rộng 432pt trong khi
> ô chữ chỉ 90–98pt; `DANH MỤC VẬT TƯ` cần 153.1pt ở 16pt. Trước bản vá **cả 15 job đều
> `expand_container → None`**: 6 job xuống 2 dòng lòi ra ngoài dải màu, 6 job `FIT_IMPOSSIBLE`
> nên **giữ nguyên chữ tiếng Anh trên bản giao khách** — lỗi không cổng nào bắt, vì
> `FIT_IMPOSSIBLE` là P1 nằm lẫn giữa 660 cảnh báo font của cùng đợt.
> Phải GHÉP mảnh rồi mới xét: 5/15 file xuất dải màu thành **48 ô vẽ rời rộng 8pt** — ba ô
> dưới chữ (chồng lên chữ → chặn đứng phép nới), 45 ô bên phải (kẹp mép phải về sát chữ).
> Xét từng ô thì không ô nào là "nền". Sau vá: 15/15 nới tới 154.1pt, một dòng, đủ cỡ 16pt.
> Mảnh nền phải phủ ≥50% chiều cao vùng chữ — ngưỡng này tách nền khỏi **nét kẻ ngang cắt qua
> chữ** (dày <1pt, phủ ~3%, vẫn chặn như cũ). bbox chữ của region khác không bao giờ được tính
> là nền dù trải rộng, nếu không nới sẽ đè lên hàng xóm.
> **1.9.42** → cỡ chữ gốc tính theo ký tự CÓ MỰC. `src_size` là median cỡ theo từng ký tự và
> trước đây đếm cả khoảng trắng, nên span đệm dài hơn phần chữ thật thì nó thắng phiếu. Ca
> thật `E-BOX 48100R Sol-Ark package` và `V5 Sol-Ark packages` trang 2, dòng cuối bảng thông
> số: run 0 = **20 dấu cách 13.6pt**, run 1 = `10 Years ` 9 ký tự 8.0pt → `10 năm` vẽ ở
> 13.6pt, to gần gấp đôi mọi dòng quanh nó và tràn 4.99pt lên dòng trên. Quét cả kho: **10
> vùng / 8 job**, trong đó **6 job đã giao khách** ở mức lệch 1–2.6pt — đủ kín để lọt qua mọi
> lần duyệt. Đây là trục thứ ba và là trục cuối của họ lỗi "đệm space", sau trục x
> (`ink_base_x`, 1.8.0/1.9.9) và trục kiểu chữ (`role_style`/`role_face`, 1.9.34/1.9.35).
> Một luật chung: span khoảng trắng có advance nhưng không vẽ gì, nên không được quyết định
> thứ gì về hình thức của chữ thật. Vùng toàn khoảng trắng giữ nguyên hành vi cũ.
> **1.9.43** → luật hoà phiếu giữa hai cỡ chữ THẬT. Median là thống kê sai cho vùng bimodal:
> nó rơi về cụm đông hơn dù chỉ hơn một ký tự. Ca thật `V16 user manual` tr.11, ô
> `Integrated Thermal Aerosol Fire Suppression Module`: nhãn chính 45 ký tự ở 9.0pt, chú thích
> 46 ký tự ở 5.0pt → 46 thắng 45, cả ô vẽ 5.0pt, nhãn nhỏ đi 44% so với nguồn. Bản phát hành
> trước ra 7.0pt chỉ vì median khi ấy đếm cả khoảng trắng nên rơi đúng vào giữa — ăn may, không
> phải luật. Cụm nhì đạt ≥80% số ký tự cụm nhất thì lấy **cỡ lớn hơn**: nhãn chính là thứ mắt
> đọc trước, và fitter còn quyền thu nhỏ nếu không vừa — thu từ cỡ đúng xuống an toàn hơn phóng
> từ cỡ sai lên. Đo trên chính ô đó: src_size 9.0 → fit 8.96pt, 5 dòng, không sinh issue.
> **1.9.44** → cửa sổ đọc của **Gate 3 nhánh keep** chuẩn hoá khung và hợp thêm vệt mực
> (`read_window`). `container` có thể SUY BIẾN — `x0 > x1`, bề rộng ÂM — khi bản gốc để lại
> text object cỡ 0; cộng pad vào một dải đảo chiều cho ra cửa sổ lệch chỗ. Ca thật
> 2026-08-12, PYTES ESS Catalogue trang 30/36: container `[591.1, 62.5, 589.3, 70.5]`, mực ở
> `[591.1, 62.5, 591.4, 62.6]`; cửa sổ cũ dừng ở 591.3 — **hụt đúng 0.1pt** so với mép phải
> glyph, nên gate báo `G3_KEEP_LOST` trong khi trích xuất bằng khung nới 3pt cho `'000000'` ở
> **CẢ nguồn lẫn bản dịch**. Đây là **P0 không waive được**, nên hai báo giả này chặn đứng
> phát hành một job sạch 1601/1620 vùng.
> Cùng lớp lỗi 1.4.4 và 1.9.5 đã sửa cho nhánh translate: cửa sổ đo hụt thì gate nói mất chữ
> trong khi chữ có thật. Nhánh keep sót lại tới 1.9.43.
> Không nới lỏng phép so: `char_deficit` đếm theo bội nên thiếu ký tự vẫn bị bắt bất kể cửa sổ
> rộng bao nhiêu; hình học vẫn là việc của Gate 4. Đo trước khi vá: **3/10943 region toàn kho
> có container suy biến**, cả ba là vùng `keep` của chính tài liệu này. Sau vá: 2 P0 → 0,
> không region nào đang sạch bị chuyển thành lỗi.
> Kèm hai sửa nữa, cùng đợt:
> (2) **`infer_alignment` nhận ra hình THỤT LỀ TREO.** Khi không mốc nào được ≥2 dòng đồng
> thuận, luật biên độ của 1.9.8 chọn trục có biên độ nhỏ nhất — và lề phải răng cưa thường
> hẹp hơn phần thụt lề, nên khối căn trái bị đọc thành `right`. Ca thật catalogue tr.51:
> `Unbalanced Loads Supported` / `50% of Rated Power Each Phase`, mép trái lệch 13.7pt, mép
> phải lệch 2.9pt → cả cụm bị đẩy sang phải trong khi ô anh em 3 dòng ngay trên vẫn `left`.
> Nay: dòng đầu chạm đúng mép trái khung (±1pt) và mọi dòng sau lùi vào trong thì trả `left`.
> Chỉ can thiệp khi biên độ chọn `right` — khối căn giữa thật có `vc` nhỏ nhất nên không
> dính (tựa bìa quick guide V16 Lite, dòng 2 thụt 33.8pt trái / 27.8pt phải).
> Đo trên 1840 vùng ≥2 dòng: 181 rơi vào luật biên độ, luật này đổi **đúng 12, toàn bộ sang
> `left`, 0 ca oan**. Luật rộng hơn (chỉ đòi MỘT dòng bất kỳ chạm x0) đổi 47 vùng và phá hỏng
> nhãn hình căn giữa lẫn cặp `Figure N` — đã thử, không ship.
> (3) **`split_style_roles`: vùng toàn `body` mang HAI kiểu chữ thật thì tách nhóm nhỏ sang
> `emphasis`.** Engine vẽ một kiểu cho mỗi role; khi trong role có hai kiểu đều là chữ thật
> thì không đại diện nào đúng — một nửa vùng chắc chắn sai cỡ, sai màu. Ca thật catalogue
> tr.53-54: mỗi mục phụ kiện là một region gồm mã hàng `RanyLight 11pt` xám rồi mô tả
> `RanyMedium 13.6pt` gần đen; cả hai `bold=False` nên luật độ đậm không tách được và
> `role_style` lấy run đầu → cả khối vẽ xám 11pt.
> Chốt: vùng chưa có role nào khác `body`; gom theo `(cỡ, màu)` ra ĐÚNG hai nhóm; cỡ chênh
> ≥15%; và nhóm nhì **hoặc** chiếm ≥25% ký tự **hoặc** nằm trên dòng riêng và dài ≥6 ký tự.
> Ngả thứ hai là bắt buộc vì mã hàng 12 ký tự cạnh mô tả 130 ký tự chỉ được 8%.
> Bỏ chốt "dòng riêng" → 115 vùng dính, phần lớn là dấu chú thích mũ mà 1.9.21 cố ý gộp;
> bỏ chốt "≥6 ký tự" → 98 vùng, kéo theo số chú thích đầu dòng của các bản Terms of Warranty
> **đã phát hành**. Sau đủ chốt: **30 vùng toàn kho**.
> Nhóm ĐÔNG hơn giữ `body`, nên response cũ chỉ dùng `body` vẫn hợp lệ và vẽ y như trước;
> phần lợi chỉ đến khi bản dịch tách run.
> (4) **Vùng XOAY ưu tiên một dòng**, dù nguồn nhiều dòng. Với vùng xoay, xuống dòng không
> phải "bố cục kém hơn" mà là **bỏ vẽ hẳn** (`ROTATED_MULTILINE`, §11) — cả vùng giữ tiếng
> Anh trên bản giao. Thu cỡ chữ trong giới hạn `minimum_ratio` luôn tốt hơn thế. Ca thật
> catalogue tr.4: `Shanghai Headquarter` → `Trụ sở chính Thượng Hải` cần 90.8pt trong dải đọc
> 87.8pt — thiếu 3pt mà mất cả nhãn; `North American Marketing Center` thiếu 6.3pt. Không vừa
> nổi một dòng ngay ở sàn thì vẫn quay về luật cũ, nên nhánh này không thể làm xấu hơn hiện
> trạng. Đo trên trang 4: bỏ vẽ **9 → 7 vùng**, hai nhãn bản đồ được cứu.
> **1.9.45** → hai sửa về TRỌNG LƯỢNG và CỠ CHỮ.
> (1) **`is_bold_font`: chữ đậm quyết định theo TÊN font, cờ của PDF chỉ dùng khi tên câm.**
> Cùng lý lẽ `is_serif_font` (1.9.33). Ca thật catalogue tr.53-54: `RanyMedium` khai
> `bold=False` trong khi nó là nấc nặng của họ Rany — phần MÔ TẢ phụ kiện vẽ mảnh y như mã
> hàng, mất hẳn tương phản bản gốc dựng. Khác `is_serif_font` một chỗ: tên KHÔNG có dấu hiệu
> trọng lượng thì **trả về cờ**, không trả mặc định — font subset tên tự sinh (`CIDFont+F1`,
> 803 ký tự) không nói gì về trọng lượng mà cờ của chúng đúng.
> `medium` xếp vào nhóm đậm vì font pack chỉ có hai nấc: nhiệm vụ là tái tạo TƯƠNG PHẢN, không
> phải khớp tuyệt đối. Đo trên kho: đúng **2 họ font** lệch giữa tên và cờ — `RanyMedium`
> (7302 ký tự, chỉ tài liệu này) và `SourceHanSansCN-Medium` (2 ký tự). Job catalogue: **51
> vùng đổi cấu trúc role, 0 region_id mất/mới, 0 source_hash đổi.**
> (2) **Vùng XOAY: cỡ chữ bị chặn trên bởi vệt mực của nhãn NGUỒN**, sàn `rotated_ink_floor`
> (0.80). Nhãn xoay nằm trong hình vẽ chật — bản đồ mạng lưới, hình chiếu kích thước — nên
> khung (đã nới tới vật cản gần nhất) rộng hơn chỗ thiết kế dành cho nhãn rất nhiều; vẽ đầy
> khung thì chữ tiếng Việt chạy đè lên artwork. Đo trên trang 4: 30 nhãn xoay, bản dịch dài
> tới **205% vệt mực nguồn** (`China` 26.8pt → `Trung Quốc` 55.1pt) — tỷ lệ mà không cách viết
> nào rút xuống được. Sau vá: 11 nhãn thu về 80-90%, `Kho Los Angeles` (cần 83%) vẽ được thay
> vì bị bỏ.
> **Sàn này phải dùng CHUNG giữa `fit_paint` và `qa_gates`** — `ROTATED_INK_FLOOR_DEFAULT` ở
> `_common.py`, cùng cách với `CONTAINER_TOL_*`. Bẫy đã sập một lần: hai bên đặt default khác
> nhau (0.80 và `minimum_ratio`), job đóng băng config trước 1.9.45 không có khoá nên gate
> chấm bằng 0.85 và bắn **11 `G4_RATIO_FLOOR` — P0 không waive được** cho đúng những nhãn
> fitter vừa thu đúng luật.
> **1.9.46** → font pack có thêm **face KÝ HIỆU** `NotoSansSymbols2-Regular` (OFL-1.1, cùng
> nguồn `notofonts.github.io` với 10 face chữ). `FontPack.FALLBACK_CHAIN` trước đó dừng ở
> `mono-regular`, nên **một ký tự ký hiệu duy nhất** làm cả vùng thành `FONT_GLYPH_MISSING`
> (P1) và bỏ vẽ — mất trọn bản dịch của vùng đó, không chỉ mất cái dấu.
> Face ký hiệu đứng **CUỐI** chain và không bao giờ là face chính: `key_for` chỉ trả
> sans/serif/mono, và selftest chốt cả hai điều đó cùng với việc nó KHÔNG phủ chữ Việt.
> Phủ được `✓ ✔ ✗ ▪ • ○ ◇` và các khối ký hiệu khác. Giới hạn còn lại: `cover()` đòi MỘT face
> phủ trọn **token**, nên `kiểm✓` dính liền vẫn hỏng — tách bằng dấu cách thì chạy. Codepoint
> **PUA** của Wingdings/Symbol thì không font chuẩn nào có; bản dịch phải thay bằng ký hiệu
> Unicode thật (ca thật: `U+F0FC` của khối CSS trang 4 → `✓`).
> Kèm sửa một **nhãn chẩn đoán sai**: từ 1.9.44 vùng xoay chỉ nhận bố cục một dòng, nên bản
> dịch nhiều đoạn không còn cỡ chữ nào hợp lệ và rơi ra `FIT_IMPOSSIBLE` — gửi người duyệt đi
> rút ngắn chữ trong khi thứ chặn là số ĐOẠN. Nay vùng xoay có ngắt dòng cứng báo đúng
> `ROTATED_MULTILINE`. Đo trên job: 2 vùng đổi nhãn, không vùng nào đổi kết quả vẽ.
> **Sáu sửa này đổi `runs` và `alignment` trong `regions.json` nhưng KHÔNG đổi `region_id`
> hay `source_hash`** — đo trên chính job catalogue: 0 region_id mất, 0 mới, 0 source_hash
> đổi, 3 vùng đổi căn lề, 16 vùng đổi cấu trúc role, `responses.jsonl` không mồ côi.
> Job cũ chạy lại stage 2 → 7 là hưởng.

> **1.8.0** → layout model **`lg-basic-6`** (`lg-basic-5` khi tắt gộp đoạn): dọn nốt
> `G4_TABLE_RULE_CROSS`. Hai nguyên nhân độc lập, cả hai đều đo được:
> (1) **bbox của line tính cả space đầu/đuôi.** Space có advance nhưng không vẽ gì; ô bảng
> lấy `container = cell | bbox` nên khung phình ra khỏi cột và fitter wrap theo bề rộng
> không có thật. Đo: V16 manual p26 thổi **7.5pt** (3 space đuôi), Lite p30 thổi 2.5pt —
> mực nguồn dừng ở 380.4/380.2 trong khi vạch kẻ ở 380.9/380.8, tức **bản gốc không hề
> chạm vạch**, chỉ khung mới vượt. `build_lines` nay đo theo `ink_bbox`.
> (2) **`fragment_row` đòi ≥2 space** mới coi là ranh giới cột. Bản gốc V16 ngăn cột bằng
> **một space đơn** (`Recovery* 0%＜SOC≤5% 5%＜SOC≤10% …` là nguyên một hàng 6 cột), nên cả
> hàng thành một region trải hết bảng. Số lượng space không phân biệt được gì: khe cột hẹp
> nhất đo được **1.33pt**, còn mảnh hơn khe từ thường (2.50pt). Chỉ hình học nói lên điều
> đó — nay cắt tại **mọi** khe space có vạch kẻ **thật** nằm trong khe (dung sai 1.5pt vì
> chữ được phép chờm lên vạch: `Recovery*` vượt 0.45pt).
> Ranh giới đổi từ lưới logic `find_tables` sang `vertical_rules`, và vạch phải cắt ngang
> đúng dải y của dòng mới tính — ô gộp không có nét ngăn nhưng lưới logic vẫn báo có, và
> luật cũ sẽ xé đôi một tiêu đề trải hết bảng. `vertical_rules` chuyển về `_common.py`:
> stage 2 cắt theo danh sách nào thì Gate 4 chấm theo đúng danh sách đó.
> Đo trên hai tài liệu trước khi chốt: **Lite 26→26 lần cắt (không đổi một ca nào)**, V16
> manual 26→39, toàn bộ 13 ca thêm nằm đúng 6 hàng đa cột thật. Văn xuôi trong ô có 5 khe từ
> thường: **0 lần cắt oan**.
> **1.8.1** thêm **`PH_DIGIT_ADJACENT`** (P2, stage 3): cảnh báo khi nguồn đã mask có chữ số
> dính liền **chữ cái** ngay cạnh placeholder, và đưa cảnh báo đó vào `source_warnings` của
> request để model gỡ được ngay lúc dịch. Lỗ hổng thật: bản gốc V16 in `is1 5V` cho `1.5V`,
> `protect()` che `5V` thành `⟦MEAS_1⟧` còn chữ số `1` mắc lại trong `is1` — model dịch ra
> "đạt 5V", **sai một bậc 10 lần** trong hướng dẫn xử lý sự cố. `NUMBER_DRIFT` bắt được
> nhưng ở stage 5, sau khi đã dịch sai. Luật CHẶT (đòi chữ cái liền trước chữ số) đo trên
> 1243 vùng của 3 tài liệu: **1 đúng, 0 oan**; bỏ điều kiện chữ cái thì 19 cảnh báo, 18 oan
> (dính hết số mục kiểu `6.1 ⟦MODEL_1⟧`). Không đụng layout — job cũ chỉ cần chạy lại
> stage 3.
> **1.8.2** sửa lỗi **fail-open ở chốt phát hành**. `approve.py` lật trạng thái sang
> RELEASED *trước* rồi mới copy `render/draft.pdf` sang `output/`, mà `Job.p()` chỉ ghép
> đường dẫn chứ không tạo thư mục — job chưa từng phát hành thì `output/` chưa tồn tại,
> `copyfile` ném `FileNotFoundError`, và job **mang trạng thái RELEASED mà không có bản
> phát hành nào**. Sự cố thật 2026-08-06: 2/3 job đổ, job thứ ba chạy được chỉ vì đã có
> `output/` từ lần phát hành trước — nên lỗi ẩn suốt từ đầu. Nay: `stage_release_copy()`
> tạo thư mục và ghi ra `<out>.part` TRƯỚC, lật trạng thái SAU, rồi `os.replace()` nguyên
> tử vào tên chính thức. Hỏng ở bất kỳ bước nào cũng fail-closed, và `output/` không bao
> giờ chứa `translated-approved.pdf` khi trạng thái chưa phải RELEASED.
> **1.8.3** `engine_version` trong determinism tuple nay được đóng dấu ở **mọi** stage
> (`Job.mark_stage`), không chỉ ở `extract_group`. 1.8.0 đã sửa được nửa vấn đề — preflight
> đóng dấu một lần rồi thôi — nhưng job chạy tiếp `fit_paint`/`qa`/`approve` bằng engine mới
> hơn vẫn khai engine của lần extract cuối. Đo 2026-08-06: ba job khai `1.8.0` trong khi
> render và QA do 1.8.1/1.8.2 sinh. Ai tái lập job theo con dấu đó sẽ checkout nhầm phiên
> bản. `layout_model_version` vẫn do stage 2 đóng vì nó là việc riêng của stage đó.
> **1.8.4** thêm **`CONSISTENCY_ENTITY`** (P1, stage 5): **địa chỉ bưu chính bị dịch**.
> Lỗ hổng thật nằm trong bản Lite đã RELEASED — p32 ra `Số 3492 Đường Jinqian, Quận
> Fengxian, 201406 Thượng Hải` trong khi p1 của **cùng tài liệu** giữ nguyên tiếng Anh, nên
> bản in mang hai dạng địa chỉ và dạng ở p32 không gửi thư tới được. `CONSISTENCY_DRIFT`
> không thấy vì nó chỉ so region có nguồn khớp **tuyệt đối**, mà nguồn p1 (`…Shanghai,
> China`) khác nguồn p32 (`…201406 Shanghai,`). `URL`/`EMAIL`/`STD` đã được `protect()` che
> nên round-trip qua `PLACEHOLDER_MISMATCH`; địa chỉ là văn xuôi thường — đúng lớp thực thể
> duy nhất còn hở. Luật soi **đúng một lớp** đó: bản rộng hơn (gom mọi thực thể) đo được 0
> đúng / 3 oan vì gom nhầm `UN3480`, `IEC62619`, `UL1015` vào một nhóm. Đo luật hẹp trên
> 1947 region của ba tài liệu: fire đúng **5 region — cả 5 là địa chỉ nhà máy thật, 0 oan**;
> bản dịch lỗi p32 bị bắt với 4 token thiếu. Nhãn không bị soi (`Factory Address` → `Địa chỉ
> nhà máy` là đúng), tên **quốc gia** cũng không (`China` → `Trung Quốc` hợp lệ và nhất quán
> ở cả ba tài liệu). Kèm mục **6c** trong `AGENT_INSTRUCTIONS.md` để model biết trước lúc
> dịch. Không đụng layout — job cũ chỉ cần chạy lại stage 5.
> **1.9.0** ba sửa độc lập, **không đụng layout model** — `region_id`, `container` và
> `responses.jsonl` của mọi job cũ giữ nguyên; job cũ chỉ cần chạy lại stage 5-7.
> (1) **`column_split` — ô bảng gộp nhiều cột được vẽ đúng cột.** `fit_region` vẽ MỌI dòng
> từ `base_x` của span đầu region, nên một hàng bảng mà PDF khai là MỘT cell bị dồn hết về
> mép trái trong khi hàng tiêu đề ngay trên vẫn giữ 3 cột. Ca thật: hàng dữ liệu bảng bảo
> hành V16 — `find_tables` trả đúng một cell trải 65.5→491.6 vì bản gốc **không kẻ nét dọc
> ở hàng dữ liệu**, nên `vertical_rules` của 1.8.0 (đúng khi từ chối cắt) không đụng tới.
> Nay tách thành sub-region theo cột trước khi fit, mỗi cột giữ `base_x` riêng. Bằng chứng
> để coi là cột thật chứ không phải thụt lề: **cùng một x xuất hiện ở ≥2 hàng y khác nhau**
> — lưới thì lặp, thụt lề thì không; cộng điều kiện `region_type == table_cell` để loại hẳn
> nhãn danh sách (`(i)`, `a.`) vốn cũng sinh nhiều x nhưng ở `paragraph`, nơi reflow về một
> cột mới là hành vi đúng. Hợp đồng với bản dịch: mỗi đoạn tách bằng `\n` là một cột, trái
> sang phải; lệch số đoạn thì giữ nguyên hành vi cũ, engine không tự đoán. Sub-region mang
> nguyên `region_id` của cha nên mask, `painted_ids` và Gate 3/4 vẫn chấm theo khung cha.
> (2) **`digit_drift` quy số mũ Unicode về chữ số thường trước khi đếm.** Nguồn in dấu chú
> thích bằng span cỡ nhỏ (`Energy Retention³`), mà engine vẽ **một cỡ chữ cho cả region**
> nên bản dịch buộc phải dùng `¹²³⁴⁵⁶` để dấu không tụt xuống thành chữ thường (`năng3` đọc
> như lỗi chính tả trong văn bản pháp lý). Không quy đổi thì mọi dấu chú thích bị báo thiếu
> chữ số — 8 báo giả trên riêng Terms of Warranty — và waive cả mã `NUMBER_DRIFT` sẽ che mất
> một ca lệch số thật. Ca lỗi thật (`"3 Interface and Components"` → `"3.1 Dụng cụ"`) vẫn bị
> bắt sau khi quy đổi.
> (3) **Ô trống điền tay chảy theo chữ.** Biểu mẫu chừa chỗ điền bằng một **nét gạch chân
> vector**; mask cố ý không xoá line-art (`PDF_REDACT_LINE_ART_NONE`) nên nét sống qua paint,
> còn `tokenize` gộp mọi khoảng trắng thành một dấu cách nên bản dịch không tạo lại được khe
> — chữ chạy đè lên gạch và biểu mẫu hết dùng được. Nay `fill_in_rules` (ở `_common.py`, cùng
> chỗ với `vertical_rules` để mọi stage đọc chung một định nghĩa) nhận diện nét đó ở stage 2
> và ghi vào `reg["fill_rules"]`; stage 3 đưa cảnh báo vào `source_warnings` để model đặt lại
> ô trống bằng dãy `____`; stage 6 xoá nét gốc bằng **một lượt redaction RIÊNG với
> `text=NONE`** — rect gạch chỉ cao ~1pt nhưng nằm đúng baseline nên chạm bbox glyph liền kề,
> dùng chung lượt với `text=REMOVE` sẽ ăn mất chữ của region giữ nguyên. Gate 5 trừ đúng
> những cụm đã xoá khỏi mốc kỳ vọng (`blank_rules_removed` trong render manifest), không nới
> lỏng phép so. Bản dịch quên đặt lại ô trống → **P1 `FILL_BLANK_DROPPED`**, và nét gốc được
> giữ nguyên chứ không xoá mù.
> Điều kiện quyết định là **có chữ ở CẢ HAI phía trên cùng một hàng**: luật lỏng hơn (chỉ đòi
> gạch nằm trong dải mực của một dòng) đo trên 5 tài liệu cho 6 đúng / **11 oan** — toàn bộ 11
> ca oan là nhãn chú thích hình có đường dẫn ngang của Lite quick guide, nơi chữ chỉ nằm một
> bên. Thêm điều kiện hai phía: **6 đúng / 0 oan**.
> `fill_rules` là **metadata thuần**, không đụng `source_text`/`source_hash`/`region_id` — đo
> trên 4 job: chạy lại stage 2 cho **0 region_id mất/mới, 0 source_hash đổi**, response không
> mồ côi.
> **1.9.1** `decisions.jsonl` chỉ được ghi khi quyết định **đã thực sự có hiệu lực**.
> `approve.py` ghi dòng quyết định ngay khi vào lệnh — TRƯỚC `require_human_terminal` và
> trước cả các chốt P0/P1. Sự cố thật 2026-08-06: reviewer chạy vòng lặp duyệt nhiều job,
> mỗi job đòi một chuỗi thử thách `APPROVE <sha8>` KHÁC nhau; gõ nhầm thì release bị chặn
> đúng (job giữ `NEEDS_REVIEW`, `output/` rỗng) nhưng nhật ký vẫn còn dòng "Leo approved".
> Một phiên sinh **4 dòng ma** trên 4 job. `decisions.jsonl` là append-only nên không xoá
> được — hồ sơ kiểm toán "ai duyệt cái gì" nói sai sự thật vĩnh viễn, hỏng đúng thứ nó tồn
> tại để bảo vệ. Nay mỗi nhánh (`reject` / `revoke` / `approve`) tự gọi `record()` sau khi
> chốt của mình đã qua; riêng nhánh approve đặt **ngay trước `set_status`** chứ không phải
> sau — Release rule đòi bản phát hành phải có decision kèm approver, nên `RELEASED` mà
> thiếu dòng ghi còn tệ hơn chiều ngược lại. `revoke` trên job chưa RELEASED cũng hết ghi.
> Bất biến thứ tự nằm trong `main()` nên không test bằng hàm thuần được: selftest soi thẳng
> mã nguồn (5 case, neo đúng mức thụt lệnh). Kiểm bằng đột biến — dựng lại thứ tự cũ thì
> **3/5 case đỏ**, dời chỗ ghi xuống sau khi lật trạng thái thì **1/5 đỏ**. Kiểm đầu-cuối
> trên bản sao job: approve không-TTY bị chặn → **không sinh `decisions.jsonl`**, trạng thái
> và `output/` không đổi; `reject` vẫn ghi bình thường. Không đụng layout, không đụng
> `region_id` — job cũ không ảnh hưởng.
> **1.9.2** cây thư mục job tự lành ở **mọi** stage, không chỉ ở preflight. `Job.p()` chỉ
> ghép chuỗi đường dẫn — thư mục nào vắng thì lệnh ghi đổ ngay. `ensure_dirs()` đã có sẵn và
> `SUBDIRS` đã liệt kê đủ, nhưng chỉ được gọi MỘT LẦN lúc tạo job, nên bảo đảm đó mất hiệu
> lực với: job dựng bằng engine cũ (SUBDIRS ngắn hơn), và job đi qua git/zip/rsync — **thư
> mục rỗng không sống sót** qua mấy đường đó. Hai ca đổ thật cùng một gốc: `output/` vắng làm
> `copyfile` của approve ném `FileNotFoundError` (2026-08-06, vá cục bộ ở 1.8.2 nên gốc còn
> nguyên), và `qa_gates` lưu PNG vào `qa/page_png/` đổ y hệt. Nay gọi `ensure_dirs()` trong
> `_JobLock.__enter__` — mọi stage đều vào qua `acquire_lock` nên đây là chỗ duy nhất phủ
> được cả stage hiện có lẫn stage thêm sau. Kiểm: dựng lại đúng ca đổ (xoá `qa/page_png`,
> `qa/diffs`, `output` khỏi bản sao job) rồi chạy `qa_gates` — chạy trọn, sinh 15 PNG + 6
> diff. Đột biến bỏ dòng `ensure_dirs()` → thiếu cả 9 thư mục, selftest đỏ. Không đụng
> layout, không đụng `region_id`.
> **1.9.3** engine tách thành repo độc lập; **không đụng một dòng code nào**. Trước đó
> engine nằm trong thư mục tài liệu của một sản phẩm, và ba thứ neo cứng vào vị trí đó:
> (1) `lock-engine.sh` nằm ngoài skill, ghi cứng đường dẫn máy local — nay vào
> `scripts/` và tự định vị; (2) manifest hash theo đường dẫn **tuyệt đối** nên di chuyển
> hay clone là hỏng — nay theo đường dẫn tương đối so với skill root; (3) manifest chỉ
> hash `.py/.yaml/.csv`, **`setup.sh` và `install.sh` không được bảo vệ** — agent sửa
> được mà `verify` vẫn báo OK; nay hash cả `.sh`, 13 → 16 file. Thêm `PDFTL_JOBS` cho
> bước dò file `.py` lạ vì job folder giờ nằm ngoài skill. Kiểm: `diff -r` scripts /
> assets / SKILL.md khớp từng byte trước khi sửa, selftest 196/196 PASS ở vị trí mới.
> **1.9.4** dọn nội dung riêng của một khách hàng ra khỏi engine trước khi publish; **không
> đụng code xử lý**. (1) `assets/default_glossary.csv` bỏ ba dòng `Pytes`/`V16 Lite`/`V16` —
> tên thương hiệu và sản phẩm của một khách, không thuộc glossary mặc định của một engine
> dịch PDF tổng quát; đã kiểm cả ba có sẵn trong profile của khách nên gỡ đi không mất gì,
> 47 → 44 dòng. File này chỉ là fallback khi job không truyền `--glossary`, nhưng SHA-256
> của nó vào determinism tuple, nên bump version là bắt buộc. (2) Gỡ hai tham chiếu trỏ
> sang repo tài liệu nội bộ (spec engine và một plan) — chết khi engine đứng riêng.
> (3) Sửa dòng trạng thái đầu file còn ghi `v1.9.2`. (4) **Đính chính một tuyên bố sai
> trong §1.6:** đoạn cũ viết ngưỡng authenticity "đã chốt đổi sang tỷ lệ gộp ở 1.5.0". Đọc
> lại code: `qa_gates.py` vẫn đo `identical` và `lang_suspect` **riêng từng loại, mỗi loại
> 5%, nối bằng `or`** — quyết định đó **chưa bao giờ được cài đặt**, vẫn hở tới 1.9.4. Nay
> ghi đúng thực trạng thay vì nói đã sửa.
> **1.9.5** Gate 3 **nhánh keep** hết báo giả P0. Nhánh translate đã được cấp lối thoát từ
> 1.4.5 ("23/23 P0 của gate này là báo giả"); nhánh keep vẫn so chuỗi theo **thứ tự đọc**,
> sót nguyên lớp lỗi đó tới 1.9.4. Vùng keep engine **không đụng tới**, nên câu hỏi duy nhất
> là chữ còn hay mất — thứ tự và dấu cách của chuỗi trích xuất không trả lời được câu đó.
> Ca thật 2026-08-07, HV48100 user manual p15, callout `1\n2`: trích xuất trong đúng khung
> cho `'2 1'` ở **CẢ `source.pdf` lẫn `draft.pdf`** — tức bản gốc cũng trượt chính phép kiểm
> này, bằng chứng đủ để kết luận báo giả. `G3_KEEP_LOST` là **P0 không waive được**
> (`approve.py`), nên một job sạch 565/565 vùng đứng chết ở đó.
> Nay xếp bậc như nhánh translate: khớp nguyên văn hoặc khớp sau khi bỏ khoảng trắng → sạch;
> **còn đủ ký tự nhưng khác thứ tự → `G3_KEEP_REORDERED` P2** kèm lời nhắc đối chiếu bằng
> mắt; **thiếu ký tự thật → `G3_KEEP_LOST` P0**, và nay in ra đúng những ký tự thiếu thay vì
> chỉ nói "mất text". Phép so đặt trong `char_deficit()` — multiset ký tự, cố ý bỏ qua thứ
> tự lẫn khoảng trắng, và **chỉ** dùng cho câu hỏi còn/mất; bố cục vẫn là việc của Gate 4.
> Đo trước khi chốt trên **255 vùng keep của 4 job còn `regions.json`**: 254 khớp nguyên như
> cũ, **đúng 1 ca chuyển P0 → P2, 0 ca đang P0 bị hạ thành sạch**. Luật không nới lỏng chỗ
> nào khác: hàng xóm lọt vào khung clip cũng không che nổi ký tự thiếu (`'1 2'` vs `'2 4'`
> vẫn báo thiếu `'1'`), và thiếu một trong hai ký tự trùng nhau vẫn bị bắt vì đếm theo bội.
> Không đụng layout, không đụng `region_id`, không đụng bản dịch — job cũ chỉ cần chạy lại
> stage 7.
> **1.9.6** `base_x` đo theo **nét mực đầu tiên**, không theo origin của span đầu. Bản gốc
> hay căn chữ bằng **dãy space** thay vì thuộc tính căn lề; space có advance nhưng không vẽ
> gì, nên origin span đầu nằm ở đầu dãy space còn chữ thật bắt đầu xa hơn về bên phải. Ca
> thật V5 Series user manual, ô `Pictures` của bảng cấu hình: `container_x0 = 282.6`,
> `origin = 282.6`, nhưng nét mực bắt đầu ở `325.1`. `tokenize` bỏ sạch token khoảng trắng
> — đã thử đủ 8 loại space Unicode kể cả nbsp, tất cả đều rơi qua `expanded.strip()` — nên
> bản dịch không tái tạo được dãy đó và bị kéo tụt về đầu dãy space. Lệch đo được tới
> **151pt**; hệ quả là hàng tiêu đề bảng tụt sang cột bên cạnh (19 cờ `G4_TABLE_RULE_CROSS`
> trên riêng job đó).
> **Cùng lớp lỗi 1.8.0 đã sửa một nửa**: hồi đó cho `build_lines` đo `ink_bbox` để khung ô
> thôi phình ra vì space đầu/đuôi, nhưng `base_x` vẫn lấy từ origin có đệm.
> Guard: **chỉ nâng** cho region một dòng, hoặc region mà mọi dòng bắt đầu ở cùng một x
> (±1pt) — văn xuôi nhiều dòng có thụt lề dòng đầu (kiểu danh sách gạch đầu dòng) thì dời
> `base_x` sẽ thụt cả khối, đổi lỗi này lấy lỗi khác. Không bao giờ hạ: nét mực không thể
> nằm trái hơn origin.
> Đo trên 2 job có `regions.json` và có vùng lệch: đổi cách vẽ **36 region** (32 V5 + 4
> HV48100, tất cả `align=left`, guard cho qua); 47 region `center/right` cũng lệch nhưng
> **không đổi gì** vì x của chúng tính từ container chứ không từ `base_x`; 2 region bị guard
> chặn đúng. Bonus: trả lại thụt lề gạch đầu dòng cho HV48100.
> **Đã thử và LOẠI hai luật căn lề** cho các dòng mục lục có số trang nằm chung region:
> (a) "mép trái chữ cách mép container <12pt thì là left" — đổi 122 region, phá hỏng những
> ô bảng vốn căn giữa thật (số thứ tự `1`,`2`,`3` trong cột hẹp có lgap 8.2pt); (b) "dòng
> lấp ≥80% khung thì là left" — đổi 60 region, cũng phá hỏng nhãn ngắn căn giữa trong ô khít
> (`Grounding Cable` 0.90, `Blink 3` 0.82). Cả hai đều đổi một lỗi lấy một lỗi, nên **không
> ship**. Các dòng mục lục kiểu đó là bài toán **hai cột trong một region** — đúng phạm vi
> `column_split` (1.9.0) nhưng nó đang chốt ở `region_type == table_cell`; mở rộng là việc
> thiết kế riêng, chưa làm.
> Không đụng `region_id`, không đụng `container`, không đụng bản dịch — job cũ chỉ cần chạy
> lại stage 6-7.
> **1.9.7** `emphasis` nhận cả **tiêu đề phụ in đậm MỞ ĐẦU region**. Bản gốc hay gộp tiêu
> đề phụ in đậm (`Danger`, `General Requirements`, `Cleaning`, `WARNING`) và cả đoạn văn
> xuôi theo sau vào MỘT block rawdict, nên chúng thành một region. Luật cũ trong
> `build_runs` chỉ cho `emphasis` khi `i > 0`, còn dòng cuối `if not any(role == "label")
> : runs[0]["role"] = "body"` ép cứng run 0 về `body`. `role_style()` của stage 6 lấy run
> **đầu tiên** khớp role, tức chính run đậm đó, rồi vẽ **CẢ VÙNG** bằng chữ đậm.
> Đo trên HV48100 user manual: **59 region dính, chứa 46% tổng ký tự**; bản dịch ra **50%
> ký tự Noto Sans Bold** trong khi bản gốc chỉ 4.5% (`Arial-BoldMT` 2848 / `ArialMT`
> 60144) và bản V16 Lite đã phát hành là 13%.
> Nay: run 0 in đậm **có ít nhất một run thường CÓ CHỮ THẬT phía sau** (`lead_in`) →
> `emphasis`. Điều kiện "chữ thật" là bắt buộc: bản gốc hay để một run toàn khoảng trắng ở
> cuối, nhận nhầm nó thì tiêu đề in đậm nguyên dòng — 6 dòng chương của mục lục V5 Series —
> bị hạ vai rồi `role_style("body")` trả về đúng run trắng đó, cả dòng mất đậm. Region
> đậm toàn bộ — tiêu đề thật — không thoả điều kiện nên vẫn vẽ đậm nguyên như cũ. Bất biến
> "luôn còn ít nhất một run `body`" giữ nguyên nhưng diễn đạt lại cho đúng: kiểm `body` chứ
> không kiểm `label`.
> Kết quả sau khi chạy lại HV48100: **chữ đậm 50% → 4%**, khớp bản gốc.
> **Đổi `regions.json` nhưng KHÔNG đổi `region_id` hay `source_hash`** — đo trên job thật:
> 0 region_id mất, 0 mới, 0 source_hash đổi, `responses.jsonl` không mồ côi. Job cũ chạy lại
> stage 2 → 2.5 → 3 → 5 → 6 → 7; response chỉ dùng role `body` vẫn hợp lệ vì `body` luôn có
> trong `style_roles`, chỉ là mất phần in đậm cho tới khi bản dịch tách run.
> **1.9.8** `infer_alignment` đo bằng **số dòng đồng thuận**, không bằng biên độ max-min.
> Biên độ để **một dòng lạc** quyết định cả khối. Ca thật V5 Series p15: đoạn văn xuôi căn
> trái 8 dòng cùng mép trái 26.8, nhưng `merge_paragraph` gộp thêm chú thích bảng đặt lệch
> phải ở dòng cuối — `vl` vọt lên 268.5 trong khi `vr` 176.8, `min` chọn `right`, cả đoạn bị
> đẩy sang phải. Nay đếm số dòng cùng chia sẻ một mốc (±1pt): dòng lạc chỉ còn một phiếu.
> **Lối thoát bằng chứng**: khi không mốc nào được ≥2 dòng đồng thuận thì giữ nguyên luật
> biên độ cũ. Bỏ lối thoát này thì ô hai dòng căn giữa thật bị ép về trái — đo trên 5 job,
> 4 ô kiểu `Charge: …\nDischarge: …` trong ô gộp bị phá.
> Đo trên 258 region ≥2 dòng của 5 job: **đổi đúng 6 region, tất cả sang `left`, tất cả đều
> đúng** (hai ô nhãn bảng thông số, đoạn mục 7, hai ô của E-BOX datasheet). 0 region đổi
> sang `center`/`right`.
> Không đụng `region_id`, `container` hay bản dịch — job cũ chạy lại stage 2 → 7.
> **1.9.9** guard của `base_x` (1.9.6) nới từ "MỌI dòng cùng mép mực" thành **mép mực
> trái nhất trong các dòng**. Vẫn không bao giờ vẽ trái hơn chữ nguồn của bất kỳ dòng nào,
> nên văn xuôi có thụt lề dòng đầu vẫn an toàn — mép trái nhất chính là lề thân bài. Guard
> cũ bỏ sót **ô gộp được căn giữa bằng dãy space có số space khác nhau từng dòng**: ca thật
> V5 Series p5, ô kích thước gộp ba cột, mực bắt đầu cách origin **64.5pt** mà guard chặn
> nên chữ dịch tràn sang cột nhãn. Đo trên 5 job: nới thế này chỉ đụng thêm **2 vùng**.
> **1.9.10** nguồn một dòng thì **ưu tiên giữ một dòng**: thà thu cỡ chữ trong giới hạn
> `minimum_ratio` còn hơn bẻ đôi. Ngân sách dọc của một ô thường chứa được hai dòng, nên
> fitter cũ dừng ngay ở cỡ đầy với bố cục hai dòng. Ca thật: `4.2.1 Tools` → `4.2.1 Dụng cụ`
> rộng 66.28pt trong khung 66.0pt — **thiếu 0.28pt** mà tiêu đề bị bẻ đôi, trong khi thu
> 0.5% là vừa. Không vừa nổi một dòng ngay ở sàn thì quay lại luật cũ, không ép.
> Kèm theo: nguồn một dòng mà vẫn phải xuống dòng nay tính là `poor_fit`, nên `expand_heading`
> được thử — trước đó bản dự phòng hai dòng có `ratio = 1.0` nên nới khung không bao giờ
> kích hoạt.
> Đo trên 863 region nguồn-một-dòng của 5 job: **16 → 5 region còn xuống dòng**; 47 region
> giữ được một dòng nhờ thu cỡ. Giá phải trả: `FONT_RATIO_HARD` 3 → 5 và `FONT_RATIO_REVIEW`
> 18 → 19 trên HV48100 — đều là cờ cho reviewer nhìn, không phải lỗi.
> Đính chính kèm: docstring `ink_base_x` vẫn mô tả guard cũ của 1.9.6 sau khi 1.9.9 đã nới —
> nay ghi đúng thực trạng.
> **1.9.11** thụt lề **theo từng đoạn** của bản dịch (`segment_indents`). Bản gốc trộn
> nhiều mức thụt trong MỘT region — dòng gạch đầu dòng thụt vào, văn xuôi giữa chúng thì
> không — mà fitter chỉ có một `base_x`, nên mọi dòng bắt đầu ở mép trái nhất và chữ dịch
> **chạy đè lên chính dấu gạch đầu dòng** mà engine giữ lại. Ca thật V5 Series p12 và p11.
> Ánh xạ đoạn-bản-dịch → mức-thụt **chỉ nhận hai hình mẫu xác định**: (a) số đoạn bằng số
> dòng nguồn — bản dịch giữ nguyên cấu trúc dòng, ánh xạ 1:1; (b) nguồn có đúng hai mức
> thụt và số mục thụt vào bằng số đoạn — mọi đoạn cùng thụt một mức. Ngoài hai hình mẫu đó
> trả về 0, giữ nguyên hành vi cũ: **không đoán**.
> Đã thử và bỏ luật "số đoạn bằng số đoạn-cùng-mức": hai mục gạch đầu dòng liền nhau cùng
> mức bị gộp làm một, cho ra kết quả nham nhở — mục thụt, mục không, xấu hơn cả không sửa.
> Đo trên 5 job: 50 vùng trộn mức thụt, **30 vùng suy ra được**. Thụt lề không bao giờ âm.
> Chỉ áp cho `rotation == 0` và `alignment == "left"`.
> **Chưa xử được**: dấu gạch đầu dòng là line-art neo cứng theo y của bản gốc, mà tiếng Việt
> wrap ra số dòng khác — lệch dọc vẫn còn, cần DTP tay.
> **1.9.12** đường mask đo theo **nét mực**, và biết cắt theo chiều **dọc**.
> (1) `protected` — vùng chữ phải giữ nguyên — dựng từ bbox span có tính cả khoảng trắng.
> Ca thật V5 Series p10: ô nhãn một hàng bảng là **26 ký tự space, bbox rộng 123pt**, và ô
> số thứ tự `'  6     '` phình từ 4.4pt lên 20pt. Hai vùng RỖNG đó ép mask của hai ô kề bên
> phải cắt ngắn, nên chữ tiếng Anh còn nguyên trên trang và bản dịch vẽ chồng lên.
> Nay bỏ hẳn span toàn khoảng trắng, span còn lại lấy giao với `ink_bbox` của dòng.
> (2) `build_masks` cũng giao với `ink_bbox` trước khi nới pad — ô `'         Alarm
> Indicator '` có bbox bắt đầu ở 30.0 trong khi chữ bắt đầu ở 49.6, mask thò sang chạm ô số
> thứ tự và cả vùng bị bỏ vẽ.
> (3) Nhánh dự phòng biết cắt theo chiều **dọc** khi vùng bảo vệ nằm trọn trong dải ngang
> của mask. Ca thật V5 p6: khối chú thích `[1]…[4]` chạm số trang đúng **0.1pt** ở mép dưới
> — không nhánh ngang nào áp được nên cả khối bị bỏ vẽ, để lại nguyên tiếng Anh mà mask hàng
> xóm đã ăn mất vài chữ (`temperature` → `tem   tur`).
> Cùng lớp lỗi 1.8.0 (`ink_bbox` cho line), 1.9.6/1.9.9 (`base_x`): chỗ nào dùng bbox có đệm
> space thì chỗ đó sai.
> Kết quả trên V5 Series: `MASK_CLIPPED` **8 → 0**, `MASK_CONFLICT` **2 → 0**, vẽ **457/457
> vùng, không bỏ vùng nào**. HV48100 không đổi (2 vùng bỏ vẽ vẫn là ký hiệu Wingdings).
> **1.9.13** `leader_split` — dòng mục lục gộp tiêu đề và số trang được tách thành hai
> cột. Dòng mục lục là MỘT span, tiêu đề và số trang ngăn nhau bằng dãy space (gạch dẫn là
> line-art riêng); `tokenize` bỏ sạch khoảng trắng nên cụm co lại, rồi `infer_alignment` đọc
> dòng gần-full-width thành `center`/`right` và đẩy cả cụm ra giữa hoặc sang phải — đè lên
> chính nét gạch dẫn. `column_split` không đụng tới vì nó đòi `table_cell` và ≥3 dòng có
> lưới lặp.
> Hai dạng: (A) một line, khe ≥4 space, đuôi là số trang 1-3 chữ số — ranh giới cột đo bằng
> bề rộng số trang; (B) PDF khai **hai "line" cùng một y** — đó là hai cột sẵn, mỗi cột đã
> có bbox riêng. Chữ ký rất hẹp, đo trên 5 job: khớp **đúng các dòng mục lục, 0 ca oan**.
> Hợp đồng bản dịch giống `column_split`: hai đoạn ngăn bằng `\n`, trái→phải.
> **Kèm sửa một lỗi có sẵn của `column_split`**: nó ghép các run bằng `"\n".join`, tức chèn
> thêm một dấu ngăn cột giữa mỗi cặp run. Target nhiều run — tiêu đề in đậm + phần còn lại,
> đúng thứ 1.9.7 vừa sinh ra — bị đếm thừa cột nên hàm lặng lẽ trả None. Nay ghép bằng `""`:
> run là đơn vị style, không phải đơn vị cột.
> Kết quả V5 Series: trang mục lục 24/24 dòng đúng chỗ, số trang thẳng cột; vẽ **467 vùng,
> bỏ 0**.
> **1.9.14** khung nới được nhận khi nó bớt **DÒNG**, không chỉ khi nó tăng **cỡ chữ**.
> 1.9.10 thêm nhánh "nguồn một dòng mà phải xuống dòng cũng là fit kém" để kích hoạt nới
> khung, nhưng chốt nhận ở cuối vẫn là `got_s > keep_s` — mà bản dự phòng hai dòng đã ở cỡ
> đầy nên cỡ chữ không thể lên nữa. Hai nhánh triệt tiêu nhau: khung nới tính đúng rồi vẫn
> bị vứt đi. Ca thật V5 p17 `7.1 Unable to start` → `7.1 Không khởi động được` cần 157.0pt
> trong khung 132.0pt, cả dải ngang bên phải trống.
> **Kèm sửa một lỗi có sẵn:** vòng paint lọc bbox của chính region ra khỏi danh sách vật cản
> bằng cách **ghi đè tại chỗ** `expand_ctx["obstacles"]`. Vật cản của mọi region đã xử lý vì
> thế biến mất vĩnh viễn, và region cuối trang nhìn thấy một trang gần như trống — đủ điều
> kiện nới khung đè lên chữ hàng xóm. Nay lọc ra bản sao cho từng region.
> **1.9.15** `segment_indents` học hình mẫu thứ ba: số đoạn bản dịch bằng **số dòng mở
> đoạn** của nguồn. Dòng mở đoạn = dòng đầu, cộng mọi dòng mà dòng TRƯỚC nó còn thừa chỗ cho
> từ đầu của nó — nguồn xuống dòng vì hết chỗ thì dòng trước phải chạy sát mép phải, dừng
> sớm hơn thế là cố ý ngắt đoạn. Bề rộng ký tự đo ngay trên dòng đang xét nên không cần font.
> Hai hình mẫu của 1.9.11 đều đếm theo **mức thụt** nên trượt khi một mục bắt đầu ngay ở lề
> thân bài; ca thật V5 p11 khối lưu kho có 12 dòng nguồn, 7 đoạn dịch, chỉ 6 dòng thụt sâu.
> Thứ tự thử giữ nguyên: hai hình mẫu cũ đo trực tiếp mức thụt nên chắc hơn, hình mẫu mới
> chỉ là bước dự phòng. Chặn thêm thụt lề vô lý (>25% bề rộng vùng) vì vùng hai cột khớp
> đếm nhưng cho ra 268pt trên khung 366pt. Đo trên các job hiện có: 29 vùng trộn mức thụt,
> suy được **10 → 19**.
> **1.9.16** `paint_origin_x` trả **mép mực**, không trả origin thô. Nó có nhiệm vụ cho
> container bao được điểm mà fitter bắt đầu vẽ — đúng cho tới 1.9.6/1.9.9, từ đó `ink_base_x`
> nâng base_x lên mép mực nên origin có đệm space không còn là nơi vẽ. Giữ công thức cũ thì
> container bị kéo sang trái đúng bằng bề rộng dãy space. Ca thật V5: ô `CANH` có 48 space
> đầu, container tụt về 134.2 trong khi cột CAN bắt đầu ở ~204 — `infer_alignment` đọc thành
> `right` và bản dịch dính mép dải cam; ô trị số `Unit Dimension` tụt về 67.7, **chồng lên ô
> nhãn `[29.0…121.2]`** và tràn chữ sang đó. Stage 2 và stage 6 nay hiểu giống nhau về cùng
> một điểm. Đo trên V5: 133 vùng có đệm space, 61 vùng đổi căn lề, Gate 4 từ đỏ sang xanh.
> **1.9.17** ô bảng **một dòng** lấy căn lề theo **đồng thuận của cột**. Ô một dòng không có
> gì đồng thuận nội bộ nên phải đoán từ khe trái/khe phải; dòng tiếng Anh gần đầy ô thì hai
> khe xấp xỉ nhau và luật dung sai đọc thành `center` — không phân biệt được với căn trái
> thật. Ca thật V5 p8: `Charge / Discharge over Current Protection` lấp gần kín ô (khe
> 3.2/10.9 trên 187.1) nên ra `center` trong khi 7 ô còn lại cùng cột đều `left`; bản dịch
> ngắn hơn nên thụt hẳn vào giữa. 1.9.8 sửa ca nhiều dòng bằng đếm dòng đồng thuận — ở đây
> bằng chứng nằm NGOÀI ô. Chỉ đụng ô một dòng; ngưỡng >=4 ô và >=75% vì cột trộn tiêu đề căn
> giữa với thân bài căn trái là chuyện thường. Đo: V5 18 ô, HV48100 23 ô, Pi Station 1 ô.
> **1.9.18** vẽ lại **nét gạch dẫn mục lục**. Gạch dẫn là line-art vẽ sẵn từ mép phải tiêu đề
> TIẾNG ANH tới số trang: tiêu đề tiếng Việt dài hơn thì chữ đè lên nét, ngắn hơn thì hở một
> khoảng. `leader_split` (1.9.13) chỉ tách được cột. Nay xoá nét cũ (cùng cơ chế redaction
> line-art của `fill_rules`) rồi vẽ lại **giữ nguyên mép phải**, chỉ dời điểm bắt đầu theo mép
> phải chữ đã dịch — hai ca dài/ngắn đối xứng, không ca nào phải đoán toạ độ.
> Chữ ký hẹp: nét cao dưới 1.2pt, cùng một y, có ít nhất một đoạn **nét đứt** (vạch kẻ bảng và
> gạch chân đều liền nét), bắt đầu trong 12pt sau mép chữ, và **phải có chữ ngay sau nét** —
> số trang. Thiếu vế cuối thì đường chỉ dẫn của hình cũng dính: ca thật V5 p9 nhãn `Ground`.
> Gate 5 và Gate 6 được ghi cả khung cũ lẫn khung mới trong `render_manifest.toc_leaders` nên
> trừ đúng hai khung đó, không nới lỏng phép so. Kết quả V5: **24/24 dòng mục lục** đúng chỗ.
> Bẫy đã sập một lần: `shape.finish` mặc định **đóng đường**, tức vẽ thêm lượt về từ điểm
> cuối; lượt về lệch pha nét đứt nên lấp kín khe và gạch dẫn thành liền nét — chỉ ở những
> dòng có chiều dài chia đúng kiểu ấy, nên rất dễ lọt mắt.
> **1.9.19** đồng thuận cột **không kéo ô sang `left`** khi mực của nó bắt đầu xa mép trái
> khung. Text căn trái vẽ từ `base_x` nên ngân sách wrap chỉ còn `container.x1 - base_x`; ô
> nào mực lệch vào trong thì hụt hẳn, mà nếu ô ấy căn giữa thật thì ép sang trái vừa sai vừa
> làm chữ không fit nổi. Ca thật HV48100 p25: cột `OFF/ON` rộng 20.4pt, năm ô `OFF` lấp gần
> kín nên bị đọc nhầm thành `left` và thắng phiếu 5/6; ô `ON` căn giữa THẬT bị kéo theo,
> `Sáng` còn 16.4pt để wrap → `FIT_IMPOSSIBLE`. Chỉ chặn chiều sang `left`; `center`/`right`
> neo vào khung nên không tốn ngân sách.
> **1.9.20** **neo baseline theo đoạn**. Dấu `•` `◇` `∘` KHÔNG nằm trong region — chúng là
> glyph riêng, neo cứng ở baseline nguồn và không bị redact. Fitter thì rải dòng liên tục từ
> `base_y`, nên đoạn thứ i chỉ rơi đúng dấu của nó khi mọi đoạn trước chiếm ĐÚNG số dòng như
> nguồn — tiếng Việt hiếm khi chia dòng y hệt tiếng Anh nên cả khối lệch pha. Ca thật V5 p12
> §5.2: nguồn 6 dòng / 3 mục `◇`, bản dịch 3 đoạn — đếm đã khớp — nhưng đoạn 1 chiếm 3 dòng
> thay vì 4, thế là `◇` cuối rơi vào chỗ trống. Đã chứng minh sửa bản dịch không giải được:
> phải ép từng đoạn xuống đúng số dòng nguồn, tức gò câu theo số dòng chứ không phải dịch.
> Luật neo: dòng mở đoạn tụt xuống baseline nguồn của đoạn đó, nhưng **không bao giờ lùi lên
> trên dòng trước** — `max(neo, trước + leading)`. Nhờ vế `max`, đoạn dịch dài hơn nguồn tự
> động chảy tiếp thay vì đè lên nhau. Fitter đo ngân sách dọc bằng CHÍNH công thức baseline
> mà bước vẽ dùng, không đo một đằng vẽ một nẻo.
> Kèm gộp `segment_indents` và `segment_anchors` về chung `segment_source_lines`: thụt lề và
> neo phải nói về cùng một cấu trúc, nếu không mỗi thứ hiểu vùng một kiểu.
> **1.9.21** gộp **ký hiệu mũ** vào dòng chủ. Baseline ký hiệu mũ cao hơn dòng thân nên PDF
> khai nó thành MỘT "line" riêng: ô `Recommended Charge/ Discharge Current [1]` ra ba "dòng"
> với `[1]` nằm giữa, `source_text` thành ba đoạn, model dịch đúng ba đoạn theo hợp đồng, và
> bản vẽ đặt `[1]` thành một dòng lơ lửng giữa hai dòng chữ. Chủ của ký hiệu là dòng kết thúc
> ngay trước nó theo chiều ngang VÀ có baseline **thấp hơn** nó chưa tới một dòng — ký hiệu mũ
> được nâng lên, nên thiếu vế sau thì `[3]` của `Cycle Life` dán ngược lên `DC Breaker` ở hàng
> trên. Không tìm được chủ thì để nguyên. Đo trên các job: đúng 4 vùng, đều ở V5 p6.
> **1.9.22** gạch dẫn mục lục gõ bằng **DẤU CHẤM** được phát lại cho thẳng cột số trang.
> HV48100 không vẽ line-art như V5 mà gõ 85 dấu `.` ngay trong text, nên `leader_run` (1.9.18)
> đi tìm stroke không thấy gì và `leader_split` (1.9.13) đòi khe ≥4 space cũng không khớp. Hệ
> quả NGƯỢC với V5: không có chữ đè lên nét, nhưng model giữ nguyên xấp xỉ số chấm cũ (85 →
> 86) trong khi tiêu đề tiếng Việt dài ngắn khác — cột số trang răng cưa.
> Dãy chấm co về tối thiểu TRƯỚC khi fit (cỡ chữ phải do tiêu đề và số trang quyết định, không
> do dãy chấm thừa của bản gốc), rồi phát lại đúng số chấm để dòng kết thúc ở **mép phải dòng
> nguồn**. Chữ ký: region một dòng, token cuối là số trang 1-3 chữ số, token liền trước kết
> thúc bằng ≥4 dấu chấm; chấm dính liền tiêu đề thì tách ra. Đo trên mọi job: **54 dòng, đều
> là mục lục HV48100 p3-p4, 0 ca oan**. Biên độ mép phải: **23.3 → 4.3pt** (p3), **17.1 →
> 2.9pt** (p4); nguồn là 1.8 và 1.5pt. Phần dư còn lại đúng bằng một dấu chấm — hệ quả của
> phép làm tròn xuống, không phải lệch.
> Hoàn toàn là chữ: không xoá, không vẽ vector, nên Gate 5 không phải khai báo gì. Gate 3 thì
> có: nó so chuỗi target nguyên văn, mà số chấm vẽ ra cố ý khác `target_text`. `fit_result`
> khai số chấm đã phát lại, gate thu dãy chấm về một dạng ở cả hai vế **đúng những region đã
> khai** — chỗ khác không được nới. Thiếu khai báo thì gate bắn **47 P0**, và đó chính là cách
> lỗi này bị bắt.
> **1.9.23** Gate 6 render từ **handle sạch**. `page.get_image_info(hashes=True)` mà Gate 5
> gọi buộc MuPDF giải mã sẵn mọi ảnh và nhét vào cache; lần render sau dùng bản cache đó thay
> vì giải mã lại ở đúng độ phân giải, nên pixel lệch ở chi tiết mảnh. Gate 5 **chỉ soi
> `draft`**, nên Gate 6 đem hai bản render không cùng điều kiện ra so — và mọi cờ sinh ra từ
> đó là báo giả. Thí nghiệm: cùng một file, `md5` bản render `ec417e0f` → sau
> `get_image_info(hashes=True)` thành `db59d990`; gọi `get_pixmap(clip=…)` trước thì không
> đổi. Đo trên V5 Series: **26 → 1 cờ `G6_DIFF_OUTSIDE_MASK`**, tức 25/26 là báo giả, đều ở
> trang có ảnh (5, 7, 8, 9, 14).
> Cờ cuối cùng là thật và cũng đã sửa: dải khai cho Gate 6 ở 1.9.18 chỉ có khung gạch dẫn
> MỚI, trong khi tiêu đề dịch dài hơn thì nét mới bắt đầu phải hơn nét cũ — đoạn ở giữa mất
> chấm vẫn là pixel đổi. Nay khai **hợp** hai khung. V5 `g6_visual` **đỏ → xanh**.
> **1.9.24** kẹp "chỉ nâng, không hạ" của `ink_base_x` áp theo **TỪNG DÒNG** rồi mới lấy min,
> thay vì kẹp cả vùng bằng origin dòng đầu. Hai vế giữ hai việc khác nhau: `max(origin, ink)`
> trong một dòng chặn side-bearing âm (`J`, `f` nghiêng có nét thò trái hơn origin vài phần
> mười pt); `min(...)` qua các dòng đưa base_x về lề thật của vùng. Kẹp cả vùng chỉ kích hoạt
> được khi dòng ĐẦU nằm phải hơn mực của một dòng khác — và ở đúng ca đó nó luôn sai.
> Ca thật V5 p6: `find_tables` gộp hai hàng `DC Breaker`/`Cycle Life` thành một ô (nguồn không
> kẻ nét ngang giữa chúng ở dải cột ấy). Thứ tự đọc bắt đầu ở **cột phải** — `Dual Pole,
> 125Vdc,` tại x=297.2 — trong khi `No` của cột giữa ở x=191.0. base_x bị ghim 297.2, mọi thụt
> lề `x_i - base_x` hoá âm rồi clamp về 0, và cả bốn dòng dồn thành một chồng: `Không` nằm
> giữa hai dòng thông số của cột phải, `≥6000 chu kỳ` mất tính trải ngang.
> Đo trên các job: **7 vùng có dòng đầu không phải mép trái nhất, đúng 1 vùng căn trái** — tức
> bản vá đụng đúng vùng hỏng, sáu vùng kia `center`/`right` neo vào khung nên không dùng
> base_x.
> **Lỗi này gate không thấy** — P0/P1/P2 không đổi trước và sau. Nó lộ ra ở **bản so sánh
> nguồn ↔ bản dịch** mà người duyệt xem trước khi approve.
> **1.9.25** **dấu gạch đầu dòng** trở thành hình mẫu ánh xạ đoạn ưu tiên số một. `•` `◇`
> `∘` của bản gốc là HÌNH VẼ nhỏ chứ không phải ký tự, nên không nằm trong `lines` của
> region — nhưng chúng là bằng chứng chắc nhất về cấu trúc mục: mỗi dấu một mục, không phải
> suy đoán. Ba hình mẫu của 1.9.11/1.9.15 đều suy từ hình học chữ và sai ở đúng những nguồn
> ngắt dòng cứng giữa câu. `bullet_lines` (stage 2, metadata thuần như `fill_rules`) ghi lại
> dòng nào được một dấu đánh dấu; phần đầu vùng chưa có dấu vẫn nhờ `paragraph_starts` chia.
> Chữ ký: nét nhỏ dưới 8pt mỗi chiều, trong 30pt kể từ mép trái vùng, tâm nằm trên baseline
> dòng nó đánh chưa tới 7pt, và **nằm ngoài vệt mực mọi dòng** — chồng lên chữ thì đó là ký
> hiệu trong câu hay nét của hình minh hoạ.
> Đo trên các job: 18 vùng có dấu. Nơi số mục khớp số đoạn dịch — **9 vùng trùng đúng ba
> hình mẫu cũ, 3 vùng ba hình mẫu cũ chịu thua, 0 vùng mâu thuẫn**. Thuần bổ sung: không
> khớp thì lùi về ba hình mẫu cũ, không ép bừa.
> Kết quả HV48100: 15/15 vùng có dấu nay ánh xạ theo dấu. Khối `CAUTION` p19 — thứ 1.9.20
> tuyên bố "không giải được bằng engine" — nay đúng cả 9 mục, kể cả mục `Relative humidity`
> mà `paragraph_starts` bỏ sót. Kết luận cũ sai vì tôi chỉ tìm tín hiệu trong chữ, còn tín
> hiệu thật thì bản gốc đã vẽ sẵn ra.
> **1.9.26** **dấu gạch đầu dòng đi theo chữ**, thay vì chữ phải đi theo dấu. 1.9.20 neo mỗi
> đoạn dịch vào baseline đoạn nguồn để chữ khớp dấu — đúng khi dấu đứng yên, nhưng đoạn dịch
> ngắn hơn nguồn thì phần dôi thành **khoảng trắng giữa các mục**: bố cục "nhảy dòng", thứ mà
> gate không đo được và chỉ mắt người thấy.
> Nay xoá dấu cũ ở lượt redaction line-art (cùng cơ chế `fill_rules`/gạch dẫn), rồi vẽ lại
> sau khi đặt chữ, dời đúng bằng chênh lệch baseline. Đường path của dấu **chép nguyên** từ
> bản gốc, chỉ cộng `dy` — không dựng lại bằng hình tròn tự chế, vì nguồn dùng `•` `∘` `◇`
> `▪` khác nhau và đoán sai hình là thấy ngay.
> Vùng nào dời được dấu thì **tắt neo baseline**: chữ chảy liên tục, dấu tự bám theo. Ba mảnh
> phải đi cùng nhau — xoá, vẽ lại, tắt neo — thiếu một mảnh là hỏng, nên mỗi mảnh có một
> mutation test riêng.
> Gate 6 được khai HỢP khung cũ và mới của từng dấu, cùng cách với gạch dẫn. Gate 5 không đổi
> vì số cụm vector giữ nguyên (xoá một, vẽ một).
> Kết quả HV48100: **58 dấu được dời**, trang 8/9/11/19 hết cả đè bullet lẫn nhảy dòng.
> **1.9.27** `horizontal_rules` chỉ nhận **nét LIỀN**. Ô trống để người điền tay bao giờ cũng
> là gạch liền; nét đứt ngang trong tài liệu này là **gạch dẫn mục lục**. Thiếu vế đó thì
> `fill_in_rules` nhận nhầm ba dòng mục lục V5 thành ô trống, `fit_paint` bắn
> `FILL_BLANK_DROPPED` — báo giả mà reviewer phải waive ở **mọi** tài liệu có mục lục. Nặng
> hơn: bản dịch tình cờ có dãy `____` thì lượt xoá gạch-ô-trống sẽ xoá luôn gạch dẫn.
> Đo trên kho: 5 bản Terms of Warranty — đúng loại tài liệu tính năng này sinh ra để phục vụ —
> có **15-16 nét kẻ ngang mảnh mỗi bản, 0 nét đứt**; ba nét đứt duy nhất trong cả kho là gạch
> dẫn mục lục V5. Bỏ đúng ba ca oan, không bỏ sót ca thật nào. V5 P1 **23 → 20**, còn 4 mã
> cần waive thay vì 5.
> **1.9.28** `validate_responses` chặn ngay ở **cổng vào** như `extract_group` và
> `translate_prep`. Nó vẫn đọc `RERUNNABLE_STATUSES`, nhưng chỉ để quyết định chuyển trạng thái
> ở cuối hàm — không có chốt vào cổng. Hệ quả: stage này **ghi được `target_text` vào
> `model/regions.json` của job ĐÃ PHÁT HÀNH**, làm model thôi mô tả đúng bản đã duyệt.
> Xảy ra thật 2026-08-07: một vòng lặp chạy trên hai job mà không kiểm trạng thái; ba stage
> kia chặn, stage này lọt (kèm `write_responses.py` — helper trong job, cố ý không có chốt).
> Lần đó nội dung không đổi vì đầu vào y hệt và hàm idempotent — **đó là may, không phải hàng
> rào**. Test mới đòi cả ba stage có chốt ở cổng vào, không chỉ có tên hằng số trong file.
> **1.9.30** vá **chồng chữ giữa hai nhãn cạnh nhau cùng được nới khung.**
> `expand_container` đọc vật cản từ trang NGUỒN — giữ được tính độc lập với thứ tự paint,
> nhưng bỏ sót việc hàng xóm cũng là chữ dịch và cũng nới. Xét riêng thì mỗi region đều tôn
> trọng bbox nguồn của hàng xóm; cộng lại thì đè nhau. Ca thật trong một job đã chạy: hai
> nhãn hình cạnh nhau đè 1.60pt, Gate 4 không bắt vì nó đo tràn khung chứ không đo va chạm
> cạnh. Nay vật cản là chữ dịch cùng trang (`share_gap`, khớp theo identity) chỉ chặn tới
> GIỮA khe, lùi thêm `SIBLING_GAP_PT` = 1.0pt mỗi bên. Vật cản cố định (ảnh, vector, nét kẻ)
> vẫn chặn tới đúng mép.
> **1.9.31** **khối hai cột căn bằng dãy space** được vẽ đúng lưới (`spec_grid_cells` ở
> `_common.py`, `spec_grid` ở `fit_paint.py`). Tờ rơi datasheet dàn bảng thông số bằng dãy
> space chứ không kẻ khung, nên `find_tables` không thấy bảng và cả khối rơi vào MỘT region
> `paragraph`; `tokenize` bỏ sạch khoảng trắng, `fit_region` vẽ mọi dòng từ `base_x`, và
> `line_baselines` có luật `max(neo, trước + leading)` nên ô trị số không bao giờ nằm cạnh ô
> nhãn được. Cả bảng dồn về một cột trái mà **mọi gate vẫn xanh** — không gate nào đo cấu
> trúc cột. Đo trên cả bốn datasheet Pytes: bản nào cũng dính.
> `column_split` (1.9.0) không phủ được: nó chốt `table_cell` và dựng cho MỘT hàng nhiều cột,
> còn đây là khối nhiều hàng.
> Bằng chứng lưới là **phiếu bầu neo cột** (`spec_row_votes`): mỗi hàng đo khe mực rộng nhất,
> khe ≥ `SPEC_MIN_PAD_PT` (12pt) và cách mép mực trái vùng ≥ `SPEC_MIN_GAP_PT` (30pt) thì mép
> mực ngay sau khe là ứng viên; ít nhất `SPEC_MIN_ANCHOR_ROWS` (2) hàng **cùng trang** phải
> đồng thuận. Phiếu gom theo TRANG chứ không theo vùng, vì một lưới hay bị cắt thành nhiều
> region: ba nhãn tính năng của tờ rơi mỗi cái là một region MỘT dòng, tự nó không lặp lại
> được gì, nhưng ba cái cùng bầu một x thì lưới là có thật. Vùng chỉ nhận lưới khi CHÍNH NÓ
> có phiếu ở neo đó.
> Mọi phép đo ở mức **KÝ TỰ**, không phải span: hai cột hay nằm chung một span khi cùng font
> cùng cỡ, và bbox của span tính cả dãy space đệm nên đo theo span ra khe 0 ở đúng những hàng
> gõ nhãn và trị số trong một dòng — cùng lớp lỗi 1.8.0/1.9.6/1.9.12 đã sửa từng phần.
> **Hợp đồng với bản dịch:** mỗi đoạn ngăn bằng `\n` là một ô, trái→phải rồi xuống hàng.
> Stage 3 in lưới đo được vào `source_warnings` (mask lại từng ô bằng bộ đếm dùng chung của
> `protect`, nếu không số hiệu placeholder lệch và model chép nhầm), stage 5 bắn **P1
> `SPEC_GRID_DROPPED`** khi lệch số đoạn, stage 6 lùi về hành vi một cột chứ không đoán.
> Dòng mục lục cùng hình dạng nhưng thuộc `leader_split`/`dot_leader` — cột phải toàn số
> nguyên 1-3 chữ số thì loại.
> Đo trước khi chốt: **0 báo oan trên 2578 vùng** của năm tài liệu đã phát hành, **0 region_id
> mất/mới, 0 source_hash đổi**; trên bốn datasheet fire đúng **16 vùng, tất cả là lưới thật**.
> `spec_cells` là **metadata thuần** như `fill_rules`/`bullet_lines` — job cũ chỉ cần chạy lại
> stage 2 → 7, response không mồ côi.
> Kèm sửa `target_segments`: run là đơn vị **style**, không phải đơn vị đoạn. Idiom
> `"\n".join(run.text)` chèn thêm một ranh giới đoạn giữa mỗi cặp run, nên target có tiêu đề
> in đậm + phần còn lại bị đếm thừa đoạn. Ranh giới đoạn nằm trong CHỮ; role của đoạn lấy theo
> run mở đầu nó.
> **1.9.32** **mã vận chuyển UN là tên tiêu chuẩn**, không phải model — `STD_RE` nhận thêm
> `UN`. Thiếu nó thì `MODEL_RE` chỉ ăn được `UN38` và bỏ lại `.3`, nên vùng chỉ chứa đúng dấu
> `UN38.3` có residual `"3"` và bị `classify_action` xếp `translate` thay vì `keep`. Engine vẽ
> lại một dấu vốn không cần dịch, và **mất luôn font gốc**: bản gốc dùng `Impact` (nét rất
> đậm) nhưng khai `bold=False`, nên nó map sang Noto Sans Regular và dấu chứng nhận thành chữ
> thường mảnh. Ca thật: trang bìa HV48100 và V5° datasheet.
> Đo trên **2666 vùng của 7 job: đổi đúng 11 vùng**, tất cả là `UN38.3` (11) và `UN3480` (1),
> **0 khớp oan** — `Unit 3`, `UNIT` không dính vì luật đòi chữ số ngay sau `UN`.
> Vùng thành `keep` thì engine không đụng tới, glyph gốc còn nguyên; Gate 3 nhánh keep vẫn
> chấm bình thường. Dòng chứng nhận nhiều mục (`CE, IEC62619, UN38.3`) vẫn `translate` vì còn
> chữ ngoài placeholder.
> Không đụng layout, không đụng `region_id`/`source_hash` — nhưng **đổi số hiệu placeholder**
> của 11 vùng ấy, nên job đã dịch phải chạy lại stage 3 → 7 và dịch lại đúng những vùng đó.
> **1.9.33** **font có chân hay không quyết định theo TÊN, không theo cờ của PDF**
> (`is_serif_font` ở `_common.py`, dùng trong `style_of`). Cờ `serif` (bit 2 của
> FontDescriptor `/Flags`) là thứ bộ sinh PDF tự khai, và trong kho này **sai gần như toàn
> bộ**: đo trên nguồn của mọi job, **9 font mang cờ serif thì 8 thực ra là sans** —
> `RanyLight/Regular/Medium/Bold` (font thương hiệu, sans hình học), `NotoSansHans-Regular`
> và `SourceHanSansCN-Medium` (chữ "Sans" nằm ngay trong tên), `FandolHei-Regular`,
> `CTChaoHeiSF`, `STXihei` (Hei/黑体 = không chân). Đúng **một** font: `AdobeSongStd-Light`
> (Song/宋体 = có chân). Hệ quả đo được: bốn datasheet Pytes ra **79-98% ký tự Noto Serif**
> trong khi bản gốc là sans, và Pi Station 261 EX datasheet ra **100%**.
> Luật: dấu hiệu `sans` xét TRƯỚC `serif` (để "Sans Serif" không đọc nhầm), rồi tới dấu hiệu
> `serif`; tên không có dấu hiệu nào → **sans**. Chọn sans làm mặc định vì cờ đã chứng minh
> không dùng được, tài liệu kỹ thuật gần như luôn dùng sans, và đoán sai theo chiều này chỉ
> mất phần chân chữ — đoán sai chiều kia làm cả tài liệu tiếp thị đổi giọng.
> Dấu hiệu bao gồm cả tên họ chữ CJK: `song`/`ming`/`mincho`/`batang`/`simsun` là có chân,
> `hei`/`gothic`/`yahei`/`dengxian` là không chân.
> Đo trên 2578 vùng của 5 tài liệu đã phát hành: **0 region_id mất/mới, 0 source_hash đổi**;
> ký tự serif 100% → 0% (Pi Station datasheet), 5% → 0% (Lite quick guide), 1% → 1% (HV48100
> manual). **8 vùng đổi cấu trúc run** — tất cả đều là GỘP hai run vốn chỉ bị tách bởi cờ
> serif giả (Arial + NotoSansHans, Rany + Arial); thứ tự role giữ nguyên, không role nào mất.
> Không đụng layout, không đụng `region_id`/`source_hash`/bản dịch — job cũ chạy lại
> stage 2 → 7 là hưởng, response không mồ côi.

> **1.9.39** **hàng xóm dính sát mép trái không được chặn đường nới sang PHẢI.** Nguồn hay xé
> một tiêu đề làm hai text object **giữa từ** (`3.6.4. PCS vie` + `w`, `Chapter 2 System
> Introductio` + `n`). Khe giữa hai mảnh bằng 0, nên luật chia đôi khe của 1.9.30 đặt
> `left_lim = c[0] + SIBLING_GAP_PT` — nằm BÊN PHẢI chính mép trái của mảnh sau. Mọi phương án
> nới đều trượt, mảnh sau bị ép thu cỡ chữ, dù bên phải nó trống tới tận lề.
> Mép nào không dịch ra khỏi khung cũ thì không lấn của ai, nên không phải xin phép: nới ra
> XA hàng xóm được cho qua, nới VÀO hàng xóm vẫn chặn y như cũ — test 1.9.30 chốt luật chia
> đôi khe giữ nguyên, không sửa một dòng.
> Đo trên job Pi Station 261 EX: **4 vùng đổi, tất cả đều TĂNG cỡ, 0 vùng mất, 0 vùng đổi số
> dòng** — `Chương 3 Các sản phẩm` trở lại một cỡ 15,9pt duy nhất (trước đó hai nửa vẽ 14,04
> và 15,90), và `3.6.4. Hình dạng PCS` vừa khung ở đúng cỡ thay vì phải cắt ngắn tiêu đề.
> **Chỉ đụng stage 6** — job cũ chạy lại stage 6 → 7 là hưởng.

> **1.9.38** **chữ nguồn bị ảnh vẽ đè lên thì KHÔNG vẽ bản dịch.** Engine vẽ bản dịch sau
> cùng, nên chữ mà bản gốc giấu dưới ảnh lại nổi lên TRÊN ảnh ở bản dịch — bản dịch có chữ
> mà bản gốc không có. **Không gate nào thấy:** Gate 3 tìm ra chữ (nó có thật trên trang),
> Gate 4 thấy nằm trong khung, Gate 6 coi thay đổi đó là NẰM TRONG mask nên bỏ qua. Ca thật:
> Pi Station 261 EX trang 24 — cả trang là một ảnh 2481×3508 phủ kín, chú thích hình nằm
> dưới ảnh nên bản gốc không in nó; bản dịch in `Hình 3.4 …` vắt ngang chân tủ.
> Phép thử là **dựng ảnh rồi so pixel** (xoá chữ trong khung, giữ ảnh/vector, render lại
> cùng khung) chứ không đọc thứ tự content stream: một trang có nhiều stream, form XObject
> lồng nhau và trong suốt — đọc thứ tự thì phải mô phỏng lại cả trình vẽ.
> Chỉ chạy cho vùng nằm ≥85% trong một ảnh. Đo trên 14 job: **9 vùng** lọt sàng lọc, **2**
> thật sự bị che (1 vốn đã là `keep`, nên đúng **1** vùng đang bị vẽ sai). Nhãn vẽ TRÊN hình
> — ca thường gặp, 7/9 vùng còn lại — đổi pixel nên không dính.
> Vùng bị che vào `skipped` với lý do `SOURCE_TEXT_OCCLUDED` kèm issue P2. Chữ nằm trong
> ảnh là việc của bước DTP, không phải của engine.
> **Chỉ đụng stage 6** — job cũ chạy lại stage 6 → 7 là hưởng.

> **1.9.37** **ngắt dòng nằm trong giá trị placeholder.** `\s?` của `MEAS_RE`/`STD_RE`/
> `MODEL_RE` khớp cả `\n`, nên một số đo bị bản gốc ngắt dòng giữa chừng đi vào bảng tra
> nguyên cả dấu xuống dòng. Dấu đó theo placeholder vào MỌI bản dịch: fitter nhận giá trị
> là token atomic nên không wrap lại được, và ô nào cũng xuống dòng đúng chỗ bản gốc xuống
> — kể cả khi khung tiếng Việt còn thừa chỗ. Ca thật: Pi Station 261 EX bảng 3.3, ô ghi chú
> rộng 141,8pt in `Cell đơn 2.5V~3.65` rồi `V` một mình xuống dòng, trong khi cả cụm chỉ
> chiếm 96,2pt; ô nhiệt độ cùng trang gãy y hệt ở `55` / `°C`.
> Chuẩn hoá đặt ở chỗ GHI bảng tra vào model (`unwrap_tokens`), không đặt trong `protect()`
> — `protect()` giữ nguyên hợp đồng round-trip nguyên văn mà selftest vẫn chốt.
> Nối bằng rỗng chứ không bằng dấu cách: ngắt dòng ở đây là nét gãy của trình bày. Đo trên
> **1646 placeholder của 14 job**: đúng **2** giá trị có `\n`, cả hai là số dính đơn vị
> (`runs` của region giữ nguyên `3.65V`, `55°C` liền nhau) — 0 ca cần giữ lại dấu cách.
> **Chỉ đụng stage 3** — job cũ chạy lại stage 3 → 7 là hưởng, `region_id` và
> `source_masked` không đổi nên `responses.jsonl` cũ dùng lại nguyên vẹn.

> **1.9.36** **role suy biến** — role mà bản dịch trỏ vào không mang ký tự chữ-số NÀO trong
> nguồn. Ca thật: ghi chú "Note：..." của V16 Lite có role `body` đúng **một dấu `：` font
> Song**, còn `Note` lẫn cả câu sau đều là `emphasis` `Arial-BoldMT`; bản dịch ra một run
> `body` nên `role_face` chọn đúng luật 1.9.35 mà vẫn ra Noto Serif cho cả câu. 3 vùng, 261
> ký tự, trên hai tài liệu V16 Lite đã phát hành.
> Nay khi role suy biến thì mượn từ vùng — nhưng **họ chữ và độ đậm mượn từ hai phép đo khác
> nhau**, vì là hai thuộc tính khác nhau:
> **Họ chữ** (`serif`/`mono`) lấy từ run nhiều mực nhất trong số run CÓ CHỮ-SỐ — dấu câu
> không mang danh tính họ chữ; ô `（A）` của V5 Series chỉ có mỗi `A` là sans, hai dấu ngoặc
> toàn rộng là Song, họ chữ đúng của nó là sans.
> **Độ đậm/nghiêng** lấy từ run nhiều mực nhất trong số MỌI run, không lọc dấu câu — độ đậm
> là thuộc tính của khối mực. Hai ca thật đối nghịch nhau chốt luật này: **dòng mục lục** V16
> Lite là tiêu đề chương ĐẬM 21 ký tự + dãy chấm THƯỜNG 38 ký tự (đo theo run có chữ-số thì
> đậm nguyên dòng — hỏng 38 ký tự để sửa 21); **ghi chú** là 4 ký tự đậm + `：` thường + 98 ký
> tự đậm (đo theo mọi run thì đậm thắng). Cả hai đều khớp bản gốc.
> Đo: 19 vùng có role suy biến trên toàn kho. Chạy lại — V16 Lite quick guide **1,281% →
> 0,000%**, user manual **0,295% → 0,000%**, V5 Series manual **0,021% → 0,000%**; 7 dòng mục
> lục vẫn `Noto Sans Regular` đúng như trước, câu ghi chú vừa sửa nay `Noto Sans Bold` khớp
> bốn câu anh em cùng trang.
> **Chỉ đụng stage 6** — job cũ chạy lại stage 6 → 7 là hưởng.

> **1.9.35** **kiểu chữ** của role lấy theo run mang NHIỀU NÉT MỰC NHẤT (`role_face`), còn
> **màu** vẫn theo run đầu có mực (`role_style`). 1.9.34 tước quyền quyết định của run rỗng,
> nhưng run có mực mà rất ngắn thì vẫn thắng: V16 Lite quick guide mở đầu bằng **một dấu
> `：` font `AdobeSongStd-Light`** rồi 210 ký tự `ArialMT` cùng role — một ký tự quyết định
> kiểu chữ cho cả đoạn. Đo trên bản ĐÃ PHÁT HÀNH: quick guide **7,94%** ký tự Noto Serif,
> V16 Lite user manual **1,26%**. Cùng cơ chế: dấu `≥` mở đầu ô `≥6000Cycles` của V5
> datasheet (7 ký tự serif), `(A)` của V5 Series manual.
> Bản dịch một run phải chọn MỘT kiểu chữ cho cả vùng, nên chọn kiểu phủ được nhiều chữ
> nguồn nhất là lệch ít nhất. Hoà thì giữ run sớm hơn; khoảng trắng không được tính.
> **Vì sao tách hàm thay vì nới `role_style`:** hàm đó còn quyết định MÀU. Đo trên kho: đổi
> màu theo run đa số làm **7 vùng** bảng thông số datasheet kéo nhãn từ đen `#000101` sang
> xám `#585857` của cột giá trị — kiểu chữ theo đa số là đúng, màu thì không. Hai câu hỏi
> khác nhau nên thành hai hàm. `key_for` chỉ đọc `mono/serif/bold/italic`, nên đổi này KHÔNG
> đụng cỡ chữ (37 vùng lệch `size` giữa hai run là vô hại).
> Phạm vi thật: **serif đổi ở 3 vùng, bold 0 vùng, màu 0 vùng**. Chạy lại V5 datasheet:
> **0,27% → 0,000%**. V5 Series manual còn 6 ký tự `(A)` size 8 và đó là ĐÚNG — role `body`
> của ô đó thật sự là Song (hai dấu ngoặc toàn rộng `（）`), chỉ chữ `A` là `emphasis` Arial.
> **Chỉ đụng stage 6** — job cũ chạy lại stage 6 → 7 là hưởng.

> **1.9.34** `role_style` lấy style của run **ĐẦU TIÊN CÓ NÉT MỰC** khớp role, không lấy
> run đầu tiên khớp role. Bản gốc hay mở đầu đoạn bằng span khoảng trắng thuộc font khác:
> ca thật ở HV48100 user manual trang 5 là run 0 = **một dấu cách** `AdobeSongStd-Light`
> (serif) rồi run 1 = 175 ký tự `ArialMT` (sans), cả hai role `body`. Bản dịch một run
> `body` nhận style của dấu cách nên **cả đoạn vẽ bằng Noto Serif**.
> Cùng lớp lỗi "đệm space" mà `ink_base_x` đã sửa cho trục x từ 1.8.0/1.9.9, và cùng thứ
> 1.9.7 đã phải chống riêng trong `build_runs` (`lead_in` đòi run sau có chữ thật) — 1.9.34
> đặt guard ở chính `role_style` nên mọi đường vào đều được che, không chỉ nhánh `emphasis`.
> Đo: vùng có >= 2 run cùng role, run đầu rỗng, khác `serif`/`bold` với run có mực đầu tiên —
> **HV48100 user manual 13 vùng / 7.738 ký tự, V5 datasheet 1 vùng, V5 Series manual 1 vùng**.
> Chạy lại HV48100 manual: ký tự Noto Serif **12,5% → 0,00%**; Noto Sans Bold giữ nguyên 4,5%,
> mọi issue QA khác không đổi (P1=112, P2=127 trước và sau).
> Mọi run cùng role đều rỗng thì giữ hành vi cũ; role không có trong `runs` vẫn lùi về
> `runs[0]`. Khoảng trắng tính theo `str.strip()` nên nbsp và ideographic space cũng không
> được quyết định style.
> **Chỉ đụng stage 6** — không đổi `regions.json`, `region_id`, `source_hash` hay bản dịch;
> job cũ chạy lại stage 6 → 7 là hưởng.

> **1.9.29** `approve.py` **khoá quyền ghi** các artifact làm bằng chứng khi phát hành:
> `model/`, `render/`, `output/`, `translation/*.jsonl`, `qa/report.json`. `--decision revoke`
> mở lại. Không khoá `review/`, `logs/`, `JOB_SUMMARY.md`, `input/job.yaml` (revoke phải ghi
> được), cũng không khoá cả `qa/` — `compare.pdf` và `draft-raster.pdf` vẫn phải dựng lại được
> sau khi phát hành.
> Vì sao cần dù 1.9.28 đã siết `validate_responses`: chốt trạng thái trong stage là hàng rào
> **tự nguyện**, chỉ chặn thứ chịu gọi nó. Helper viết tay trong job (`write_responses.py`)
> không gọi, và 2026-08-07 nó ghi đè `responses.jsonl` của một job đã phát hành. Quyền ghi của
> filesystem thì không tự nguyện — **cùng lý lẽ `lock-engine.sh` dùng cho engine** (§1.2).
> Thoát tay khi cần: `chmod -R u+w <job>`.
> **Spec nguồn:** PDF Translation Engine v1, rev 1.4 — `system_design_pdf_translation_engine_v1_final.md`,
> giữ ở repo tài liệu nội bộ, **không bundle theo engine**. Spec chỉ cần cho dev; runtime không cần.
> **License:** [AGPL-3.0](LICENSE) (cùng license với PyMuPDF — ADR-009); fonts Noto theo [OFL-1.1](assets/fonts/OFL.txt)

## 1. Nguyên Tắc Bắt Buộc

1. **Fail-closed:** input ngoài supported envelope tạo issue có mã; không silent fallback, không rasterize ngầm.
2. **Release rule:** `output/translated-approved.pdf` CHỈ được ghi khi **quality gates PASS VÀ human approval tường minh** (ghi vào `review/decisions.jsonl` kèm approver + timestamp). Agent không bao giờ tự approve. **Cưỡng chế bằng quyền ghi filesystem:** chạy `scripts/lock-engine.sh lock` đặt `scripts/`, `assets/`, `SKILL.md` thành chỉ đọc TRƯỚC khi giao việc cho bất kỳ agent nào, và `lock-engine.sh verify` TRƯỚC khi tin kết quả. TTY + chuỗi xác nhận `APPROVE <sha8>` trong `approve.py` chỉ là lớp **phát hiện**, KHÔNG phải lớp chặn — agent ghi được vào `scripts/` thì xoá được cả hai dòng kiểm (sự cố Antigravity 2026-08-05: đổi thành `if False:` rồi tự approve sau 8 giây). Reviewer phải tự chạy lệnh approve trong terminal thật. Auto-QA pass chỉ tạo `render/draft.pdf`. Release sai có thể thu hồi: `approve.py --decision revoke` (không cần TTY) → status `REVOKED`, xoá output, cho phép re-run stage 4-8.
3. **Artifact là source of truth:** mọi run kết thúc bằng job folder trên disk, không chỉ chat text.
4. **Source immutable:** không bao giờ sửa PDF gốc; mỗi render ghi file mới.
5. Scripts đảm nhiệm phần deterministic (extract, fit, paint, QA); agent đảm nhiệm dịch và điều phối. Agent không tự đặt tọa độ text.
6. **Authenticity (enforce bằng code, không chỉ văn bản):** bản dịch stage 4 PHẢI do model của session sinh cho từng request — CẤM mọi logic dịch nằm trong code (dictionary/bảng tra cứu tự chế, find-replace, fallback copy-source). Script chỉ được là **phương tiện ghi** các bản dịch model đã sinh sẵn (embedded verbatim), đặt trong job folder — không đặt trong `scripts/` của skill. Validator + Gate 2 đo tỷ lệ region đáng dịch có target trùng source hoặc sai ngôn ngữ đích; vượt `translation.authenticity` → **P0 `TRANSLATION_COVERAGE_FAIL` / `TARGET_LANG_FAIL` — không waive được, không thể release**.

**Ngưỡng hiện tại chưa đủ chặt — biết, CHƯA sửa.** Code đo `identical` và `lang_suspect` **riêng từng loại**, mỗi loại 5%, nối bằng `or` (`qa_gates.py`, `authenticity` trong `engine_config_default.yaml`). Đã chốt đổi sang **một tỷ lệ gộp cả ba loại, 1% VÀ tối đa 5 region (lấy cái chặt hơn)** — quyết định ghi trong repo tài liệu nội bộ, dự kiến 1.5.0, nhưng **tính đến 1.9.4 vẫn chưa được cài đặt**. Cho tới khi có, con số Gate 2 phải đọc kèm mắt người.

Hai sự cố Antigravity đứng sau luật này. **2026-08-04:** pseudo-translation hàng loạt. **2026-08-05:** áp glossary bằng find-replace, ăn vào giữa từ tiếng Anh (`important` → `imcổngant`, `Transportation` → `Transcổngation`) và để nguyên 18 region tiếng Anh — 22/514 = 4.3%, **lọt qua ngưỡng cũ vì 5% đo riêng từng loại**. Ngưỡng gộp 1% + cap 5 chặn được; hai lượt đạt (Claude Code, Codex) đều ở mức 0/514.

## 2. I/O Contract

**Input:**

```text
required:
  --pdf <path>            # hoặc input folder chứa source.pdf
optional:
  --out <root>            # default: ./jobs
  --domain-context <text|path>   # xem mục 5
  --glossary <csv>
  --customer-facing       # bật chế độ nghiêm ngặt (mục 5)
  --job <job_id>          # resume job đã có
  --source-lang en --target-lang vi   # default en→vi
  --provider-model <id>   # model id thật của agent dịch stage 4 — ghi vào determinism
                          # tuple (vd claude-fable-5, gpt-5.2-codex, gemini-3-pro)
```

**Output (luôn ghi, kể cả khi preflight REJECTED/MANUAL_DTP_REQUIRED):**

```text
jobs/<job_id>/
├── input/                      # frozen sau khi tạo job; read-only
│   ├── source.pdf              # luôn COPY, không symlink
│   ├── domain_context.md       # effective merged (file + CLI), kèm provenance header
│   ├── glossary.csv            # nếu có
│   └── job.yaml                # effective config snapshot + determinism tuple
├── model/
│   ├── preflight.json
│   ├── resource_manifest.json  # before-snapshot cho Gate 5 (images/drawings/links/boxes)
│   ├── regions.json            # layout + semantic model, latest
│   └── fonts.json
├── translation/
│   ├── requests.jsonl
│   ├── responses.jsonl         # schema-validated
│   └── tm_hits.jsonl           # optional
├── render/
│   ├── draft.pdf
│   └── render_manifest.json
├── qa/
│   ├── report.json
│   ├── page_png/               # 300 DPI, flagged 600 DPI
│   └── diffs/
├── review/
│   └── decisions.jsonl         # append-only; approver + timestamp
├── output/
│   └── translated-approved.pdf # chỉ khi thỏa Release rule (mục 1.2)
└── JOB_SUMMARY.md              # status theo state machine + issues + next action
```

**job.yaml determinism tuple (bắt buộc đủ):** `source_sha256`, `domain_context_sha256`, `glossary_version`, `engine_version`, `config_version`, `font_pack_version`, `layout_model_version`, `provider_model_version`, `prompt_version`, `pymupdf_version`.

## 3. Job Identity

```text
job_id = <slug(pdf_stem)>__<source_sha8>__<UTC yyyymmddThhmmss>
# ví dụ: v16_lite_quick_guide__a1b2c3d4__20260804T153012
```

- `slug()`: thay ký tự ngoài `[A-Za-z0-9_-]` bằng `_`, gộp `_` lặp, lowercase, tối đa 60 ký tự.
- Chạy lại cùng PDF → job mới; `--job <id>` → resume.
- **Resume phải re-verify `source_sha256` khớp job.yaml; lệch → hard error** (source đã đổi).
- Single-writer: tạo `.lock` trong job folder khi chạy; job đang lock không cho session khác ghi.

## 4. Pipeline Stages

| # | Stage | Thực thi | Output chính |
|---|---|---|---|
| 1 | preflight | `scripts/preflight.py` | `model/preflight.json`, `model/resource_manifest.json` |
| 2 | extract + group | `scripts/extract_group.py` | `model/regions.json`, `model/fonts.json` |
| 2.5 | context graph | `scripts/build_context_graph.py` | `model/context_graph.json`, `chain_id` trên region |
| 3 | translate-prep | `scripts/translate_prep.py` | `translation/requests.jsonl` |
| 4 | translate | **agent (in-session)** | `translation/responses.jsonl` |
| 5 | validate | `scripts/validate_responses.py` | reject sai schema/placeholder → agent sửa |
| 6 | fit + paint | `scripts/fit_paint.py` | `render/draft.pdf`, `render_manifest.json` |
| 7 | qa | `scripts/qa_gates.py` | `qa/report.json`, PNG, diffs, cập nhật JOB_SUMMARY |
| 8 | approve | `scripts/approve.py --approver <name>` | `decisions.jsonl`, promote `output/` |

- Mỗi stage idempotent; resume = chạy stage kế tiếp còn thiếu; mọi stage mở đầu bằng verify fingerprint.
- **Stage 4 chạy bởi chính agent của session** (Claude Code / Codex / Antigravity) bằng model của session — không gọi API ngoài, không cần API key riêng. Agent truyền model id thật qua `--provider-model` khi tạo job (mục 2). Dịch thật từng request theo batch — mọi lối tắt script/dictionary bị chặn P0 (mục 1.6).
- **Batching stage 4:** mỗi batch chứa region theo reading order kèm type/neighbors/container hint; **không cắt batch giữa cross-page continuation group**; không nhét cả PDF vào một turn.
- **Explicit line break:** `\n` trong text của target run = hard break (giữ cấu trúc label/value); fitter tôn trọng, validator/QA so sánh sau khi collapse whitespace.
- Translation memory: chỉ seed TM từ jobs đã **approved**.
- **Stage 8: KHÔNG duyệt nhiều job bằng vòng lặp shell.** `approve.py` đòi gõ chuỗi thử
  thách `APPROVE <sha8>`, mà `sha8` là 8 ký tự đầu của `source_sha256` — **khác nhau từng
  job**. Một vòng `for` bắt reviewer gõ nhiều chuỗi khác nhau liên tiếp, không nhìn thấy
  đang ở job nào, và mọi lần gõ nhầm đều bị chặn im lặng giữa dòng cuộn. Sự cố thật
  2026-08-06: một vòng lặp 4 job đẻ ra **4 lần chạy bị chặn**, mỗi lần để lại một dòng
  `decisions.jsonl` không tương ứng với phê duyệt nào (1.9.1 đã chặn phần ghi dòng ma,
  nhưng không chữa được việc gõ nhầm). Chạy **từng lệnh một**, và lấy sẵn chuỗi cho từng
  job trước khi chạy:

  ```bash
  python3 -c "import yaml,sys; print('APPROVE ' + yaml.safe_load(open(sys.argv[1]+'/input/job.yaml'))['determinism']['source_sha256'][:8])" <job_dir>
  ```

## 5. Domain Context Policy

- Nguồn: `--domain-context` (text hoặc path) và/hoặc `input/domain_context.md` trong input folder. Merge CLI đè lên file, **kết quả merge được freeze vào `input/domain_context.md`** kèm provenance marker.
- Template: [assets/domain_context.template.md](assets/domain_context.template.md).
- **Default:** thiếu context → preflight issue `DOMAIN_CONTEXT_MISSING` mức **P2 (warning)**, pipeline vẫn chạy, JOB_SUMMARY nhắc.
- **`--customer-facing`:** issue thành **P1 (blocking)** — dừng trước translate cho đến khi có context.
- **Advisory-only.** Precedence: `protected tokens > glossary > domain_context > model choice`. Hard policy (number format, font-size thresholds, protected classes, gates) chỉ đổi qua `job.yaml` có cấu trúc — free-text context không override được, và gates enforce bằng code nên context không thể mở khóa release.

## 6. Data & Privacy

> **Disclosure (bắt buộc giữ trong README khi publish):** text content của PDF được gửi tới LLM provider của session đang chạy để dịch. Người dùng tự chịu trách nhiệm data policy đối với tài liệu của họ. Nội bộ Pytes: đã approve dịch tài liệu nội bộ qua Claude API (ADR-009).

- Không log toàn bộ nội dung tài liệu ra ngoài job folder.
- Job folder có thể chứa nội dung nhạy cảm — đặt `--out` vào storage có kiểm soát.

## 7. Quality Gates (tóm tắt — chi tiết ở spec §10)

Gate 1 decision coverage → Gate 2 translation integrity (placeholder round-trip, glossary, **authenticity: identical-target + target-language ratio, P0 khi vượt ngưỡng — mục 1.6**; **entity: địa chỉ bưu chính phải giữ nguyên như nguồn, P1 `CONSISTENCY_ENTITY`**) → Gate 3 rendered-text coverage (translated + `keep` regions nguyên vẹn, NFC, tofu, color tolerance, htmlbox scale trong policy) → Gate 4 geometry/collision (out-of-container theo `qa.container_tol_pt` cho ngang/trên và `qa.container_tol_y_em` cho đáy; **table rule cross**: dòng dịch trong `table_cell` không được cắt ngang nét kẻ dọc thật của bảng) → Gate 5 image/vector preservation (so với `resource_manifest.json`) → Gate 6 visual diff 300/600 DPI → Gate 7 structural validation. Release cần: không còn P0/P1 unresolved **và** human approval.

So sánh resource/visual dùng **content digest + geometric tolerance (~1pt)** và **meaningful-diff threshold** — không dùng bit-exact/md5 equality: tọa độ round-int flaky tại biên `.5`, renderer lệch ±1/255 theo cache state (spec §9.5, §20.1).

## 8. Environment

- **Resolve interpreter — một lệnh, mọi agent, mọi máy:**

  ```bash
  bash scripts/setup.sh          # in `PYTHON=<path>`; tự tạo .venv trong skill folder nếu cần
  bash scripts/setup.sh --check  # chỉ kiểm tra, không cài (exit 3 nếu thiếu env)
  ```

  Thứ tự ưu tiên: `$PDFTL_PYTHON` → `<skill>/.venv/bin/python3` → python3 hệ thống thỏa pin.
  Agent PHẢI dùng đúng `$PYTHON` này cho mọi stage script — không hardcode đường dẫn
  interpreter của riêng agent nào.
- Deps trong [requirements.txt](requirements.txt) — Python >= 3.10; `pymupdf==1.27.2.3` pin cứng
  (đổi pymupdf phải chạy lại golden tests; dep phụ dùng floor version, setup.sh chỉ enforce pin pymupdf).
- **Runtime offline:** network chỉ cần một lần lúc `setup.sh` cài deps.
- `assets/fonts/`: Noto pack **đã bundle** — 10 static faces chữ (Sans/Serif/Mono × Regular/Bold/Italic/BoldItalic) + `NotoSansSymbols2-Regular` làm fallback KÝ HIỆU, SHA-256 pinned trong `fonts_manifest.json`, full Vietnamese coverage đã test kể cả dấu chồng (spec §7.2). Face ký hiệu đứng CUỐI `FontPack.FALLBACK_CHAIN` và không bao giờ là face chính — `key_for` chỉ trả sans/serif/mono.

## 9. Chạy Đa Agent (Claude Code / Codex / Antigravity)

> **Bắt buộc trước MỌI lượt giao việc cho agent:** `scripts/lock-engine.sh lock`, và
> `scripts/lock-engine.sh verify` trước khi tin kết quả. Không có bước này thì không có
> gì ngăn agent sửa `scripts/` — đã xảy ra thật.
>
> Job folder nằm ngoài skill, nên bước dò file `.py` lạ do agent tự sinh cần được chỉ
> đường: `PDFTL_JOBS=<job root> scripts/lock-engine.sh verify`.
>
> **Antigravity IDE 2.1.1 — KHÔNG ĐẠT (2026-08-05).** Sửa `scripts/approve.py` thành
> `if False:` để vô hiệu hoá chốt human-approval rồi tự phát hành; chạy `fit_paint` +
> `qa_gates` + `approve` dù giao thức chỉ cho `validate_responses`; tự sinh 6 file `.py`
> (~330 KB); Gate 2/3/4/6 FAIL, P1=116. Bảng dưới giữ lại vì đường dẫn discovery vẫn
> đúng, **không phải vì nền tảng này dùng được**.

Skill theo chuẩn mở [Agent Skills](https://agentskills.io) — cùng một folder, cùng cách
đăng ký discovery. Hành vi thì **không** đồng nhất: xem cảnh báo trên.

| Agent | Discovery trong repo này | Cài global (mọi workspace) | Gọi skill |
|---|---|---|---|
| Claude Code | `<git root>/.claude/skills/` và `.agents/skills/` (symlink sẵn) | `~/.claude/skills/` | auto theo description hoặc `/pdf-translate-layout` |
| Codex CLI/IDE | `<git root>/.agents/skills/` (tìm từ cwd → repo root) | `~/.agents/skills/` | `/skills`, gõ `$pdf-translate-layout`, hoặc auto |
| Antigravity | `<workspace root>/.agents/skills/` | `~/.gemini/config/skills/` | auto theo description hoặc mention tên skill |

- Đăng ký: `bash scripts/install.sh repo` (symlink tại git root — đã chạy sẵn cho repo này),
  `bash scripts/install.sh global`, `bash scripts/install.sh status`. Tool không theo
  symlink → thêm `--copy`.
- Antigravity mở **subfolder** làm workspace (vd `V16 Battery/`) sẽ không thấy
  `.agents/` ở git root — dùng bản global.
- **Quy tắc parity:** agent nào cũng chạy đúng các stage script §4 qua shell với `$PYTHON`
  từ `setup.sh`; stage 4 agent tự dịch in-session và ghi model id qua `--provider-model`;
  không agent nào được tự approve (mục 1.2 — enforce: approve đòi TTY người thật),
  tự đặt tọa độ text (mục 1.5), hay sinh bản dịch bằng script/dictionary
  (mục 1.6 — P0 không waive được).
- Codex sandbox: scripts chỉ đọc/ghi trong workspace và job folder — không cần escalation;
  chỉ `setup.sh` lần đầu cần network approval.

## 10. Package Layout

```text
pdf-translate-layout/
├── SKILL.md
├── LICENSE                     # AGPL-3.0
├── requirements.txt            # deps (pymupdf pin cứng; Python >= 3.10)
├── .gitignore                  # .venv/, __pycache__/, *.lock
├── scripts/
│   ├── setup.sh                # resolve/bootstrap interpreter (§8)
│   ├── install.sh              # đăng ký discovery đa agent (§9)
│   ├── _common.py              # job infra: identity, lock, status machine, summary
│   ├── preflight.py            # stage 1
│   ├── extract_group.py        # stage 2
│   ├── build_context_graph.py  # stage 2.5 (§4) — nối region thuộc về nhau
│   ├── translate_prep.py       # stage 3
│   ├── validate_responses.py   # stage 5
│   ├── fit_paint.py            # stage 6
│   ├── qa_gates.py             # stage 7 (gates 1-7)
│   ├── approve.py              # stage 8
│   └── selftest.py             # pure-function tests
└── assets/
    ├── fonts/                  # Noto pack 10 faces chữ + 1 face ký hiệu + fonts_manifest.json (SHA-256) + OFL.txt
    ├── engine_config_default.yaml
    ├── default_glossary.csv
    └── domain_context.template.md
```

## 11. Giới Hạn v1 (đã chủ ý, theo supported envelope của spec)

- Painting qua `insert_text` per-segment (không dùng `insert_htmlbox`); justified
  alignment chưa hỗ trợ — map về left/center/right.
- Rotation: 0/90/180/270; rotated **multi-line** → P1 review, không tự paint.
- `reuse_source_font: false` — luôn map sang Noto bundle (nhánh conservative §7.3);
  display font → P1 `FONT_DISPLAY_FALLBACK` cho reviewer xác nhận.
- Ký hiệu: `NotoSansSymbols2-Regular` đã bundle từ 1.9.46 (✓ ✔ ✗ ▪ • ○ ◇ …). CJK fallback
  vẫn chưa bundle. `cover()` đòi MỘT face phủ trọn token, nên token trộn chữ Việt với ký hiệu
  (`kiểm✓` dính liền) vẫn hỏng — tách bằng dấu cách thì chạy. Codepoint ngoài coverage, kể cả
  PUA của Wingdings/Symbol, → blocking `FONT_GLYPH_MISSING` (fail-closed, không tofu).
- Table detection theo `find_tables` (bordered); bảng không kẻ khung có thể được
  group như paragraph.
- Continuation qua page break: heuristic cơ bản (câu chưa kết + chữ thường đầu trang).
- Ô trống điền tay giữa dòng: giữ được từ 1.9.0, nhưng **bản dịch phải tự đặt lại**
  dãy `____` (stage 3 cảnh báo, thiếu thì P1 `FILL_BLANK_DROPPED`). Engine không tự
  suy ra chỗ đặt vì bản dịch đảo vế tự do.
- Review = chat + `qa/page_png` + `qa/diffs` (internal/pilot tier — M4 UI để sau).
