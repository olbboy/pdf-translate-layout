"""Self-test các pure function chủ chốt. Chạy: python3 selftest.py (exit 0 = pass)."""

from __future__ import annotations

import collections
import os
import re
import unicodedata

from _common import (STATUS_TRANSITIONS, BlockingError as _BE, fill_in_rules, nfc,
                     new_job_id, slug)
from fit_paint import column_split, wrap_lines
from translate_prep import NUMERIC_RE, PH_DIGIT_ADJ as _PDA, PH_RE, protect, restore
from validate_responses import apply_punct_map

FAILURES = []
TOTAL = 0


def check(name: str, cond: bool, detail: str = ""):
    global TOTAL
    TOTAL += 1
    if not cond:
        FAILURES.append(f"{name}: {detail}")
    print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if not cond and detail else ""))


# slug + job id
check("slug basic", slug("V16 Lite quick guide -20260123") == "v16_lite_quick_guide_-20260123",
      slug("V16 Lite quick guide -20260123"))
check("slug maxlen", len(slug("x" * 200)) <= 60)
jid = new_job_id("/tmp/Đơn hàng (bản cuối).pdf", "a1b2c3d4" + "0" * 56)
check("job_id shape", jid.count("__") == 2 and jid.split("__")[1] == "a1b2c3d4", jid)

# protected tokens roundtrip (spec §6.5)
KEEP = ["Pytes", "V16 Lite", "V16", "Victron", "RS485"]
src = ("Connect the Pytes V16 Lite battery to the RS485 port at 48V and 25°C. "
       "See https://pytes.com or mail sales@pytes.com. Pytes M5X12 bolt, torque 8Nm.")
masked, mapping = protect(src, KEEP)
check("protect masks brand", "Pytes" not in PH_RE.sub("", masked), masked)
check("protect longer-first", "⟦BRAND_" in masked and "V16 Lite" in mapping.values())
check("protect url", "https://" not in PH_RE.sub("", masked))
check("protect meas", any(v in ("48V", "25°C", "8Nm") for v in mapping.values()), str(mapping))
check("roundtrip exact", restore(masked, mapping) == src)
m2, mp2 = protect("Pytes and Pytes again", ["Pytes"])
check("repeated tokens distinct", len(mp2) == 2 and restore(m2, mp2) == "Pytes and Pytes again")

# numeric keep
check("numeric keep", bool(NUMERIC_RE.match("211.48")) and bool(NUMERIC_RE.match("4/0"))
      and not NUMERIC_RE.match("48V"))

# ── PH_DIGIT_ADJACENT 1.8.1 ─────────────────────────────────────────────
# Bản gốc V16 in `is1 5V` cho `1.5V`; protect() che `5V` còn chữ số `1` mắc lại trong
# `is1`, model dịch ra "đạt 5V" — sai một bậc 10 lần. Luật phải CHẶT: đòi chữ cái liền
# trước chữ số, nếu không số mục `6.1 ⟦MODEL_1⟧` cũng dính (18/19 cảnh báo là oan).
check("ph-adj bắt chữ số dính chữ trước placeholder",
      bool(_PDA.search("confirm if external charging voltage is1 ⟦MEAS_1⟧ or arece.")))
check("ph-adj bắt cả khi không có dấu cách",
      bool(_PDA.search("voltage is1⟦MEAS_1⟧ or above")))
check("ph-adj BỎ QUA số mục có dấu chấm phân cách",
      not _PDA.search("6.1 ⟦MODEL_1⟧ port"))
check("ph-adj BỎ QUA số đứng riêng cạnh placeholder",
      not _PDA.search("Bảng 7-1 ⟦BRAND_1⟧ LED"))
check("ph-adj BỎ QUA chiều ngược — placeholder rồi số đo là dạng bình thường",
      not _PDA.search("range ⟦MEAS_1⟧ 5V or above"))
check("ph-adj sạch trên nguồn bình thường",
      not _PDA.search("Charge current ⟦MEAS_1⟧ at ⟦MEAS_2⟧ ambient"))

# punctuation map ngoài placeholder
pm = {"，": ", ", "：": ": "}
out, changed = apply_punct_map("A，B：C ⟦MEAS_1⟧，D", pm)
check("punct map", out == "A, B: C ⟦MEAS_1⟧, D" and changed, out)
check("punct token intact", "⟦MEAS_1⟧" in out)

# NFC (spec §6.6): NFD input → precomposed
nfd = unicodedata.normalize("NFD", "hệ thống điện")
check("nfc normalize", nfc(nfd) == "hệ thống điện" and len(nfc("ệ")) == 1)

# wrap_lines greedy
check("wrap basic", wrap_lines([10, 10, 10], 2, 25) == [[0, 1], [2]])
check("wrap single fits", wrap_lines([24], 2, 25) == [[0]])
check("wrap too-wide token", wrap_lines([10, 30], 2, 25) is None)
check("wrap exact width", wrap_lines([25], 2, 25) == [[0]])

# ── space_w theo font token liền kề (engine 1.5.0 phase 1) ──
# Dòng trộn font: khe sau token mono rộng hơn khe sau token sans. Đo thật ở cỡ 7pt:
# space NotoSans-Bold = 1.82pt, NotoSansMono = 4.20pt → 4 khe lệch 9.5pt, đủ để dòng
# thò khỏi ô. Ca hồi quy: hàng SOC p11/table_cell/11_34/19 của job V16 manual, fitter
# tính dòng kết thúc ở 380.2pt còn render thật ở 389.7pt.
check("wrap khe không đều: khe rộng đẩy token sang dòng sau",
      wrap_lines([10, 10, 10], [1.0, 6.0, 1.0], 22) == [[0, 1], [2]])
check("wrap khe không đều: khe hẹp giữ đủ ba token",
      wrap_lines([10, 10, 10], [1.0, 1.0, 1.0], 22) is not None
      and len(wrap_lines([10, 10, 10], [1.0, 1.0, 1.0], 32)) == 1)
check("wrap khe list == khe scalar khi mọi khe bằng nhau",
      wrap_lines([10, 10, 10], [2.0, 2.0, 2.0], 25) == wrap_lines([10, 10, 10], 2, 25))

# column_split (1.9.0) — hàng bảng gộp nhiều cột. Dựng region tối thiểu đúng hình học
# hàng dữ liệu bảng bảo hành V16: 3 cột × 2 hàng, x lặp lại ở cả hai hàng.
def _reg(rtype, xy, target, container=(66, 571, 491, 615)):
    return {"region_type": rtype, "rotation": 0, "container": list(container),
            "lines": [{"spans": [{"origin": [x, y], "text": "x"}]} for x, y in xy],
            "target_runs": [{"role": "body", "text": target}]}


_GRID = [(70.9, 583.2), (205.8, 583.2), (338.5, 583.2), (338.5, 598.9), (205.8, 598.9)]
_subs = column_split(_reg("table_cell", _GRID, "V16\ncột hai\ncột ba"))
check("column_split: hàng 3 cột tách đúng 3", _subs is not None and len(_subs) == 3)
check("column_split: mỗi cột giữ base_x riêng",
      _subs is not None
      and [round(s["lines"][0]["spans"][0]["origin"][0], 1) for s in _subs] == [70.9, 205.8, 338.5])
check("column_split: khung cột chặn ở cột kế tiếp",
      _subs is not None and [round(s["container"][2], 1) for s in _subs] == [205.8, 338.5, 491.0])
check("column_split: lệch số đoạn thì không tách",
      column_split(_reg("table_cell", _GRID, "chỉ một đoạn")) is None)
check("column_split: paragraph không tách dù nhiều x (nhãn danh sách)",
      column_split(_reg("paragraph", _GRID, "a\nb\nc")) is None)
# Thụt lề không lặp qua nhiều hàng → không phải lưới.
check("column_split: thụt lề một cấp không bị coi là cột",
      column_split(_reg("table_cell", [(70.9, 583.2), (106.9, 583.2), (70.9, 598.9)],
                        "a\nb")) is None)

# fill_in_rules (1.9.0) — ô trống điền tay. Hình học thật của Terms of Warranty p1 và của
# nhãn chú thích hình Lite quick guide p8 (ca báo oan phải loại).
def _reg_lines(bboxes, container):
    return {"container": list(container),
            "lines": [{"bbox": list(b), "spans": [{"origin": [b[0], (b[1] + b[3]) / 2]}]}
                      for b in bboxes]}


_FORM = _reg_lines([(70.9, 229.0, 121.9, 242.6), (223.9, 229.0, 470.9, 242.6)],
                   (70.9, 224.4, 572.9, 249.3))
check("fill_in_rules: gạch có chữ hai phía = ô trống",
      len(fill_in_rules(_FORM, [(121.9, 237.6, 223.9, 237.6)])) == 1)
# Nhãn `Handle` + đường dẫn ngang chỉ vào hình: chữ chỉ nằm bên trái gạch.
_LABEL = _reg_lines([(200.0, 461.0, 221.3, 474.0)], (196.0, 458.0, 300.0, 478.0))
check("fill_in_rules: đường dẫn nhãn hình KHÔNG phải ô trống",
      fill_in_rules(_LABEL, [(221.3, 467.8, 239.4, 467.8)]) == [])
check("fill_in_rules: nét kẻ trải gần hết khung là kẻ bảng, bỏ qua",
      fill_in_rules(_FORM, [(75.0, 237.6, 560.0, 237.6)]) == [])
check("fill_in_rules: gạch ngoài dải mực của dòng thì bỏ qua",
      fill_in_rules(_FORM, [(121.9, 300.0, 223.9, 300.0)]) == [])

# decisions.jsonl chỉ được ghi khi quyết định ĐÃ có hiệu lực (1.9.1). Bất biến này nằm ở
# thứ tự lệnh trong `main()` nên không test bằng hàm thuần được — soi thẳng mã nguồn.
# Ca thật 2026-08-06 job HV48100: reviewer gõ sai chuỗi xác nhận, release bị chặn đúng
# nhưng nhật ký append-only vẫn giữ mãi dòng "Leo approved" cho một job chưa từng phát hành.
_APPROVE_SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "approve.py"), encoding="utf-8").read()
_common_path = _APPROVE_SRC[_APPROVE_SRC.index("decision = {"):
                            _APPROVE_SRC.index('if args.decision == "reject"')]
# Đếm CHỖ GỌI, không đếm chỗ định nghĩa: dòng gọi chỉ có `record()`, còn dòng định nghĩa
# là `def record() -> None:` nên không khớp neo đầu/cuối dòng.
_CALL_RE = re.compile(r"^\s+record\(\)$", re.M)
# Neo đúng 12 dấu cách = mức lệnh trong `with job.acquire_lock(...)`. Thân của `record()`
# thụt 16 nên không dính; nhờ vậy check này tự bắt được cả kiểu ghi thẳng `append_jsonl`
# trên đường chung — đúng thứ tự cũ đã gây sự cố — chứ không phải chỉ bắt `record()`.
_STMT_WRITE_RE = re.compile(r"^ {12}(?:record\(\)|append_jsonl\()", re.M)
check("approve: không ghi decisions.jsonl trên đường chung (trước mọi chốt)",
      not _STMT_WRITE_RE.search(_common_path))
check("approve: append_jsonl chỉ có một chỗ gọi duy nhất, nằm trong record()",
      _APPROVE_SRC.count("append_jsonl(") == 1)
check("approve: đúng ba nhánh quyết định, mỗi nhánh ghi một lần",
      len(_CALL_RE.findall(_APPROVE_SRC)) == 3)
check("approve: ghi decisions.jsonl SAU chốt human-terminal",
      _APPROVE_SRC.index("require_human_terminal(job)")
      < _APPROVE_SRC.rindex("record()"))
check("approve: ghi decisions.jsonl TRƯỚC khi lật trạng thái phát hành",
      _APPROVE_SRC.rindex("record()") < _APPROVE_SRC.index('set_status("HUMAN_APPROVED"'))

# Cây thư mục job phải tự lành ở MỌI stage (1.9.2), không chỉ ở preflight: thư mục rỗng biến
# mất qua git/zip/rsync, và job dựng bằng engine cũ có SUBDIRS ngắn hơn. Hai ca đổ thật đều
# cùng gốc — `output/` (approve, 1.8.2) và `qa/page_png/` (qa_gates). Mọi stage vào qua
# acquire_lock nên test đúng chỗ đó.
import tempfile
from _common import Job as _Job

with tempfile.TemporaryDirectory() as _tmp:
    _job = _Job(_tmp)
    check("job dir: thiếu thư mục trước khi vào stage",
          not os.path.isdir(_job.p("qa", "page_png")))
    with _job.acquire_lock("selftest"):
        _missing = [d for d in _Job.SUBDIRS if not os.path.isdir(_job.p(d))]
    check("job dir: acquire_lock tạo đủ mọi SUBDIRS", not _missing, str(_missing))
    check("job dir: SUBDIRS phủ đúng các thư mục từng gây lỗi",
          {"qa/page_png", "qa/diffs", "output"} <= set(_Job.SUBDIRS))

# state machine terminals — RELEASED không còn terminal: chỉ được phép thu hồi (REVOKED)
for terminal in ("MANUAL_DTP", "REJECTED", "CANCELLED"):
    check(f"terminal {terminal}", STATUS_TRANSITIONS[terminal] == set())
check("RELEASED chỉ thoát qua REVOKED", STATUS_TRANSITIONS["RELEASED"] == {"REVOKED"})
check("no direct RENDERED→RELEASED", "RELEASED" not in STATUS_TRANSITIONS["RENDERED"])
check("no direct AUTO_QA→RELEASED", "RELEASED" not in STATUS_TRANSITIONS["AUTO_QA_PASS"])

# ── authenticity (chống pseudo-translation — sự cố 2026-08-04) ──
from _common import STATUS_TRANSITIONS as _ST, authenticity_check, authenticity_cfg

check("auth identical EN paragraph",
      authenticity_check("We strongly recommend that you read this manual before installing.",
                         "We strongly recommend that you read this manual before installing.") == "identical")
check("auth real VI translation OK",
      authenticity_check("We strongly recommend that you read this manual.",
                         "Chúng tôi đặc biệt khuyến nghị bạn đọc kỹ tài liệu này.") is None)
check("auth mixed EN+VI flagged",
      authenticity_check("Caution, a battery can present a risk of electric shock and burns.",
                         "Chú Ý, a battery can present a risk of electric shock and burns.") == "lang_suspect")
check("auth short label identical OK",
      authenticity_check("No.", "No.") is None)
check("auth address identical OK (under min_words)",
      authenticity_check("Best regards,", "Best regards,") is None)
check("auth placeholder-heavy skipped",
      authenticity_check("⟦MODEL_1⟧ ⟦MEAS_1⟧ ⟦MEAS_2⟧", "⟦MODEL_1⟧ ⟦MEAS_1⟧ ⟦MEAS_2⟧") is None)
check("auth non-vi target lang skipped",
      authenticity_check("Read the manual carefully before use today.",
                         "Lesen Sie das Handbuch sorgfaltig vor der Nutzung.",
                         target_lang="de") is None)
check("auth cfg defaults", authenticity_cfg({})["identical_ratio_max"] == 0.05)

# ── keep-term không bị coi là "chưa dịch" (engine 1.5.1) ──
# Ca thật: quick guide giữ nguyên tên pháp nhân đúng theo glossary type=keep, Gate 2 vẫn
# báo TRANSLATION_IDENTICAL và làm gate đỏ, buộc reviewer waive một bản dịch đúng.
_KEEP = ["Pytes", "Shanghai PYTES Energy Co., Ltd.", "V16 Lite"]
check("auth source toàn keep-term giữ nguyên là hợp lệ",
      authenticity_check("Shanghai PYTES Energy Co., Ltd.",
                         "Shanghai PYTES Energy Co., Ltd.", keep_terms=_KEEP) is None)
check("auth không có keep-list thì vẫn báo identical",
      authenticity_check("Shanghai PYTES Energy Co., Ltd.",
                         "Shanghai PYTES Energy Co., Ltd.") == "identical")
check("auth câu văn lẫn keep-term vẫn bị xét",
      authenticity_check("Connect the Pytes battery to the inverter now",
                         "Connect the Pytes battery to the inverter now",
                         keep_terms=_KEEP) == "identical")

# ── truncation 1.4.2 (sự cố 2026-08-05: ghi đè theo chỉ số dòng + audit bản Lite) ──
# Ca thật: câu miễn trừ trách nhiệm 11 từ bị thay bằng tiêu đề 3 từ. Sàn cũ 12 để lọt.
check("auth truncated: câu 11 từ thay bằng tiêu đề 3 từ",
      authenticity_check(
          "Product is not intended for use in medical or aviation-related applications, and should ",
          "Trước khi Dùng") == "truncated")
# Câu an toàn 7 từ đếm — floor 6 phủ được, floor cũ 12 thì không.
check("auth truncated: câu cấm ngắn mất ruột",
      authenticity_check("Danger, do not place near open flame or flammable materials.",
                         "Nguy hiểm") == "truncated")
# Nhãn 3-4 từ dịch gọn hợp lệ — dưới sàn 6, không bao giờ xét.
check("auth label ngắn dịch gọn OK",
      authenticity_check("Peak Discharge Current Protection", "Bảo vệ dòng xả đỉnh") is None)
# Tier 0.60 cho source dài: ca thật bản Lite RELEASED — mất "Do not short-circuit
# the Li-ion battery." khỏi caption ký hiệu, ratio từ 11/19=0.58.
check("auth truncated: caption dài rơi câu cấm (tier 0.60)",
      authenticity_check(
          "Caution, a battery can present a risk of electric shock and burns by high \n"
          "short-circuit current. Do not short-circuit the Li-ion battery.",
          "Chú ý: Pin có thể gây điện giật và bỏng do dòng ngắn mạch cao.") == "truncated")
# VI súc tích hợp lệ giữ >=60% số từ — không cờ (ca thật p30 lite, 11/17=0.65).
check("auth VI súc tích 0.65 OK",
      authenticity_check(
          "If the battery still \ndoes not \ndischarge properly \nafter following the \n"
          "above steps,\nplease contact the \nlocal reseller or \n⟦BRAND_1⟧.",
          "Nếu vẫn không xả được sau các bước trên, liên hệ đại lý hoặc ⟦BRAND_1⟧.") is None)

# ── content-drift checks 1.4.1/1.4.2 (validate_responses) ──
from validate_responses import carry_through, digit_drift, negation_drop, symbol_drift

# ── carry-through 1.4.3 (find-replace lọt vào bản đã RELEASED) ──
check("carry_through: quy trình khởi động chỉ đổi mỗi 'Step'",
      carry_through("Step 1. Turn on the DC breaker.\nStep 2. Turn on the power button.\n"
                    "Step 3. Press SW button for 1 second to turn on the battery.",
                    "Bước 1. Turn on the DC breaker.\nBước 2. Turn on the power button.\n"
                    "Bước 3. Press SW button for 1 second to turn on the battery.") is not None)
check("carry_through: câu ngắn 3 từ thường vẫn bắt",
      carry_through("Step 1. Press SW button for 3 seconds.",
                    "Bước 1. Press SW button for 3 seconds.") is not None)
check("carry_through: bản dịch thật không bị bắt",
      carry_through("Turn on the DC breaker before starting the system.",
                    "Bật aptomat DC trước khi khởi động hệ thống.") is None)
check("carry_through: tên riêng giữ nguyên là hợp lệ",
      carry_through("Shanghai PYTES Energy Co., Ltd.",
                    "Công ty Shanghai PYTES Energy Co., Ltd.") is None)
check("carry_through: dòng thông số giữ thuật ngữ EN vẫn hợp lệ",
      carry_through("Default baud rate of RS-485 port: 9600bps",
                    "Tốc độ baud mặc định của cổng RS-485: 9600bps") is None)

# Ca thật 1.4.1: Flash dịch mục lục thành mục lục khác — số mục lệch.
check("digit_drift: mục lục bịa",
      digit_drift("3  Interface and Components...", "3.1 Dụng cụ...") is not None)
check("digit_drift: đổi dấu phân cách nghìn OK",
      digit_drift("Rated capacity 1,000 Wh", "Dung lượng định mức 1.000 Wh") is None)
check("digit_drift: số trong placeholder không tính",
      digit_drift("Charge: ⟦MEAS_1⟧~⟦MEAS_2⟧", "Sạc: ⟦MEAS_1⟧~⟦MEAS_2⟧") is None)
# 1.9.0: dấu chú thích phải dùng ký tự số mũ Unicode (engine vẽ một cỡ chữ cho cả region),
# nên chữ số dạng số mũ được quy về chữ số thường trước khi đếm. ¹²³ ở Latin-1, ⁴⁵⁶ ở U+2070.
for _mark, _sup in (("1", "¹"), ("2", "²"), ("3", "³"),
                    ("4", "⁴"), ("5", "⁵"), ("6", "⁶")):
    check(f"digit_drift: dấu chú thích {_sup} không bị báo thiếu",
          digit_drift(f"Energy Retention{_mark}", f"Mức duy trì điện năng{_sup}") is None)
