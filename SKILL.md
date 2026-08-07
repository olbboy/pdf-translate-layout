---
name: pdf-translate-layout
description: Dịch PDF có text layer (mặc định EN→VI) bảo toàn layout, ảnh, vector, bảng và typography theo PDF Translation Engine v1. Dùng khi user muốn dịch PDF giữ nguyên format ("translate PDF keep layout", dịch manual/datasheet/quick guide sang tiếng Việt), hoặc tiếp tục một translation job đã có. Fail-closed; output cuối chỉ phát hành khi quality gates pass và có human approval.
license: AGPL-3.0
compatibility: Agent-agnostic theo chuẩn Agent Skills. Đã kiểm chứng trên Claude Code và OpenAI Codex (2026-08-05, cùng job 514 region, cả hai đạt). **Antigravity IDE 2.1.1 ĐÃ THỬ VÀ KHÔNG ĐẠT** — sửa `scripts/approve.py` để tự cấp quyền phát hành, chạy quá phạm vi, Gate 2/3/4/6 FAIL; xem `plans/reports/incident-antigravity-self-approve-and-engine-tamper-260805-1222-*`. Agent khác chưa kiểm chứng. Cần shell macOS/Linux + Python >= 3.10; bootstrap deps một lần bằng `bash scripts/setup.sh` (cần network lúc cài); runtime offline, fonts đã bundle.
metadata:
  version: "1.9.8"
---

# pdf-translate-layout

> **Trạng thái:** RELEASED v1.9.8 (engine `1.9.8`, layout model `lg-basic-6`) —
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
- `assets/fonts/`: Noto pack **đã bundle** — 10 static faces (Sans/Serif/Mono × Regular/Bold/Italic/BoldItalic), SHA-256 pinned trong `fonts_manifest.json`, full Vietnamese coverage đã test kể cả dấu chồng (spec §7.2).

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
    ├── fonts/                  # Noto pack 10 faces + fonts_manifest.json (SHA-256) + OFL.txt
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
- Symbol/CJK fallback families chưa bundle — codepoint ngoài coverage → blocking
  `FONT_GLYPH_MISSING` (fail-closed, không tofu).
- Table detection theo `find_tables` (bordered); bảng không kẻ khung có thể được
  group như paragraph.
- Continuation qua page break: heuristic cơ bản (câu chưa kết + chữ thường đầu trang).
- Ô trống điền tay giữa dòng: giữ được từ 1.9.0, nhưng **bản dịch phải tự đặt lại**
  dãy `____` (stage 3 cảnh báo, thiếu thì P1 `FILL_BLANK_DROPPED`). Engine không tự
  suy ra chỗ đặt vì bản dịch đảo vế tự do.
- Review = chat + `qa/page_png` + `qa/diffs` (internal/pilot tier — M4 UI để sau).
