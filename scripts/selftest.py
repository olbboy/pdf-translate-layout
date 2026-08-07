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
from extract_group import build_lines, fragment_row, ink_bbox, split_multicol_rows
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
check("base_x: region không có lines thì trả nguyên span_x",
      _fp.ink_base_x({"lines": []}, 45.7) == 45.7)

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

# ── tổng kết ────────────────────────────────────────────────────────────
# PHẢI là thứ cuối cùng trong file. Trước 1.8.0 khối này nằm giữa file, nên ~100 case
# thêm sau nó (context graph, gộp đoạn, chốt RELEASED, hướng nới dự phòng) in "FAIL"
# mà tiến trình vẫn thoát 0 và dòng tổng kết vẫn nói ALL PASS.
print()
if FAILURES:
    print(f"SELFTEST FAIL ({len(FAILURES)}/{TOTAL}):")
    for f in FAILURES:
        print(" -", f)
    raise SystemExit(1)
print(f"SELFTEST: ALL PASS ({TOTAL} case)")