check("digit_drift: quy số mũ vẫn bắt được lệch số thật",
      digit_drift("Retention3 of 70%", "Mức duy trì³ 90%") is not None)
# Ca thật audit Lite: câu cấm nối tiếp bị rơi hẳn khỏi target.
check("negation_drop: rơi câu forbidden",
      negation_drop("Batteries connected in series are forbidden, high voltage would lead to hazard shock.",
                    "Các khối pin kết nối song song...") is True)
check("negation_drop: VI giữ phủ định OK",
      negation_drop("Do not short-circuit the Li-ion battery.",
                    "Không làm ngắn mạch pin Li-ion.") is False)
check("negation_drop: 'No.' cột bảng không phải phủ định",
      negation_drop("No.", "STT") is False)
check("negation_drop: 'No.3492' địa chỉ không phải phủ định",
      negation_drop("No.3492 Jinqian Road, Fengxian District", "Số 3492 Đường Jinqian, Quận Fengxian") is False)
check("negation_drop: 'do not hesitate' dịch xuôi hợp lệ",
      negation_drop("please do not hesitate to contact us",
                    "vui lòng liên hệ với chúng tôi") is False)
check("negation_drop: 'no <noun>' là phủ định thật",
      negation_drop("no heat source, flammable or explosive materials",
                    "nguồn nhiệt, vật liệu dễ cháy nổ") is True)
check("negation_drop: n't nháy cong",
      negation_drop("the indicator doesn’t respond", "đèn báo phản hồi") is True)
check("symbol_drift: lật ≤ thành ≥",
      symbol_drift("Storage: T≤35°C", "Lưu trữ: T≥35°C") is not None)
check("symbol_drift: fullwidth ＜ quy về < OK",
      symbol_drift("⟦MEAS_1⟧＜T≤⟦MEAS_2⟧", "⟦MEAS_1⟧<T≤⟦MEAS_2⟧") is None)
check("symbol_drift: mất ±",
      symbol_drift("130±⟦MEAS_1⟧", "130 ⟦MEAS_1⟧") is not None)

# ── CONSISTENCY_ENTITY 1.8.4 (địa chỉ bưu chính không được dịch) ──
from validate_responses import address_entity_drift as _aed

_ADDR_SRC = "Factory Address：No. 3492 Jinqian Road, Fengxian District, 201406 Shanghai, "
check("entity: ca thật Lite p32 — địa chỉ bị dịch",
      _aed(_ADDR_SRC,
           "Địa chỉ nhà máy: Số 3492 Đường Jinqian, Quận Fengxian, 201406 Thượng Hải, ")
      == ["No", "Road", "District", "Shanghai"])
check("entity: bản dịch đạt — chỉ nhãn được dịch",
      _aed(_ADDR_SRC,
           "Địa chỉ nhà máy: No. 3492 Jinqian Road, Fengxian District, 201406 Shanghai, ")
      == [])
check("entity: tên quốc gia được dịch là hợp lệ",
      _aed("Factory Address：No. 3492 Jinqian Road, Fengxian District, Shanghai, China",
           "Địa chỉ nhà máy: No. 3492 Jinqian Road, Fengxian District, Shanghai, "
           "Trung Quốc") == [])
check("entity: viết tắt DST cũng là từ cấu trúc",
      _aed("Address: No. 3492 Jinqian Road, Fengxian DST, Shanghai",
           "Địa chỉ: No. 3492 Jinqian Road, Quận Fengxian, Thượng Hải")
      == ["DST", "Shanghai"])
check("entity: 'No.' cột bảng không phải địa chỉ",
      _aed("No.", "STT") == [])
check("entity: 'Set DIP Address' không phải địa chỉ",
      _aed("5.3.5   Set DIP Address", "5.3.5 Đặt địa chỉ DIP") == [])
check("entity: 'Sets protocol address' không phải địa chỉ",
      _aed("Sets protocol address for inverter communication.",
           "Đặt địa chỉ giao thức cho truyền thông biến tần.") == [])
check("entity: 'Floor mount bracket' không phải địa chỉ",
      _aed("Floor mount\nbracket", "Giá đỡ đặt\nsàn") == [])
check("entity: thành phố không kèm số nhà thì không soi",
      _aed("Shanghai PYTES Energy Co., Ltd.", "Công ty TNHH Shanghai PYTES Energy") == [])

# ── revoke path trong state machine ──
check("RELEASED -> REVOKED allowed", "REVOKED" in _ST["RELEASED"])
check("REVOKED -> TRANSLATED allowed (re-run)", "TRANSLATED" in _ST["REVOKED"])
check("RELEASED -> REJECTED still illegal", "REJECTED" not in _ST["RELEASED"])
check("REVOKED not directly releasable",
      "RELEASED" not in _ST["REVOKED"] and "HUMAN_APPROVED" not in _ST["REVOKED"])

check("auth dimension row not substantive",
      authenticity_check("150 × 200 × 300 mm", "150 × 200 × 300 mm") is None)
check("auth symbols not counted as words",
      authenticity_check("A × B ÷ C × D × E", "A × B ÷ C × D × E") is None)

check("auth url-dominant VI target OK",
      authenticity_check("visit our website at http://www.example-very-long-domain.com now",
                         "truy cập http://www.example-very-long-domain.com") is None)
check("auth email label OK",
      authenticity_check("Email: contact_support@example-corp.com please write",
                         "Email: contact_support@example-corp.com") is None)

check("auth truncated flagged",
      authenticity_check("One two three four five six seven eight nine ten eleven twelve thirteen fourteen.",
                         "Một hai ba.") == "truncated")
check("auth full translation not truncated",
      authenticity_check("Keep the battery away from water, dust and contamination at all times please.",
                         "Luôn giữ pin tránh xa nước, bụi bẩn và các chất gây ô nhiễm mọi lúc.") is None)
check("auth short source no truncation check",
      authenticity_check("Contact PYTES for support.", "Liên hệ PYTES.") is None)

# ── lg-basic-5: tách hàng bảng gõ liền bằng space (extract_group) ──
import pymupdf

from _common import vertical_rules
from extract_group import (build_lines, fragment_row, ink_bbox, split_multicol_rows,
                           trace_lines)
from fit_paint import painted_rect


def mkline(text: str, x0: float = 50.0, cw: float = 6.0, y0: float = 100.0) -> dict:
    """Line 1 span, mỗi ký tự rộng cw — đủ shape cho fragment_row/split_multicol_rows."""
    chars, x = [], x0
    for ch in text:
        chars.append({"c": ch, "origin": [x, y0 + 8], "bbox": [x, y0, x + cw, y0 + 10]})
        x += cw
    span = {"text": text, "origin": [x0, y0 + 8], "bbox": [x0, y0, x, y0 + 10],
            "size": 10.0, "flags": 0, "font": "Arial", "color": 0, "chars": chars}
    return {"bbox": [x0, y0, x, y0 + 10], "dir": (1.0, 0.0), "wmode": 0,
            "block": 0, "spans": [span]}


def texts(frags: list) -> list:
    return ["".join(s["text"] for s in f["spans"]) for f in frags]


# "Model" x50-80, khe x80-104, "V16 Lite" từ x104
row = mkline("Model    V16 Lite")
check("fragment_row cắt tại vạch trong khe", texts(fragment_row(row, [92.0])) == ["Model", "V16 Lite"],
      str(texts(fragment_row(row, [92.0]))))
check("fragment_row giữ space đơn trong ô", "V16 Lite" in texts(fragment_row(row, [92.0])))
check("fragment_row bỏ qua khe không có vạch", len(fragment_row(row, [300.0])) == 1)
check("fragment_row không cắt đoạn văn 2 space sau dấu chấm",
      len(fragment_row(mkline("Xong.  Bước kế tiếp là siết bu lông."), [])) == 1)
padded = fragment_row(mkline("  A   B  "), [77.0])
check("fragment_row cắt trắng hai đầu fragment", texts(padded) == ["A", "B"], str(texts(padded)))
lig = mkline("Model    V16")
lig["spans"][0]["chars"][0]["c"] = "fi"  # char nhiều ký tự → index lệch
check("fragment_row bỏ cắt khi char nhiều ký tự",
      len(fragment_row(lig, [92.0])) == 1 and fragment_row(lig, [92.0])[0] is lig)
# 1.8.0 — bản gốc V16 ngăn cột bằng MỘT space; số lượng space không phân biệt được
# ranh giới cột với khe từ thường, chỉ vạch kẻ trong khe mới nói lên điều đó.
# "8pcs" x50-74, khe đơn x74-80, "1408-M8" từ x80
single = mkline("8pcs 1408-M8")
check("fragment_row cắt tại khe MỘT space có vạch",
      texts(fragment_row(single, [77.0])) == ["8pcs", "1408-M8"], str(texts(fragment_row(single, [77.0]))))
check("fragment_row không cắt khe một space không có vạch",
      len(fragment_row(single, [200.0])) == 1)
prose = mkline("Dùng để lắp vào khe cắm phía trước")
check("fragment_row không xé văn xuôi trong ô có vạch ở xa",
      len(fragment_row(prose, [40.0, 300.0])) == 1, str(texts(fragment_row(prose, [40.0, 300.0]))))
# chữ được phép chờm lên vạch (V16 p11: "Recovery*" vượt vạch 0.45pt) → dung sai 1.5pt
check("fragment_row nhận vạch chờm trong dung sai",
      len(fragment_row(single, [73.0])) == 2, str(texts(fragment_row(single, [73.0]))))
check("fragment_row bỏ vạch ngoài dung sai",
      len(fragment_row(single, [72.0])) == 1, str(texts(fragment_row(single, [72.0]))))

TWO_COL = [{"bbox": [40, 90, 200, 200],
            "cells": [[40, 95, 100, 115], [100, 95, 200, 115]]}]
RULE_AT_ROW = [(100.0, 95.0, 115.0)]      # vạch cắt ngang dải y của dòng
iss: list = []
out = split_multicol_rows([mkline("Model    V16 Lite")], TWO_COL, RULE_AT_ROW, iss, 0)
check("split_multicol_rows tách hàng trong bảng", texts(out) == ["Model", "V16 Lite"], str(texts(out)))
check("split_multicol_rows báo TABLE_ROW_SPLIT",
      len(iss) == 1 and iss[0]["code"] == "TABLE_ROW_SPLIT", str(iss))
iss2: list = []
outside = [mkline("Model    V16 Lite", y0=300.0)]  # tâm ngoài bbox bảng
check("split_multicol_rows bỏ qua line ngoài bảng",
      texts(split_multicol_rows(outside, TWO_COL, RULE_AT_ROW, iss2, 0)) == ["Model    V16 Lite"]
      and not iss2)
# Ô gộp: lưới logic vẫn báo ranh giới cột, nét vẽ thì dừng trước hàng này.
merged_rule = [(100.0, 130.0, 190.0)]
check("split_multicol_rows không xé hàng ô gộp (vạch không cắt dải y)",
      texts(split_multicol_rows([mkline("Model    V16 Lite")], TWO_COL, merged_rule, [], 0))
      == ["Model    V16 Lite"])
lines_in = [mkline("Model    V16 Lite")]
check("split_multicol_rows no-op khi không có vạch",
      split_multicol_rows(lines_in, TWO_COL, [], [], 0) is lines_in)
check("split_multicol_rows no-op khi không có bảng",
      split_multicol_rows(lines_in, [], RULE_AT_ROW, [], 0) is lines_in)
# hai hàng đưa vào theo thứ tự y ngược — output phải sắp lại theo (y, x)
multi = split_multicol_rows([mkline("Bravo    Yoke", y0=140.0),
                             mkline("Alpha    Xray", y0=100.0)], TWO_COL,
                            [(100.0, 95.0, 155.0)], [], 0)
check("split_multicol_rows sort theo (y, x)",
      texts(multi) == ["Alpha", "Xray", "Bravo", "Yoke"], str(texts(multi)))

# ── ink_bbox: space đầu/đuôi không được thổi khung (1.8.0) ──
# Space đuôi có advance nhưng không vẽ gì; tính vào bbox thì container ô bảng phình
# qua vạch kẻ và dòng dịch được wrap theo bề rộng không có thật.
_pad = mkline("AB  ")
check("ink_bbox bỏ space đuôi", ink_bbox(_pad["spans"])[2] == 62.0,
      str(ink_bbox(_pad["spans"])))
check("ink_bbox bỏ space đầu", ink_bbox(mkline("  AB")["spans"])[0] == 62.0,
      str(ink_bbox(mkline("  AB")["spans"])))
check("ink_bbox line toàn khoảng trắng → None", ink_bbox(mkline("   ")["spans"]) is None)
_ink_doc = pymupdf.open()
_ink_page = _ink_doc.new_page(width=300, height=300)
_ink_page.insert_text(pymupdf.Point(50, 100), "AB   ", fontsize=10)
_ink_raw = _ink_page.get_text("rawdict")["blocks"][0]["lines"][0]["bbox"]
_ink_line = build_lines(_ink_page)[0][0]
check("build_lines lấy bbox theo mực, không theo advance của space đuôi",
      _ink_line["bbox"][2] < _ink_raw[2] - 1.0,
      f"line={_ink_line['bbox'][2]} raw={round(_ink_raw[2], 2)}")
_ink_doc.close()

# ── trace_lines: vớt chữ rawdict bỏ sót (extract_group) ──
# Ca thật Phocos Guide for V5 trang 2: đoạn "Plug in the battery end into the RS485 port…"
# in ra bình thường nhưng rawdict không trả về, texttrace thấy đủ. Không line → không
# region → stage 4 không dịch, mà G6 so pixel nguồn↔đích nên đoạn không dịch KHÔNG sinh
# diff: im lặng tuyệt đối. Đo trước khi vá trên 44 hướng dẫn ghép biến tần: 8 file, 4.760
# ký tự rơi kiểu này.
def _trace_span(text: str, x0: float = 50.0, y: float = 100.0, cw: float = 6.0,
                stype: int = 0, font: str = "ArialMT") -> dict:
    """Span kiểu get_texttrace(): char là tuple (ucs, gid, origin, bbox)."""
    chars, x = [], x0
    for ch in text:
        chars.append((ord(ch), 0, (x, y), (x, y - 8.0, x + cw, y + 2.0)))
        x += cw
    return {"chars": chars, "bbox": (x0, y - 8.0, x, y + 2.0), "dir": (1.0, 0.0),
            "wmode": 0, "font": font, "size": 12.0, "flags": 0,
            "color": (0.0, 0.0, 0.0), "type": stype, "seqno": 0}


class _FakeTracePage:
    def __init__(self, spans):
        self._spans = spans

    def get_texttrace(self):
        return self._spans


_recovered = trace_lines(_FakeTracePage([_trace_span("Plug in the battery end")]), "")
check("trace_lines vớt được dòng rawdict bỏ sót", len(_recovered) == 1,
      str(_recovered))
check("... và giữ nguyên văn bản",
      _recovered and "".join(s["text"] for s in _recovered[0]["spans"]) ==
      "Plug in the battery end")
# So khớp theo CHUỖI, không theo bbox: texttrace gộp span khác cách rawdict (một span của
# nó trải hai dòng) nên so tâm bbox báo thừa hàng loạt — thử trên các bản ĐÃ GIAO KHÁCH thì
# V16 Lite user manual bị báo 13.021 ký tự "mất" trong khi những câu đó đã dịch đủ.
check("trace_lines không nhân đôi chữ rawdict đã có",
      trace_lines(_FakeTracePage([_trace_span("Program the inverter")]),
                  "Programtheinverter") == [])
check("trace_lines bỏ qua chữ vô hình (lớp OCR, type 3)",
      trace_lines(_FakeTracePage([_trace_span("bong ma", stype=3)]), "") == [])
# texttrace trải một span qua hai dòng; giữ nguyên sẽ ra bbox cao bằng cả đoạn và region
# bị thổi. Cắt theo đường chân chữ mới đúng.
_two = trace_lines(_FakeTracePage(
    [{"chars": _trace_span("AB", y=100.0)["chars"] + _trace_span("CD", y=120.0)["chars"],
      "bbox": (50.0, 92.0, 62.0, 122.0), "dir": (1.0, 0.0), "wmode": 0, "font": "ArialMT",
      "size": 12.0, "flags": 0, "color": (0.0, 0.0, 0.0), "type": 0, "seqno": 0}]), "")
check("trace_lines cắt span trải hai dòng theo đường chân chữ", len(_two) == 2,
      str([l["bbox"] for l in _two]))
# Chỗ rawdict rơi ligature nó trả "BaƩery QuanƟty" còn texttrace trả "Battery Quantity":
# khác chuỗi nên lọt vòng so chuỗi, và nếu không chặn sẽ thêm line ĐÈ lên line cũ. Đếm
# theo ký tự nằm trong line rawdict, không theo diện tích khung — span texttrace trải
# ngang hai cột thì khoảng hở giữa cột kéo tỷ lệ diện tích xuống dưới ngưỡng.
_lig = _trace_span("Battery Quantity")
check("trace_lines không chồng lên line rawdict đã phủ quá nửa ký tự",
      trace_lines(_FakeTracePage([_lig]), "BaƩeryQuanƟty", [_lig["bbox"]]) == [])
check("... nhưng chỉ chớm mép thì vẫn vớt",
      len(trace_lines(_FakeTracePage([_lig]), "BaƩeryQuanƟty",
                      [(0.0, 0.0, 60.0, 200.0)])) == 1)


class _FakeTracePageBox(_FakeTracePage):
    rect = pymupdf.Rect(0, 0, 595, 842)


# Chữ ngoài khổ giấy không in ra; dịch nó chỉ đẻ region bbox âm. Ca thật: V5 Series manual
# trang 16 có 3 ghi chú ở x0 = -402.
check("trace_lines bỏ chữ nằm ngoài khổ giấy",
      trace_lines(_FakeTracePageBox([_trace_span("ngoai trang", x0=-402.0)]), "") == [])
check("... chữ trong khổ giấy vẫn vớt",
      len(trace_lines(_FakeTracePageBox([_trace_span("trong trang", x0=50.0)]), "")) == 1)

_issues_tr: list = []
trace_lines(_FakeTracePage([_trace_span("Plug in the battery end")]), "", None,
            _issues_tr, 3)
check("trace_lines báo issue để reviewer biết chỗ nào là chữ vớt",
      [i["code"] for i in _issues_tr] == ["TEXT_RECOVERED_BY_TRACE"], str(_issues_tr))

# ── painted_rect: hộp mực theo góc xoay (fit_paint) ──
LINE = {"y": 100.0, "x": 50.0, "width": 60.0,
        "segments": [{"x": 50.0, "width": 30.0}, {"x": 82.0, "width": 28.0}]}
check("painted_rect rot0 bám mép segment",
      painted_rect(LINE, {"size": 10.0, "rotation": 0}) == [50.0, 87.0, 110.0, 104.5],
      str(painted_rect(LINE, {"size": 10.0, "rotation": 0})))
check("painted_rect rot270 trải theo trục dọc",
      painted_rect(LINE, {"size": 10.0, "rotation": 270}) == [45.5, 95.5, 63.0, 164.5],
      str(painted_rect(LINE, {"size": 10.0, "rotation": 270})))
check("painted_rect rot90 trải lên trên",
      painted_rect(LINE, {"size": 10.0, "rotation": 90}) == [37.0, 35.5, 54.5, 104.5],
      str(painted_rect(LINE, {"size": 10.0, "rotation": 90})))
check("painted_rect rot180 lùi về trái",
      painted_rect(LINE, {"size": 10.0, "rotation": 180}) == [-10.0, 95.5, 50.0, 113.0],
      str(painted_rect(LINE, {"size": 10.0, "rotation": 180})))
_r270 = painted_rect(LINE, {"size": 10.0, "rotation": 270})
check("painted_rect xoay: cạnh dọc = width + 2×descent",
      round(_r270[3] - _r270[1], 2) == round(60.0 + 2 * 4.5, 2))
_narrow = dict(LINE, segments=[{"x": 50.0, "width": 1.0}])
check("painted_rect xoay không phụ thuộc segments",
      painted_rect(_narrow, {"size": 10.0, "rotation": 270}) == _r270)

# ── vertical_rules: chỉ nét kẻ dọc thật (qa_gates) ──
_doc = pymupdf.open()
_page = _doc.new_page(width=300, height=300)
_page.draw_line(pymupdf.Point(100, 50), pymupdf.Point(100, 200))    # vạch dọc
_page.draw_line(pymupdf.Point(20, 250), pymupdf.Point(280, 250))    # vạch ngang → bỏ
_page.draw_rect(pymupdf.Rect(150, 50, 250, 150))                    # khung viền → 2 cạnh
_page.draw_rect(pymupdf.Rect(80, 50, 81, 200), color=None, fill=(0, 0, 0))  # thanh mảnh
_xs = {round(x, 1) for x, _, _ in vertical_rules(_page)}
check("vertical_rules bắt đủ vạch dọc/khung/thanh mảnh",
      _xs == {80.5, 100.0, 150.0, 250.0}, str(sorted(_xs)))
