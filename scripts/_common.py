"""Shared job infrastructure for pdf-translate-layout engine scripts.

Spec: docs/system_design_pdf_translation_engine_v1_final.md (rev 1.3).
Job folder contract: SKILL.md §2. All stage scripts import from here.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
import unicodedata

import pymupdf
import yaml

ENGINE_VERSION = "1.9.46"
# Mốc trước: lg-basic-3 tách hàng bảng gõ liền theo lưới cột logic; lg-basic-4 thêm gộp
# cross-block các dòng cùng đoạn.
# lg-basic-5: bbox của line chỉ tính ký tự CÓ MỰC, và hàng đa cột được tách tại MỌI khe
# space có vạch kẻ dọc thật nằm trong khe (không còn đòi ≥2 space, không còn dùng lưới
# logic của find_tables).
LAYOUT_MODEL_VERSION = "lg-basic-5"
# lg-basic-6: lg-basic-5 + gộp CROSS-BLOCK các dòng cùng một đoạn. PDF hay đặt mỗi dòng vào
# một block rawdict riêng (thư ngỏ V16: 28 dòng = 28 block), mà `group_block_lines` chỉ gộp
# trong một block, nên câu bị xé theo dòng và bản dịch không đảo vế qua ranh giới được.
LAYOUT_MODEL_MERGED = "lg-basic-6"


def layout_model_for(cfg: dict) -> str:
    """Layout model thực tế phụ thuộc cờ gộp đoạn — regions.json của cùng một source khác
    hẳn nhau giữa hai chế độ, nên determinism tuple phải phân biệt được."""
    return (LAYOUT_MODEL_MERGED
            if (cfg.get("layout") or {}).get("merge_paragraph", True)
            else LAYOUT_MODEL_VERSION)

# Dung sai container — fit_paint (được phép dôi ra) và qa_gates (chấp nhận phần
# dôi đó) PHẢI đọc cùng con số, nếu không fitter tạo layout mà gate tự báo lỗi.
# Config `qa.container_tol_*` override; hằng này là default cho job cũ thiếu key.
CONTAINER_TOL_PT_DEFAULT = 1.5
CONTAINER_TOL_Y_EM_DEFAULT = 0.6
# Sàn cỡ chữ riêng cho vùng XOAY (1.9.45). Phải dùng CHUNG giữa `fit_paint` và `qa_gates`:
# fitter thu tới sàn nào thì gate phải chấm theo đúng sàn đó, nếu không mọi nhãn xoay thu
# đúng luật đều thành `G4_RATIO_FLOOR` — P0 không waive được. Job đóng băng config trước
# 1.9.45 không có khoá này nên cả hai bên đều rơi về hằng số này.
ROTATED_INK_FLOOR_DEFAULT = 0.80


def vertical_rules(page: pymupdf.Page, tol: float = 0.8) -> list:
    """Nét kẻ dọc THỰC SỰ vẽ trên trang → [(x, y0, y1)].

    Dùng nét vẽ chứ không dùng lưới logic của `find_tables`: ô gộp không có nét
    ngăn nên tiêu đề trải hết bảng là hợp lệ, trong khi lưới logic vẫn báo có
    ranh giới cột ở đó và sinh false positive.

    Đặt ở đây vì hai stage phải đọc CÙNG một danh sách: stage 2 cắt hàng đa cột tại
    các vạch này, stage 7 lấy chính chúng làm chuẩn cho `G4_TABLE_RULE_CROSS`. Hai
    định nghĩa lệch nhau thì fitter tạo layout mà gate tự báo lỗi.
    """
    out = []
    for d in page.get_drawings():
        stroked = d.get("type") in ("s", "fs")
        for it in d["items"]:
            if it[0] == "l":
                p, q = it[1], it[2]
                if abs(p.x - q.x) <= tol and abs(p.y - q.y) > 2:
                    out.append(((p.x + q.x) / 2, min(p.y, q.y), max(p.y, q.y)))
            elif it[0] == "re":
                r = it[1]
                if r.height <= 2:
                    continue
                if r.width <= 1.5:      # thanh mảnh dùng làm vạch kẻ
                    out.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
                elif stroked:           # khung có viền → hai cạnh dọc
                    out.append((r.x0, r.y0, r.y1))
                    out.append((r.x1, r.y0, r.y1))
    return out


# Ô trống điền tay: nét ngang mảnh, đủ dài để viết lên.
FILL_RULE_MAX_H = 1.5
FILL_RULE_MIN_W = 10.0
# Gạch trải gần hết khung region là nét kẻ bảng, không phải chỗ điền.
FILL_RULE_MAX_W_RATIO = 0.9
FILL_RULE_Y_SLACK = 2.0    # gạch nằm ở hoặc ngay dưới baseline
FILL_RULE_ROW_TOL = 2.5    # hai dòng cùng một hàng khi baseline lệch dưới ngần này
FILL_RULE_GAP_TOL = 8.0    # khe cho phép giữa mép chữ và mép gạch


def horizontal_rules(page) -> list:
    """Nét kẻ ngang mảnh LIỀN trên trang → [(x0, y0, x1, y1)].

    Chỉ nhận nét liền: ô trống để người điền tay bao giờ cũng là gạch liền, còn nét ĐỨT ngang
    trong tài liệu này là **gạch dẫn mục lục**. Thiếu vế đó thì `fill_in_rules` nhận nhầm ba
    dòng mục lục V5 thành ô trống và `fit_paint` bắn `FILL_BLANK_DROPPED` — báo giả mà reviewer
    phải waive ở mọi tài liệu có mục lục. Tệ hơn: nếu bản dịch tình cờ có dãy `____` thì lượt
    xoá gạch-ô-trống sẽ xoá luôn gạch dẫn.
    Đo trên kho: 5 bản Terms of Warranty — đúng loại tài liệu tính năng này sinh ra để phục vụ
    — có **15-16 nét kẻ ngang mảnh mỗi bản, 0 nét đứt**; ba nét đứt duy nhất trong cả kho là
    gạch dẫn mục lục V5. Chốt này bỏ đúng ba ca oan, không bỏ sót ca thật nào.
    """
    return [(d["rect"].x0, d["rect"].y0, d["rect"].x1, d["rect"].y1)
            for d in page.get_drawings()
            if d["rect"].height <= FILL_RULE_MAX_H and d["rect"].width >= FILL_RULE_MIN_W
            and d.get("dashes") in (None, "", "[] 0")]


def fill_in_rules(reg: dict, page_rules: list) -> list:
    """Nét gạch chân dành cho người điền tay, nằm GIỮA chữ của region → [[x0,y0,x1,y1]].

    Biểu mẫu (Terms of Warranty, thoả thuận đại lý) chừa chỗ điền bằng một nét vẽ vector.
    Mask cố ý không xoá line-art nên nét đó sống qua paint, trong khi `tokenize` gộp mọi
    khoảng trắng thành một dấu cách — bản dịch không tạo lại được khe, chữ chạy đè lên gạch
    và ô trống hết dùng được.

    Điều kiện quyết định là **có chữ ở CẢ HAI phía trên cùng một hàng**. Luật lỏng hơn (chỉ
    đòi gạch nằm trong dải mực của một dòng) đo trên 5 tài liệu cho 6 đúng / **11 oan** —
    toàn bộ 11 ca oan là nhãn chú thích hình có đường dẫn ngang (`Handle`, `Drill template`,
    `Battery side wall-mounted bracket` của Lite quick guide), nơi chữ chỉ nằm một bên.
    Thêm điều kiện hai phía: **6 đúng / 0 oan** trên cùng tập đo.
    """
    c = reg["container"]
    cw = c[2] - c[0]
    hits = []
    for x0, y0, x1, y1 in page_rules:
        if x1 - x0 > FILL_RULE_MAX_W_RATIO * cw:
            continue
        band = [ln for ln in reg["lines"]
                if ln["bbox"][1] <= y0 <= ln["bbox"][3] + FILL_RULE_Y_SLACK]
        if not band:
            continue
        ybase = min(l["spans"][0]["origin"][1] for l in band)
        row = [ln for ln in reg["lines"]
               if abs(ln["spans"][0]["origin"][1] - ybase) <= FILL_RULE_ROW_TOL]
        left = any(abs(ln["bbox"][2] - x0) <= FILL_RULE_GAP_TOL for ln in row)
        right = any(abs(ln["bbox"][0] - x1) <= FILL_RULE_GAP_TOL for ln in row)
        if left and right:
            hits.append([x0, y0, x1, y1])
    return hits


FONT_SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")
# Dấu hiệu SERIF trong tên font, gồm cả tên họ chữ CJK có chân (Song/宋, Ming/明, Mincho,
# Batang). `roman` bắt "Times New Roman"; `sans` được xét TRƯỚC nên "Sans Serif" không dính.
SERIF_NAME_HINTS = ("serif", "times", "roman", "georgia", "garamond", "palatino",
                    "baskerville", "caslon", "century", "cambria", "constantia", "didot",
                    "charter", "charis", "utopia", "bookman", "slab", "song", "sung",
                    "ming", "mincho", "batang", "kai", "fangsong", "simsun", "nsimsun")
# Dấu hiệu SANS. `hei`/黑体 và `gothic`/ゴシック là tên họ chữ không chân của CJK.
SANS_NAME_HINTS = ("sans", "arial", "helvetica", "calibri", "verdana", "tahoma", "segoe",
                   "roboto", "lato", "futura", "avenir", "franklin", "myriad", "impact",
                   "frutiger", "univers", "gill", "grotesk", "grotesque", "inter",
                   "hei", "gothic", "yahei", "dengxian", "yuanti", "quan")


def is_serif_font(name: str, flags: int = 0) -> bool:
    """Font có chân hay không, quyết định theo TÊN chứ không theo cờ của PDF.

    Cờ `serif` (bit 2 của `flags`, tức FontDescriptor /Flags bit 2) là thứ bộ sinh PDF tự
    khai và trong kho này **sai gần như toàn bộ**: đo trên nguồn của mọi job, 9 font mang cờ
    serif thì **8 thực ra là sans** — `RanyLight/Regular/Medium/Bold` (font thương hiệu, sans
    hình học), `NotoSansHans-Regular` và `SourceHanSansCN-Medium` (chữ "Sans" nằm ngay trong
    tên), `FandolHei-Regular`, `CTChaoHeiSF`, `STXihei` (Hei/黑体 = không chân). Đúng đúng
    MỘT font: `AdobeSongStd-Light` (Song/宋体 = có chân). Hệ quả: bốn datasheet Pytes ra
    79-98% ký tự Noto **Serif** trong khi bản gốc là sans.

    Nên: tên nói gì thì nghe tên. `sans` xét trước `serif` để "Sans Serif" không bị đọc nhầm.
    Tên không có dấu hiệu nào → **sans**, vì cờ đã chứng minh là không dùng được và tài liệu
    kỹ thuật gần như luôn dùng sans; đoán sai theo chiều này chỉ mất phần chân chữ, còn đoán
    sai chiều kia làm cả tài liệu tiếp thị đổi giọng.
    """
    n = FONT_SUBSET_PREFIX_RE.sub("", name or "").lower()
    if any(k in n for k in SANS_NAME_HINTS):
        return False
    return any(k in n for k in SERIF_NAME_HINTS)


BOLD_NAME_HINTS = ("bold", "black", "heavy", "semibold", "demibold", "medium")
REGULAR_NAME_HINTS = ("light", "thin", "regular", "book", "roman")


def is_bold_font(name: str, flags: int = 0) -> bool:
    """Chữ đậm hay không: TÊN font nói trước, cờ của PDF chỉ dùng khi tên câm.

    Cùng lý lẽ `is_serif_font` (1.9.33): cờ là thứ bộ sinh PDF tự khai và nó nói dối. Ca thật
    catalogue trang 53-54: `RanyMedium` khai `bold=False` trong khi mắt thấy rõ nó nặng hơn
    `RanyLight`/`RanyRegular` của cùng họ — nên phần MÔ TẢ phụ kiện vẽ ra mảnh y như mã hàng,
    mất hẳn tương phản mà bản gốc dựng.

    Khác `is_serif_font` ở một chỗ: tên KHÔNG có dấu hiệu trọng lượng thì **trả về cờ**, không
    trả mặc định. Font subset tên tự sinh (`CIDFont+F1`) không nói gì về trọng lượng, mà đo
    trên kho thì cờ của chúng đúng — 803 ký tự khai `bold=True` và đúng là chữ đậm. Bỏ vế này
    là làm hỏng chúng để sửa một họ font khác.

    `medium` xếp vào nhóm đậm vì font pack chỉ có hai trọng lượng: Regular và Bold. Trong một
    họ bốn nấc (Light/Regular/Medium/Bold) thì Medium thuộc nửa nặng, và nhiệm vụ ở đây là tái
    tạo TƯƠNG PHẢN của bản gốc chứ không phải khớp tuyệt đối trọng lượng.
    """
    n = FONT_SUBSET_PREFIX_RE.sub("", name or "").lower()
    if any(k in n for k in BOLD_NAME_HINTS):
        return True
    if any(k in n for k in REGULAR_NAME_HINTS):
        return False
    return bool(flags & 16)


SPEC_COL_X_TOL = 3.0       # hai hàng coi là cùng một neo cột khi mép mực lệch dưới ngần này
SPEC_ROW_Y_TOL = 2.0       # hai span cùng một hàng khi baseline lệch dưới ngần này
SPEC_MIN_ANCHOR_ROWS = 2   # neo cột phải phải có mặt ở ít nhất ngần này HÀNG cùng trang
SPEC_MIN_GAP_PT = 30.0     # và cách mép trái vùng ít nhất ngần này
SPEC_MIN_PAD_PT = 12.0     # khe ngăn cột phải rộng ít nhất ngần này
PAGE_NUM_RE = re.compile(r"\d{1,3}")   # cột phải toàn số kiểu này = dòng mục lục


SPEC_TYPES = ("paragraph", "figure_caption", "list_item")


def _spec_rows(reg: dict):
    """→ (baseline từng hàng, [(li, si, ci, char)] ký tự CÓ MỰC, mép mực trái vùng) hoặc None.

    Đơn vị đo là KÝ TỰ, không phải span: nhãn tính năng hai cột của tờ rơi nằm gọn trong MỘT
    span (hai cột cùng font cùng cỡ, ngăn nhau bằng dãy space giữa span), nên đo theo span
    thì cả hàng chỉ có một mốc và không khe nào đo được.
    """
    if reg.get("region_type") not in SPEC_TYPES or reg.get("rotation") != 0:
        return None
    lines = reg.get("lines") or []
    ink = [(li, si, ci, ch)
           for li, ln in enumerate(lines)
           for si, sp in enumerate(ln.get("spans") or [])
           for ci, ch in enumerate(sp.get("chars") or [])
           if not ch.get("c", "").isspace()]
    if not ink:
        return None
    rows: list[float] = []
    for _, _, _, ch in ink:
        y = ch["origin"][1]
        if not any(abs(y - r) <= SPEC_ROW_Y_TOL for r in rows):
            rows.append(y)
    rows.sort()
    return rows, ink, min(ch["bbox"][0] for *_, ch in ink)


def _row_of(rows: list, y: float) -> int:
    return min(range(len(rows)), key=lambda k: abs(y - rows[k]))


def spec_row_votes(reg: dict) -> list[float]:
    """Ứng viên neo cột của từng HÀNG: mép mực ngay sau khe mực rộng nhất của hàng đó.

    Mỗi hàng bỏ đúng một phiếu. Cụm ký tự rời rạc bên trong một ô (`0°C~45°C(32°F~113°F)`)
    vì thế không dựng nổi neo giả — đo trên HV48100 BMU: luật "x lặp ở ≥3 hàng" cho 7 neo
    ứng viên, luật khe cho 1.
    """
    got = _spec_rows(reg)
    if not got:
        return []
    rows, ink, left = got
    out = []
    for r in range(len(rows)):
        cur = sorted((ch["bbox"][0], ch["bbox"][2])
                     for *_, ch in ink if _row_of(rows, ch["origin"][1]) == r)
        best, at, reach = 0.0, None, cur[0][1]
        for x0, x1 in cur[1:]:
            if x0 - reach > best:
                best, at = x0 - reach, x0
            reach = max(reach, x1)
        if at is not None and best >= SPEC_MIN_PAD_PT and at - left >= SPEC_MIN_GAP_PT:
            out.append(at)
    return out


def spec_grid_cells(reg: dict, page_votes=()) -> tuple[list[dict], float] | None:
    """Khối hai cột căn bằng space → ([ô theo thứ tự đọc], x neo cột phải), hoặc None.

    Tờ rơi datasheet dàn bảng thông số bằng **dãy space** chứ không kẻ khung, nên
    `find_tables` không thấy bảng và cả khối rơi vào MỘT region `paragraph`. `tokenize` bỏ
    sạch khoảng trắng, `fit_region` vẽ mọi dòng từ `base_x`, và `line_baselines` có luật
    `max(neo, trước + leading)` nên ô trị số không bao giờ nằm cạnh ô nhãn được — cả bảng
    dồn về một cột trái. Ca thật: trang thông số của cả bốn datasheet Pytes.

    `column_split` (1.9.0) không cứu được: nó chốt `table_cell` và dựng cho MỘT hàng nhiều
    cột, còn đây là khối NHIỀU hàng.

    Bằng chứng để coi là lưới thật chứ không phải thụt lề là **phiếu bầu neo cột**
    (`spec_row_votes`): ít nhất `SPEC_MIN_ANCHOR_ROWS` hàng CÙNG TRANG phải trỏ vào một x.
    Phiếu tính trên cả trang chứ không riêng trong vùng, vì cùng một lưới hay bị cắt thành
    nhiều region: ba nhãn tính năng của tờ rơi mỗi cái là một region MỘT dòng, tự nó không
    lặp lại được gì, nhưng ba cái cùng bầu một x thì lưới là có thật. Vùng chỉ nhận lưới khi
    CHÍNH NÓ có phiếu ở neo đó — trang có lưới không biến mọi vùng thành lưới.

    Ô là một dải KÝ TỰ `[li, si, c0, c1)`, không phải cả span: hai cột hay nằm chung một span
    khi cùng font cùng cỡ.

    Fail-closed ở mọi chỗ mơ hồ: hai neo cùng thắng, hoặc một hàng có mực trái chờm qua mực
    phải, thì trả None — engine không đoán lưới.
    """
    got = _spec_rows(reg)
    if not got:
        return None
    rows, ink, _ = got
    mine = spec_row_votes(reg)
    if not mine:
        return None

    votes = list(page_votes) or list(mine)
    tally = [(x, sum(1 for v in votes if abs(v - x) <= SPEC_COL_X_TOL)) for x in set(mine)]
    top = max(n for _, n in tally)
    winners = [x for x, n in tally if n == top]
    if top < SPEC_MIN_ANCHOR_ROWS or max(winners) - min(winners) > SPEC_COL_X_TOL:
        return None
    anchor = min(winners)

    # Gom ký tự thành dải liền mạch theo (hàng, cột, span). Cột phải = mọi ký tự có mực từ
    # neo trở đi, không riêng ký tự ĐÚNG tại neo: một trị số trải dài về bên phải.
    cells: dict[tuple[int, int], list] = {}
    for li, si, ci, ch in ink:
        key = (_row_of(rows, ch["origin"][1]),
               1 if ch["bbox"][0] >= anchor - SPEC_COL_X_TOL else 0)
        cur = cells.setdefault(key, [])
        # Nới dải qua cả khoảng trắng nằm giữa: chữ trong một ô cách nhau bằng dấu cách bình
        # thường, bỏ chúng thì `spec_cell_text` ra "ControllerWorkingVoltage". Một span bị
        # cắt nhiều nhất một lần (tại neo) nên dải vẫn liền mạch theo thứ tự đọc.
        if cur and cur[-1][0] == li and cur[-1][1] == si:
            cur[-1][3] = ci + 1
        else:
            cur.append([li, si, ci, ci + 1])
    right = [k for k in cells if k[1] == 1]
    if not right:
        return None

    # Dòng MỤC LỤC cũng là hai cột căn bằng space, nhưng cột phải chỉ có số trang và
    # `leader_split`/`dot_leader` đã lo đúng ca đó — nhận nhầm ở đây sẽ giành mất chúng.
    # Chữ ký hẹp: cột phải toàn số nguyên 1-3 chữ số. Trị số thật luôn mang đơn vị hoặc dấu.
    if all(PAGE_NUM_RE.fullmatch(spec_cell_text(reg, {"spans": cells[k]})) for k in right):
        return None

    # Hai cột phải TÁCH BẠCH trên mọi hàng: mực của ô trái phải dừng trước ô phải. Chồng lấn
    # nghĩa là neo cắt ngang một cụm chữ liền mạch — đó là thụt lề chứ không phải lưới.
    def ink_x(k):
        box = [reg["lines"][li]["spans"][si]["chars"][c]["bbox"]
               for li, si, c0, c1 in cells[k] for c in range(c0, c1)]
        return min(b[0] for b in box), max(b[2] for b in box)

    for r in range(len(rows)):
        if (r, 0) in cells and (r, 1) in cells \
                and ink_x((r, 0))[1] > ink_x((r, 1))[0] + SPEC_COL_X_TOL:
            return None
    return ([{"row": r, "col": c, "spans": cells[(r, c)]}
             for r, c in sorted(cells)], anchor)


def spec_cell_text(reg: dict, cell: dict) -> str:
    """Chữ nguồn của một ô — dùng cho cảnh báo stage 3 và thông điệp validate."""
    lines = reg["lines"]
    return "".join(lines[li]["spans"][si]["text"][c0:c1]
                   for li, si, c0, c1 in cell["spans"]).strip()


SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(SKILL_ROOT, "assets")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")

# State machine — spec §11.5. Value: các trạng thái được phép chuyển đến.
STATUS_TRANSITIONS = {
    "INGESTED": {"PREFLIGHTED", "CANCELLED"},
    "PREFLIGHTED": {"TRANSLATED", "MANUAL_DTP", "REJECTED", "CANCELLED"},
    "TRANSLATED": {"RENDERED", "CANCELLED"},
    "RENDERED": {"NEEDS_REVIEW", "AUTO_QA_PASS", "CANCELLED"},
    "NEEDS_REVIEW": {"TRANSLATED", "HUMAN_APPROVED", "MANUAL_DTP", "REJECTED", "CANCELLED"},
    "AUTO_QA_PASS": {"HUMAN_APPROVED", "CANCELLED"},
    "HUMAN_APPROVED": {"RELEASED", "CANCELLED"},
    "RELEASED": {"REVOKED"},           # thu hồi release (approve.py --decision revoke)
    "REVOKED": {"TRANSLATED", "CANCELLED"},  # re-run stage 4-8 sau khi thu hồi
    "MANUAL_DTP": set(),
    "REJECTED": set(),
    "CANCELLED": set(),
}

# Status mà stage 2/3/5 chạy lại được. `REVOKED` có trong danh sách vì thu hồi tồn tại để
# sửa lỗi của bản đã phát hành — kể cả lỗi LAYOUT, mà sửa layout thì bắt buộc re-run từ
# stage 2. Trước 1.8.0 chỉ `validate_responses` nhận REVOKED, hai stage kia thì không, nên
# thu hồi xong là bế tắc. Mọi status ở đây phải đi tới được TRANSLATED (xem selftest).
RERUNNABLE_STATUSES = ("PREFLIGHTED", "NEEDS_REVIEW", "REVOKED")

SEVERITIES = ("P0", "P1", "P2")


class BlockingError(Exception):
    """Fail-closed: lỗi chặn stage; caller thoát exit code 2."""


def refuse_if_released(job, stage: str) -> None:
    """Chặn stage render/QA chạy trên job đã RELEASED.

    Vì sao: `approve.py` **copy** `render/draft.pdf` sang `output/translated-approved.pdf`.
    Chạy lại `fit_paint` sau đó làm draft đổi mà file trong `output/` giữ nguyên — job vẫn
    ghi RELEASED trong khi file mang nhãn "approved" là bản cũ. Sự cố thật 2026-08-06: bản
    phát hành thiếu đúng ba sửa đổi vừa được yêu cầu, chỉ phát hiện nhờ so sha256 bằng tay.

    Muốn sửa tiếp thì `approve.py --decision revoke` trước — revoke tự đổi tên output thành
    `REVOKED-<ts>.pdf` nên dấu vết luôn khớp trạng thái. Muốn thử engine mới trên bản đã phát
    hành thì chạy trên BẢN SAO của job.
    """
    if job.status() == "RELEASED":
        raise BlockingError(
            f"{stage}: job đang RELEASED — chạy lại sẽ làm render/draft.pdf lệch khỏi "
            "output/translated-approved.pdf đã duyệt. Thu hồi trước "
            "(`approve.py --decision revoke`), hoặc thử nghiệm trên bản sao của job.")


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def slug(stem: str, max_len: int = 60) -> str:
    s = stem.lower()
    s = re.sub(r"[^a-z0-9_-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:max_len] or "pdf"


def new_job_id(pdf_path: str, source_sha256: str) -> str:
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{slug(stem)}__{source_sha256[:8]}__{ts}"


def load_json(path: str, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def append_jsonl(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(path: str) -> list:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def load_default_config() -> dict:
    with open(os.path.join(ASSETS_DIR, "engine_config_default.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Translation authenticity (chống pseudo-translation / copy-through) ──
# Sự cố 2026-08-04: agent thay stage 4 bằng script dictionary → 76% target trùng
# source. Các heuristic dưới đây là input cho P0 gate không waive được.
_AUTH_PH_RE = re.compile(r"⟦[A-Z]+_\d+⟧")
# [^\W\d_] = unicode letter thuần — KHÔNG dùng dải À-ỹ vì nó chứa cả ký hiệu ×, ÷
_AUTH_WORD_RE = re.compile(r"[^\W\d_]{3,}")
_AUTH_LETTER_RE = re.compile(r"[^\W\d_]")
_AUTH_VI_RE = re.compile(r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọ"
                         r"ốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", re.IGNORECASE)


def authenticity_check(source: str, target: str, target_lang: str = "vi",
                       min_words: int = 4, keep_terms=()) -> str | None:
    """Phân loại một cặp source/target của translate-region.

    Trả về:
      None           — không có dấu hiệu bất thường (hoặc region quá ngắn để xét)
      "identical"    — region đáng dịch nhưng target trùng source (chưa dịch)
      "lang_suspect" — target dài nhưng gần như không có chữ tiếng Việt
                       (chỉ xét khi target_lang == "vi")
      "truncated"    — target mất khối lượng nội dung so với source. Hai mức:
                       (a) source >=6 từ mà target <45% — sự cố 2026-08-04 #3
                           (mục an toàn 147→29 từ) và 2026-08-05 (câu miễn trừ
                           trách nhiệm 11 từ bị ghi đè bằng tiêu đề 3 từ — sàn
                           cũ 12 từ để lọt đúng vì thiếu 1 từ);
                       (b) source >=12 từ mà target <60% — audit bản Lite đã
                           RELEASED tìm thấy 9 region mất nguyên câu an toàn
                           (cấm ngắn mạch, cấm nối tiếp, tiếp địa, Bước 1 lắp
                           đặt) đều nằm ở ratio 0.45–0.59, trong khi mọi cột
                           dịch đạt không có cặp nào dưới 0.60. Bản dịch VI
                           chuẩn của tài liệu này giữ >=75% số từ EN.
    """
    src = _AUTH_PH_RE.sub(" ", source)
    tgt = _AUTH_PH_RE.sub(" ", target)
    # Region mà source CHỈ gồm thuật ngữ `keep` của glossary thì giữ nguyên là đúng, không
    # phải "chưa dịch". Ca thật: `Shanghai PYTES Energy Co., Ltd.` — glossary ghi rõ keep vì
    # là tên pháp nhân, nhưng Gate 2 vẫn báo TRANSLATION_IDENTICAL và làm gate đỏ.
    # Chỉ bỏ qua khi KHÔNG còn từ nào ngoài các term đó; region lẫn văn xuôi vẫn được xét.
    if keep_terms:
        residue = src
        for term in sorted(keep_terms, key=len, reverse=True):
            if term:
                residue = re.sub(rf"(?i)(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])",
                                 " ", residue)
        if not _AUTH_WORD_RE.findall(residue):
            return None
    # URL/email là nội dung không dịch — loại khỏi phép đo để không làm nhiễu
    # word-count lẫn tỷ lệ dấu tiếng Việt (edge: gate2 đo trên text đã restore
    # placeholder nên URL thật xuất hiện trong target).
    _noise = re.compile(r"(?:https?://|www\.)\S+|\S+@\S+\.\S+")
    src = _noise.sub(" ", src)
    tgt = _noise.sub(" ", tgt)
    if len(_AUTH_WORD_RE.findall(src)) < min_words:
        return None  # label/số/địa chỉ ngắn — identical hợp lệ
    src_c = re.sub(r"\s+", " ", src).strip().lower()
    tgt_c = re.sub(r"\s+", " ", tgt).strip().lower()
    if src_c == tgt_c:
        return "identical"
    src_w = len(_AUTH_WORD_RE.findall(src))
    tgt_w = len(_AUTH_WORD_RE.findall(tgt))
    if src_w >= 6 and tgt_w < 0.45 * src_w:
        return "truncated"
    if src_w >= 12 and tgt_w < 0.60 * src_w:
        return "truncated"
    if target_lang == "vi":
        alpha = _AUTH_LETTER_RE.findall(tgt)
        if len(alpha) >= 20 and len(_AUTH_VI_RE.findall(tgt)) / len(alpha) < 0.05:
            return "lang_suspect"
    return None


def authenticity_cfg(cfg: dict) -> dict:
    """Ngưỡng authenticity từ engine config, default an toàn cho job cũ."""
    a = cfg.get("translation", {}).get("authenticity", {})
    return {"identical_ratio_max": a.get("identical_ratio_max", 0.05),
            "lang_suspect_ratio_max": a.get("lang_suspect_ratio_max", 0.05),
            "min_words": a.get("min_words", 4)}


def make_issue(code: str, severity: str, stage: str, detail: str,
               page: int | None = None, region_id: str | None = None) -> dict:
    assert severity in SEVERITIES, severity
    return {"code": code, "severity": severity, "stage": stage, "detail": detail,
            "page": page, "region_id": region_id, "ts": utc_now()}


class Job:
    """Một PDF = một job directory (SKILL.md §2-3)."""

    SUBDIRS = ("input", "model", "translation", "render", "qa/page_png", "qa/diffs",
               "review", "output", "logs")

    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    # ── paths ──
    def p(self, *parts: str) -> str:
        return os.path.join(self.root, *parts)

    @property
    def yaml_path(self) -> str:
        return self.p("input", "job.yaml")

    @property
    def source_pdf(self) -> str:
        return self.p("input", "source.pdf")

    def ensure_dirs(self) -> None:
        for d in self.SUBDIRS:
            os.makedirs(self.p(d), exist_ok=True)

    # ── job.yaml ──
    def load(self) -> dict:
        with open(self.yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def save(self, meta: dict) -> None:
        tmp = self.yaml_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, self.yaml_path)

    @property
    def config(self) -> dict:
        return self.load()["config"]

    # ── fingerprint (SKILL.md §3: resume phải re-verify) ──
    def verify_fingerprint(self) -> None:
        meta = self.load()
        actual = sha256_file(self.source_pdf)
        if actual != meta["determinism"]["source_sha256"]:
            raise BlockingError(
                f"source fingerprint mismatch: job.yaml={meta['determinism']['source_sha256'][:12]} "
                f"actual={actual[:12]} — source đã thay đổi, tạo job mới thay vì resume")

    # ── status ──
    def status(self) -> str:
        return self.load()["status"]

    def set_status(self, new: str, note: str = "") -> None:
        meta = self.load()
        cur = meta["status"]
        if new == cur:
            return
        if new not in STATUS_TRANSITIONS.get(cur, set()):
            raise BlockingError(f"illegal status transition {cur} -> {new}")
        meta["status"] = new
        meta.setdefault("status_history", []).append(
            {"from": cur, "to": new, "ts": utc_now(), "note": note})
        self.save(meta)
        self.log_event("status", "info", "STATUS", f"{cur} -> {new} {note}".strip())

    def mark_stage(self, stage: str, state: str = "done") -> None:
        meta = self.load()
        meta.setdefault("stages", {})[stage] = {"state": state, "ts": utc_now()}
        # Đóng dấu engine ở MỌI stage. 1.8.0 mới chỉ cho `extract_group` làm mới, nên job
        # chạy tiếp fit_paint/qa/approve bằng engine mới hơn vẫn khai engine của lần extract
        # cuối — đo được 2026-08-06: ba job khai 1.8.0 trong khi render và QA do 1.8.1/1.8.2
        # sinh ra. Tuple determinism phải tả đúng engine đã chạm vào job lần cuối, nếu không
        # người tái lập job sẽ checkout nhầm phiên bản.
        meta.setdefault("determinism", {})["engine_version"] = ENGINE_VERSION
        self.save(meta)

    # ── structured log (spec §16) ──
    def log_event(self, stage: str, level: str, code: str, msg: str,
                  page: int | None = None, region_id: str | None = None) -> None:
        append_jsonl(self.p("logs", "events.jsonl"),
                     {"ts": utc_now(), "stage": stage, "level": level, "code": code,
                      "msg": msg, "page": page, "region_id": region_id})

    # ── lock (SKILL.md §3: single-writer) ──
    def acquire_lock(self, stage: str):
        return _JobLock(self, stage)

    # ── issues gộp từ mọi artifact (cho summary/qa) ──
    def collect_issues(self) -> list:
        issues = []
        pf = load_json(self.p("model", "preflight.json"))
        if pf:
            issues += pf.get("issues", [])
        for name in ("regions_issues", "validate_issues"):
            issues += load_json(self.p("model", f"{name}.json"), [])
        rm = load_json(self.p("render", "render_manifest.json"))
        if rm:
            issues += rm.get("issues", [])
        qa = load_json(self.p("qa", "report.json"))
        if qa:
            issues += qa.get("issues", [])
        return issues

    def severity_counts(self, issues: list | None = None) -> dict:
        issues = self.collect_issues() if issues is None else issues
        out = {s: 0 for s in SEVERITIES}
        for i in issues:
            out[i["severity"]] = out.get(i["severity"], 0) + 1
        return out

    # ── JOB_SUMMARY.md ──
    def write_summary(self, next_action: str) -> None:
        meta = self.load()
        issues = self.collect_issues()
        sev = self.severity_counts(issues)
        lines = [
            f"# JOB SUMMARY — {meta['job_id']}",
            "",
            f"- **Status:** {meta['status']}",
            f"- **Source:** `{os.path.basename(meta['source_name'])}` "
            f"(sha256 `{meta['determinism']['source_sha256'][:12]}…`, {meta['page_count']} trang)",
            f"- **Ngôn ngữ:** {meta['config']['languages']['source']} → {meta['config']['languages']['target']}",
            f"- **Issues:** P0={sev['P0']}  P1={sev['P1']}  P2={sev['P2']}",
            f"- **Cập nhật:** {utc_now()}",
            "",
            "## Stages",
            "",
            "| Stage | Trạng thái |",
            "|---|---|",
        ]
        for st in ("preflight", "extract_group", "translate_prep", "translate",
                   "validate", "fit_paint", "qa", "approve"):
            info = meta.get("stages", {}).get(st)
            lines.append(f"| {st} | {info['state'] + ' ' + info['ts'] if info else 'pending'} |")
        if issues:
            lines += ["", "## Issues (mới nhất 30)", "",
                      "| Severity | Code | Page | Region | Detail |", "|---|---|---|---|---|"]
            for i in issues[-30:]:
                lines.append(f"| {i['severity']} | {i['code']} | {i.get('page','')} | "
                             f"{(i.get('region_id') or '')[:24]} | {i['detail'][:90]} |")
        lines += ["", "## Next action", "", next_action, ""]
        with open(self.p("JOB_SUMMARY.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


class _JobLock:
    def __init__(self, job: Job, stage: str):
        self.job, self.stage = job, stage
        self.path = job.p(".lock")

    def __enter__(self):
        # Mọi stage đều vào qua đây, nên đây là chỗ duy nhất bảo đảm được cây thư mục job.
        # `ensure_dirs()` trước 1.9.2 chỉ chạy MỘT LẦN ở preflight, nên job nào thiếu thư
        # mục thì mọi stage sau đổ ngay tại lệnh ghi: `Job.p()` chỉ ghép chuỗi, không tạo
        # thư mục. Hai ca thật đều cùng gốc này: 2026-08-06 `output/` không có nên
        # `copyfile` của approve ném FileNotFoundError (vá cục bộ ở 1.8.2), và
        # `qa_gates` lưu PNG vào `qa/page_png/` cũng đổ y hệt khi thư mục vắng.
        # Thư mục RỖNG biến mất qua git/zip/rsync và job dựng bằng engine cũ có SUBDIRS
        # ngắn hơn — nên không thể coi "preflight đã tạo rồi" là bảo đảm.
        self.job.ensure_dirs()
        if os.path.exists(self.path):
            try:
                old = json.load(open(self.path, encoding="utf-8"))
                os.kill(old["pid"], 0)  # raises nếu pid chết
                raise BlockingError(f"job đang bị lock bởi pid {old['pid']} (stage {old['stage']})")
            except (ProcessLookupError, PermissionError, ValueError, KeyError, json.JSONDecodeError):
                pass  # stale lock → takeover
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "stage": self.stage, "ts": utc_now()}, f)
        return self

    def __exit__(self, *exc):
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass
        return False


def load_glossary(job: Job) -> list[dict]:
    """Glossary đã freeze trong input/, fallback default của skill."""
    import csv
    path = job.p("input", "glossary.csv")
    if not os.path.exists(path):
        path = os.path.join(ASSETS_DIR, "default_glossary.csv")
    out = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("term"):
                out.append({"term": row["term"].strip(), "type": row.get("type", "keep").strip(),
                            "target": (row.get("target") or "").strip()})
    return out


def exit_blocking(job: Job | None, stage: str, err: BlockingError) -> None:
    msg = str(err)
    if job is not None:
        job.log_event(stage, "error", "BLOCKING", msg)
        try:
            job.write_summary(f"BLOCKED tại stage `{stage}`: {msg}")
        except Exception:
            pass
    print(f"BLOCKING [{stage}]: {msg}", file=sys.stderr)
    sys.exit(2)