_yspan = [(y0, y1) for x, y0, y1 in vertical_rules(_page) if round(x, 1) == 100.0]
check("vertical_rules giữ đúng đoạn y của vạch", _yspan == [(50.0, 200.0)], str(_yspan))
_blank = _doc.new_page(width=300, height=300)
check("vertical_rules trang trắng → rỗng", vertical_rules(_blank) == [])
_doc.close()

# ── dung sai container: fit_paint và qa_gates phải dùng CÙNG con số ──
import fit_paint as _fp
import qa_gates as _qg
import yaml as _yaml

from _common import (ASSETS_DIR, CONTAINER_TOL_PT_DEFAULT, CONTAINER_TOL_Y_EM_DEFAULT,
                     ENGINE_VERSION, LAYOUT_MODEL_VERSION)

check("tol descent chung fit_paint↔qa_gates",
      _fp.CONTAINER_TOL_Y_EM_DEFAULT == _qg.CONTAINER_TOL_Y_EM_DEFAULT == CONTAINER_TOL_Y_EM_DEFAULT)
_default_cfg = _yaml.safe_load(open(os.path.join(ASSETS_DIR, "engine_config_default.yaml"),
                                    encoding="utf-8"))
check("config default khớp hằng số",
      _default_cfg["qa"]["container_tol_pt"] == CONTAINER_TOL_PT_DEFAULT
      and _default_cfg["qa"]["container_tol_y_em"] == CONTAINER_TOL_Y_EM_DEFAULT,
      str(_default_cfg["qa"].get("container_tol_y_em")))

# version stamp: SKILL.md từng tụt lại 1.2.1 trong khi engine đã 1.3.0 — job ghi
# sai determinism tuple thì không reproduce được, nên khoá lại bằng test.
_skill = open(os.path.join(os.path.dirname(ASSETS_DIR), "SKILL.md"), encoding="utf-8").read()
_m = re.search(r'^\s*version:\s*"([^"]+)"', _skill, re.M)
check("SKILL.md version khớp ENGINE_VERSION",
      bool(_m) and _m.group(1) == ENGINE_VERSION, f"SKILL.md={_m.group(1) if _m else None}")
check("layout model version có dạng lg-basic-N",
      bool(re.fullmatch(r"lg-basic-\d+", LAYOUT_MODEL_VERSION)), LAYOUT_MODEL_VERSION)
check("config có cờ layout.expand_heading",
      _default_cfg.get("layout", {}).get("expand_heading") is True)

# ── nới khung heading (1.5.2) ───────────────────────────────────────────
# Khung lấy theo bbox chữ NGUỒN; tiếng Việt dài hơn nên heading vừa khít ở bản gốc thành
# FIT_IMPOSSIBLE dù quanh nó là khoảng trắng. Ca thật: tựa bìa 196.6pt, "Hướng dẫn sử dụng"
# cần 250pt. Nới ngang là phép duy nhất khả thi — khung cao 33.7pt không chứa nổi 2 dòng
# cỡ 25.1pt (cần 57.7pt).
_PAGE = [0.0, 0.0, 420.9, 595.3]
_MARGINS = (37.9, 388.4)


def _heading(bbox, container, rtype="heading", src="User Manual"):
    return {"page": 0, "region_type": rtype, "source_text": src, "bbox": list(bbox),
            "container": list(container), "rotation": 0,
            "lines": [{"spans": [{"origin": [bbox[0], bbox[3]]}]}]}


# Tựa bìa: tâm chữ 209.45 ≈ tâm trang 210.45 → nới đối xứng VÀ đổi sang căn giữa, vì text
# căn trái vẽ từ base_x nên nới suông sẽ đẩy chữ lệch phải khỏi bố cục gốc.
_cover = _heading((131.6, 126.7, 287.3, 153.1), (131.6, 126.7, 328.3, 160.4))
_got = _fp.expand_container(_cover, 250.2, [], _PAGE, _MARGINS, "left")
check("nới tựa bìa căn giữa", _got is not None and _got[1] == "center", str(_got))
if _got:
    _c, _ = _got
    check("khung nới đủ rộng cho bản dịch", _c[2] - _c[0] >= 250.2, f"{_c[2]-_c[0]:.1f}pt")
    check("khung nới giữ tâm trang",
          abs((_c[0] + _c[2]) / 2 - 210.45) < 0.6, f"tâm={(_c[0]+_c[2])/2:.2f}")
    check("khung nới nằm trong lề thân bài", _c[0] >= 37.9 and _c[2] <= 388.4, str(_c))

# Vật cản trong cùng dải dọc chặn việc nới — luật phải có răng, không nới bừa vào chỗ có chữ.
_blocked = _fp.expand_container(
    _cover, 250.2, [[300.0, 120.0, 360.0, 160.0]], _PAGE, _MARGINS, "left")
check("vật cản cùng dải chặn nới", _blocked is None, str(_blocked))

# Heading căn trái (không ở tâm trang) chỉ nới sang phải và GIỮ alignment.
_left = _heading((37.9, 159.4, 123.4, 175.2), (37.9, 159.4, 146.2, 177.3),
                 rtype="list_item", src="2.2 Packing List")
_gl = _fp.expand_container(_left, 126.4, [], _PAGE, _MARGINS, "left")
check("heading căn trái nới phải, không đổi align",
      _gl is not None and _gl[1] is None and _gl[0][0] == 37.9, str(_gl))

# Không nới khi đã đủ chỗ — tránh đụng vào region đang chạy tốt.
check("đủ chỗ thì không nới",
      _fp.expand_container(_cover, 100.0, [], _PAGE, _MARGINS, "left") is None)

check("tiêu đề đánh số bị xếp nhầm list_item vẫn đủ điều kiện nới",
      _fp.expandable_region(_left))
check("đoạn văn dài không được nới",
      not _fp.expandable_region(_heading(
          (40, 100, 300, 112), (40, 100, 320, 114), rtype="paragraph",
          src="Thank you for purchasing our Pytes V16 Lite LFP Battery for home use")))
# Nhãn ngắn cạnh hình bị extract xếp thành `paragraph` — ca thật `Dry Contact` ở Lite p13,
# "Tiếp điểm khô" tụt còn 85% cỡ chữ dù bên phải là khoảng trắng.
check("nhãn ngắn xếp nhầm paragraph vẫn được nới",
      _fp.expandable_region(_heading((82.6, 316.5, 124.6, 327.4), (82.6, 316.5, 126.6, 331.6),
                                     rtype="paragraph", src="Dry Contact")))
check("nhãn hình được nới",
      _fp.expandable_region(_heading((85.8, 365.2, 124.6, 376.0), (85.8, 365.2, 126.6, 376.3),
                                     rtype="figure_caption", src="DIP Switch")))
# Text căn phải neo vào mép phải khung: nới sang phải sẽ đẩy chữ đi, phải nới sang TRÁI.
_r = _heading((200.0, 100.0, 260.0, 112.0), (200.0, 100.0, 262.0, 114.0),
              rtype="figure_caption", src="Battery side")
_gr = _fp.expand_container(_r, 100.0, [], _PAGE, _MARGINS, "right")
check("nhãn căn phải nới sang trái, giữ mép phải",
      _gr is not None and abs(_gr[0][2] - 262.0) < 0.01 and _gr[0][0] < 200.0, str(_gr))

# ── dải nền sau tiêu đề mục — 1.9.41 ────────────────────────────────────
# Ca thật: tiêu đề `BOM LIST` trên dải vàng của 15 hướng dẫn ghép biến tần. Ô chữ 98.3pt,
# `DANH MỤC VẬT TƯ` cần 153.1pt, mà dải vàng rộng 432pt đang nằm ngay SAU chữ đó. Dải được
# xuất thành 48 ô rời rộng 8pt: ba ô dưới chữ, 45 ô bên phải. Xét từng ô thì ô dưới chữ
# chặn đứng phép nới còn ô bên phải kẹp mép phải về sát chữ.
_bom = _heading((81.4, 88.6, 157.7, 111.4), (81.4, 88.6, 179.7, 121.4), src="BOM LIST")
_tiles = [[81.4 + 8.0 * i, 90.4, 81.4 + 8.0 * (i + 1), 108.8] for i in range(54)]
_gbom = _fp.expand_container(_bom, 153.1, _tiles, _PAGE, _MARGINS, "left")
check("tiêu đề trên dải nền ghép từ ô rời vẫn nới được",
      _gbom is not None and _gbom[0][2] - _gbom[0][0] >= 153.1, str(_gbom))
check("nới không tràn khỏi dải nền",
      _gbom is not None and _gbom[0][2] <= 81.4 + 54 * 8.0 + 0.01, str(_gbom))

# Mutation: bỏ phép ghép mảnh (mỗi ô xét riêng) thì phải hỏng lại — chỉ ô rộng đúng bằng cả
# dải mới cứu được. Đây là thứ phân biệt bản vá thật với bản vá chỉ nới thêm bừa.
check("một ô rời không tự nó là dải nền của vùng",
      _fp.backdrop_band(_bom["bbox"], [_tiles[0]], []) is None)
check("ghép đủ mảnh mới thành dải bao được chữ",
      _fp.backdrop_band(_bom["bbox"], _tiles, []) is not None)

# Khe rộng hơn `BACKDROP_TILE_GAP_PT` cắt dải làm đôi → nửa trái không bao hết chữ nữa.
_split = [t for t in _tiles if t[0] < 129.4] + [[t[0] + 6.0, t[1], t[2] + 6.0, t[3]]
                                                for t in _tiles if t[0] >= 129.4]
check("khe lớn cắt dải, không còn bao được chữ",
      _fp.backdrop_band(_bom["bbox"], _split, []) is None)

# Nét kẻ ngang mảnh cắt ngang chữ KHÔNG phải nền — phủ dọc quá thấp, vẫn chặn như cũ.
_rule = [[70.0, 99.6, 300.0, 100.2]]
check("nét kẻ mảnh cắt qua chữ vẫn chặn nới",
      _fp.backdrop_band(_bom["bbox"], _rule, []) is None
      and _fp.expand_container(_bom, 153.1, _rule, _PAGE, _MARGINS, "left") is None)

# Chữ của region khác nằm cùng dải dọc KHÔNG được tính là nền, dù trải rộng: nới đè lên nó
# là chồng chữ. `share_gap` giữ đúng object đó.
_neighbour = [70.0, 88.0, 300.0, 112.0]
check("bbox chữ hàng xóm không bao giờ là nền",
      _fp.backdrop_band(_bom["bbox"], [_neighbour], [_neighbour]) is None)

# Chữ hàng xóm ĐỨNG CẠNH vẫn chặn đúng mép giữa khe, kể cả khi có dải nền chạy qua cả hai.
_side = [200.0, 88.6, 260.0, 111.4]
_gside = _fp.expand_container(_bom, 153.1, _tiles + [_side], _PAGE, _MARGINS, "left",
                              share_gap=[_side])
check("có dải nền vẫn không lấn qua chữ hàng xóm",
      _gside is None or _gside[0][2] <= (157.7 + 200.0) / 2 + 0.01, str(_gside))

# ── context graph 1.6.0 ─────────────────────────────────────────────────
import build_context_graph as _cg

def _reg(rid, page, rtype, text, bbox, nlines=1, size=9.0, ri=0):
    return {"region_id": rid, "page": page, "region_type": rtype, "source_text": text,
            "bbox": list(bbox), "reading_index": ri, "translation_action": "translate",
            "runs": [{"size": size}], "lines": [{}] * nlines}


# Câu bị xé theo dòng PDF phải nối lại được — gốc của cả stage này.
_a = _reg("a", 1, "paragraph", "We strongly recommend that you carefully read this manual before", (40, 100, 414, 112))
_b = _reg("b", 1, "paragraph", "installing the Product and follow the instructions carefully.", (40, 114.7, 414, 126.7), ri=1)
check("nối được câu xé theo dòng", _cg.flow_link(_a, _b, 12.0) is not None)

# Tiêu đề đánh số bị extract xếp thành list_item — không được nuốt đoạn văn theo sau.
# Không có guard này thì 9/10 chuỗi ngoài trang thư ngỏ là nối sai (đo trên V16 manual).
_h = _reg("h", 15, "list_item", "5.1.1  Safety Requirements", (40, 100, 200, 112))
_body = _reg("bd", 15, "paragraph", "Only those who have been trained in the power system", (40, 114, 414, 126), ri=1)
check("tiêu đề đánh số không nuốt thân bài", _cg.flow_link(_h, _body, 12.0) is None)

_toc = _reg("t", 5, "list_item", "2.2  Packing List...................... 9", (40, 100, 380, 112))
check("dòng mục lục không nối", _cg.flow_link(_toc, _body, 12.0) is None)

_tab = _reg("tb", 23, "paragraph", "Table 6-2 RS485 and CAN Connector Pin Assignments", (40, 114, 380, 126), ri=1)
check("Table N mở khối mới, không nối", _cg.flow_link(_a, _tab, 12.0) is None)

# Chuỗi địa chỉ từng nuốt luôn hai dòng Website/Email nằm dưới.
_addr = _reg("ad", 1, "paragraph", "Factory Address：No. 3492 Jinqian Road, Fengxian District, Shanghai,", (40, 100, 380, 112))
_web = _reg("w", 1, "paragraph", "Website: http://www.pytesgroup.com", (40, 114, 380, 126), ri=1)
check("dòng 'Nhãn: giá trị' không nối", _cg.flow_link(_addr, _web, 12.0) is None)

_short = _reg("s1", 13, "paragraph", "Dry Contact", (40, 100, 90, 112))
_short2 = _reg("s2", 13, "paragraph", "LINK 1 Port", (40, 114, 90, 126), ri=1)
check("nhãn ngắn không thành chuỗi văn xuôi", _cg.flow_link(_short, _short2, 12.0) is None)

# Cụm nhãn nhiều dòng cạnh hình = MỘT đơn vị dịch. Ca thật Lite p19, khe đo được 0.33pt
# trên dòng cao 9.56pt (tỉ lệ 0.035).
_l1 = _reg("l1", 19, "figure_caption", "Battery side", (174, 359, 210, 368.6))
_l2 = _reg("l2", 19, "figure_caption", "wall-mounted bracket", (144, 368.9, 210, 378.5), ri=1)
check("cụm nhãn 2 dòng được nối", _cg.label_stack_link(_l1, _l2) is not None)

# Hai nhãn RỜI xếp chồng thì không. Ca thật V16 p13: khe 2.83pt/dòng 9.40pt (tỉ lệ 0.301)
# và 1.88pt/10.85pt (0.173) — ngưỡng 0.12 tách bạch khỏi 0.035 của cụm thật.
_n1 = _reg("n1", 13, "figure_caption", "Negative Power\nTerminal", (100, 300, 156, 318.8), nlines=2)
_n2 = _reg("n2", 13, "figure_caption", "Positive Power\nTerminal", (100, 321.6, 153, 340.4), nlines=2, ri=1)
check("hai nhãn rời xếp chồng KHÔNG nối", _cg.label_stack_link(_n1, _n2) is None)

check("nhận diện tiêu đề đánh số", _cg.is_heading_like("5.3.2  Connect Power Cable")
      and not _cg.is_heading_like("Only qualified personnel"))
check("soft_end phân biệt câu kết và câu lửng",
      _cg.soft_end("developed and produced") and not _cg.soft_end("energy storage systems."))

# ── gộp dòng thành đoạn, lg-basic-4 (G3) ────────────────────────────────
from extract_group import merge_flow_regions as _merge
from _common import layout_model_for as _lmf

def _line(x0, y0, x1, y1, text, size=9.0):
    return {"bbox": [x0, y0, x1, y1], "dir": (1.0, 0.0), "wmode": 0, "block": 0,
            "spans": [{"text": text, "origin": [x0, y1], "bbox": [x0, y0, x1, y1],
                       "size": size, "flags": 0, "font": "Noto", "color": 0, "chars": []}]}


def _para(y0, text, x0=40.0, x1=414.0, rtype="paragraph"):
    from extract_group import make_region
    r = make_region(1, rtype, [_line(x0, y0, x1, y0 + 12, text)], 0.9)
    return r


# Thư ngỏ V16: mỗi dòng một block rawdict nên group_block_lines không thấy nhau; khe thật
# 2.72pt. Gộp lại thì fitter mới được wrap tự do và tiếng Việt mới đảo vế được.
_l1 = _para(100.0, "We strongly recommend that you carefully read this manual before")
_l2 = _para(114.72, "installing the Product and follow the instructions carefully.")
_out = _merge([_l1, _l2], 12.0, 1)
check("gộp hai dòng cùng đoạn", len(_out) == 1 and _out[0].get("merged_lines") == 2)
check("đoạn gộp giữ đủ chữ của cả hai dòng",
      _out and "carefully read this manual" in _out[0]["source_text"]
      and "follow the instructions" in _out[0]["source_text"])

# Guard của graph phải áp nguyên vào merge — nếu không, 9/10 lần gộp ngoài trang thư ngỏ
# là gộp sai (đo trên V16 user manual).
_head = _para(100.0, "5.1.1  Safety Requirements", x1=200.0, rtype="list_item")
_body = _para(114.72, "Only those who have been trained in the power system may install")
check("không gộp tiêu đề đánh số vào thân bài", len(_merge([_head, _body], 12.0, 1)) == 2)

_addr = _para(100.0, "Factory Address: No. 3492 Jinqian Road, Fengxian District, Shanghai,")
_web = _para(114.72, "Website: http://www.pytesgroup.com")
check("không gộp dòng 'Nhãn: giá trị'", len(_merge([_addr, _web], 12.0, 1)) == 2)

_far = _para(140.0, "installing the Product and follow the instructions carefully.")
check("khe dọc quá lớn thì không gộp", len(_merge([_l1, _far], 12.0, 1)) == 2)

_indent = _para(114.72, "installing the Product and follow the instructions.", x0=90.0)
check("lệch mép trái thì không gộp", len(_merge([_l1, _indent], 12.0, 1)) == 2)

check("layout model theo cờ merge_paragraph",
      _lmf({"layout": {"merge_paragraph": True}}) == "lg-basic-6"
      and _lmf({"layout": {"merge_paragraph": False}}) == "lg-basic-5")

# ── chốt chống lệch bản phát hành (1.7.2) ───────────────────────────────
# approve.py COPY render/draft.pdf sang output/. Chạy lại fit_paint sau đó làm draft đổi mà
# file trong output/ giữ nguyên → job ghi RELEASED nhưng bản "approved" là bản cũ. Sự cố thật
# 2026-08-06: bản phát hành thiếu đúng ba sửa đổi vừa yêu cầu.
from _common import refuse_if_released as _rir


class _FakeJob:
    def __init__(self, st): self._st = st
    def status(self): return self._st


_blocked = False
try:
    _rir(_FakeJob("RELEASED"), "fit_paint")
except Exception as e:
    _blocked = isinstance(e, _BE) and "RELEASED" in str(e)
check("RELEASED thì chặn stage render/QA", _blocked)

# ── chốt phát hành không được fail-open (1.8.2) ─────────────────────────
# `Job.p()` chỉ ghép đường dẫn. Job chưa từng phát hành thì `output/` chưa tồn tại và
# copyfile ném FileNotFoundError — 2026-08-06 hai job Lite đổ ở đúng chỗ này SAU khi đã
# lật trạng thái sang RELEASED, tức job "đã phát hành" mà không có file nào.
import tempfile as _tf

from approve import stage_release_copy as _src

with _tf.TemporaryDirectory() as _d:
    _draft = os.path.join(_d, "render", "draft.pdf")
    os.makedirs(os.path.dirname(_draft))
    open(_draft, "wb").write(b"%PDF-1.7 fake")
    _out = os.path.join(_d, "output", "translated-approved.pdf")   # output/ CHƯA tồn tại
    _tmp = _src(_draft, _out)
    check("stage_release_copy tự tạo thư mục output/ còn thiếu", os.path.isdir(
        os.path.dirname(_out)))
    check("stage_release_copy ghi ra tên tạm, chưa chiếm tên chính thức",
          os.path.exists(_tmp) and _tmp != _out and not os.path.exists(_out), _tmp)
    check("stage_release_copy giữ nguyên nội dung draft",
          open(_tmp, "rb").read() == b"%PDF-1.7 fake")
    os.replace(_tmp, _out)
    check("đổi tên nguyên tử cho ra đúng tên chính thức",
          os.path.exists(_out) and not os.path.exists(_tmp))

# ── determinism: engine_version phải theo kịp stage cuối (1.8.3) ────────
# Trước 1.8.3 chỉ extract_group làm mới con dấu, nên job chạy tiếp fit_paint/qa/approve
# bằng engine mới hơn vẫn khai engine của lần extract cuối — ai tái lập sẽ dùng nhầm bản.
import yaml as _y

from _common import ENGINE_VERSION as _EV, Job as _Job

with _tf.TemporaryDirectory() as _d:
    os.makedirs(os.path.join(_d, "input"))
    _y.safe_dump({"determinism": {"engine_version": "0.1.0",
                                  "layout_model_version": "lg-basic-1"}},
                 open(os.path.join(_d, "input", "job.yaml"), "w"))
    _j = _Job(_d)
    _j.mark_stage("qa")
    _meta = _j.load()
    check("mark_stage làm mới engine_version của mọi stage",
          _meta["determinism"]["engine_version"] == _EV,
          _meta["determinism"]["engine_version"])
    check("mark_stage không đụng layout_model_version",
          _meta["determinism"]["layout_model_version"] == "lg-basic-1")
    check("mark_stage vẫn ghi đúng bản ghi stage",
          _meta["stages"]["qa"]["state"] == "done" and _meta["stages"]["qa"]["ts"])
for _st in ("NEEDS_REVIEW", "TRANSLATED", "RENDERED", "REVOKED", "AUTO_QA_PASS"):
    _ok = True
    try:
        _rir(_FakeJob(_st), "qa")
    except Exception:
        _ok = False
    check(f"status {_st} vẫn chạy được", _ok)

# Thu hồi tồn tại để sửa lỗi bản đã phát hành, kể cả lỗi LAYOUT — mà sửa layout thì phải
# re-run từ stage 2. Trước 1.8.0 chỉ validate nhận REVOKED nên thu hồi xong là bế tắc.
from _common import RERUNNABLE_STATUSES as _RS

check("REVOKED chạy lại được stage 2/3/5", "REVOKED" in _RS, str(_RS))
check("mọi status re-run được đều đi tới TRANSLATED",
      all("TRANSLATED" in STATUS_TRANSITIONS[s] for s in _RS),
      str({s: sorted(STATUS_TRANSITIONS[s]) for s in _RS}))
_src = {n: open(os.path.join(os.path.dirname(os.path.abspath(__file__)), n),
                encoding="utf-8").read()
        for n in ("extract_group.py", "translate_prep.py", "validate_responses.py")}
check("ba stage đọc chung RERUNNABLE_STATUSES, không hardcode",
      all("RERUNNABLE_STATUSES" in s and '"NEEDS_REVIEW")' not in s for s in _src.values()),
      str([n for n, s in _src.items() if "RERUNNABLE_STATUSES" not in s]))
# Chốt phải nằm ở CỔNG VÀO, không phải chỉ dùng để quyết định chuyển trạng thái cuối hàm.
# `validate_responses` từng chỉ có vế sau nên ghi được vào job đã phát hành (2026-08-07).
_GATE = "if job.status() not in RERUNNABLE_STATUSES:"
check("cả ba stage chặn ngay ở cổng vào, không chỉ ở bước chuyển trạng thái",
      all(_GATE in s for s in _src.values()),
      str([n for n, s in _src.items() if _GATE not in s]))

# Hướng dự phòng: nhãn hình có đường chỉ dẫn chắn ngay bên phải thì nới sang TRÁI và neo
# mép phải, giữ nguyên điểm nối của đường chỉ dẫn. Ca thật Lite p13: vật cản ở x=129.5,
# nhãn kết thúc ở 124.6 — chỉ còn 5pt bên phải, trong khi bên trái còn tới lề 37.9.
_lbl = _heading((82.6, 316.5, 124.6, 327.4), (82.6, 316.5, 126.6, 331.6),
                rtype="paragraph", src="Dry Contact")
_blk = [[129.5, 322.3, 192.1, 391.0]]
_gb = _fp.expand_container(_lbl, 53.2, _blk, _PAGE, _MARGINS, "left")
check("bị chắn bên phải thì nới sang trái", _gb is not None and _gb[1] == "right", str(_gb))
if _gb:
    check("nới trái vẫn neo đúng mép phải cũ", abs(_gb[0][2] - 126.6) < 0.01, str(_gb[0]))
    check("nới trái không vượt lề", _gb[0][0] >= 37.9, str(_gb[0]))
# Chắn cả hai bên → không nới, chữ co lại như cũ.
check("chắn cả hai bên thì không nới",
      _fp.expand_container(_lbl, 53.2, _blk + [[40.0, 316.0, 80.0, 330.0]],
                           _PAGE, _MARGINS, "left") is None)

# ── hai nhãn cạnh nhau cùng nới thì phải chia đôi khe, không được đè (1.9.30) ──
# Ca thật: dải nhãn hình dưới một hàng ảnh. Xét RIÊNG từng nhãn thì cả
# hai đều "tôn trọng vật cản" theo bbox NGUỒN của hàng xóm — nhưng hàng xóm cũng nới, nên
# cộng lại thành đè 1.60pt. Nhãn giữa bị kẹp cả hai bên nên nó nới sang TRÁI, đúng hướng
# đã gây lỗi.
_CAP_MARGINS = (27.8, 330.3)
_capA = _heading((36.3, 167.9, 90.4, 177.4), (36.3, 167.9, 90.4, 177.4),
                 rtype="figure_caption", src="Caption One")
_capB = _heading((112.4, 168.0, 145.1, 177.4), (112.4, 168.0, 145.1, 177.4),
                 rtype="figure_caption", src="Caption Two")
_capC = _heading((158.0, 168.0, 196.9, 177.4), (158.0, 168.0, 196.9, 177.4),
                 rtype="figure_caption", src="Caption Three")
_caps = [_capA["bbox"], _capB["bbox"], _capC["bbox"]]

_gA = _fp.expand_container(_capA, 71.7, [_capB["bbox"], _capC["bbox"]],
                           _PAGE, _CAP_MARGINS, "left", _caps)
_gB = _fp.expand_container(_capB, 50.0, [_capA["bbox"], _capC["bbox"]],
                           _PAGE, _CAP_MARGINS, "left", _caps)
# Không nới được thì vùng vẽ vẫn là bbox nguồn — so mép thực tế, không so riêng kết quả nới.
_edgeA = _gA[0][2] if _gA else _capA["bbox"][2]
_edgeB = _gB[0][0] if _gB else _capB["bbox"][0]
check("hai nhãn cạnh nhau cùng nới thì không đè lên nhau",
      _edgeB - _edgeA >= 2 * _fp.SIBLING_GAP_PT - 0.01,
      f"mép phải A={_edgeA:.2f} mép trái B={_edgeB:.2f} khe={_edgeB - _edgeA:.2f}pt")
_mid = (90.4 + 112.4) / 2
check("không nhãn nào lấn quá giữa khe",
      _edgeA <= _mid + 0.01 and _edgeB >= _mid - 0.01,
      f"giữa khe={_mid:.2f} A={_edgeA:.2f} B={_edgeB:.2f}")

# Vật cản KHÔNG tự nới được (hình, vector, nét kẻ) vẫn phải chặn tới đúng mép của nó —
# chia đôi khe với một tấm ảnh nghĩa là vẽ đè lên ảnh.
_gFixed = _fp.expand_container(_capB, 50.0, [_capA["bbox"], _capC["bbox"]],
                               _PAGE, _CAP_MARGINS, "left")
check("vật cản cố định vẫn chặn tới mép",
      _gFixed is None or _gFixed[0][0] >= 90.4 - 0.01, str(_gFixed))

# ── hàng xóm DÍNH SÁT mép trái không được chặn đường nới sang PHẢI (1.9.39) ──
# Nguồn hay xé một tiêu đề làm hai text object GIỮA TỪ (`3.6.4. PCS vie` + `w`,
# `Chapter 2 System Introductio` + `n`). Khe giữa hai mảnh bằng 0, nên luật chia đôi khe cho
# `left_lim = c[0] + SIBLING_GAP_PT` — lớn hơn chính mép trái của mảnh sau. Mọi phương án
# nới đều trượt và mảnh sau bị ép thu cỡ chữ, dù bên phải nó trống tới tận lề.
_adjA = _heading((56.6, 391.1, 135.8, 408.3), (56.6, 391.1, 135.8, 413.3),
                 rtype="list_item", src="3.6.4. PCS vie")
_adjB = _heading((135.8, 391.1, 145.4, 408.3), (135.8, 391.1, 167.4, 413.3),
                 rtype="paragraph", src="w")
_adj = [_adjA["bbox"], _adjB["bbox"]]
_gAdj = _fp.expand_container(_adjB, 41.3, [_adjA["bbox"]], _PAGE,
                             (56.6, 538.5), "left", _adj)
check("mảnh sau dính sát mảnh trước vẫn nới được sang phải", _gAdj is not None, str(_gAdj))
check("... và mép TRÁI của nó không nhúc nhích",
      _gAdj is not None and abs(_gAdj[0][0] - 135.8) < 0.01, str(_gAdj))
check("... nới đủ bề ngang cần", _gAdj is not None and _gAdj[0][2] - _gAdj[0][0] >= 41.3,
      str(_gAdj))
# Chiều ngược lại vẫn phải bị chặn: mảnh sau KHÔNG được lấn ngược sang chỗ mảnh trước.
_gBack = _fp.expand_container(_adjB, 41.3, [_adjA["bbox"]], _PAGE,
                              (56.6, 145.4), "left", _adj)
check("hết chỗ bên phải thì không được lùi sang trái đè hàng xóm",
      _gBack is None or _gBack[0][0] >= 135.8 - 0.01, str(_gBack))

# ── nhận khung nới khi nó bớt DÒNG chứ không chỉ khi tăng cỡ chữ (1.9.14) ──
# Ca thật V5 p17: `7.1 Unable to start` → `7.1 Không khởi động được` cần 157.0pt trong khung
# 132.0pt. Bản dự phòng hai dòng đã ở cỡ đầy nên cỡ chữ không thể lên nữa; điều kiện cũ
# `got_s > keep_s` luôn sai và khung nới tính đúng rồi vẫn bị vứt đi.
_V5_MARGINS = (24.78, 398.99)   # lề thân bài đo trên chính job V5 Series
_h71 = {"page": 16, "region_type": "heading", "rotation": 0, "alignment": "left",
        "source_text": "7.1 Unable to start",
        "bbox": [27.78, 38.3, 131.81, 55.48], "container": [27.78, 38.3, 159.82, 63.12],
        "lines": [{"bbox": [27.78, 38.3, 131.81, 55.48],
                   "spans": [{"origin": [27.78, 50.97], "text": "7.1 Unable to start",
                              "size": 12.0}]}],
        "runs": [{"text": "7.1 Unable to start", "bold": True, "italic": False,
                  "serif": False, "mono": False, "size": 12.0, "color": 0,
                  "font": "Arial-BoldMT", "role": "body"}],
        "target_runs": [{"role": "body", "text": "7.1 Không khởi động được"}]}
_fr71, _fi71 = _fp.fit_region(dict(_h71), _fp.FontPack(), _default_cfg,
                              {"obstacles": [], "page_rect": _PAGE, "margins": _V5_MARGINS})
check("nới khung: tiêu đề một dòng bị bẻ đôi được nới, giữ nguyên một dòng",
      _fr71 is not None and len(_fr71["lines"]) == 1,
      str(_fr71 and len(_fr71["lines"])))
check("nới khung: bớt dòng ở cùng cỡ chữ vẫn tính là tốt hơn",
      _fr71 is not None and abs(_fr71["size"] - 12.0) < 0.01
      and any(c == "CONTAINER_EXPANDED" for c, _, _ in _fi71),
      str([c for c, _, _ in _fi71]))
# Không có chỗ nới (vật cản sát bên phải) thì vẫn bẻ đôi như cũ — luật phải có răng.
_fr71b, _ = _fp.fit_region(dict(_h71), _fp.FontPack(), _default_cfg,
                           {"obstacles": [[132.0, 30.0, 300.0, 60.0]],
                            "page_rect": _PAGE, "margins": _V5_MARGINS})
check("nới khung: bị chắn thì không nới, vẫn xuống dòng",
      _fr71b is not None and len(_fr71b["lines"]) == 2, str(_fr71b and len(_fr71b["lines"])))

# Vật cản của region đã xử lý không được biến mất khỏi danh sách dùng chung: lọc tại chỗ thì
# region cuối trang thấy trang gần như trống và nới khung đè lên chữ hàng xóm.
_fpsrc = open(os.path.join(os.path.dirname(ASSETS_DIR), "scripts", "fit_paint.py"),
              encoding="utf-8").read()
check("nới khung: lọc vật cản ra bản sao, không ghi đè danh sách dùng chung",
      'expand_ctx["obstacles"] =' not in _fpsrc)

# ── dòng mục lục tách tiêu đề / số trang (1.9.13) ───────────────────────
# Dòng mục lục là hai cột nằm trong một region; tokenize bỏ khe space nên cụm co lại rồi bị
# căn giữa/phải, đè lên nét gạch dẫn.
def _toc_reg(lines, runs, rtype="paragraph"):
    return {"region_type": rtype, "rotation": 0, "container": [45.7, 152.5, 414.9, 169.7],
            "source_text": "x", "lines": lines, "target_runs": runs}


_two = [{"bbox": [45.7, 152.5, 232.7, 168.2],
         "spans": [{"origin": [45.7, 164.1], "text": "2 Interface ", "size": 11.0}]},
        {"bbox": [374.5, 152.7, 380.6, 167.7],
         "spans": [{"origin": [374.5, 164.1], "text": "  9", "size": 11.0}]}]
_subs = _fp.leader_split(_toc_reg(_two, [{"role": "emphasis", "text": "Tiêu đề"},
                                         {"role": "body", "text": "\n9"}]), _fp.FontPack())
check("mục lục: hai line cùng y = hai cột, tách được",
      _subs is not None and len(_subs) == 2, str(_subs is None))
check("mục lục: cột số trang căn phải đúng mép nguồn",
      _subs and _subs[1]["alignment"] == "right"
      and abs(_subs[1]["container"][2] - 380.6) < 0.01)
check("mục lục: ghép run bằng '' — target hai run vẫn ra đúng hai cột",
      _subs and _subs[0]["target_runs"][0]["text"] == "Tiêu đề"
      and _subs[1]["target_runs"][0]["text"] == "9")
check("mục lục: đuôi không phải số trang thì không tách",
      _fp.leader_split(_toc_reg(
          [_two[0], {"bbox": [374.5, 152.7, 380.6, 167.7],
                     "spans": [{"origin": [374.5, 164.1], "text": " xyz", "size": 11.0}]}],
          [{"role": "body", "text": "a\nb"}]), _fp.FontPack()) is None)
# ── gạch dẫn mục lục gõ bằng DẤU CHẤM (1.9.22) ─────────────────────────
# HV48100 gõ gạch dẫn bằng ký tự `.` ngay trong text (85 chấm/dòng) chứ không vẽ line-art như
# V5, nên `leader_run` không thấy gì. Model giữ nguyên xấp xỉ số chấm cũ trong khi tiêu đề
# tiếng Việt dài ngắn khác → cột số trang răng cưa: biên độ mép phải 1.8pt → 23.3pt.
def _dot_reg(target, nlines=1):
    return {"lines": [{"bbox": [39.7, 123.7, 374.8, 137.4],
                       "spans": [{"origin": [39.7, 133.9]}]}] * nlines,
            "target_runs": [{"role": "body", "text": target}], "placeholders": {}}


_dr1 = _dot_reg("1 Thông tin an toàn ..................... 5")
_tk1 = _fp.tokenize(_dr1)
check("gạch dẫn chấm: bắt đúng token dãy chấm",
      _fp.dot_leader_token(_dr1, _tk1) == len(_tk1) - 2
      and set(_tk1[-2]["text"]) == {"."}, str([t["text"] for t in _tk1[-3:]]))
# Dấu chấm dính liền tiêu đề thì phải tách ra, nếu không cả cụm bị đo như một từ.
_dr2 = _dot_reg("3. Vận chuyển và lưu kho................... 18")
_tk2 = _fp.tokenize(_dr2)
_i2 = _fp.dot_leader_token(_dr2, _tk2)
check("gạch dẫn chấm: tách dãy chấm dính liền tiêu đề",
      _i2 == len(_tk2) - 2 and set(_tk2[_i2]["text"]) == {"."}
      and _tk2[_i2 - 1]["text"] == "kho", str([t["text"] for t in _tk2[-3:]]))
check("gạch dẫn chấm: đuôi không phải số trang thì bỏ",
      _fp.dot_leader_token(*(lambda r: (r, _fp.tokenize(r)))(
          _dot_reg("Mục nào đó ................... xong"))) is None)
check("gạch dẫn chấm: số quá dài không phải số trang",
      _fp.dot_leader_token(*(lambda r: (r, _fp.tokenize(r)))(
          _dot_reg("Mã sản phẩm ................... 480100"))) is None)
check("gạch dẫn chấm: region nhiều dòng không đụng",
      _fp.dot_leader_token(*(lambda r: (r, _fp.tokenize(r)))(
          _dot_reg("1 Thông tin an toàn ......... 5", nlines=2))) is None)
# Đo đầu-cuối: dòng phải kết thúc đúng mép phải dòng NGUỒN, sai lệch dưới một dấu chấm.
_toc_full = {"page": 2, "region_type": "paragraph", "rotation": 0, "alignment": "left",
             "source_text": "1 Safety Information..... 5",
             "bbox": [39.7, 123.7, 374.8, 137.4],
             "container": [39.67, 123.71, 414.95, 138.71],
             "lines": [{"bbox": [39.7, 123.7, 374.8, 137.4],
                        "spans": [{"origin": [39.7, 133.9], "text": "x", "size": 8.0}]}],
             "runs": [{"text": "1 Safety Information..... 5", "bold": False, "italic": False,
                       "serif": False, "mono": False, "size": 8.0, "color": 0,
                       "font": "ArialMT", "role": "body"}],
             "target_runs": [{"role": "body", "text": "1 Thông tin an toàn ....... 5"}]}
_frd, _ = _fp.fit_region(dict(_toc_full), _fp.FontPack(), _default_cfg)
_end = _frd and (_frd["lines"][0]["x"] + _frd["lines"][0]["width"])
check("gạch dẫn chấm: dòng kết thúc đúng mép phải dòng nguồn",
      _frd is not None and len(_frd["lines"]) == 1 and 371.0 <= _end <= 374.9,
      str(_end))
# Gate 3 so chuỗi nguyên văn. Số chấm vẽ ra cố ý khác `target_text`, nên fit_paint PHẢI khai
# ra và gate phải chuẩn hoá đúng vùng đã khai — không khai thì gate bắn P0 hàng loạt (đã xảy
# ra: 47 P0 trên HV48100).
check("gạch dẫn chấm: fit_result khai số chấm đã phát lại",
      _frd is not None and _frd.get("dot_leader", 0) > _fp.DOT_LEADER_MIN,
      str(_frd and _frd.get("dot_leader")))
# ── Gate 6 render từ handle sạch (1.9.23) ──────────────────────────────
# `page.get_image_info(hashes=True)` mà Gate 5 gọi buộc MuPDF giải mã sẵn mọi ảnh vào cache;
# lần render sau dùng bản cache đó nên pixel lệch ở chi tiết mảnh. Gate 5 chỉ soi `draft`,
# nên Gate 6 đem hai bản render KHÔNG cùng điều kiện ra so — 26/26 cờ trên V5 là báo giả.
_qgsrc = open(os.path.join(os.path.dirname(ASSETS_DIR), "scripts", "qa_gates.py"),
              encoding="utf-8").read()
check("Gate 6: render bằng handle riêng, không dùng lại handle đã soi ảnh",
      "src_r[pno].get_pixmap" in _qgsrc and "draft_r[pno].get_pixmap" in _qgsrc
      and "sp = src[pno].get_pixmap" not in _qgsrc)
# Nét gạch dẫn cũ rộng hơn nét mới khi tiêu đề dịch DÀI hơn: đoạn giữa mất chấm vẫn là pixel
# đổi, nên dải khai cho Gate 6 phải là HỢP hai khung.
check("gạch dẫn: dải khai cho Gate 6 là hợp khung cũ và mới",
      'min(d["old"][0], d["new"][0])' in _fpsrc and 'max(d["old"][2], d["new"][2])' in _fpsrc)

check("gạch dẫn chấm: Gate 3 chỉ chuẩn hoá vùng đã khai",
      'want, got = DOTS_RE.sub("....", want), DOTS_RE.sub("....", got)' in open(
          os.path.join(os.path.dirname(ASSETS_DIR), "scripts", "qa_gates.py"),
          encoding="utf-8").read())

check("mục lục: ô bảng để column_split lo, không đụng",
      _fp.leader_split(_toc_reg(_two, [{"role": "body", "text": "a\nb"}], "table_cell"),
                       _fp.FontPack()) is None)

# ── vẽ lại nét gạch dẫn mục lục (1.9.18) ────────────────────────────────
# Gạch dẫn là line-art vẽ từ mép phải tiêu đề TIẾNG ANH tới số trang. Tiêu đề tiếng Việt dài
# hơn thì chữ đè lên nét, ngắn hơn thì hở khoảng. `leader_split` chỉ tách được cột.
import pymupdf as _mu  # noqa: E402


def _stroke(x0, x1, y, dashes="[ 1.414 1.414 ] 0"):
    return {"type": "s", "rect": _mu.Rect(x0, y, x1, y), "dashes": dashes,
            "color": (0.1, 0.05, 0.05), "width": 0.709}


def _toc_row(x0=45.7, x1=129.4, y0=95.5, y1=111.2, nlines=1):
    return {"bbox": [x0, y0, x1, y1], "container": [x0, y0, 374.0, y1 + 1.5],
            "lines": [{"bbox": [x0, y0, x1, y1]}] * nlines}


_dr = [_stroke(131.67, 132.38, 103.89, "[] 0"), _stroke(133.79, 370.58, 103.89),
       _stroke(371.29, 372.0, 103.89, "[] 0")]
_NUM = [{"bbox": [374.4, 95.7, 380.6, 110.7]}]   # số trang ngay sau nét
_run = _fp.leader_run(_dr, _toc_row(), _NUM)
check("gạch dẫn: bắt được dãy nét sau tiêu đề, giữ mép phải",
      _run is not None and abs(_run["x1"] - 372.0) < 0.01 and abs(_run["gap"] - 2.27) < 0.01,
      str(_run and (_run["x1"], _run["gap"])))
check("gạch dẫn: xoá cả ba nét, không sót đầu mẩu",
      _run and len(_run["rects"]) == 3)
# Vạch kẻ bảng và gạch chân đều LIỀN nét — đòi nét đứt để không đụng nhầm.
check("gạch dẫn: nét liền không phải gạch dẫn",
      _fp.leader_run([_stroke(131.67, 372.0, 103.89, "[] 0")], _toc_row(), _NUM) is None)
check("gạch dẫn: region nhiều dòng không đụng",
      _fp.leader_run(_dr, _toc_row(nlines=3), _NUM) is None)
# Nét nằm xa mép chữ thì là thứ khác — vd gạch trang trí ở cột bên.
check("gạch dẫn: khe quá rộng thì bỏ",
      _fp.leader_run([_stroke(200.0, 372.0, 103.89)], _toc_row(), _NUM) is None)
check("gạch dẫn: nét bắt đầu TRƯỚC chữ thì không phải của vùng này",
      _fp.leader_run([_stroke(20.0, 372.0, 103.89)], _toc_row(), _NUM) is None)
# Không có chữ sau nét = đường chỉ dẫn của hình, không phải gạch dẫn mục lục.
check("gạch dẫn: không có số trang sau nét thì không đụng (đường chỉ dẫn hình)",
      _fp.leader_run(_dr, _toc_row(), []) is None)
check("gạch dẫn: mép phải chữ đã fit đo trên dòng dài nhất",
      abs(_fp.painted_right({"lines": [{"x": 45.7, "width": 60.0},
                                       {"x": 45.7, "width": 91.2}]}) - 136.9) < 0.01)
# Mặc định của pymupdf là ĐÓNG đường: vẽ thêm lượt về, lệch pha nét đứt nên lấp kín khe và
# gạch dẫn thành LIỀN nét — chỉ ở những dòng có chiều dài chia đúng kiểu ấy, nên rất dễ lọt.
check("gạch dẫn: vẽ đường hở, không đóng đường",
      "closePath=False" in _fpsrc)

# ── vùng bảo vệ đo theo nét mực, không theo bbox có đệm space (1.9.12) ──
# Ca thật V5 Series p10: ô nhãn một hàng bảng là 26 ký tự space, bbox rộng 123pt, "bảo vệ"
# chỗ trống rỗng và ép mask của ô kề bên cắt ngắn → chữ nguồn còn nguyên, bản dịch vẽ chồng.
_pline = lambda lb, sb, t: {"bbox": lb, "spans": [{"bbox": sb, "text": t, "size": 9.0}]}  # noqa: E731

check("bảo vệ: span toàn khoảng trắng thì không bảo vệ gì",
      _fp.protected_rects({"lines": [_pline([66.0, 262.7, 189.6, 273.7],
                                            [66.0, 262.7, 189.6, 273.7], "        ")]}) == [])
_pr = _fp.protected_rects({"lines": [_pline([34.5, 262.7, 38.9, 273.7],
                                            [30.0, 262.7, 50.0, 273.7], "  6     ")]})
check("bảo vệ: span có đệm space bị cắt về đúng nét mực",
      len(_pr) == 1 and abs(_pr[0].x0 - 34.5) < 0.01 and abs(_pr[0].x1 - 38.9) < 0.01,
      str(_pr))
check("bảo vệ: span kín chữ giữ nguyên bề rộng",
      [round(r.x1 - r.x0, 1) for r in _fp.protected_rects(
          {"lines": [_pline([40.0, 10.0, 90.0, 20.0], [40.0, 10.0, 90.0, 20.0], "ALM")]})]
      == [50.0])

_MCFG = {"render": {"mask_pad_ratio": 0.15, "mask_pad_min_pt": 0.3, "mask_pad_max_pt": 1.0}}


def _mask_of(line_bbox, span_bbox, text, prot):
    import pymupdf as _mu
    reg = {"lines": [{"bbox": line_bbox,
                      "spans": [{"bbox": span_bbox, "text": text, "size": 9.0}]}]}
    return _fp.build_masks(reg, [_mu.Rect(p) for p in prot], _MCFG)


# Chạm 0.1pt ở mép dưới với số trang → cắt dọc, không bỏ cả khối.
_r, _i = _mask_of([29.3, 561.1, 223.0, 569.7], [29.3, 561.1, 223.0, 569.7], "abc",
                  [[208.3, 569.6, 212.6, 579.1]])
check("mask: chạm mép dưới thì cắt dọc, không bỏ cả vùng",
      len(_r) == 1 and [c[0] for c in _i] == ["MASK_CLIPPED"], str(_i))
check("mask: cắt dọc đúng tới mép vùng bảo vệ",
      _r and abs(_r[0].y1 - 569.6) < 0.01, str(_r))
# Ô có 9 space đầu: mask phải bắt đầu ở nét mực, không chạm ô số thứ tự bên trái.
_r2, _i2 = _mask_of([49.6, 215.7, 103.3, 226.7], [30.0, 215.7, 105.6, 226.7],
                    "         Alarm Indicator ", [[34.2, 208.3, 38.7, 219.2]])
check("mask: space đầu ô không kéo mask sang ô bên cạnh",
      len(_r2) == 1 and not _i2 and _r2[0].x0 > 38.7, str(_i2) + str(_r2))

# ── thụt lề theo từng đoạn của bản dịch (1.9.11) ────────────────────────
# Bản gốc trộn nhiều mức thụt trong MỘT region: dòng gạch đầu dòng thụt vào, văn xuôi giữa
# chúng thì không. Một `base_x` cho cả vùng làm chữ dịch đè lên chính dấu gạch đầu dòng.
_rl = lambda *xs: {"lines": [{"bbox": [x, 0.0, x + 10.0, 10.0]} for x in xs]}  # noqa: E731

check("thụt lề: mỗi đoạn là một mục thụt vào thì tất cả cùng thụt (không nham nhở)",
      _fp.segment_indents(_rl(36.0, 27.7, 27.7, 27.7, 36.0, 36.0), 27.7, 3)
      == [8.3, 8.3, 8.3])
check("thụt lề: hai mức nhưng số mục không khớp số đoạn thì bỏ qua",
      _fp.segment_indents(_rl(36.0, 27.7, 27.7, 36.0), 27.7, 3) == [0.0, 0.0, 0.0])
check("thụt lề: số đoạn bằng số dòng nguồn thì suy ra được",
      _fp.segment_indents(_rl(36.0, 27.7), 27.7, 2) == [8.3, 0.0])
check("thụt lề: không khớp cả hai thì trả toàn 0 (giữ hành vi cũ)",
      _fp.segment_indents(_rl(36.0, 27.7, 27.7, 36.0, 36.0, 36.0), 27.7, 7) == [0.0] * 7)
check("thụt lề: không bao giờ âm — chữ dịch không vẽ trái hơn base_x",
      _fp.segment_indents(_rl(20.0, 40.0), 30.0, 2) == [0.0, 10.0])
check("thụt lề: region một dòng không có gì để suy",
      _fp.segment_indents(_rl(36.0), 27.7, 1) == [0.0])

# ── hình mẫu thứ ba: đếm dòng MỞ ĐOẠN (1.9.15) ─────────────────────────
# Ca thật V5 p11 khối lưu kho: 12 dòng nguồn, 7 đoạn dịch, chỉ 6 dòng thụt sâu — hai hình
# mẫu trên đều trượt vì một mục bắt đầu ngay ở lề thân bài. Dòng nào mà dòng TRƯỚC còn
# thừa chỗ cho từ đầu của nó thì dòng đó mở đoạn: nguồn ngắt sớm là cố ý, không phải hết chỗ.
def _pl(x0, x1, text):
    return {"bbox": [x0, 0.0, x1, 10.0], "spans": [{"text": text}]}


# mép phải chung = 397.1; dòng 0,1,3 dừng sớm → dòng sau mở đoạn; dòng 2 chạy sát mép → dòng
# 3 là phần xuống dòng của nó... trừ khi chính nó dừng sớm.
_mix = {"lines": [_pl(43.1, 206.3, "Relative humidity: 20%-80%, no condensation"),
                  _pl(42.7, 102.9, "Altitude: <4000m"),
                  _pl(29.8, 391.5, "For long-term storage, charge the LFP battery to more"),
                  _pl(29.8, 325.1, "than 90% of its rated capacity"),
                  _pl(43.1, 397.1, "Keep the SOC of the battery at 40%-60% during storage")]}
check("thụt lề: suy được từ số dòng mở đoạn khi hai hình mẫu kia trượt",
      _fp.segment_indents(_mix, 29.8, 4) == [13.3, 12.9, 0.0, 13.3],
      str(_fp.segment_indents(_mix, 29.8, 4)))
check("thụt lề: dòng chạy sát mép phải là dòng xuống dòng, không mở đoạn",
      _fp.paragraph_starts(_mix["lines"]) == [0, 1, 2, 4],
      str(_fp.paragraph_starts(_mix["lines"])))
check("thụt lề: số dòng mở đoạn không khớp số đoạn thì vẫn trả 0",
      _fp.segment_indents(_mix, 29.8, 2) == [0.0] * 2)
# Vùng hai cột khớp đếm nhưng cho ra thụt lề 268pt trên khung 366pt — chặn lại.
_wide = {"lines": [_pl(29.8, 120.0, "Note"),
                   _pl(29.8, 395.9, "left column text runs all the way to the right edge"),
                   _pl(29.8, 200.0, "continuation of that line"),
                   _pl(298.2, 395.9, "right column")]}
check("thụt lề: thụt vô lý (vùng hai cột) thì bỏ, không ném chữ ra giữa trang",
      _fp.segment_indents(_wide, 29.8, 3) == [0.0] * 3,
      str(_fp.segment_indents(_wide, 29.8, 3)))
# ── khoá quyền ghi artifact khi phát hành (1.9.29) ─────────────────────
# Chốt trạng thái trong stage là hàng rào TỰ NGUYỆN — chỉ chặn thứ chịu gọi nó. Helper viết
# tay trong job không gọi, và 2026-08-07 nó ghi đè `responses.jsonl` của job đã phát hành.
# Quyền ghi filesystem thì không tự nguyện, cùng lý lẽ `lock-engine.sh` dùng cho engine.
import tempfile  # noqa: E402

import approve as _ap  # noqa: E402


class _FakeJob:
    def __init__(self, root):
        self.root = root

    def p(self, *parts):
        return os.path.join(self.root, *parts)


_tmp = tempfile.mkdtemp()
_files = ["model/regions.json", "render/draft.pdf", "output/translated-approved.pdf",
          "translation/responses.jsonl", "translation/requests.jsonl", "qa/report.json",
          "qa/compare.pdf", "review/decisions.jsonl"]
for _f in _files:
    os.makedirs(os.path.dirname(os.path.join(_tmp, _f)), exist_ok=True)
    open(os.path.join(_tmp, _f), "w").write("x")
_job = _FakeJob(_tmp)


def _writable(rel):
    return os.access(os.path.join(_tmp, rel), os.W_OK)


_n = _ap.freeze_release(_job, True)
check("khoá phát hành: bằng chứng thành chỉ đọc",
      not any(_writable(f) for f in
              ("model/regions.json", "render/draft.pdf", "output/translated-approved.pdf",
               "translation/responses.jsonl", "translation/requests.jsonl", "qa/report.json")),
      str([f for f in _files if _writable(f)]))
# Revoke phải ghi được vào `review/`; `compare.pdf` phải dựng lại được sau phát hành.
check("khoá phát hành: review/ và qa/compare.pdf vẫn ghi được",
      _writable("review/decisions.jsonl") and _writable("qa/compare.pdf"))
check("khoá phát hành: có đổi thật, không phải no-op", _n > 0, str(_n))
_ap.freeze_release(_job, False)
check("khoá phát hành: revoke mở lại được hết",
      all(_writable(f) for f in _files), str([f for f in _files if not _writable(f)]))
import shutil as _sh  # noqa: E402
_sh.rmtree(_tmp, ignore_errors=True)
# Hàm đúng mà release không gọi thì vô dụng — và đó là lỗi im lặng.
_apsrc = open(os.path.join(os.path.dirname(ASSETS_DIR), "scripts", "approve.py"),
              encoding="utf-8").read()
check("khoá phát hành: release có gọi khoá, revoke có gọi mở",
      "freeze_release(job, True)" in _apsrc and "freeze_release(job, False)" in _apsrc)

# ── ô trống điền tay là nét LIỀN, gạch dẫn là nét đứt (1.9.27) ─────────
# `fill_in_rules` nhận nhầm ba dòng mục lục V5 thành ô trống điền tay → `FILL_BLANK_DROPPED`
# báo giả ở mọi tài liệu có mục lục. Nặng hơn: bản dịch có dãy `____` thì lượt xoá gạch-ô-trống
# xoá luôn gạch dẫn. Đo trên 5 bản Terms of Warranty: 15-16 nét mảnh mỗi bản, 0 nét đứt.
from _common import horizontal_rules as _cm_horizontal_rules  # noqa: E402

_doc = _mu.open()
_pg = _doc.new_page(width=300, height=200)
_sh = _pg.new_shape(); _sh.draw_line(_mu.Point(40, 100), _mu.Point(200, 100))
_sh.finish(width=0.7, closePath=False); _sh.commit()
_sh = _pg.new_shape(); _sh.draw_line(_mu.Point(40, 140), _mu.Point(200, 140))
_sh.finish(width=0.7, dashes="[1.4 1.4] 0", closePath=False); _sh.commit()
_hr = _cm_horizontal_rules(_doc[0])
check("ô trống: nét liền được nhận",
      any(abs(r[1] - 100) < 1.5 for r in _hr), str(_hr))
check("ô trống: nét đứt (gạch dẫn mục lục) bị loại",
      not any(abs(r[1] - 140) < 1.5 for r in _hr), str(_hr))
_doc.close()

# ── dấu gạch đầu dòng là bằng chứng cấu trúc mạnh nhất (1.9.25) ────────
# `•` `◇` `∘` của bản gốc là HÌNH VẼ nhỏ, không phải ký tự, nên không nằm trong `lines`.
# Chúng nói đúng số mục, còn `paragraph_starts` chỉ đoán từ chỗ ngắt dòng và sai ở nguồn
# ngắt dòng cứng giữa câu — ca thật HV48100 p19 `CAUTION`.
def _bl_reg(xs, bullets, ys=None):
    ys = ys or [100.0 + 12.0 * i for i in range(len(xs))]
    r = {"lines": [{"bbox": [x, y - 8.0, x + 60.0, y + 2.0],
                    "spans": [{"origin": [x, y], "text": "x" * 40}]}
                   for x, y in zip(xs, ys)]}
    r["bullet_lines"] = bullets
    return r


# Ba dòng, dấu ở dòng 1 và 2; dòng 0 là tiêu đề → 3 mục, khớp 3 đoạn dịch.
_bl = _bl_reg([27.4, 38.7, 38.7], [1, 2])
check("bullet: dấu quyết định ánh xạ, đứng trên ba hình mẫu suy đoán",
      _fp.segment_source_lines(_bl, 3) == ([0, 1, 2], 0),
      str(_fp.segment_source_lines(_bl, 3)))
# Số mục theo dấu không khớp số đoạn dịch → lùi về hình mẫu cũ, không ép bừa.
check("bullet: số mục không khớp số đoạn thì lùi về hình mẫu cũ",
      (_fp.segment_source_lines(_bl_reg([27.4, 38.7, 38.7], [2]), 3) or (None, None))[1] != 0)
check("bullet: vùng không có dấu thì không đụng gì",
      (_fp.segment_source_lines(_bl_reg([27.4, 38.7, 38.7], []), 3) or (None, None))[1] != 0)

# ── dời dấu gạch đầu dòng theo chữ (1.9.26) ────────────────────────────
# Neo baseline (1.9.20) giữ chữ khớp dấu khi dấu ĐỨNG YÊN, nhưng đoạn dịch ngắn hơn nguồn thì
# phần dôi thành khoảng trắng — "nhảy dòng". Dời được dấu thì chữ chảy liên tục.
_mkd = lambda x, y: {"rect": _mu.Rect(x, y - 1.1, x + 2.2, y + 1.1), "type": "f",  # noqa: E731
                     "fill": (0, 0, 0), "color": None, "width": None,
                     "items": [("l", _mu.Point(x, y), _mu.Point(x + 2.2, y))]}
_mreg = {"bbox": [27.4, 92.0, 200.0, 126.0], "bullet_lines": [0, 1],
         "lines": [{"bbox": [38.7, 92.0, 160.0, 102.0], "spans": [{"origin": [38.7, 100.0]}]},
                   {"bbox": [38.7, 104.0, 160.0, 114.0], "spans": [{"origin": [38.7, 112.0]}]}]}
_pairs = _fp.bullet_marks(_mreg, [_mkd(29.4, 97.5), _mkd(29.4, 109.5)])
check("dời dấu: ghép được dấu với dòng nó đánh",
      [li for li, _ in _pairs] == [0, 1], str([li for li, _ in _pairs]))
check("dời dấu: vùng chưa khai bullet_lines thì không ghép gì",
      _fp.bullet_marks({**_mreg, "bullet_lines": []}, [_mkd(29.4, 97.5)]) == [])
# Ba mảnh phải đi cùng nhau, thiếu một mảnh là hỏng: xoá dấu cũ, vẽ lại dấu mới, và TẮT neo.
check("dời dấu: xoá dấu cũ trong lượt redaction",
      'for d, _ in moves:' in _fpsrc and "page.add_redact_annot(d[\"rect\"]" in _fpsrc)
check("dời dấu: vẽ lại dấu sau khi đặt chữ",
      "redraw_mark(page, d, dy)" in _fpsrc)
check("dời dấu: vùng có dấu thì KHÔNG neo baseline nữa",
      'not reg.get("bullet_lines")' in _fpsrc)

# ── neo baseline theo đoạn (1.9.20) ────────────────────────────────────
# Dấu `•` `◇` `∘` là glyph riêng, neo cứng ở baseline nguồn. Fitter rải dòng liên tục nên
# đoạn i chỉ rơi đúng dấu của nó khi mọi đoạn trước chiếm đúng số dòng như nguồn.
check("neo: không có anchors thì rải liên tục như cũ",
      _fp.line_baselines([0, 0, 1], 100.0, 10.0, None) == [100.0, 110.0, 120.0])
# Đoạn 0 dịch ngắn hơn nguồn (1 dòng thay vì 2) → đoạn 1 vẫn phải rơi đúng baseline nguồn.
check("neo: đoạn dịch ngắn hơn thì đoạn sau tụt về đúng baseline nguồn",
      _fp.line_baselines([0, 1], 100.0, 10.0, [100.0, 120.0]) == [100.0, 120.0])
# Đoạn 0 dịch dài hơn nguồn → không được đè lên nhau, chảy tiếp như cũ.
check("neo: đoạn dịch dài hơn thì chảy tiếp, không đè",
      _fp.line_baselines([0, 0, 0, 1], 100.0, 10.0, [100.0, 120.0]) == [100.0, 110.0, 120.0, 130.0])
check("neo: neo không bao giờ kéo dòng lên trên dòng trước",
      _fp.line_baselines([0, 0, 1], 100.0, 10.0, [100.0, 105.0]) == [100.0, 110.0, 120.0])
_anch = {"lines": [{"bbox": [36.0, 0, 100.0, 10], "spans": [{"origin": [36.0, 100.0]}]},
                   {"bbox": [27.7, 0, 100.0, 10], "spans": [{"origin": [27.7, 113.0]}]},
                   {"bbox": [36.0, 0, 100.0, 10], "spans": [{"origin": [36.0, 126.0]}]}]}
check("neo: baseline lấy từ đúng dòng nguồn của mỗi đoạn",
      _fp.segment_anchors(_anch, 3) == [100.0, 113.0, 126.0],
      str(_fp.segment_anchors(_anch, 3)))
check("neo: không suy được ánh xạ thì không neo",
      _fp.segment_anchors(_anch, 4) is None)
# Thụt lề và neo PHẢI dùng chung ánh xạ, nếu không hai thứ nói về hai cấu trúc khác nhau.
check("neo: dùng chung ánh xạ với thụt lề",
      _fp.segment_source_lines(_anch, 3)[0] == [0, 1, 2])

check("thụt lề: dòng không có span chữ thì không đoán",
      _fp.paragraph_starts([{"bbox": [30.0, 0, 100.0, 10]},
                            {"bbox": [40.0, 0, 90.0, 10]}]) is None)

# ── căn lề đo bằng số dòng đồng thuận, không bằng biên độ (1.9.8) ───────
# Biên độ max-min để MỘT dòng lạc quyết định cả khối. Ca thật V5 Series p15: 8 dòng cùng
# mép trái 26.8 + một chú thích bảng lệch phải ở dòng cuối → cả đoạn bị đẩy sang phải.
import extract_group as _eg  # noqa: E402

_ln = lambda a, b: {"bbox": [a, 0.0, b, 10.0]}  # noqa: E731
_CONT = [27.0, 0.0, 415.0, 100.0]

check("căn lề: một dòng lạc không lật được khối căn trái",
      _eg.infer_alignment([_ln(26.8, 386.1)] * 4 + [_ln(295.0, 392.9)], _CONT) == "left")
check("căn lề: khối căn phải thật vẫn là right",
      _eg.infer_alignment([_ln(300.0, 392.0), _ln(320.0, 392.0), _ln(280.0, 392.0)],
                          _CONT) == "right")
check("căn lề: khối căn giữa thật vẫn là center",
      _eg.infer_alignment([_ln(100.0, 300.0), _ln(120.0, 280.0), _ln(110.0, 290.0)],
                          _CONT) == "center")
check("căn lề: hai dòng không mốc nào đồng thuận thì giữ luật biên độ cũ",
      _eg.infer_alignment([_ln(120.0, 300.0), _ln(150.0, 290.0)], _CONT) == "center")
check("căn lề: region một dòng không đụng tới nhánh mới",
      _eg.infer_alignment([_ln(30.0, 200.0)], _CONT) == "left")

# ── thụt lề treo: dòng đầu chạm mép trái khung thì khối căn trái (1.9.44) ───────
# Ca thật catalogue tr.51: mép trái lệch 13.7pt, mép phải lệch 2.9pt → luật biên độ chọn
# "right" và cả cụm bị đẩy sang phải, dù ô anh em 3 dòng ngay trên vẫn "left".
check("căn lề: thụt lề treo (dòng đầu chạm mép trái khung) → left",
      _eg.infer_alignment([_ln(27.0, 205.7), _ln(40.7, 208.6)], _CONT) == "left")
check("căn lề: dòng đầu KHÔNG chạm mép trái khung thì giữ luật biên độ",
      _eg.infer_alignment([_ln(120.0, 300.0), _ln(150.0, 297.1)], _CONT) == "right")
check("căn lề: dòng sau nằm TRÁI hơn dòng đầu thì không phải thụt lề treo",
      _eg.infer_alignment([_ln(27.0, 300.0), _ln(20.0, 297.1)], _CONT) != "left")
check("căn lề: khối căn giữa thật (biên độ chọn center) không dính luật thụt lề treo",
      _eg.infer_alignment([_ln(74.9, 344.7), _ln(108.7, 316.9)],
                          [74.9, 0.0, 413.5, 100.0]) == "center")

# ── vùng xoay vẽ được nhiều dòng (1.9.47) ──────────────────────────────
# 1.9.44 ép vùng xoay về một dòng vì v1 chưa vẽ được nhiều dòng; 1.9.47 vẽ được nên bỏ ép —
# nguồn hai dòng thì bản dịch cũng hai dòng, khớp bản gốc hơn.
_fpsrc = open(os.path.join(os.path.dirname(ASSETS_DIR), "scripts", "fit_paint.py"),
              encoding="utf-8").read()
check("fit: hết ép vùng xoay về một dòng",
      'single_line_src = len(reg["lines"]) == 1\n' in _fpsrc)
check("fit: hết từ chối vùng xoay nhiều dòng",
      "ROTATED_MULTILINE" not in _fpsrc)

# Neo CHẶT: đoạn đi đúng neo của nó. Dãy neo của vùng xoay zig-zag vì `reg["lines"]` theo
# thứ tự ĐỌC chứ không theo thứ tự nhìn — ca thật khối CSS tr.4: u = 549.8 / 516.7 / 534.3.
_ZZ = [549.8, 516.7, 534.3]
check("neo chặt: mỗi đoạn đi đúng neo, kể cả khi dãy neo zig-zag",
      _fp.line_baselines([0, 1, 2], 516.7, 16.2, _ZZ, True) == _ZZ)
check("neo chặt: dòng WRAP trong một đoạn vẫn chạy tiếp bằng leading",
      _fp.line_baselines([0, 0, 1], 516.7, 16.0, [516.7, 534.3], True)
      == [516.7, 532.7, 534.3])
check("neo thường (rot 0) vẫn giữ luật max — dãy neo lùi không kéo dòng lên trên",
      [round(v, 1) for v in _fp.line_baselines([0, 1, 2], 516.7, 16.2, _ZZ, False)]
      == [516.7, 532.9, 549.1])
check("neo chặt: không neo thì cả hai chế độ rải liên tục như nhau",
      _fp.line_baselines([0, 0, 0], 10.0, 5.0, None, True)
      == _fp.line_baselines([0, 0, 0], 10.0, 5.0, None, False) == [10.0, 15.0, 20.0])
# Bất biến nối dây: `fit_region` phải BẬT neo chặt đúng khi có ánh xạ đoạn↔dòng của vùng
# xoay, và phải truyền cờ đó vào cả hai chỗ gọi `line_baselines` (một chỗ để ĐO trong vòng
# tìm cỡ chữ, một chỗ để VẼ). Đo một đằng vẽ một nẻo là lỗi đã sập ở 1.9.20.
check("fit: neo chặt bật theo ánh xạ đoạn↔dòng của vùng xoay",
      "strict_anchor = bool(rot_map)" in _fpsrc)
check("fit: cả hai chỗ gọi line_baselines đều truyền neo chặt",
      _fpsrc.count("anchors, strict_anchor)") == 2)

# ── sàn cỡ chữ vùng xoay: fitter và gate phải đọc CÙNG một con số (1.9.45) ──────
# Lệch nhau thì fitter thu đúng luật mà Gate 4 tự bắn G4_RATIO_FLOOR — P0 không waive được.
# Job đóng băng config trước 1.9.45 không có khoá `rotated_ink_floor`, nên cả hai bên rơi về
# hằng số chung; hai default khác nhau là đúng cái bẫy đó.
from _common import ROTATED_INK_FLOOR_DEFAULT as _RIF  # noqa: E402
check("sàn xoay: fit_paint và qa_gates dùng chung hằng số của _common",
      f'cfg["fonts"].get("rotated_ink_floor", ROTATED_INK_FLOOR_DEFAULT)' in _fpsrc
      and 'cfg["fonts"].get("rotated_ink_floor", ROTATED_INK_FLOOR_DEFAULT)' in _qgsrc)
check("sàn xoay: hằng số nằm dưới minimum_ratio (có nới thật)",
      _RIF < 0.85)

# ── is_bold_font: TÊN quyết định, cờ chỉ dùng khi tên câm (1.9.45) ──────
from _common import is_bold_font as _ibf  # noqa: E402
check("bold: RanyMedium là nấc nặng dù cờ khai False",
      _ibf("RanyMedium", 0) is True)
check("bold: RanyLight không đậm dù cờ khai True",
      _ibf("RanyLight", 16) is False)
check("bold: RanyBold vẫn đậm",
      _ibf("RanyBold", 0) is True)
check("bold: tên câm thì NGHE CỜ — font subset tự sinh khai đúng",
      _ibf("CIDFont+F1", 16) is True and _ibf("CIDFont+F1", 0) is False)
check("bold: tiền tố subset 6 chữ hoa không che được tên",
      _ibf("ABCDEF+RanyMedium", 0) is True)

# ── face ký hiệu trong font pack (1.9.46) ──────────────────────────────
# Một ký tự ký hiệu duy nhất từng làm cả vùng thành FONT_GLYPH_MISSING và mất trọn bản dịch.
_pack = _fp.FontPack()
check("font pack: có face ký hiệu",
      "symbols-regular" in _pack.entries)
check("font pack: dấu tick ✓ được face ký hiệu phủ",
      _pack.cover("sans-regular", "✓") == "symbols-regular")
check("font pack: face ký hiệu đứng CUỐI chain fallback",
      _pack.FALLBACK_CHAIN[-1] == "symbols-regular")
check("font pack: key_for KHÔNG bao giờ trả face ký hiệu",
      all(_pack.key_for({"bold": b, "italic": i, "serif": s, "mono": m})[0]
          != "symbols-regular"
          for b in (0, 1) for i in (0, 1) for s in (0, 1) for m in (0, 1)))
check("font pack: face ký hiệu không phủ chữ Việt (không được thay face chính)",
      not _pack.font("symbols-regular").has_glyph(ord("ệ")))
check("font pack: codepoint PUA của Wingdings vẫn nằm ngoài pack",
      _pack.cover("sans-regular", "") is None)

# ── điểm vẽ thật = mép mực, không phải origin có đệm space (1.9.16) ─────
# `ink_base_x` của stage 6 nâng base_x lên mép mực từ 1.9.6/1.9.9; stage 2 vẫn trả origin
# thô nên container ô bảng bị kéo sang trái đúng bề rộng dãy space. Ca thật V5: ô `CANH`
# 48 space đầu kéo container về 134.2 trong khi cột CAN bắt đầu ở ~204.
_pad = {"lines": [{"bbox": [241.0, 0.0, 263.6, 10.0],
                   "spans": [{"origin": [134.2, 8.0]}]}]}
check("điểm vẽ: ô có đệm space lấy mép mực, không lấy origin",
      abs(_eg.paint_origin_x(_pad) - 241.0) < 0.01, str(_eg.paint_origin_x(_pad)))
_noPad = {"lines": [{"bbox": [30.0, 0.0, 90.0, 10.0], "spans": [{"origin": [30.0, 8.0]}]},
                    {"bbox": [42.0, 0.0, 88.0, 10.0], "spans": [{"origin": [42.0, 8.0]}]}]}
check("điểm vẽ: không đệm thì vẫn là origin dòng đầu",
      abs(_eg.paint_origin_x(_noPad) - 30.0) < 0.01)
# Dòng sau thụt trái hơn origin dòng đầu: chỉ NÂNG, không bao giờ hạ — khớp `ink_base_x`.
_deep = {"lines": [{"bbox": [50.0, 0.0, 90.0, 10.0], "spans": [{"origin": [50.0, 8.0]}]},
                   {"bbox": [30.0, 0.0, 88.0, 10.0], "spans": [{"origin": [30.0, 8.0]}]}]}
check("điểm vẽ: chỉ nâng, không hạ dưới origin dòng đầu",
      abs(_eg.paint_origin_x(_deep) - 50.0) < 0.01, str(_eg.paint_origin_x(_deep)))

# ── ô bảng một dòng lấy căn lề theo đồng thuận của cột (1.9.17) ─────────
# Ô một dòng không có gì đồng thuận nội bộ. Dòng tiếng Anh gần đầy ô thì hai khe xấp xỉ
# nhau, luật dung sai đọc thành `center`. Ca thật V5 p8: 7 ô cùng cột `left`, một ô `center`.


def _cell(align, x0=29.9, x1=217.0, nlines=1, ink=None):
    return {"region_type": "table_cell", "alignment": align, "container": [x0, 0.0, x1, 10.0],
            "bbox": [ink if ink is not None else x0 + 1.0, 0.0, x1 - 1.0, 10.0],
            "lines": [{"bbox": [0, 0, 1, 1]}] * nlines}


_col = [_cell("left") for _ in range(6)] + [_cell("center")]
check("căn lề cột: ô lạc bị cả cột kéo về",
      _eg.column_consensus(_col) == 1 and all(c["alignment"] == "left" for c in _col))
# Cột trộn tiêu đề căn giữa + thân bài căn trái, chỉ 3 ô một dòng — bằng chứng chưa đủ.
_few = [_cell("center"), _cell("center"), _cell("left")]
check("căn lề cột: dưới 4 ô một dòng thì không đụng",
      _eg.column_consensus(_few) == 0 and _few[2]["alignment"] == "left")
_split = [_cell("center"), _cell("center"), _cell("left"), _cell("left")]
check("căn lề cột: đồng thuận dưới 75% thì không đụng",
      _eg.column_consensus(_split) == 0)
# Ô nhiều dòng có bằng chứng nội bộ thật — không được đụng, và không được tính phiếu.
_multi = [_cell("left") for _ in range(4)] + [_cell("center", nlines=3)]
check("căn lề cột: ô nhiều dòng không bị đụng",
      _eg.column_consensus(_multi) == 0 and _multi[4]["alignment"] == "center")
# Cột khác thì không lây phiếu sang nhau.
_two = [_cell("left") for _ in range(4)] + [_cell("center", x0=250.0, x1=390.0)]
check("căn lề cột: hai cột khác nhau tính riêng",
      _eg.column_consensus(_two) == 0 and _two[4]["alignment"] == "center")
# Hàm đúng mà pipeline không gọi thì vô dụng — và đây là lỗi im lặng, không test nào khác bắt.
# Ô hẹp lấp gần kín thì luật dung sai đọc nhầm thành `left` và thắng phiếu — ô căn giữa THẬT
# bị kéo theo, ngân sách wrap tụt còn `x1 - base_x` và chữ hết fit. Ca thật HV48100 p25.
_tight = [_cell("left", 170.9, 191.3, ink=172.6) for _ in range(5)] \
    + [_cell("center", 170.9, 191.3, ink=174.9)]
check("căn lề cột: không kéo ô mực-lệch-phải sang trái (mất ngân sách wrap)",
      _eg.column_consensus(_tight) == 0 and _tight[5]["alignment"] == "center")
# Chiều ngược lại không hụt ngân sách: center/right neo vào khung, cứ nhận.
_toC = [_cell("center", 29.9, 217.0, ink=100.0) for _ in range(5)] \
    + [_cell("left", 29.9, 217.0, ink=100.0)]
check("căn lề cột: đổi sang center thì không cần chốt mực",
      _eg.column_consensus(_toC) == 1 and _toC[5]["alignment"] == "center")
# ── gộp ký hiệu mũ vào dòng chủ (1.9.21) ───────────────────────────────
# Baseline ký hiệu mũ cao hơn dòng thân nên PDF khai nó thành một "line" riêng: source_text
# thành ba đoạn và bản vẽ đặt `[1]` lơ lửng giữa hai dòng chữ. Ca thật V5 p6.
def _sline(x0, x1, oy, text, size=8.0):
    return {"bbox": [x0, oy - 8.0, x1, oy + 2.0],
            "spans": [{"text": text, "size": size, "origin": [x0, oy]}]}


_sup = [_sline(31.7, 116.6, 224.5, "Recommended Charge/"),
        _sline(98.9, 103.8, 230.6, "[1]", 4.0),
        _sline(31.7, 96.6, 235.5, "Discharge Current ")]
_folded = _eg.fold_superscripts(_sup)
check("ký hiệu mũ: gộp vào dòng chủ, không còn dòng riêng",
      len(_folded) == 2 and "".join(s["text"] for s in _folded[1]["spans"])
      == "Discharge Current [1]", str([[s["text"] for s in l["spans"]] for l in _folded]))
check("ký hiệu mũ: bbox dòng chủ nới ra bao ký hiệu",
      abs(_folded[1]["bbox"][2] - 103.8) < 0.01, str(_folded[1]["bbox"]))
# Ký hiệu mũ được NÂNG lên: chủ luôn ở baseline THẤP HƠN nó. `[3]` của `Cycle Life` không
# được dán ngược lên `DC Breaker` ở hàng trên, dù hàng đó cũng kết thúc trước nó.
_two_rows = [_sline(31.7, 66.0, 373.0, "DC Breaker"),
             _sline(68.2, 73.0, 383.7, "[3]", 4.0),
             _sline(31.7, 68.7, 388.7, "Cycle Life")]
_f2 = _eg.fold_superscripts(_two_rows)
check("ký hiệu mũ: không dán ngược lên hàng trên",
      len(_f2) == 2 and "".join(s["text"] for s in _f2[1]["spans"]) == "Cycle Life[3]",
      str([[s["text"] for s in l["spans"]] for l in _f2]))
# Không có dòng nào kết thúc trước nó ở đúng tầm baseline → để nguyên, thà giữ dòng riêng.
check("ký hiệu mũ: không tìm được chủ thì để nguyên",
      len(_eg.fold_superscripts([_sline(31.7, 36.5, 224.5, "[1]", 4.0),
                                 _sline(60.0, 120.0, 260.0, "Something else")])) == 2)
check("ký hiệu mũ: chữ thường cỡ bình thường không bị gộp",
      len(_eg.fold_superscripts(_sup[:1] + [_sline(98.9, 118.0, 230.6, "ABC")])) == 2)
check("ký hiệu mũ: make_region thật sự gộp trước khi dựng source_text",
      "lines = fold_superscripts(lines)" in open(
          os.path.join(os.path.dirname(ASSETS_DIR), "scripts", "extract_group.py"),
          encoding="utf-8").read())

# Dấu phải nằm NGOÀI vệt mực mọi dòng — chồng lên chữ thì đó là ký hiệu trong câu hoặc nét
# của hình minh hoạ, không phải gạch đầu dòng.
_mk = lambda x, y: {"rect": _mu.Rect(x, y - 1.1, x + 2.3, y + 1.1)}  # noqa: E731
_breg = {"bbox": [27.4, 92.0, 200.0, 126.0],
         "lines": [{"bbox": [38.7, 92.0, 160.0, 102.0],
                    "spans": [{"origin": [38.7, 100.0]}]},
                   {"bbox": [38.7, 104.0, 160.0, 114.0],
                    "spans": [{"origin": [38.7, 112.0]}]}]}
check("bullet: dấu ngoài vệt mực được tính",
      _eg.bullet_lines(_breg, [_mk(29.4, 97.5), _mk(29.4, 109.5)]) == [0, 1])
check("bullet: nét nằm TRONG vệt mực không phải dấu",
      _eg.bullet_lines(_breg, [_mk(40.0, 97.5)]) == [],
      str(_eg.bullet_lines(_breg, [_mk(40.0, 97.5)])))
check("bullet: nét quá xa mép trái vùng không phải dấu",
      _eg.bullet_lines(_breg, [_mk(120.0, 97.5)]) == [])
check("bullet: nét to không phải dấu",
      _eg.bullet_lines(_breg, [{"rect": _mu.Rect(29.4, 94.0, 45.0, 101.0)}]) == [])
check("căn lề cột: stage 2 thật sự gọi đồng thuận sau khi gán alignment",
      "column_consensus(ordered)" in open(
          os.path.join(os.path.dirname(ASSETS_DIR), "scripts", "extract_group.py"),
          encoding="utf-8").read())

# ── role của tiêu đề phụ in đậm mở đầu region (1.9.7) ───────────────────
# Bản gốc gộp tiêu đề phụ in đậm + văn xuôi vào một block. Luật cũ chỉ cho `emphasis` khi
# i > 0 nên run 0 in đậm rơi về `body`, rồi `role_style()` lấy nó làm style cho CẢ VÙNG.


def _span(text, bold, x=0.0):
    return {"text": text, "font": "Arial-BoldMT" if bold else "ArialMT", "size": 9.0,
            "color": 0, "flags": 16 if bold else 0, "origin": (x, 10.0),
            "bbox": (x, 0.0, x + 10.0, 10.0)}


_roles = lambda spans: [r["role"] for r in _eg.build_runs(spans)]  # noqa: E731

check("role: tiêu đề phụ đậm mở đầu → emphasis, thân bài → body",
      _roles([_span("Danger", True), _span("Ensure that power is off.", False)])
      == ["emphasis", "body"])
check("role: nhãn đậm kết thúc bằng ':' vẫn là label",
      _roles([_span("Statement:", True), _span("nội dung", False)]) == ["label", "body"])
check("role: region đậm toàn bộ vẫn là body (tiêu đề thật, vẫn vẽ đậm)",
      _roles([_span("2 Product Description", True)]) == ["body"])
check("role: run đậm ở giữa vẫn là emphasis như cũ",
      _roles([_span("mở", False), _span("ĐẬM", True), _span("kết", False)])
      == ["body", "emphasis", "body"])
check("role: luôn còn ít nhất một run body",
      "body" in _roles([_span("Danger", True), _span("thân bài", False)]))
check("role: run thường theo sau chỉ có khoảng trắng thì KHÔNG hạ vai (giữ đậm cả dòng)",
      _roles([_span("1 Specifications", True), _span("   ", False)]) == ["body", "body"])
check("role: đậm mở đầu nhưng sau toàn đậm thì không đổi vai",
      _roles([_span("A", True), _span("B", True)]) == ["body"])

# ── hai kiểu chữ thật cùng role body → tách sang emphasis (1.9.44) ──────
# Ca thật catalogue tr.53-54: mã hàng RanyLight 11pt xám + mô tả RanyMedium 13.6pt gần đen,
# cả hai bold=False nên luật độ đậm không tách được và cả khối vẽ theo run đầu.
def _sp2(text, size, color, x=0.0, y=10.0):
    return {"text": text, "font": "ArialMT", "size": size, "color": color, "flags": 0,
            "origin": (x, y), "bbox": (x, y - 10.0, x + 10.0, y)}


check("role: hai kiểu chữ thật cùng body → nhóm nhỏ sang emphasis",
      _roles([_sp2("161412100245/161412100244", 11.0, 5855063),
              _sp2("UL10269-4AWG-2000mm-Negative/Positive", 13.6, 257)])
      == ["emphasis", "body"])
check("role: nhóm đông hơn giữ body (bất biến còn chỗ cho role_style)",
      "body" in _roles([_sp2("mã hàng", 11.0, 5855063),
                        _sp2("mô tả dài hơn nhiều lần", 13.6, 257)]))
check("role: dấu chú thích mũ quá ngắn thì KHÔNG tách (giữ gộp như 1.9.21)",
      _roles([_sp2("Cycle Life", 10.0, 0), _sp2("[2]", 6.0, 0)]) == ["body", "body"])
check("role: mã hàng ngắn nhưng CHIẾM TRỌN dòng riêng thì vẫn tách",
      _roles([_sp2("161412101071", 11.0, 5855063, y=10.0),
              _sp2("Standard Communication Cable, compatible with many inverters",
                   13.6, 257, y=24.0)]) == ["emphasis", "body"])
check("role: số chú thích đầu dòng riêng nhưng dưới 6 ký tự thì KHÔNG tách",
      _roles([_sp2("6", 4.5, 0, y=10.0), _sp2("Local Laws và phần thân dài hơn", 9.0, 0,
                                              y=24.0)]) == ["body", "body"])
check("role: cùng cỡ khác màu là nhãn/trị số của bảng, không tách",
      _roles([_sp2("Nhiệt độ vận hành", 10.0, 0), _sp2("-20~55°C", 10.0, 5855063)])
      == ["body", "body"])
check("role: ba nhóm kiểu trở lên thì không tách (bảng trộn nhiều mức)",
      _roles([_sp2("aaaaaa", 10.0, 0), _sp2("bbbbbb", 13.0, 0), _sp2("cccccc", 16.0, 0)])
      == ["body", "body", "body"])
check("role: vùng đã có emphasis do độ đậm thì luật cỡ chữ không đụng vào",
      _roles([_span("Danger", True), _sp2("thân bài dài hơn hẳn", 13.6, 257)])
      == ["emphasis", "body"])


def _spf(text, font, flags=0):
    return {"text": text, "font": font, "size": 12.0, "color": 0, "flags": flags,
            "origin": (0.0, 10.0), "bbox": (0.0, 0.0, 10.0, 10.0)}


# Bất biến nối dây: `style_of` phải gọi `is_bold_font`, không đọc thẳng cờ. Test hàm thuần ở
# khối 1.9.45 không phát hiện được chỗ nối này — đo bằng đột biến: đổi về cờ thì test kia vẫn
# xanh, chỉ test này đỏ.
check("role: style_of dùng is_bold_font (RanyMedium cờ False vẫn thành emphasis)",
      _roles([_spf("Mô tả phụ kiện", "RanyMedium"),
              _spf("mã hàng", "RanyLight")]) == ["emphasis", "body"])

# ── base_x theo nét mực, không theo origin có đệm space (1.9.6) ─────────
# Bản gốc căn chữ bằng dãy space; space có advance nhưng không vẽ gì, còn tokenize thì bỏ
# sạch token khoảng trắng — nên bản dịch bị kéo về đầu dãy space. Ca thật V5 Series: ô
# "Pictures" có origin 282.6 trong khi nét mực bắt đầu ở 325.1.
def _reg_lines(*bounds, span_x=0.0):
    return {"lines": [{"bbox": [b, 0.0, b + 20.0, 10.0],
                       "spans": [{"origin": [span_x, 8.0]}]} for b in bounds]}


check("base_x: một dòng thì nâng lên đầu nét mực",
      _fp.ink_base_x(_reg_lines(325.1, span_x=282.6), 282.6) == 325.1)
check("base_x: không có đệm thì giữ nguyên",
      _fp.ink_base_x(_reg_lines(45.7, span_x=45.7), 45.7) == 45.7)
check("base_x: chỉ nâng, không bao giờ hạ",
      _fp.ink_base_x(_reg_lines(40.0, span_x=45.7), 45.7) == 45.7)
check("base_x: nhiều dòng cùng mép mực thì vẫn nâng",
      _fp.ink_base_x(_reg_lines(187.0, 187.0, span_x=138.0), 138.0) == 187.0)
check("base_x: nhiều dòng lệch mép thì lấy mép trái nhất, không lấy dòng đầu",
      _fp.ink_base_x(_reg_lines(60.0, 45.7, span_x=45.7), 45.7) == 45.7)
check("base_x: mọi dòng đều thụt (ô gộp căn bằng space) thì nâng tới mép trái nhất",
      _fp.ink_base_x(_reg_lines(92.2, 107.3, span_x=27.7), 27.7) == 92.2)
# Kẹp "chỉ nâng" phải áp theo TỪNG DÒNG. Ô bảng gộp mà thứ tự đọc bắt đầu ở cột PHẢI thì
# kẹp cả vùng bằng origin dòng đầu ghim base_x vào cột phải, thụt lề hoá âm rồi clamp về 0 và
# cả khối dồn thành một chồng. Ca thật V5 p6, ô gộp hàng `DC Breaker`/`Cycle Life`.
_merged = {"lines": [{"bbox": [297.2, 0.0, 365.7, 10.0], "spans": [{"origin": [297.19, 8.0]}]},
                     {"bbox": [191.0, 0.0, 201.2, 10.0], "spans": [{"origin": [191.0, 8.0]}]},
                     {"bbox": [297.2, 0.0, 359.9, 10.0], "spans": [{"origin": [297.19, 8.0]}]}]}
check("base_x: dòng đầu ở cột phải không được ghim cả vùng",
      abs(_fp.ink_base_x(_merged, 297.19) - 191.0) < 0.01, str(_fp.ink_base_x(_merged, 297.19)))
# Side-bearing âm chỉ được chặn TRONG dòng của nó, không lan sang dòng khác.
_sb = {"lines": [{"bbox": [44.9, 0.0, 90.0, 10.0], "spans": [{"origin": [45.7, 8.0]}]},
                 {"bbox": [60.0, 0.0, 90.0, 10.0], "spans": [{"origin": [60.0, 8.0]}]}]}
check("base_x: side-bearing âm bị chặn trong dòng, không lan ra vùng",
      abs(_fp.ink_base_x(_sb, 45.7) - 45.7) < 0.01, str(_fp.ink_base_x(_sb, 45.7)))

check("base_x: region không có lines thì trả nguyên span_x",
      _fp.ink_base_x({"lines": []}, 45.7) == 45.7)

# ── ink_size: trục cỡ chữ của họ lỗi "đệm space" — 1.9.42 ───────────────
# Ca thật: `E-BOX 48100R Sol-Ark package` tr.2 dòng `Warranty / 10 Years`. Run 0 là 20 dấu
# cách ở 13.6pt, run 1 là `10 Years ` (9 ký tự) ở 8.0pt. Median đếm cả trắng ra 13.6 → dòng
# dịch vẽ to gần gấp đôi hàng xóm và tràn 4.99pt lên dòng trên.
import statistics as _stats_ink


def _runs(*pairs):
    return {"runs": [{"size": s, "text": t, "role": "body"} for s, t in pairs]}

check("cỡ chữ không để 20 dấu cách 13.6pt lấn lướt 9 ký tự 8pt",
      _fp.ink_size(_runs((13.6, " " * 20), (8.0, "10 Years "))) == 8.0)
check("không có đệm thì kết quả không đổi",
      _fp.ink_size(_runs((8.0, "10 Years"))) == 8.0)
check("vùng toàn khoảng trắng giữ nguyên hành vi cũ",
      _fp.ink_size(_runs((13.6, "   "))) == 13.6)
check("median vẫn tính theo số ký tự CÓ MỰC, không phải theo số run",
      _fp.ink_size(_runs((9.0, "aaa"), (12.0, "bbbbb"), (12.0, "cc"))) == 12.0)

# ── luật hoà phiếu giữa hai cỡ chữ thật — 1.9.43 ───────────────────────
# Ca thật `V16 user manual` tr.11: nhãn chính 45 ký tự ở 9.0pt, chú thích 46 ký tự ở 5.0pt.
# Median rơi về cụm đông hơn dù chỉ hơn MỘT ký tự → cả ô vẽ 5.0pt, nhãn nhỏ đi 44%.
check("hai cụm cỡ chữ xấp xỉ nhau thì lấy cỡ lớn hơn",
      _fp.ink_size(_runs((9.0, "a" * 45), (5.0, "b" * 46))) == 9.0)
check("chênh lệch rõ thì KHÔNG hoà, vẫn theo median",
      _fp.ink_size(_runs((9.0, "a" * 10), (5.0, "b" * 90))) == 5.0)
check("hoà phiếu không cứu lại được span khoảng trắng",
      _fp.ink_size(_runs((13.6, " " * 20), (8.0, "10 Years "))) == 8.0)
# Mutation: bỏ luật hoà thì ca V16 phải trả 5.0 trở lại.
check("mutation: không có luật hoà thì ô V16 rơi về 5.0",
      _stats_ink.median([9.0] * 45 + [5.0] * 46) == 5.0)
# Mutation: đếm cả khoảng trắng thì case đầu phải trả 13.6 — nếu không, case không đo gì.
_mut = _runs((13.6, " " * 20), (8.0, "10 Years "))
check("mutation: đếm cả khoảng trắng thì hỏng lại",
      _stats_ink.median([r["size"] for r in _mut["runs"] for _ in r["text"]]) == 13.6)

# ── Gate 3 nhánh keep: chữ còn hay mất, không phải thứ tự (1.9.5) ───────
# Vùng keep engine không đụng tới, nên chuỗi trích xuất lệch thứ tự chỉ nói lên thứ tự đọc
# của PDF chứ không nói mất chữ. Ca thật HV48100 manual p15: callout `1\n2` trích ra '2 1'
# ở CẢ bản gốc lẫn bản dịch — bản gốc trượt chính phép kiểm này.
check("keep: khớp nguyên văn thì không thiếu ký tự",
      not _qg.char_deficit("Port 1", "Port 1"))
check("keep: lệch thứ tự đọc vẫn đủ chữ (ca HV48100 p15)",
      not _qg.char_deficit("1\n2", "2 1"))
check("keep: lệch dấu cách vẫn đủ chữ",
      not _qg.char_deficit("Link 0", "Link0"))
check("keep: hàng xóm lọt vào khung không che được chữ thiếu",
      _qg.char_deficit("1 2", "2 4") == collections.Counter({"1": 1}))
check("keep: mất hẳn thì báo đúng ký tự thiếu",
      _qg.char_deficit("ALM", "") == collections.Counter({"A": 1, "L": 1, "M": 1}))
check("keep: thiếu một trong hai ký tự trùng nhau vẫn bị bắt",
      _qg.char_deficit("11", "1") == collections.Counter({"1": 1}))

import pymupdf as _pymupdf

# ── read_window: cửa sổ đọc của Gate 3 nhánh keep (engine 1.9.44) ─────────────────────
# Ca thật catalogue trang 30/36: container bề rộng ÂM, mực thò 0.1pt khỏi cửa sổ cũ.
_DEGEN = [591.1, 62.5, 589.3, 70.5]      # x0 > x1
_INK = [591.1, 62.5, 591.4, 62.6]
check("read_window: container suy biến được chuẩn hoá, bao trọn dải x thật",
      _qg.read_window(_DEGEN, None).contains(
          _pymupdf.Rect(_DEGEN).normalize()))
check("read_window: cửa sổ bao trọn vệt mực của container suy biến",
      _qg.read_window(_DEGEN, _INK).contains(_pymupdf.Rect(_INK)))
check("read_window: cửa sổ CŨ (pad thẳng, không chuẩn hoá) hụt mép phải vệt mực",
      not (_pymupdf.Rect(_DEGEN) + (-2, -2, 2, 2)).contains(_pymupdf.Rect(_INK)))
check("read_window: container bình thường vẫn nới đúng 2pt mỗi phía",
      _qg.read_window([10, 20, 110, 40], None) == _pymupdf.Rect(8, 18, 112, 42))
check("read_window: bbox mực nằm trong khung thì không nới thêm",
      _qg.read_window([10, 20, 110, 40], [30, 25, 60, 35])
      == _pymupdf.Rect(8, 18, 112, 42))

# ── tổng kết ────────────────────────────────────────────────────────────
# PHẢI là thứ cuối cùng trong file. Trước 1.8.0 khối này nằm giữa file, nên ~100 case
# thêm sau nó (context graph, gộp đoạn, chốt RELEASED, hướng nới dự phòng) in "FAIL"
# mà tiến trình vẫn thoát 0 và dòng tổng kết vẫn nói ALL PASS.
# ── spec_grid: khối hai cột căn bằng space (engine 1.9.31) ────────────────────────────
# Hình học rút gọn từ trang thông số HV48100: nhãn ở x=60, trị số ở x=320, ba hàng.
from _common import spec_cell_text as _sct, spec_grid_cells as _sgc, spec_row_votes as _srv
from fit_paint import spec_grid as _sg, target_segments as _tsg


def _chars(text, x0, y, w=6.0):
    out, x = [], x0
    for ch in text:
        out.append({"c": ch, "origin": [x, y], "bbox": [x, y - 8, x + w, y + 2]})
        x += w
    return out


def _sp(text, x0, y):
    cs = _chars(text, x0, y)
    return {"text": text, "origin": [x0, y], "size": 10.0, "font": "F", "color": 0,
            "bbox": [x0, y - 8, cs[-1]["bbox"][2], y + 2], "chars": cs}


def _line(*spans):
    return {"bbox": [spans[0]["bbox"][0], spans[0]["bbox"][1],
                     spans[-1]["bbox"][2], spans[-1]["bbox"][3]], "spans": list(spans)}


def _spec_reg(lines, tgt="", rtype="paragraph", container=(55, 100, 580, 200)):
    runs = [{"text": "".join(s["text"] for l in lines for s in l["spans"]),
             "role": "body", "size": 10.0, "font": "F", "color": 0}]
    return {"region_type": rtype, "rotation": 0, "container": list(container),
            "lines": lines, "runs": runs,
            "target_runs": [{"role": "body", "text": tgt}] if tgt else []}


# Ba hàng nhãn/trị số; hàng 2 gõ nhãn và trị số trong MỘT span có dãy space ở giữa.
_L1 = _line(_sp("Cell Type", 60, 120), _sp("LFP", 320, 120))
_L2 = _line(_sp("Nominal Energy" + " " * 30 + "5.12kWh", 60, 140))
_L3 = _line(_sp("Weight", 60, 160), _sp("43 kg", 320, 160))
_SPEC = [_L1, _L2, _L3]

_reg_spec = _spec_reg(_SPEC)
_got = _sgc(_reg_spec)
check("spec_grid_cells: ba hàng hai cột → 6 ô", _got is not None and len(_got[0]) == 6,
      str(_got and len(_got[0])))
check("spec_grid_cells: neo cột đúng mép mực trị số",
      _got is not None and abs(_got[1] - 320) < 1.0, str(_got and _got[1]))
check("spec_grid_cells: ô cắt giữa span vẫn ra đúng chữ",
      _got is not None and [_sct(_reg_spec, c) for c in _got[0]]
      == ["Cell Type", "LFP", "Nominal Energy", "5.12kWh", "Weight", "43 kg"],
      str(_got and [_sct(_reg_spec, c) for c in _got[0]]))

# Guard: một hàng đơn độc không dựng nổi lưới (ngưỡng phiếu).
check("spec_grid_cells: một hàng không đủ phiếu", _sgc(_spec_reg([_L1])) is None)
# Guard: cột phải toàn số trang → dòng mục lục, để leader_split lo.
_TOC = [_line(_sp("Chuong mot", 60, 120), _sp("10", 320, 120)),
        _line(_sp("Chuong hai", 60, 140), _sp("11", 320, 140)),
        _line(_sp("Chuong ba", 60, 160), _sp("12", 320, 160))]
check("spec_grid_cells: mục lục (cột phải toàn số trang) bị loại",
      _sgc(_spec_reg(_TOC)) is None)
# Guard: khe từ thường không phải ranh giới cột.
_PROSE = [_line(_sp("mot hai ba bon nam sau bay", 60, 120)),
          _line(_sp("tam chin muoi mot hai ba", 60, 140)),
          _line(_sp("bon nam sau bay tam chin", 60, 160))]
check("spec_grid_cells: văn xuôi không khe rộng thì không có lưới",
      _sgc(_spec_reg(_PROSE)) is None)
# Guard: bảng có kẻ khung là việc của column_split, không phải của lưới space.
check("spec_grid_cells: table_cell không nhận lưới space",
      _sgc(_spec_reg(_SPEC, rtype="table_cell")) is None)

# Phiếu bầu gom theo TRANG: hai region một dòng cùng neo thì dựng được lưới,
# còn tự mỗi region thì không.
_C1 = _spec_reg([_line(_sp("Higher Energy Density", 60, 120),
                       _sp("Lower Resistive Losses", 320, 120))])
_C2 = _spec_reg([_line(_sp("Superior Performance", 60, 160),
                       _sp("Remote Upgrading", 320, 160))])
_pv = _srv(_C1) + _srv(_C2)
check("spec_row_votes: mỗi hàng bỏ đúng một phiếu", len(_pv) == 2, str(_pv))
check("spec_grid_cells: nhãn một dòng cần phiếu cả trang mới thành lưới",
      _sgc(_C1) is None and _sgc(_C1, _pv) is not None)

# spec_grid (stage 6) — hợp đồng đếm và khung ô.
_reg_fit = _spec_reg(_SPEC, "Loai cell\nLFP\nDien nang danh dinh\n5.12kWh\nKhoi luong\n43 kg")
_reg_fit["spec_cells"], _reg_fit["spec_anchor_x"] = _got[0], _got[1]
_subs_spec = _sg(_reg_fit)
check("spec_grid: 6 ô → 6 sub-region", _subs_spec is not None and len(_subs_spec) == 6)
check("spec_grid: ô trái dừng ở neo, ô phải chạy tới mép khung",
      _subs_spec is not None
      and [round(s["container"][2], 1) for s in _subs_spec[:2]] == [round(_got[1], 1), 580.0],
      str(_subs_spec and [s["container"][2] for s in _subs_spec[:2]]))
# Ô số 4 là trị số của hàng gõ liền trong MỘT span: origin của span đó nằm ở x=60 (đầu
# nhãn), mực của trị số bắt đầu sau dãy space. Vẽ từ origin là dồn về cột trái.
check("spec_grid: base_x ô phải là mép mực, không phải origin có đệm space",
      _subs_spec is not None and _subs_spec[3]["lines"][0]["bbox"][0] >= _got[1] - 1.0,
      str(_subs_spec and _subs_spec[3]["lines"][0]["bbox"][0]))
check("spec_grid: ô không được tự nới khung",
      _subs_spec is not None and all(s.get("no_expand") for s in _subs_spec))
_reg_bad = dict(_reg_fit, target_runs=[{"role": "body", "text": "gop het vao mot doan"}])
check("spec_grid: lệch số đoạn thì bỏ lưới (fail-closed)", _sg(_reg_bad) is None)

# target_segments: ranh giới đoạn nằm trong CHỮ, không phải giữa hai run.
_TWO_RUNS = {"target_runs": [{"role": "emphasis", "text": "A"},
                             {"role": "body", "text": "B\nC"}]}
check("target_segments: hai run không tự sinh thêm đoạn",
      [t for t, _ in _tsg(_TWO_RUNS)] == ["AB", "C"])
check("target_segments: role lấy theo run MỞ ĐẦU đoạn",
      [r for _, r in _tsg(_TWO_RUNS)] == ["emphasis", "body"])


# ── mã vận chuyển UN là tiêu chuẩn, không phải model (engine 1.9.32) ──────────────────
# Vùng chỉ chứa dấu `UN38.3` phải ra `keep`: engine không vẽ lại thì glyph gốc (font Impact
# nét đậm, khai bold=False nên map sai sang Noto Sans Regular) được giữ nguyên.
from translate_prep import classify_action as _ca

_m, _map = protect("UN38.3", [])
check("UN38.3 mask trọn thành MỘT placeholder", _m == "⟦STD_1⟧", _m)
check("UN38.3 round-trip đúng nguyên văn", restore(_m, _map) == "UN38.3")
check("vùng chỉ có UN38.3 → keep",
      _ca({"source_text": "UN38.3", "rotation": 0}, set(), len(_map), _m) == ("keep", "protected_only"),
      str(_ca({"source_text": "UN38.3", "rotation": 0}, set(), len(_map), _m)))
_m2, _map2 = protect("UN3480", [])
check("UN3480 cũng là tiêu chuẩn", _m2 == "⟦STD_1⟧", _m2)
# Không được ăn oan chữ thường hay từ có UN dính chữ.
check("`Unit 3` không bị coi là mã UN", "⟦STD" not in protect("Unit 3 hoạt động", [])[0])
check("`UNIT` không bị coi là mã UN", "⟦STD" not in protect("UNIT kiểm tra", [])[0])
# Dòng chứng nhận còn chữ khác thì vẫn phải dịch.
_m3, _map3 = protect("CE, IEC62619, UN38.3", [])
check("dòng chứng nhận nhiều mục vẫn là translate",
      _ca({"source_text": "CE, IEC62619, UN38.3", "rotation": 0}, set(), len(_map3), _m3)[0]
      == "translate")


# ── serif quyết định theo TÊN font, không theo cờ PDF (engine 1.9.33) ─────────────────
# Đo trên nguồn của mọi job: 9 font mang cờ serif thì 8 thực ra là sans. Các case dưới đây
# là font THẬT trong kho, kèm cờ thật của chúng.
from _common import is_serif_font as _isf

for _name, _flag in [("RanyLight", 4), ("RanyRegular", 5), ("RanyBold", 20), ("RanyMedium", 4),
                     ("NotoSansHans-Regular", 4), ("SourceHanSansCN-Medium", 4),
                     ("FandolHei-Regular", 4), ("CTChaoHeiSF", 4), ("STXihei", 4)]:
    check(f"cờ serif nhưng là sans thật: {_name}", _isf(_name, _flag) is False)
check("Song/宋 là serif thật, không bị luật tên làm hỏng",
      _isf("AdobeSongStd-Light", 4) is True)
check("tên có 'Serif' thì là serif dù cờ = 0", _isf("NotoSerif-Regular", 0) is True)
check("Times New Roman là serif dù cờ = 0", _isf("TimesNewRomanPSMT", 0) is True)
check("'Sans Serif' đọc là sans, không phải serif", _isf("DejaVu Sans Serif", 4) is False)
check("prefix subset không làm lệch phán đoán", _isf("ABCDEF+RanyBold", 20) is False)
check("SimSun/宋体 là serif", _isf("SimSun", 0) is True)
check("Mincho là serif", _isf("MS-Mincho", 0) is True)
check("tên lạ, không dấu hiệu → sans (cờ không dùng được)", _isf("Rany", 4) is False)
check("Arial vẫn là sans", _isf("ArialMT", 0) is False)


# `style_of` phải HỎI `is_serif_font`, không được đọc thẳng cờ — nếu không thì luật tên có
# đúng đến đâu cũng vô nghĩa vì stage 2 không dùng tới.
from extract_group import style_of as _so

check("style_of: Rany cờ serif vẫn ra sans",
      _so({"flags": 4, "font": "RanyLight"})["serif"] is False)
check("style_of: Song cờ serif ra serif",
      _so({"flags": 4, "font": "AdobeSongStd-Light"})["serif"] is True)
check("style_of: Times cờ 0 vẫn ra serif",
      _so({"flags": 0, "font": "TimesNewRomanPSMT"})["serif"] is True)
check("style_of: giữ nguyên bold/italic/mono theo cờ",
      _so({"flags": 16 | 2 | 8, "font": "ArialMT"})
      == {"bold": True, "italic": True, "serif": False, "mono": True})


# ── role_style lấy run CÓ NÉT MỰC, không lấy run đầu khớp role (engine 1.9.34) ────────
# Ca thật: HV48100 user manual trang 5 mở đầu bằng một dấu cách font Song (serif) rồi mới
# tới 175 ký tự ArialMT (sans), cả hai role `body`. Lấy run đầu thì cả đoạn ra Noto Serif.
from fit_paint import role_style as _rs

_ws_first = {"runs": [
    {"text": " ", "role": "body", "serif": True, "bold": False, "font": "AdobeSongStd-Light"},
    {"text": "The equipment is damaged", "role": "body", "serif": False, "bold": False,
     "font": "ArialMT"}]}
check("run rỗng đứng trước không quyết định style của role",
      _rs(_ws_first, "body")["font"] == "ArialMT")
check("... và không kéo theo cờ serif của nó",
      _rs(_ws_first, "body")["serif"] is False)

# Không được sửa quá tay: run đầu CÓ mực thì vẫn là nó, dù sau nó có run khác cùng role.
_ink_first = {"runs": [
    {"text": "Cảnh báo", "role": "body", "serif": True, "bold": True, "font": "SimSun"},
    {"text": " tiếp theo", "role": "body", "serif": False, "bold": False, "font": "ArialMT"}]}
check("run đầu có mực vẫn thắng như cũ", _rs(_ink_first, "body")["font"] == "SimSun")

# Mọi run cùng role đều rỗng → không có gì để so, giữ hành vi cũ chứ không nhảy sang role khác.
_all_ws = {"runs": [
    {"text": "  ", "role": "body", "serif": True, "bold": False, "font": "AdobeSongStd-Light"},
    {"text": "Tiêu đề", "role": "heading", "serif": False, "bold": True, "font": "ArialMT"}]}
check("mọi run cùng role đều rỗng thì vẫn lấy run đầu khớp role",
      _rs(_all_ws, "body")["font"] == "AdobeSongStd-Light")

# Role không tồn tại → lùi về runs[0], như cũ.
check("role không có trong runs thì lùi về runs[0]",
      _rs(_ink_first, "caption")["font"] == "SimSun")

# Khoảng trắng không chỉ là U+0020: nbsp/ideographic space cũng không được quyết định style.
_nbsp_first = {"runs": [
    {"text": " 　", "role": "body", "serif": True, "bold": False, "font": "SimSun"},
    {"text": "chữ thật", "role": "body", "serif": False, "bold": False, "font": "ArialMT"}]}
check("nbsp và ideographic space cũng tính là không có mực",
      _rs(_nbsp_first, "body")["font"] == "ArialMT")


# ── role_face: KIỂU CHỮ theo run nhiều mực nhất, MÀU vẫn theo run đầu (engine 1.9.35) ──
# Ca thật: V16 Lite quick guide mở đầu bằng một dấu `：` font Song rồi 210 ký tự ArialMT —
# một ký tự quyết định kiểu chữ cả đoạn, bản đã phát hành ra 7,94% ký tự Noto Serif.
from fit_paint import role_face as _rf

_colon = {"runs": [
    {"text": "：", "role": "body", "serif": True, "bold": False, "color": 0,
     "font": "AdobeSongStd-Light"},
    {"text": "x" * 210, "role": "body", "serif": False, "bold": False, "color": 5789783,
     "font": "ArialMT"}]}
check("một ký tự Song không quyết định kiểu chữ cho 210 ký tự Arial",
      _rf(_colon, "body")["font"] == "ArialMT")
check("... và không kéo theo cờ serif của nó", _rf(_colon, "body")["serif"] is False)

# Chốt chống nới quá tay: MÀU vẫn theo run đầu có mực. Bảng thông số datasheet có nhãn đen
# ngắn + giá trị xám dài; lấy màu theo đa số thì nhãn đen hoá xám — 7 vùng đo được.
check("màu vẫn theo run đầu có mực, không theo run đa số",
      _rs(_colon, "body")["color"] == 0)

# Hoà số ký tự thì giữ run sớm hơn — quyết định phải ổn định giữa các lượt chạy.
_tie = {"runs": [
    {"text": "AAA", "role": "body", "serif": True, "bold": False, "font": "SimSun"},
    {"text": "BBB", "role": "body", "serif": False, "bold": False, "font": "ArialMT"}]}
check("hoà số ký tự thì giữ run sớm hơn", _rf(_tie, "body")["font"] == "SimSun")

# Khoảng trắng không được tính vào "nhiều mực nhất".
_pad = {"runs": [
    {"text": "Cảnh báo", "role": "body", "serif": True, "bold": True, "font": "SimSun"},
    {"text": " " * 80, "role": "body", "serif": False, "bold": False, "font": "ArialMT"}]}
check("run toàn khoảng trắng dù dài vẫn không thắng",
      _rf(_pad, "body")["font"] == "SimSun")

# Mọi run cùng role đều rỗng → lùi về đúng hành vi của role_style.
check("không có run nào có mực thì lùi về role_style",
      _rf(_all_ws, "body")["font"] == "AdobeSongStd-Light")


# ── role suy biến: role của bản dịch chỉ có dấu câu (engine 1.9.36) ───────────────────
# Ca thật: ghi chú "Note：..." của V16 Lite — role `body` đúng một dấu `：` font Song, còn
# `Note` lẫn cả câu sau đều là `emphasis` Arial-BoldMT. Bản dịch một run `body` nên cả câu
# vẽ bằng Noto Serif.
_degen = {"runs": [
    {"text": "Note", "role": "emphasis", "serif": False, "bold": True, "mono": False,
     "font": "Arial-BoldMT"},
    {"text": "：", "role": "body", "serif": True, "bold": False, "mono": False,
     "font": "AdobeSongStd-Light"},
    {"text": "If V16 Lite battery is parallel connected" * 2, "role": "emphasis",
     "serif": False, "bold": True, "mono": False, "font": "Arial-BoldMT"}]}
check("role chỉ có dấu câu thì mượn HỌ CHỮ của run có chữ nhiều mực nhất",
      _rf(_degen, "body")["serif"] is False)
# 4 ký tự đậm + 1 dấu `：` thường + 98 ký tự đậm → khối mực là đậm, khớp bốn ghi chú anh em
# cùng trang mà nguồn cũng đậm.
check("... và mượn ĐỘ ĐẬM theo khối mực lớn nhất", _rf(_degen, "body")["bold"] is True)

# Ca đối nghịch: dòng mục lục V16 Lite là tiêu đề chương ĐẬM 21 ký tự + dãy chấm THƯỜNG 38.
# Đo độ đậm theo run CÓ CHỮ thì đậm nguyên dòng — hỏng 38 ký tự chấm để sửa 21 ký tự tiêu đề.
_toc = {"runs": [
    {"text": "1  Safety Precautions", "role": "emphasis", "serif": False, "bold": True,
     "mono": False, "font": "Arial-BoldMT"},
    {"text": "." * 38, "role": "body", "serif": False, "bold": False, "mono": False,
     "font": "ArialMT"}]}
check("dãy chấm mục lục dài hơn tiêu đề nên dòng vẫn KHÔNG đậm",
      _rf(_toc, "body")["bold"] is False)
check("... và họ chữ vẫn giữ sans như cũ", _rf(_toc, "body")["serif"] is False)

# Ca chốt HỌ CHỮ phải đo trên run CÓ CHỮ-SỐ: ô `（A）` của V5 Series manual là hai dấu ngoặc
# toàn rộng Song bọc một chữ `A` sans. Đo trên mọi run thì dấu ngoặc thắng và ô ra serif;
# đo trên run có chữ-số thì `A` thắng và ra sans — chữ duy nhất trong ô là sans.
_paren = {"runs": [
    {"text": "（", "role": "body", "serif": True, "bold": False, "mono": False,
     "font": "AdobeSongStd-Light"},
    {"text": "A", "role": "emphasis", "serif": False, "bold": True, "mono": False,
     "font": "Arial-BoldMT"},
    {"text": "）", "role": "body", "serif": True, "bold": False, "mono": False,
     "font": "AdobeSongStd-Light"}]}
check("họ chữ đo trên run CÓ CHỮ, không trên dấu ngoặc Song dài bằng",
      _rf(_paren, "body")["serif"] is False)

# Role có chữ thật thì không mượn gì — luật 1.9.35 giữ nguyên.
_normal = {"runs": [
    {"text": "：", "role": "body", "serif": True, "bold": False, "mono": False,
     "font": "AdobeSongStd-Light"},
    {"text": "x" * 210, "role": "body", "serif": False, "bold": False, "mono": False,
     "font": "ArialMT"}]}
check("role đã có chữ thật thì không mượn từ role khác",
      _rf(_normal, "body")["font"] == "ArialMT")

# CJK tính là có chữ — `宋体` không được coi là dấu câu rồi đi mượn họ chữ chỗ khác.
_cjk = {"runs": [
    {"text": "宋体说明", "role": "body", "serif": True, "bold": False, "mono": False,
     "font": "AdobeSongStd-Light"},
    {"text": "x" * 99, "role": "emphasis", "serif": False, "bold": True, "mono": False,
     "font": "Arial-BoldMT"}]}
check("chữ CJK tính là có chữ, không mượn họ chữ chỗ khác",
      _rf(_cjk, "body")["serif"] is True)

# ── ngắt dòng nằm trong placeholder (engine 1.9.37) ──────────────────────────────────
# `\s?` của MEAS_RE khớp cả `\n`, nên số đo bị bản gốc ngắt dòng giữa chừng vào bảng tra
# nguyên dấu xuống dòng rồi theo placeholder vào mọi bản dịch. Fitter coi giá trị là token
# atomic nên không wrap lại được: ô nào cũng xuống dòng đúng chỗ bản gốc xuống, kể cả khi
# khung tiếng Việt còn thừa chỗ. Ca thật: Pi Station 261 EX bảng 3.3.
from translate_prep import unwrap_tokens as _uw

_mw, _mapw = protect("Single cell 2.5V～3.65\nV", [])
check("số đo bị ngắt dòng vẫn mask trọn thành placeholder",
      _mw == "Single cell ⟦MEAS_1⟧～⟦MEAS_2⟧", _mw)
check("protect giữ round-trip nguyên văn kể cả khi có ngắt dòng",
      restore(_mw, _mapw) == "Single cell 2.5V～3.65\nV")
check("bảng đem đi vẽ đã bỏ ngắt dòng trong số đo",
      _uw(_mapw)["MEAS_2"] == "3.65V", str(_uw(_mapw)))
check("nối bằng rỗng, không chèn dấu cách", _uw({"MEAS_1": "55\n°C"})["MEAS_1"] == "55°C")
# Giá trị không có ngắt dòng phải đi qua nguyên vẹn — kể cả số đo vốn có dấu cách.
check("số đo có dấu cách thật giữ nguyên dấu cách",
      _uw({"MEAS_1": "50 mm", "BRAND_1": "Pytes"}) == {"MEAS_1": "50 mm", "BRAND_1": "Pytes"})

# ── chữ nguồn bị ảnh che (engine 1.9.38) ────────────────────────────────────────────
# Engine vẽ bản dịch sau cùng nên chữ mà bản gốc giấu dưới ảnh lại nổi lên TRÊN ảnh ở bản
# dịch. Không gate nào thấy: Gate 3 tìm ra chữ, Gate 4 thấy trong khung, Gate 6 coi là thay
# đổi nằm trong mask. Ca thật: Pi Station 261 EX trang 24.
import tempfile as _oc_tf, os as _oc_os  # noqa: E402
from fit_paint import occluded_by_image as _obi  # noqa: E402

_oc_dir = _oc_tf.mkdtemp()
_oc_path = _oc_os.path.join(_oc_dir, "occl.pdf")
_oc = pymupdf.open()
_ocp = _oc.new_page(width=200, height=200)
_oc_pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 64, 64), False)
_oc_pix.set_rect(_oc_pix.irect, (210, 40, 40))
_ocp.insert_text((20, 100), "hidden caption", fontsize=11)       # chữ vẽ TRƯỚC
_ocp.insert_image(pymupdf.Rect(0, 0, 200, 200), pixmap=_oc_pix)  # ảnh phủ kín trang
_ocp.insert_text((20, 160), "label on top", fontsize=11)         # nhãn vẽ SAU, nhìn thấy
_oc.save(_oc_path)
_oc.close()
_oc = pymupdf.open(_oc_path)
_full = [r for im in _oc[0].get_images(full=True) for r in _oc[0].get_image_rects(im[0])]
check("ảnh thử phủ kín trang", len(_full) == 1 and _full[0].get_area() > 39000, str(_full))
check("chữ bị ảnh phủ kín → nhận ra là bị che",
      _obi(_oc, 0, [20, 88, 120, 103], _full) is True)
check("nhãn vẽ trên cùng → KHÔNG bị coi là bị che",
      _obi(_oc, 0, [20, 148, 120, 163], _full) is False)
check("vùng không nằm trong ảnh nào thì bỏ qua, không dựng ảnh thử",
      _obi(_oc, 0, [20, 88, 120, 103], []) is False)
_oc.close()

# ── preflight: phân loại nguồn (OUTLINED_VECTOR_TEXT / MOJIBAKE_TOUNICODE) ──
# Ba tình huống "trang không có text layer" có tính khả thi TRÁI NGƯỢC nhau và trước đây
# dùng chung một mã lỗi, nên người vận hành không biết nên bỏ cuộc hay đi xin bản gốc:
#   scan raster  → không bao giờ dịch được (fit_paint chạy PDF_REDACT_IMAGE_NONE ở cả 4
#                  lượt redaction và không có đường nào sửa pixel ảnh)
#   chữ outline  → về nguyên tắc dịch được, nhưng cần bản gốc hoặc năng lực trích xuất mới
#   sơ đồ thuần  → đúng là không có chữ, không phải lỗi
import preflight as _pf

_rect = lambda w, h: {"rect": pymupdf.Rect(0, 0, w, h)}
_glyphs = [_rect(6, 9)] * 90            # chữ đã convert thành đường
_diagram = [_rect(180, 120)] * 90       # nét sơ đồ, to hơn glyph nhiều lần

check("chữ outline → tỉ lệ path cỡ glyph cao",
      _pf.outlined_glyph_share(_glyphs) == 1.0)
check("sơ đồ thuần → tỉ lệ path cỡ glyph bằng 0",
      _pf.outlined_glyph_share(_diagram) == 0.0)
# Corpus không có ca âm tính nào — mọi trang vector-suspect thật đều từ 0.90 trở lên. Ngưỡng
# và nửa phân biệt của luật vì thế được khoá ở đây chứ không bằng dữ liệu thật.
check("trang trộn dưới ngưỡng thì KHÔNG phải chữ outline",
      _pf.outlined_glyph_share(_glyphs[:70] + _diagram[:30]) < _pf.OUTLINED_GLYPH_SHARE,
      str(_pf.outlined_glyph_share(_glyphs[:70] + _diagram[:30])))
check("trang gần như toàn glyph thì đúng là chữ outline",
      _pf.outlined_glyph_share(_glyphs[:85] + _diagram[:15]) >= _pf.OUTLINED_GLYPH_SHARE)
check("không có nét vẽ nào thì không kết luận outline",
      _pf.outlined_glyph_share([]) == 0.0)

# ToUnicode hỏng: text layer đọc ra `(XURSHDQ JHQHUDO` trong khi trang hiện `European
# general`. Round-trip của QA vẫn khớp vì cả hai vế đều là rác giống hệt nhau, nên chỉ có
# preflight bắt được — và chỉ bằng cách hỏi chữ có đọc được không.
_shift = lambda t: "".join(chr(ord(c) - 29) if c.isalpha() and c.isascii() else c for c in t)
_en = "the system shall be installed with this bracket and it can not be used for that "
_vi = "hệ thống này phải được lắp với giá đỡ và không thể dùng cho việc khác của các "
check("mojibake rơi dưới ngưỡng", _pf.readable_ratio(_shift(_en) * 30) < _pf.READABLE_RATIO_MIN,
      str(_pf.readable_ratio(_shift(_en) * 30)))
check("tiếng Anh bình thường ở rất xa ngưỡng trên", _pf.readable_ratio(_en * 30) > 0.5)
# Lấy max hai tỉ lệ chứ không cộng: tài liệu thuần tiếng Việt không được bị phạt vì thiếu
# hư từ tiếng Anh.
check("tiếng Việt thuần cũng ở xa ngưỡng trên", _pf.readable_ratio(_vi * 30) > 0.5)
check("quá ít từ Latin thì không phán", _pf.readable_ratio(_en) is None)
check("tài liệu thuần CJK thì không phán", _pf.readable_ratio("电池系统安装说明书 " * 100) is None)

# Bản in "-Q" và bản gốc phải quy về cùng một khoá; đầu ra `_VI` thì không được coi là nguồn.
check("bản -Q và bản gốc cùng khoá",
      _pf._source_key("V16 user manual-PYTES 1.0 20251204(1).pdf").startswith(
          _pf._source_key("V16 user manual-PYTES 1.0 Q 20251021_1761114635329.pdf")[:12]))
check("đầu ra _VI bị loại khỏi ứng viên nguồn",
      bool(_pf._VI_OUTPUT.search("E-Box 48100R guide20251021-Q_VI.pdf")))
check("bản dịch có hash cũng bị loại",
      bool(_pf._VI_OUTPUT.search("v16-quick-guide-vi-a1c48a5b.pdf")))
check("tên tài liệu thật không bị nhầm là đầu ra",
      not _pf._VI_OUTPUT.search("V16 quick guide final-20251204-Q.pdf"))
check("không có đường dẫn gốc thì không dò", _pf.find_editable_source(None) is None)


print()
if FAILURES:
    print(f"SELFTEST FAIL ({len(FAILURES)}/{TOTAL}):")
    for f in FAILURES:
        print(" -", f)
    raise SystemExit(1)
print(f"SELFTEST: ALL PASS ({TOTAL} case)")
