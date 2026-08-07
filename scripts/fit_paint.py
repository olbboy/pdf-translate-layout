"""Stage 6 — Fit + safe paint: font resolve, constraint fitting, redact, insert, save.

Spec §6.8-6.10, §7, §8, §9. Output: render/draft.pdf, render/render_manifest.json.
Chạy: python3 fit_paint.py --job <job_dir> [--pages 0,1,2] [--allow-partial]
"""

from __future__ import annotations

import argparse
import os
import re
import statistics

import pymupdf

from _common import (CONTAINER_TOL_Y_EM_DEFAULT, FONTS_DIR, BlockingError, Job, exit_blocking,
                     refuse_if_released,
                     load_json, make_issue, save_json, utc_now)

STAGE = "fit_paint"
PH_RE = re.compile(r"⟦([A-Z]+_\d+)⟧")
# Biên vệt mực quanh baseline, tính theo em. `painted_rect` khai báo vùng này cho Gate 6,
# và Gate 4 đo mép dưới ô bằng chính nó — nên ngân sách dọc của fitter PHẢI trừ đúng
# `INK_DESCENT_EM`, nếu không fitter tưởng vừa còn gate lại báo tràn.
INK_ASCENT_EM = 1.3
INK_DESCENT_EM = 0.45
# Dãy gạch dưới trong bản dịch = ô trống điền tay đặt lại. 3 dấu trở lên để không nhầm
# với dấu gạch dưới trong định danh kỹ thuật (ess_support, Port_1).
BLANK_RUN_RE = re.compile(r"_{3,}")
SUBSET_PREFIX_RE = re.compile(r"^[A-Z]{6}\+")
# Family quen thuộc — style-class mapping đáng tin; ngoài list = display font
# → review trigger theo spec §11.4.
KNOWN_FAMILIES = ("arial", "helvetica", "times", "courier", "noto", "roboto",
                  "calibri", "cambria", "georgia", "verdana", "tahoma", "segoe",
                  "songti", "adobesong", "liberation", "dejavu")


# ── font resolver (spec §7) ─────────────────────────────────────────────

class FontPack:
    def __init__(self):
        mf = load_json(os.path.join(FONTS_DIR, "fonts_manifest.json"))
        if not mf:
            raise BlockingError("fonts_manifest.json thiếu — font pack chưa bundle (spec §7.2)")
        self.entries = mf["fonts"]
        self._cache: dict[str, pymupdf.Font] = {}
        self._alias: dict[str, str] = {}

    def key_for(self, style: dict) -> tuple[str, list[dict]]:
        """→ (fontkey, issues). Map style class → bundle face, degrade có ghi nhận."""
        fam = "mono" if style.get("mono") else "serif" if style.get("serif") else "sans"
        variant = (("bolditalic" if style.get("italic") else "bold") if style.get("bold")
                   else ("italic" if style.get("italic") else "regular"))
        issues = []
        for cand in (f"{fam}-{variant}",
                     f"{fam}-bold" if "bold" in variant else f"{fam}-regular",
                     f"{fam}-regular", "sans-regular"):
            if cand in self.entries:
                if cand != f"{fam}-{variant}":
                    issues.append(("STYLE_DEGRADED", f"{fam}-{variant} → {cand}"))
                return cand, issues
        raise BlockingError(f"font pack không có face nào cho {fam}-{variant}")

    def font(self, key: str) -> pymupdf.Font:
        if key not in self._cache:
            self._cache[key] = pymupdf.Font(fontfile=self.path(key))
        return self._cache[key]

    def path(self, key: str) -> str:
        return os.path.join(FONTS_DIR, self.entries[key]["file"])

    def alias(self, key: str) -> str:
        if key not in self._alias:
            self._alias[key] = f"NF{len(self._alias)}"
        return self._alias[key]

    def cover(self, key: str, text: str) -> str | None:
        """Font đầu tiên trong chain phủ hết text; None nếu không có (→ blocking)."""
        chain = [key] + [k for k in ("sans-regular", "serif-regular", "mono-regular")
                         if k != key and k in self.entries]
        for k in chain:
            f = self.font(k)
            if all(ch in ("\n", "\t", " ") or f.has_glyph(ord(ch)) for ch in text):
                return k
        return None


# ── fitting (spec §6.8, §8) ─────────────────────────────────────────────

def tokenize(reg: dict) -> list[dict]:
    """target_runs (placeholder-form) → tokens atomic đã expand, giữ role.

    "\n" trong target = explicit line break (spec §11.2): token đầu của
    dòng sau mang br=True để fitter ép xuống dòng tại đó.
    """
    mapping = reg.get("placeholders", {})
    tokens = []
    for run in reg["target_runs"]:
        for li, seg in enumerate(run["text"].split("\n")):
            first = True
            for raw in seg.split(" "):
                if raw == "":
                    continue
                expanded = PH_RE.sub(lambda m: mapping.get(m.group(1), m.group(0)), raw)
                if expanded.strip():
                    tokens.append({"text": expanded, "role": run["role"],
                                   "br": li > 0 and first})
                    first = False
    return tokens


def wrap_lines(widths: list[float], space_w, max_w: float) -> list[list[int]] | None:
    """Greedy wrap token indices theo width; None nếu một token > max_w.

    `space_w` là một số (mọi khe cùng bề rộng) hoặc list cùng độ dài `widths`, phần tử i là
    bề rộng khe ĐỨNG SAU token i. Dạng list cần cho dòng trộn font: dấu cách được vẽ bằng
    font của chính segment chứa nó, nên khe sau token mono rộng khác khe sau token sans.
    """
    def gap(i: int) -> float:
        return space_w[i] if isinstance(space_w, (list, tuple)) else space_w

    lines, cur, cur_w = [], [], 0.0
    for i, w in enumerate(widths):
        if w > max_w + 0.1:
            return None
        add = w if not cur else w + gap(i - 1)
        if cur and cur_w + add > max_w + 0.1:
            lines.append(cur)
            cur, cur_w = [i], w
        else:
            cur.append(i)
            cur_w += add
    if cur:
        lines.append(cur)
    return lines


def role_style(reg: dict, role: str) -> dict:
    for r in reg["runs"]:
        if r["role"] == role:
            return r
    return reg["runs"][0]


def ink_base_x(reg: dict, span_x: float) -> float:
    """Điểm bắt đầu vẽ theo NÉT MỰC đầu tiên, không theo origin của span đầu.

    Bản gốc hay căn chữ bằng dãy space thay vì thuộc tính căn lề. Space có advance nhưng
    không vẽ gì, nên origin của span đầu nằm ở đầu dãy space, còn chữ thật bắt đầu xa hơn
    về bên phải — đo được tới 151pt trên một ô bảng thông số. `tokenize` bỏ mọi token
    khoảng trắng (kể cả nbsp và các space Unicode khác), nên bản dịch không tái tạo được
    dãy đó và bị kéo tụt về đầu dãy space.

    Cùng lớp lỗi 1.8.0 đã sửa một nửa: hồi đó cho `build_lines` đo `ink_bbox` để khung ô
    thôi phình ra vì space đầu/đuôi — nhưng `base_x` vẫn lấy từ origin có đệm.

    Guard: lấy mép mực TRÁI NHẤT trong các dòng, và CHỈ nâng, không bao giờ hạ. Nhờ vậy
    không bao giờ vẽ trái hơn chữ nguồn của bất kỳ dòng nào — văn xuôi có thụt lề dòng đầu
    (kiểu danh sách gạch đầu dòng) vẫn an toàn vì mép trái nhất chính là lề thân bài.
    1.9.6 từng đòi MỌI dòng cùng một mép; 1.9.9 nới ra vì luật đó bỏ sót ô gộp căn giữa
    bằng dãy space có số space khác nhau từng dòng.
    """
    lines = reg.get("lines") or []
    if not lines:
        return span_x
    # Lấy mép mực TRÁI NHẤT trong các dòng: không bao giờ vẽ trái hơn chữ nguồn của bất kỳ
    # dòng nào, nên văn xuôi có thụt lề dòng đầu vẫn an toàn (mép trái nhất chính là lề thân
    # bài). 1.9.6 đòi MỌI dòng cùng mép nên bỏ sót ô gộp được căn giữa bằng dãy space có số
    # space khác nhau từng dòng — đo trên 5 job, nới thế này chỉ đụng thêm 2 vùng.
    return max(span_x, min(l["bbox"][0] for l in lines))


INDENT_MAX_FRAC = 0.25   # thụt lề suy ra không được quá ngần này bề rộng vùng


def line_text(line: dict) -> str:
    return "".join(s.get("text", "") for s in line.get("spans") or [])


def paragraph_starts(lines: list[dict]) -> list[int] | None:
    """Chỉ số các dòng MỞ ĐOẠN trong region, hoặc None nếu không đo được.

    Luật: dòng đầu luôn mở đoạn; dòng i mở đoạn khi dòng i-1 còn thừa chỗ cho từ đầu của
    dòng i. Nguồn xuống dòng vì hết chỗ thì dòng trước phải chạy sát mép phải — dừng sớm
    hơn thế nghĩa là bản gốc cố ý ngắt đoạn.

    Không cần font: bề rộng ký tự trung bình đo ngay trên dòng đang xét (bề rộng mực chia
    số ký tự không-trắng), nên tự hiệu chỉnh theo cỡ chữ và font của chính vùng đó.
    """
    if not lines:
        return None
    right = max(l["bbox"][2] for l in lines)
    starts = [0]
    for i in range(1, len(lines)):
        txt = line_text(lines[i]).strip()
        if not txt:
            return None                  # không có chữ để đo → không đoán
        avg_cw = (lines[i]["bbox"][2] - lines[i]["bbox"][0]) / len(txt)
        if right - lines[i - 1]["bbox"][2] >= avg_cw * (len(txt.split()[0]) + 1):
            starts.append(i)
    return starts


def segment_indents(reg: dict, base_x: float, n_seg: int) -> list[float]:
    """Thụt lề (pt) cho từng đoạn ngăn bằng `\n` của bản dịch, hoặc toàn 0 nếu không suy ra được.

    Bản gốc hay trộn nhiều mức thụt trong MỘT region: dòng gạch đầu dòng thụt vào, văn xuôi
    giữa chúng thì không. Fitter chỉ có một `base_x` cho cả vùng nên mọi dòng bắt đầu ở mép
    trái nhất — chữ dịch chạy đè lên chính dấu gạch đầu dòng mà engine giữ lại.

    Ánh xạ chỉ xác định được khi số đoạn của bản dịch bằng **số dòng nguồn** (bản dịch giữ
    nguyên cấu trúc dòng), bằng **số mục thụt sâu**, hoặc bằng **số dòng mở đoạn**
    (`paragraph_starts`). Ngoài ba hình mẫu đó thì không có cách nào biết đoạn nào thuộc
    mức nào — trả về toàn 0, giữ nguyên hành vi cũ. Thử theo đúng thứ tự này: hai hình mẫu
    đầu đo trực tiếp mức thụt nên chắc hơn hình mẫu thứ ba (suy từ chỗ ngắt dòng).
    Đo trên các job hiện có: 29 vùng trộn mức thụt, hình mẫu 1+2 suy được 10, thêm hình mẫu
    3 thành **19**.

    Không bao giờ trả số âm: chữ dịch không được vẽ trái hơn `base_x`.
    """
    lines = reg.get("lines") or []
    if len(lines) < 2 or n_seg < 1:
        return [0.0] * max(1, n_seg)
    lv = [l["bbox"][0] for l in lines]
    if n_seg == len(lv):
        # Bản dịch giữ nguyên cấu trúc dòng → ánh xạ 1:1, chính xác nhất.
        return [max(0.0, round(v - base_x, 2)) for v in lv]
    # Ngược lại chỉ nhận đúng một hình mẫu: hai mức thụt, mỗi đoạn bản dịch là một mục thụt
    # vào. Không dùng "đoạn cùng mức" vì hai mục gạch đầu dòng liền nhau cùng mức bị gộp làm
    # một, cho ra kết quả nham nhở — mục thụt, mục không.
    lo = min(lv)
    deep = [v for v in lv if v - lo >= 2.0]
    if deep and n_seg == len(deep) and max(deep) - min(deep) < 2.0:
        return [max(0.0, round(deep[0] - base_x, 2))] * n_seg
    # Hình mẫu thứ ba: số đoạn bản dịch bằng số dòng MỞ ĐOẠN của nguồn. Hai hình mẫu trên
    # đều đếm theo mức thụt nên trượt khi một mục bắt đầu ở lề thân bài (không thụt) — ca
    # thật V5 p11 khối lưu kho: 12 dòng nguồn, 7 đoạn dịch, chỉ 6 dòng thụt sâu.
    st = paragraph_starts(lines)
    if st and len(st) == n_seg:
        ind = [max(0.0, round(lines[i]["bbox"][0] - base_x, 2)) for i in st]
        # Chặn thụt lề vô lý: vùng hai cột (nửa trái ngắn, nửa phải ở x lớn) khớp đếm nhưng
        # cho ra 268pt trên khung 366pt. Thà không suy còn hơn ném đoạn văn sang giữa trang.
        if max(ind) <= INDENT_MAX_FRAC * (max(l["bbox"][2] for l in lines) - base_x):
            return ind
    return [0.0] * n_seg


HEADING_NUM_RE = re.compile(r"^\s*\d+(\.\d+)*[.\s]\s*\S")
# Tựa được coi là "căn giữa theo trang" khi tâm chữ nguồn lệch tâm trang không quá ngần này.
CENTERED_TOL_PT = 3.0


def expand_container(reg: dict, need_w: float, obstacles: list, page_rect: list,
                     margins: tuple[float, float], align: str) -> tuple[list, str | None] | None:
    """→ (container nới rộng, alignment mới) cho region một dòng không đủ chỗ, hoặc None.

    Vì sao cần: khung của region lấy theo bbox chữ NGUỒN. Tiếng Việt dài hơn tiếng Anh, nên
    một heading vừa khít ở bản gốc thành FIT_IMPOSSIBLE ở bản dịch dù quanh nó là khoảng
    trắng. Ca thật: tựa bìa `User Manual` (158pt) → `Hướng dẫn sử dụng` (250pt) trong khung
    196.6pt, trong khi cả dải ngang của trang không có một vật cản nào.

    Vì sao KHÔNG cho xuống thêm dòng: khung bìa cao 33.7pt, hai dòng cỡ 25.1pt cần 57.7pt —
    thiếu chiều cao chứ không thiếu số dòng. Nới ngang là phép duy nhất khả thi ở đây.

    Vì sao đặt ở stage 6 chứ không ở extract: `region_id` được sinh từ `container[0]//8` và
    `container[1]//8` (extract_group), nên đổi container ở stage 2 sẽ đổi region_id và làm
    mồ côi toàn bộ `responses.jsonl` đã dịch. Ở đây chỉ tính khung vẽ, id giữ nguyên.

    Chỉ nới đúng bề rộng cần: nới hết khoảng trống sẽ đẩy chữ căn trái về sát mép trái, lệch
    khỏi bố cục gốc.
    """
    b = reg["bbox"]
    y0, y1 = b[1], b[3]
    left_lim, right_lim = margins
    for ob in obstacles:
        if ob[3] <= y0 or ob[1] >= y1:      # không giao dải dọc của heading
            continue
        if ob[2] <= b[0]:
            left_lim = max(left_lim, ob[2])
        elif ob[0] >= b[2]:
            right_lim = min(right_lim, ob[0])
        else:
            return None                      # vật cản chồng lên chính chữ → không nới
    pad = 1.0
    c = reg["container"]
    cx_page = (page_rect[0] + page_rect[2]) / 2
    centered = abs((b[0] + b[2]) / 2 - cx_page) <= CENTERED_TOL_PT
    want = need_w + pad

    def ok(x0: float, x1: float) -> bool:
        return x0 >= left_lim and x1 <= right_lim and x1 - x0 > c[2] - c[0]

    if centered:
        # Tựa căn giữa theo trang: nới đối xứng VÀ chuyển sang alignment center. Text căn
        # trái được vẽ từ `base_x` của span nguồn, nên nới khung mà giữ "left" thì chữ vẫn
        # bắt đầu ở chỗ cũ và cụm dài hơn sẽ thò lệch sang phải so với bố cục gốc.
        half = want / 2
        if not ok(cx_page - half, cx_page + half):
            return None
        return [round(cx_page - half, 2), c[1], round(cx_page + half, 2), c[3]], "center"

    # Hướng tự nhiên theo căn lề, rồi hướng ngược lại làm dự phòng. Ca thật: nhãn hình ở
    # Lite p13 có đường chỉ dẫn chắn ngay bên phải (cách 5pt) nhưng bên trái còn ~45pt
    # trống. Nới sang trái và neo mép phải giữ nguyên điểm nối của đường chỉ dẫn — đúng
    # hơn là ép chữ nhỏ lại.
    if align == "right":
        # Text căn phải neo vào c[2]; nới sang phải sẽ đẩy chữ đi.
        cands = [(c[2] - want, c[2], None), (c[0], c[0] + want, "left")]
    else:
        cands = [(c[0], c[0] + want, None), (c[2] - want, c[2], "right")]
    for x0, x1, new_align in cands:
        if ok(x0, x1):
            return [round(x0, 2), c[1], round(x1, 2), c[3]], new_align
    return None


# Nhãn cạnh hình cũng cần nới: tiếng Việt dài hơn nên "Dry Contact" → "Tiếp điểm khô" tụt
# còn 85% cỡ chữ trong ô 43.9pt, dù bên phải là khoảng trắng. Luật vật cản lo phần an toàn —
# nhãn nào bị hình/leader line/nhãn anh em chắn thì tự động không nới được.
EXPANDABLE_TYPES = ("heading", "figure_caption", "diagram_label")
LABEL_MAX_WORDS = 4
LABEL_MAX_CHARS = 40


def expandable_region(reg: dict) -> bool:
    """Region một dòng được phép nới khung: tiêu đề, nhãn hình, và hai ca bị extract xếp
    nhầm — tiêu đề đánh số thành `list_item` (LIST_RE khớp `"5."` trong `"5.1.1 …"`), nhãn
    ngắn cạnh hình thành `paragraph` (ca thật: `Dry Contact` ở Lite p13)."""
    if reg["rotation"] != 0 or len(reg["lines"]) != 1:
        return False
    t = reg["source_text"].strip()
    if reg["region_type"] in EXPANDABLE_TYPES:
        return True
    if reg["region_type"] == "list_item":
        return bool(HEADING_NUM_RE.match(t))
    if reg["region_type"] == "paragraph":
        return len(t.split()) <= LABEL_MAX_WORDS and len(t) <= LABEL_MAX_CHARS
    return False


COLUMN_X_TOL = 3.0   # hai dòng coi là cùng một cột khi origin x lệch dưới ngần này
COLUMN_Y_TOL = 2.0   # hai dòng coi là cùng một hàng khi baseline lệch dưới ngần này


def column_split(reg: dict) -> list[dict] | None:
    """Ô bảng gộp nhiều cột → một sub-region cho mỗi cột; None nếu không phải ca đó.

    Vì sao cần: `fit_region` vẽ MỌI dòng từ `base_x` của span đầu region, nên một hàng bảng
    mà PDF khai là MỘT cell duy nhất bị dồn hết về mép trái — mất cấu trúc cột trong khi
    hàng tiêu đề ngay trên vẫn giữ 3 cột. Ca thật: hàng dữ liệu của bảng bảo hành V16,
    `find_tables` trả đúng một cell trải 65.5→491.6 vì bản gốc không kẻ nét dọc ở hàng đó,
    nên luật cắt cột theo `vertical_rules` của 1.8.0 (đúng khi từ chối) không đụng tới.

    Bằng chứng để coi là cột thật chứ không phải thụt lề: **cùng một x xuất hiện ở ít nhất
    hai hàng y khác nhau** — lưới thì lặp, thụt lề thì không. Thêm điều kiện `table_cell`
    để loại hẳn nhãn danh sách ("(i)", "a.") vốn cũng sinh nhiều x nhưng nằm trong
    `paragraph`, và ở đó reflow về một cột lại là hành vi đúng.

    Hợp đồng với bản dịch: mỗi đoạn phân tách bằng "\\n" trong target ứng với một cột, theo
    thứ tự trái→phải. Lệch số đoạn thì trả None để giữ nguyên hành vi cũ — người dịch sửa
    response, engine không tự đoán.
    """
    if reg["region_type"] != "table_cell" or reg["rotation"] != 0:
        return None
    if len(reg["lines"]) < 3:
        return None

    origins = [(l["spans"][0]["origin"][0], l["spans"][0]["origin"][1], l)
               for l in reg["lines"]]
    rows: list[float] = []
    for _, y, _ in origins:
        if not any(abs(y - r) <= COLUMN_Y_TOL for r in rows):
            rows.append(y)
    if len(rows) < 2:
        return None

    cols: list[float] = []
    for x, _, _ in origins:
        if not any(abs(x - cx) <= COLUMN_X_TOL for cx in cols):
            cols.append(x)
    cols.sort()
    if len(cols) < 2:
        return None

    def col_of(x): return min(range(len(cols)), key=lambda k: abs(x - cols[k]))
    def row_of(y): return min(range(len(rows)), key=lambda k: abs(y - rows[k]))

    # Lưới thật: >=2 cột mà mỗi cột có dòng ở >=2 hàng khác nhau.
    spread = [len({row_of(y) for x, y, _ in origins if col_of(x) == k}) for k in range(len(cols))]
    if sum(1 for n in spread if n >= 2) < 2:
        return None

    # Ghép các run bằng "" chứ KHÔNG phải "\n": run là đơn vị style, không phải đơn vị cột.
    # `"\n".join` chèn thêm một dấu ngăn cột giữa mỗi cặp run, nên target nhiều run (tiêu đề
    # in đậm + phần còn lại) bị đếm thừa cột và hàm lặng lẽ trả None.
    segments = "".join(r["text"] for r in reg["target_runs"]).split("\n")
    if len(segments) != len(cols):
        return None

    c = reg["container"]
    subs = []
    for k, cx in enumerate(cols):
        lines = [l for x, _, l in origins if col_of(x) == k]
        if not lines:
            return None
        right = cols[k + 1] if k + 1 < len(cols) else c[2]
        sub = dict(reg)
        sub["lines"] = sorted(lines, key=lambda l: l["spans"][0]["origin"][1])
        sub["container"] = [min(c[0], cx), c[1], right, c[3]]
        sub["target_runs"] = [{"role": reg["target_runs"][0]["role"], "text": segments[k]}]
        sub["column_index"] = k
        subs.append(sub)
    return subs


# Dòng mục lục: "tiêu đề" + khe rộng + "số trang", tất cả trong MỘT span.
LEADER_GAP_RE = re.compile(r"\S(\s{4,})(\S+)\s*$")


def leader_split(reg: dict, pack: "FontPack") -> list[dict] | None:
    """Dòng mục lục gộp tiêu đề và số trang → hai sub-region; None nếu không phải ca đó.

    Vì sao cần: dòng mục lục là MỘT span, tiêu đề và số trang ngăn nhau bằng một dãy space
    (gạch dẫn là line-art riêng). `tokenize` bỏ sạch khoảng trắng nên cụm co lại, rồi
    `infer_alignment` đọc dòng gần-full-width thành `center`/`right` và đẩy cả cụm ra giữa
    hoặc sang phải — đè lên chính nét gạch dẫn. `column_split` không đụng tới vì nó đòi
    `table_cell` và ≥3 dòng có lưới lặp.

    Chữ ký đo được, rất hẹp: region MỘT dòng, ngoài `table_cell`, text có khe ≥4 space và
    đuôi sau khe là **số trang 1-3 chữ số**. Đo trên 5 job: khớp đúng **7 vùng, toàn bộ là
    dòng mục lục**, 0 ca oan.

    Hợp đồng với bản dịch giống `column_split`: hai đoạn ngăn bằng "\n", trái→phải. Lệch số
    đoạn thì trả None — engine không tự đoán.
    """
    if reg["region_type"] == "table_cell" or reg["rotation"] != 0:
        return None
    segments = "".join(r["text"] for r in reg["target_runs"]).split("\n")
    if len(segments) != 2:
        return None
    c = reg["container"]

    # Dạng B: PDF khai hai "line" nhưng CÙNG một y — đó là hai cột, không phải hai dòng.
    # Không phải đo gì, mỗi cột đã có bbox riêng.
    if len(reg["lines"]) == 2:
        a, b = reg["lines"]
        same_y = abs(a["spans"][0]["origin"][1] - b["spans"][0]["origin"][1]) <= 1.0
        tail = "".join(sp["text"] for sp in b["spans"]).strip()
        if same_y and re.fullmatch(r"\d{1,3}", tail) and b["bbox"][0] > a["bbox"][2]:
            return [_leader_sub(reg, c[0], b["bbox"][0] - 2.0, "left", a, segments[0], 0),
                    _leader_sub(reg, b["bbox"][0] - 2.0, b["bbox"][2], "right", b,
                                segments[1], -1)]
        return None

    # Dạng A: một line, một span, khe bằng space ở giữa.
    if len(reg["lines"]) != 1:
        return None
    m = LEADER_GAP_RE.search(reg["source_text"])
    if not m or not re.fullmatch(r"\d{1,3}", m.group(2)):
        return None

    line = reg["lines"][0]
    right = line["bbox"][2]                       # mép phải nét mực = chỗ số trang kết thúc
    size = line["spans"][0]["size"]
    key, _ = pack.key_for(role_style(reg, reg["target_runs"][-1]["role"]))
    tail_w = pack.font(key).text_length(segments[1], fontsize=size)
    cut = right - tail_w - 4.0                    # ranh giới hai cột
    if cut <= line["bbox"][0] + 4.0:              # không còn chỗ cho tiêu đề
        return None
    return [_leader_sub(reg, c[0], cut, "left", line, segments[0], 0),
            _leader_sub(reg, cut, right, "right", line, segments[1], -1)]


def _leader_sub(reg: dict, x0: float, x1: float, align: str, line: dict,
                seg: str, run_i: int) -> dict:
    c = reg["container"]
    sub = dict(reg)
    sub["container"] = [x0, c[1], x1, c[3]]
    sub["alignment"] = align
    sub["lines"] = [{**line, "bbox": [max(line["bbox"][0], x0), line["bbox"][1],
                                      min(line["bbox"][2], x1), line["bbox"][3]]}]
    sub["target_runs"] = [{"role": reg["target_runs"][run_i]["role"], "text": seg}]
    sub["column_index"] = 0 if run_i == 0 else 1
    return sub


LEADER_MAX_H = 1.2        # nét gạch dẫn mỏng hơn ngần này mới coi là gạch dẫn
LEADER_MAX_GAP = 12.0     # và phải bắt đầu trong ngần này sau mép chữ nguồn
LEADER_MIN_LEN = 8.0      # đoạn gạch còn lại ngắn hơn ngần này thì thôi, đừng vẽ
LEADER_GAP_DEFAULT = 2.0  # khe mặc định khi dòng nguồn đã bị cắt cột, không đo được
LEADER_TAIL_GAP = 8.0     # số trang phải bắt đầu trong ngần này sau khi nét kết thúc


def leader_run(drawings: list, reg: dict, siblings: list) -> dict | None:
    """Dãy nét gạch dẫn chạy ngay sau chữ nguồn của `reg`, hoặc None.

    Vì sao cần: gạch dẫn mục lục là line-art vẽ sẵn từ mép phải tiêu đề TIẾNG ANH tới số
    trang. Tiêu đề tiếng Việt dài hơn thì chữ đè lên nét (`1.1 Cấu hình tiêu chuẩn của sản
    phẩm`), ngắn hơn thì hở một khoảng (`3 Môi trường vận hành`). `leader_split` (1.9.13) chỉ
    tách được cột — nét gạch nó không đụng tới được.

    Chữ ký: các stroke cao dưới `LEADER_MAX_H`, cùng một y, nằm trong dải dọc của region, bắt
    đầu trong `LEADER_MAX_GAP` sau mép mực phải, và dãy đó phải chứa ít nhất một đoạn NÉT
    ĐỨT. Đòi nét đứt để không đụng nhầm vạch kẻ bảng hay gạch chân — chúng liền nét.
    """
    if len(reg["lines"]) != 1:
        return None          # dòng mục lục luôn một dòng; đoạn nhiều dòng không được dính
    b = reg["bbox"]
    ink_left = reg["lines"][0]["bbox"][0]
    seg = [d for d in drawings
           if d["type"] == "s" and d["rect"].y1 - d["rect"].y0 <= LEADER_MAX_H
           and b[1] <= (d["rect"].y0 + d["rect"].y1) / 2 <= b[3]
           and d["rect"].x0 > ink_left]
    if not seg:
        return None
    y = min(seg, key=lambda d: d["rect"].x0)["rect"].y0
    seg = [d for d in seg if abs(d["rect"].y0 - y) < 0.5]
    dashed = [d for d in seg if d.get("dashes") not in (None, "", "[] 0")]
    if not dashed:
        return None
    x0 = min(d["rect"].x0 for d in seg)
    # Khe giữa chữ nguồn và nét: đo trên chính dòng nguồn nào kết thúc TRƯỚC nét. Dòng mục
    # lục đã bị `leader_split` cắt thì bbox dòng là ranh giới cột, không phải mép chữ — khi
    # đó dùng khe mặc định. Đo trên 5 job: khe thật luôn quanh 2pt.
    ends = [l["bbox"][2] for l in reg["lines"] if l["bbox"][2] <= x0 + 0.5]
    gap = round(x0 - max(ends), 2) if ends else LEADER_GAP_DEFAULT
    if not 0.0 <= gap <= LEADER_MAX_GAP:
        return None
    x1 = max(d["rect"].x1 for d in seg)
    # Phải có chữ ngay SAU nét trên cùng dòng — đó là số trang. Không có thì nét này là
    # đường chỉ dẫn của hình, không phải gạch dẫn mục lục: ca thật V5 p9, nhãn `Ground` có
    # đường nét đứt trỏ sang cọc tiếp địa, dời điểm bắt đầu của nó làm vỡ cụm vector và
    # Gate 5 báo đỏ.
    tails = [s["bbox"][0] for s in siblings if s["bbox"][1] <= y <= s["bbox"][3]]
    # Hoặc số trang là region anh em bắt đầu ngay sau nét, hoặc — khi `leader_split` đã cắt
    # dòng thành hai cột — nó là cột phải của CHÍNH region này, tức dòng nguồn còn chạy tới
    # tận cuối nét. Nhãn cạnh hình thì không thoả vế nào: chữ dừng trước khi nét bắt đầu.
    if not (any(0 <= t - x1 <= LEADER_TAIL_GAP for t in tails)
            or reg["lines"][0]["bbox"][2] >= x1 - LEADER_TAIL_GAP):
        return None
    ref = dashed[0]
    return {"y": y, "x0": x0, "x1": x1,
            "rects": [pymupdf.Rect(d["rect"].x0, y - 0.6, d["rect"].x1, y + 0.6) for d in seg],
            "color": ref["color"], "width": ref.get("width") or 0.7,
            "dashes": ref["dashes"], "gap": gap}


def painted_right(fr: dict) -> float:
    """Mép phải xa nhất của chữ đã fit — gạch dẫn phải bắt đầu sau điểm này."""
    return max((l["x"] + l["width"] for l in fr["lines"]), default=0.0)


def fit_region(reg: dict, pack: FontPack, cfg: dict,
               expand_ctx: dict | None = None) -> tuple[dict | None, list]:
    """→ (fit_result, issues). None nếu không có layout hợp lệ (fail-closed).

    `expand_ctx` (optional): `{"obstacles": [...], "page_rect": [...], "margins": (l, r)}`
    cho phép nới khung heading khi bản dịch không vừa — xem `expand_heading_container`.
    """
    issues = []
    tokens = tokenize(reg)
    if not tokens:
        return None, [("EMPTY_TOKENS", "P1", "target không có token")]

    for fname in {SUBSET_PREFIX_RE.sub("", r["font"]) for r in reg["runs"]}:
        if fname and not any(k in fname.lower() for k in KNOWN_FAMILIES):
            issues.append(("FONT_DISPLAY_FALLBACK", "P1",
                           f"display font {fname!r} map sang bundle theo style class — "
                           "reviewer xác nhận (spec §11.4)"))
            break

    src_sizes = [r["size"] for r in reg["runs"] for _ in r["text"]]
    src_size = statistics.median(src_sizes) if src_sizes else reg["runs"][0]["size"]
    floor = src_size * cfg["fonts"]["minimum_ratio"]
    c = reg["container"]
    cw, chh = c[2] - c[0], c[3] - c[1]
    if reg["rotation"] in (90, 270):
        cw, chh = chh, cw  # reading-direction extent

    # Text căn trái được vẽ từ base_x (origin của span nguồn) chứ không từ mép
    # container, nên ngân sách wrap phải trừ đúng phần thụt lề đó — nếu wrap theo
    # cả cw thì dòng gần đầy sẽ thò khỏi mép phải bằng chính phần thụt.
    # Center/right neo theo c[0]/c[2] nên bị chặn sẵn, giữ nguyên cw.
    base_x, base_y = reg["lines"][0]["spans"][0]["origin"]
    base_x = ink_base_x(reg, base_x)
    wrap_w = cw
    if reg["rotation"] == 0 and reg["alignment"] == "left":
        wrap_w = max(c[2] - base_x, 1.0)

    # resolve font/coverage per token
    tok_font: list[str] = []
    for t in tokens:
        base_key, deg = pack.key_for(role_style(reg, t["role"]))
        for code, det in deg:
            issues.append((code, "P2", det))
        k = pack.cover(base_key, t["text"])
        if k is None:
            bad = [ch for ch in t["text"] if pack.cover("sans-regular", ch) is None][:5]
            return None, issues + [("FONT_GLYPH_MISSING", "P1",
                                    f"không font nào trong pack có glyph: {bad!r}")]
        if k != base_key:
            issues.append(("FONT_FALLBACK_SUBRUN", "P2", f"{t['text'][:12]!r}: {base_key}→{k}"))
        tok_font.append(k)

    # leading nguồn (baseline-to-baseline) nếu multi-line
    origins = [l["spans"][0]["origin"][1] for l in reg["lines"]]
    if len(origins) >= 2:
        deltas = [b - a for a, b in zip(origins, origins[1:]) if b - a > 1]
        leading_ratio = (statistics.median(deltas) / src_size) if deltas else 1.15
    else:
        leading_ratio = 1.15
    leading_ratio = max(1.02, leading_ratio)
    single_line_src = len(reg["lines"]) == 1
    desc_tol_em = cfg["qa"].get("container_tol_y_em", CONTAINER_TOL_Y_EM_DEFAULT)

    # Ngân sách dọc đo từ BASELINE DÒNG ĐẦU xuống đáy container, không phải chiều cao
    # container: chữ được vẽ từ `base_y` (origin của span nguồn) chứ không từ mép trên, nên
    # phần nằm trên base_y không dùng để chứa dòng nào. Đối xứng với `wrap_w = c[2] - base_x`
    # của lg-basic-3. Dùng `chh` như cũ khiến fitter tưởng còn chỗ, dòng cuối tràn xuống
    # hàng bảng bên dưới — nguồn của phần lớn G4_OUT_OF_CONTAINER.
    avail_h = max(1.0, c[3] - base_y) if reg["rotation"] == 0 else chh

    n_seg = 1 + sum(1 for t in tokens[1:] if t.get("br"))
    seg_ind = (segment_indents(reg, base_x, n_seg)
               if reg["rotation"] == 0 and reg["alignment"] == "left" else [0.0] * n_seg)

    def layout_at(s: float, cap_one_line: bool = False):
        widths = [pack.font(k).text_length(t["text"], fontsize=s)
                  for t, k in zip(tokens, tok_font)]
        # Khe SAU token i được vẽ bằng font của token i (segment gộp `t1 + " " + t2` bằng
        # font của segment). Lấy chung font token đầu region làm lệch tới 2.38pt/khe khi
        # dòng trộn sans/mono — bốn khe là lệch 9.5pt, đủ để dòng thò khỏi ô.
        space_ws = [pack.font(k).text_length(" ", fontsize=s) for k in tok_font]
        # wrap từng đoạn giữa các explicit break rồi ghép
        segments, cur = [], []
        for i, t in enumerate(tokens):
            if t.get("br") and cur:
                segments.append(cur)
                cur = []
            cur.append(i)
        segments.append(cur)
        lines, line_seg = [], []
        for si, seg in enumerate(segments):
            ind = seg_ind[si] if si < len(seg_ind) else 0.0
            sub = wrap_lines([widths[i] for i in seg], [space_ws[i] for i in seg],
                             max(wrap_w - ind, 1.0))
            if sub is None:
                return None
            lines += [[seg[j] for j in line] for line in sub]
            line_seg += [si] * len(sub)
        n = len(lines)
        # Dòng đầu nằm ngay tại base_y nên chỉ (n-1) dòng tiếp theo mới ăn vào ngân sách.
        # Đáy vệt mực = baseline cuối + INK_DESCENT_EM (đúng thứ Gate 4 đo), được phép vượt
        # đáy container tối đa `desc_tol_em`. Viết thành một bất đẳng thức để fitter và gate
        # không bao giờ lệch nhau.
        budget = avail_h + (desc_tol_em - INK_DESCENT_EM) * s
        max_lines = max(1, int(budget // (leading_ratio * s)) + 1)
        if cap_one_line and n > 1:
            return None
        if single_line_src and n > max_lines:
            return None
        if (n - 1) * leading_ratio * s > budget:
            return None
        return {"lines": lines, "widths": widths, "space_ws": space_ws,
                "line_seg": line_seg}

    def run_search(cap_one_line: bool = False):
        lo, hi, best_, s_ = floor, src_size, None, None
        if layout_at(hi, cap_one_line):
            return layout_at(hi, cap_one_line), hi
        for _ in range(24):  # binary search max size thỏa constraints (spec §6.8)
            mid = (lo + hi) / 2
            if layout_at(mid, cap_one_line):
                lo, best_, s_ = mid, layout_at(mid, cap_one_line), mid
            else:
                hi = mid
            if hi - lo < 0.05:
                break
        return best_, s_

    align = reg["alignment"]
    # Nguồn một dòng thì ƯU TIÊN giữ một dòng: thà thu cỡ chữ trong giới hạn còn hơn xuống
    # dòng. Ngân sách dọc của ô thường chứa được hai dòng, nên fitter cũ dừng ngay ở cỡ đầy
    # với bố cục hai dòng. Ca thật: `4.2.1 Tools` → `4.2.1 Dụng cụ` rộng 66.28pt trong khung
    # 66.0pt — thiếu 0.28pt mà tiêu đề bị bẻ đôi, trong khi thu 0.5% là vừa.
    # Không vừa nổi một dòng ngay ở sàn `minimum_ratio` thì quay lại luật cũ, không ép.
    best, s_fit = (run_search(True) if single_line_src else (None, None))
    if best is None:
        best, s_fit = run_search()
    # Nới khung cũng phải kích hoạt khi heading CHỈ bị co chữ, không riêng khi fit thất bại
    # hẳn: "7.1 Unable to Start" → "7.1 Không Khởi Động Được" tụt còn 86.4% cỡ chữ (P1
    # FONT_RATIO_HARD) trong khi bên phải nó cả dải ngang là khoảng trắng.
    poor_fit = best is not None and s_fit / src_size < cfg["fonts"]["review_below_ratio"]
    # Nguồn một dòng mà phải xuống dòng cũng là "fit kém": nới khung là cách duy nhất còn
    # lại để giữ đúng một dòng như bản gốc. Không có nhánh này thì bản dự phòng hai dòng ở
    # cỡ đầy có `ratio = 1.0`, `poor_fit` False, và nới khung không bao giờ được thử.
    if single_line_src and best is not None and len(best["lines"]) > 1:
        poor_fit = True
    if (best is None or poor_fit) and expand_ctx and expandable_region(reg):
        # Bề rộng cần cho một dòng ở đúng cỡ chữ nguồn (heading luôn một dòng).
        need_w = (sum(pack.font(k).text_length(t["text"], fontsize=src_size)
                      for t, k in zip(tokens, tok_font))
                  + sum(pack.font(k).text_length(" ", fontsize=src_size)
                        for k in tok_font[:-1]))
        got = expand_container(reg, need_w, expand_ctx["obstacles"],
                               expand_ctx["page_rect"], expand_ctx["margins"], align)
        if got:
            new_c, new_align = got
            keep = (c, cw, wrap_w, avail_h, align, best, s_fit)
            old_w = c[2] - c[0]
            c = new_c
            cw = c[2] - c[0]
            if new_align:
                align = new_align
            wrap_w = cw if align != "left" else max(c[2] - base_x, 1.0)
            avail_h = max(1.0, c[3] - base_y)
            got_best, got_s = run_search()
            # Chỉ nhận khung nới khi nó thực sự tốt hơn — nới mà không được gì thì đừng đụng
            # vào bố cục gốc. "Tốt hơn" có HAI dạng: cỡ chữ lớn hơn, hoặc ÍT DÒNG HƠN ở cùng
            # cỡ chữ. Thiếu vế sau thì nhánh "nguồn một dòng bị bẻ đôi" ngay trên không bao
            # giờ dùng được khung nới: bản dự phòng hai dòng đã ở cỡ đầy nên cỡ chữ không thể
            # lên nữa, `got_s > keep[6]` luôn sai. Ca thật V5 p17 `7.1 Unable to start` →
            # `7.1 Không khởi động được` cần 157.0pt trong khung 132.0pt, cả dải ngang bên
            # phải trống, khung nới tính đúng rồi vẫn bị vứt đi.
            better = got_best is not None and (
                keep[5] is None
                or got_s > keep[6] + 0.01
                or (len(got_best["lines"]) < len(keep[5]["lines"])
                    and got_s >= keep[6] - 0.01))
            if better:
                best, s_fit = got_best, got_s
                issues.append(("CONTAINER_EXPANDED", "P2",
                               f"khung nới {old_w:.1f}→{cw:.1f}pt vào khoảng trống "
                               f"đo được (align={align}); bản dịch dài hơn nguồn"))
                reg["container_paint"] = c
            else:
                c, cw, wrap_w, avail_h, align, best, s_fit = keep
    if best is None:
        return None, issues + [("FIT_IMPOSSIBLE", "P1",
                                f"không fit được trong container ngay tại floor "
                                f"{cfg['fonts']['minimum_ratio']:.0%} (src {src_size}pt)")]

    ratio = s_fit / src_size
    if ratio < cfg["fonts"]["review_below_ratio"]:
        code = "FONT_RATIO_HARD" if ratio < 0.90 else "FONT_RATIO_REVIEW"
        issues.append((code, "P1", f"ratio={ratio:.2%} (src {src_size}pt → {s_fit:.2f}pt)"))

    # dựng line segments với alignment + sub-run theo font
    leading = leading_ratio * s_fit
    out_lines = []
    for li, idxs in enumerate(best["lines"]):
        # Bề rộng dòng = tổng token + các khe THẬT giữa chúng (khe sau token idxs[k]).
        lw = (sum(best["widths"][i] for i in idxs)
              + sum(best["space_ws"][i] for i in idxs[:-1]))
        if align == "center":
            x = c[0] + (cw - lw) / 2 if reg["rotation"] == 0 else base_x
        elif align == "right":
            x = c[2] - lw if reg["rotation"] == 0 else base_x
        else:
            ind = 0.0
            if reg["rotation"] == 0:
                seg_of = best.get("line_seg") or []
                if li < len(seg_of) and seg_of[li] < len(seg_ind):
                    ind = seg_ind[seg_of[li]]
            x = base_x + ind
        y = base_y + li * leading
        segs, cx = [], x
        cur = None
        for pos, i in enumerate(idxs):
            t, k, w = tokens[i], tok_font[i], best["widths"][i]
            color = role_style(reg, t["role"])["color"]
            prev = idxs[pos - 1] if pos else None
            # Khe đứng trước token này là khe SAU token liền kề bên trái.
            gap = best["space_ws"][prev] if prev is not None else 0.0
            if cur and cur["font"] == k and cur["color"] == color:
                cur["text"] += " " + t["text"]
                cur["width"] += gap + w
            else:
                cur = {"x": cx + gap if cur else cx, "text": t["text"], "font": k,
                       "color": color, "width": w}
                segs.append(cur)
            cx = cur["x"] + cur["width"]
        out_lines.append({"y": round(y, 2), "x": round(x, 2), "width": round(lw, 2),
                          "segments": [{k2: (round(v, 2) if isinstance(v, float) else v)
                                        for k2, v in s2.items()} for s2 in segs]})
    if reg["rotation"] in (90, 270) and len(out_lines) > 1:
        return None, issues + [("ROTATED_MULTILINE", "P1",
                                "text xoay nhiều dòng chưa hỗ trợ v1 — needs review")]
    return {"size": round(s_fit, 2), "src_size": round(src_size, 2),
            "ratio": round(ratio, 4), "leading": round(leading, 2),
            "alignment": align, "rotation": reg["rotation"],
            "lines": out_lines}, issues


# ── safe painting (spec §9) ─────────────────────────────────────────────

def painted_rect(line: dict, fr: dict) -> list:
    """Hộp bao vệt mực của một dòng đã vẽ, theo góc xoay.

    QA Gate 6 lấy đây làm vùng "được phép đổi pixel". Text xoay chạy theo trục
    dọc: đo thực tế với insert_text(rotate=270) thì mực trải từ origin xuống
    dưới đúng bằng bề rộng dòng và chỉ loe ngang chưa tới 1em — dùng công thức
    ngang sẽ khai báo sai chỗ, khiến mực thật bị tính là diff ngoài mask.
    Biên 1.3/0.45 em bao dấu chồng tiếng Việt (Ầ, Ễ) và descender.
    """
    s, rot = fr["size"], fr["rotation"]
    y, lw = line["y"], line["width"]
    a, d = INK_ASCENT_EM * s, INK_DESCENT_EM * s
    if rot == 90:
        r = (line["x"] - a, y - lw - d, line["x"] + d, y + d)
    elif rot == 180:
        r = (line["x"] - lw, y - d, line["x"], y + a)
    elif rot == 270:
        r = (line["x"] - d, y - d, line["x"] + a, y + lw + d)
    else:
        x0 = min(sg["x"] for sg in line["segments"])
        x1 = max(sg["x"] + sg["width"] for sg in line["segments"])
        r = (x0, y - a, x1, y + d)
    return [round(v, 2) for v in r]


def span_mask(span: dict, pad: float) -> pymupdf.Rect:
    b = span["bbox"]
    return pymupdf.Rect(b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad)


def protected_rects(reg: dict) -> list[pymupdf.Rect]:
    """Vùng chữ PHẢI giữ nguyên của một region không được vẽ lại — theo NÉT MỰC.

    `protected` chặn mask của region khác đè lên chữ mình giữ lại. Nhưng bbox của span tính
    cả khoảng trắng đầu/đuôi, mà space có advance và không vẽ gì — nên nó "bảo vệ" cả chỗ
    trống. Ca thật V5 Series p10: ô nhãn của một hàng bảng là **26 ký tự space**, bbox rộng
    123pt, chắn ngang giữa cột tên và cột mô tả; ô số thứ tự `'  6     '` cũng phình từ 4.4pt
    lên 20pt. Hai vùng rỗng đó ép mask của hai ô kề bên phải cắt ngắn, nên chữ tiếng Anh còn
    nguyên trên trang và bản dịch vẽ chồng lên — đọc thành chữ đè chữ.

    Cùng lớp lỗi 1.8.0 (`build_lines` đo `ink_bbox`) và 1.9.6 (`base_x` theo nét mực): chỗ
    nào dùng bbox có đệm space thì chỗ đó sai.

    Luật: bỏ hẳn span toàn khoảng trắng; span còn lại lấy giao với `ink_bbox` của dòng chứa
    nó, vốn đã trừ space đầu/đuôi từ 1.8.0.
    """
    out = []
    for line in reg.get("lines") or []:
        lb = pymupdf.Rect(line["bbox"])
        for span in line["spans"]:
            if not span["text"].strip():
                continue
            r = span_mask(span, 0.0) & lb
            if not r.is_empty and r.width > 0 and r.height > 0:
                out.append(r)
    return out


def build_masks(reg: dict, protected: list[pymupdf.Rect], cfg: dict) -> tuple[list, list]:
    """Mask cho từng span; pad co dần nếu chạm text được giữ (spec §9.1)."""
    issues, rects = [], []
    rc = cfg["render"]
    for line in reg["lines"]:
        ink = pymupdf.Rect(line["bbox"])
        for span in line["spans"]:
            if not span["text"].strip():
                continue                      # span toàn khoảng trắng: không có gì để xoá
            pad0 = min(max(rc["mask_pad_ratio"] * span["size"], rc["mask_pad_min_pt"]),
                       rc["mask_pad_max_pt"])
            rect = None
            for pad in (pad0, pad0 / 2, 0.05, 0.0):
                # Giao với nét mực của dòng TRƯỚC khi nới pad: bbox span tính cả space
                # đầu/đuôi, mà space không vẽ gì. Ca thật V5 p10: ô `'         Alarm
                # Indicator '` có bbox bắt đầu ở 30.0 trong khi chữ bắt đầu ở 49.6, nên mask
                # thò sang chạm ô số thứ tự và cả vùng bị bỏ vẽ — chữ ở lại tiếng Anh.
                cand = (span_mask(span, 0.0) & ink) + (-pad, -pad, pad, pad)
                if not any(cand.intersects(p) for p in protected):
                    rect = cand
                    break
            if rect is None:
                # Pad 0 vẫn chạm vùng giữ nguyên → cắt mask theo chiều NGANG cho hết chồng
                # lấn, thay vì bỏ cả region. Bỏ cả region nghĩa là chữ gốc ở nguyên trên
                # trang: ca thật p6 dòng mục lục "2.5 Current Limit Table ....." bị bỏ vì
                # dải chấm chạm ô số trang (region `keep`), nên cả dòng còn tiếng Anh trong
                # bản giao khách dù bản dịch có sẵn.
                cand = span_mask(span, 0.0) & ink
                for p in protected:
                    if not cand.intersects(p):
                        continue
                    if p.x1 >= cand.x1 and p.x0 > cand.x0:      # vùng bảo vệ ở bên phải
                        cand.x1 = min(cand.x1, p.x0)
                    elif p.x0 <= cand.x0 and p.x1 < cand.x1:    # ở bên trái
                        cand.x0 = max(cand.x0, p.x1)
                    # Vùng bảo vệ nằm trọn trong dải ngang của mask thì cắt theo chiều DỌC.
                    # Ca thật V5 p6: khối chú thích chạm số trang đúng 0.1pt ở mép dưới —
                    # không nhánh ngang nào áp được nên cả khối bị bỏ vẽ, để lại nguyên
                    # tiếng Anh mà mask hàng xóm đã ăn mất vài chữ.
                    elif p.y0 >= cand.y0 and p.y1 >= cand.y1:   # ở bên dưới
                        cand.y1 = min(cand.y1, p.y0)
                    elif p.y1 <= cand.y1 and p.y0 <= cand.y0:   # ở bên trên
                        cand.y0 = max(cand.y0, p.y1)
                if (cand.is_empty or cand.width < 1.0 or cand.height < 1.0
                        or any(cand.intersects(p) for p in protected)):
                    issues.append(("MASK_CONFLICT", "P1",
                                   f"mask span {span['text'][:16]!r} chạm text giữ nguyên"))
                    return [], issues
                issues.append(("MASK_CLIPPED", "P2",
                               f"mask span {span['text'][:16]!r} bị cắt ngang để tránh text "
                               "giữ nguyên — vài ký tự nguồn ở mép có thể còn hiện"))
                rect = cand
            rects.append(rect)
    return rects, issues


def paint(job: Job, pages_filter: set[int] | None, allow_partial: bool) -> None:
    refuse_if_released(job, STAGE)
    model = load_json(job.p("model", "regions.json"))
    if not model:
        raise BlockingError("chưa có regions.json")
    regions = model["regions"]
    cfg = job.config
    pack = FontPack()
    pymupdf.TOOLS.set_small_glyph_heights(True)  # giảm bbox glyph khi redact (spec §9.1)

    paintable = [r for r in regions if r["translation_action"] == "translate"
                 and r.get("target_runs")
                 and (pages_filter is None or r["page"] in pages_filter)]
    pending = [r for r in regions if r["translation_action"] == "translate"
               and not r.get("target_runs")]
    if not paintable:
        raise BlockingError("không có region nào đủ điều kiện paint (target_runs trống)")
    if pending and not allow_partial:
        raise BlockingError(f"{len(pending)} region chưa có bản dịch — dùng --allow-partial "
                            "cho dev run (job sẽ không thể release)")

    issues: list[dict] = []
    manifest = {"generated_at": utc_now(), "partial": bool(pending or pages_filter),
                "pages": {}, "regions": [], "skipped": [], "blank_rules_removed": [],
                "toc_leaders": [],
                "issues": issues}

    doc = pymupdf.open(job.source_pdf)
    by_page: dict[int, list[dict]] = {}
    for r in paintable:
        by_page.setdefault(r["page"], []).append(r)

    # Lề tài liệu = mép trái/phải thật của thân bài, đo trên các trang nội dung (bỏ bìa vì
    # bìa có bố cục riêng). Nới khung heading không bao giờ được vượt lề này.
    body = [r["bbox"] for r in regions if r["page"] > 0]
    doc_margins = ((min(b[0] for b in body), max(b[2] for b in body)) if body
                   else (0.0, doc[0].rect.x1))
    expand_on = cfg.get("layout", {}).get("expand_heading", True)

    for pno, regs in sorted(by_page.items()):
        page = doc[pno]
        links_before = page.get_links()

        expand_ctx = None
        if expand_on:
            # Vật cản = chữ của mọi region khác trên trang + vector + ảnh. Đọc từ trang
            # NGUỒN nên độc lập với thứ tự paint.
            obstacles = [r["bbox"] for r in regions if r["page"] == pno]
            obstacles += [list(d["rect"]) for d in page.get_drawings()]
            obstacles += [list(page.get_image_bbox(i)) for i in page.get_images(full=True)]
            expand_ctx = {"obstacles": obstacles, "page_rect": list(page.rect),
                          "margins": doc_margins}

        fitted: list[tuple[dict, dict]] = []
        # Ô bảng gộp nhiều cột được tách thành sub-region trước khi fit, mỗi cột giữ đúng
        # `base_x` của nó. Sub-region mang nguyên region_id của cha nên mask, `painted_ids`
        # và Gate 3/4 vẫn chấm theo khung cha — tách chỉ là chuyện nội bộ của paint.
        expanded: list[dict] = []
        for reg in regs:
            subs = column_split(reg) if reg.get("target_runs") else None
            if subs:
                issues.append(make_issue(
                    "TABLE_ROW_COLUMNS", "P2", STAGE,
                    f"hàng bảng gộp {len(subs)} cột — vẽ mỗi cột tại x nguồn của nó",
                    page=pno, region_id=reg["region_id"]))
            if not subs and reg.get("target_runs"):
                subs = leader_split(reg, pack)
                if subs:
                    issues.append(make_issue(
                        "LEADER_COLUMNS", "P2", STAGE,
                        "dòng mục lục tách tiêu đề / số trang — số trang neo lại mép phải "
                        "như bản gốc", page=pno, region_id=reg["region_id"]))
            expanded += subs or [reg]
        regs = expanded

        for reg in regs:
            ctx = expand_ctx
            if expand_ctx is not None:
                # bbox của chính region không phải vật cản của nó — nhưng lọc ra BẢN SAO,
                # không ghi đè danh sách gốc. Ghi đè thì vật cản của mọi region đã xử lý
                # trước đó biến mất vĩnh viễn, và region cuối trang thấy trang gần như
                # trống nên nới khung đè lên chữ của hàng xóm.
                ctx = dict(expand_ctx,
                           obstacles=[b for b in expand_ctx["obstacles"]
                                      if b is not reg["bbox"]])
            fr, fissues = fit_region(reg, pack, cfg, ctx)
            for code, sev, det in fissues:
                issues.append(make_issue(code, sev, STAGE, det,
                                         page=pno, region_id=reg["region_id"]))
            if fr is None:
                manifest["skipped"].append({"region_id": reg["region_id"],
                                            "reason": fissues[-1][0] if fissues else "?"})
                continue
            reg["fit_result"] = fr
            fitted.append((reg, fr))
        if not fitted:
            continue

        painted_ids = {reg["region_id"] for reg, _ in fitted}
        protected = [r for reg_ in regions
                     if reg_["page"] == pno and reg_["region_id"] not in painted_ids
                     for r in protected_rects(reg_)]

        page_masks: list[pymupdf.Rect] = []
        ok_regions: list[tuple[dict, dict]] = []
        for reg, fr in fitted:
            rects, missues = build_masks(reg, protected, cfg)
            for code, sev, det in missues:
                issues.append(make_issue(code, sev, STAGE, det,
                                         page=pno, region_id=reg["region_id"]))
            if not rects:
                manifest["skipped"].append({"region_id": reg["region_id"],
                                            "reason": "MASK_CONFLICT"})
                continue
            page_masks += rects
            ok_regions.append((reg, fr))
        if not ok_regions:
            continue

        # Gạch dẫn mục lục: xoá nét cũ ở đây, vẽ lại sau khi đặt chữ. Phải xoá TRƯỚC
        # `apply_redactions` vì lượt đó mới thật sự bỏ line-art; vẽ lại thì phải sau khi
        # `insert_text` xong, nếu không nét mới bị chính redaction ăn mất.
        page_draw = page.get_drawings() if cfg.get("layout", {}).get("toc_leader", True) else []
        leaders = []
        # Anh em đo theo DÒNG nguồn của mọi region trên trang, kể cả region `keep` không
        # vẽ: số trang mục lục thường là `keep`, và ở dòng mục lục mà PDF khai hai "line"
        # cùng một y thì số trang là dòng thứ hai của chính region ấy — bbox mức region
        # không thấy được cả hai ca.
        sib = [{"bbox": l["bbox"]} for r in regions if r["page"] == pno for l in r["lines"]]
        for reg, fr in ok_regions:
            run = leader_run(page_draw, reg, sib) if page_draw else None
            if run:
                leaders.append((reg, painted_right(fr) + run["gap"], run))

        for rect in page_masks:
            page.add_redact_annot(rect, fill=False)  # no-fill: giữ background (spec §9.2)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)

        # Ô trống điền tay: gạch của bản gốc neo cứng theo hàng nguồn, mà bản dịch wrap
        # khác hẳn — giữ lại thì chữ đè lên gạch. Xoá gạch cũ ở đây, dãy '____' trong bản
        # dịch thay chỗ và chảy cùng chữ. Lượt redaction RIÊNG với text=NONE: rect gạch chỉ
        # cao ~1pt nhưng nằm đúng baseline nên chạm bbox glyph liền kề — dùng chung lượt
        # với text=REMOVE sẽ ăn mất chữ của region giữ nguyên.
        blanks = [(reg, r) for reg, _ in ok_regions
                  for r in (reg.get("fill_rules") or [])
                  if BLANK_RUN_RE.search("".join(x["text"] for x in reg["target_runs"]))]
        if blanks:
            for _, r in blanks:
                page.add_redact_annot(pymupdf.Rect(r[0], r[1] - 0.6, r[2], r[3] + 0.6),
                                      fill=False)
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                                  graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                                  text=pymupdf.PDF_REDACT_TEXT_NONE)
            manifest["blank_rules_removed"] += [
                {"page": pno, "region_id": reg["region_id"],
                 "rect": [round(v, 2) for v in r]} for reg, r in blanks]
        if leaders:
            for _, _, run in leaders:
                for r in run["rects"]:
                    page.add_redact_annot(r, fill=False)
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                                  graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                                  text=pymupdf.PDF_REDACT_TEXT_NONE)

        missing_blank = [reg["region_id"] for reg, _ in ok_regions
                         if reg.get("fill_rules")
                         and not BLANK_RUN_RE.search(
                             "".join(x["text"] for x in reg["target_runs"]))]
        for rid in dict.fromkeys(missing_blank):
            issues.append(make_issue(
                "FILL_BLANK_DROPPED", "P1", STAGE,
                "nguồn có ô trống điền tay nhưng bản dịch không đặt lại dãy '____' — "
                "gạch gốc giữ nguyên và chữ dịch sẽ đè lên, biểu mẫu hết dùng được",
                page=pno, region_id=rid))

        for reg, fr in ok_regions:
            for line in fr["lines"]:
                for seg in line["segments"]:
                    col = seg["color"]
                    rgb = (((col >> 16) & 255) / 255, ((col >> 8) & 255) / 255, (col & 255) / 255)
                    try:
                        rv = page.insert_text(
                            pymupdf.Point(seg["x"], line["y"]), seg["text"],
                            fontsize=fr["size"], fontname=pack.alias(seg["font"]),
                            fontfile=pack.path(seg["font"]), color=rgb,
                            rotate=fr["rotation"])
                        if isinstance(rv, (int, float)) and rv < 0:
                            raise RuntimeError(f"insert_text rv={rv}")
                    except Exception as e:  # mọi insertion failure là blocking (spec §9.3)
                        issues.append(make_issue("INSERTION_FAILED", "P0", STAGE,
                                                 f"{e}", page=pno, region_id=reg["region_id"]))
            manifest["regions"].append({
                "region_id": reg["region_id"], "page": pno, **{k: fr[k] for k in
                ("size", "src_size", "ratio", "alignment", "rotation")},
                **({"column": reg["column_index"]} if "column_index" in reg else {}),
                "line_count": len(fr["lines"]),
                "fonts": sorted({s["font"] for l in fr["lines"] for s in l["segments"]}),
            })

        drawn: list[dict] = []
        # Vẽ lại gạch dẫn: giữ nguyên mép PHẢI của nét gốc, chỉ dời điểm bắt đầu theo mép
        # phải của chữ đã dịch. Tiêu đề dịch dài hơn thì nét ngắn lại, ngắn hơn thì nét dài
        # ra — hai ca đối xứng, không ca nào cần đoán toạ độ.
        for reg, x0, run in leaders:
            if run["x1"] - x0 < LEADER_MIN_LEN:
                issues.append(make_issue(
                    "TOC_LEADER_DROPPED", "P2", STAGE,
                    f"bản dịch chạm tới số trang, không còn chỗ vẽ gạch dẫn "
                    f"(còn {run['x1'] - x0:.1f}pt)", page=pno, region_id=reg["region_id"]))
                continue
            shape = page.new_shape()
            shape.draw_line(pymupdf.Point(x0, run["y"]), pymupdf.Point(run["x1"], run["y"]))
            # Vẽ đường HỞ. Mặc định của pymupdf là đóng đường, tức vẽ thêm lượt về từ điểm
            # cuối; lượt về lệch pha nét đứt nên lấp kín khe — gạch dẫn thành liền nét ở
            # đúng những dòng mà chiều dài chia hết kiểu ấy, dòng khác thì không.
            shape.finish(color=run["color"], width=run["width"], dashes=run["dashes"],
                         closePath=False)
            shape.commit()
            # Dải gạch dẫn là vùng engine CỐ Ý vẽ lại — Gate 5 và Gate 6 phải biết, nếu
            # không thì cụm vector đổi và pixel lệch đều bị báo như hỏng hóc. Ghi cả khung
            # cũ lẫn khung mới: gate trừ đúng hai khung đó, không nới lỏng phép so.
            drawn.append({"page": pno, "region_id": reg["region_id"],
                          "old": [round(run["x0"], 2), round(run["y"] - 0.6, 2),
                                  round(run["x1"], 2), round(run["y"] + 0.6, 2)],
                          "new": [round(x0, 2), round(run["y"] - 0.6, 2),
                                  round(run["x1"], 2), round(run["y"] + 0.6, 2)]})
        manifest["toc_leaders"] += drawn
        leader_bands = [d["new"] for d in drawn]

        # link preservation (spec §9.4)
        if cfg["render"]["preserve_links"]:
            after = page.get_links()
            def lkey(l):
                fr_ = l.get("from")
                return (l.get("kind"), l.get("uri", l.get("page")),
                        tuple(round(v) for v in (fr_.x0, fr_.y0, fr_.x1, fr_.y1)) if fr_ else ())
            have = {lkey(l) for l in after}
            restored = 0
            for l in links_before:
                if lkey(l) not in have:
                    try:
                        page.insert_link(l)
                        restored += 1
                    except Exception as e:
                        issues.append(make_issue("LINK_RESTORE_FAILED", "P1", STAGE,
                                                 str(e), page=pno))
            if restored:
                issues.append(make_issue("LINKS_RESTORED", "P2", STAGE,
                                         f"khôi phục {restored} link sau redaction", page=pno))

        manifest["pages"][str(pno)] = {
            "painted_regions": len(ok_regions),
            "mask_rects": [[round(v, 2) for v in (m.x0, m.y0, m.x1, m.y1)]
                           for m in page_masks] + leader_bands,
            "text_rects": [painted_rect(l, fr2)
                           for _, fr2 in ok_regions for l in fr2["lines"]],
        }

    # optimized save (spec §6.10) — native subsetting, không cần fontTools
    try:
        doc.subset_fonts(fallback=False)
    except Exception as e:
        issues.append(make_issue("SUBSET_FAILED", "P1", STAGE, str(e)))
    draft = job.p("render", "draft.pdf")
    doc.save(draft, garbage=4, deflate=True, use_objstms=1)
    doc.close()
    check = pymupdf.open(draft)
    if check.page_count != job.load()["page_count"]:
        issues.append(make_issue("PAGE_COUNT_CHANGED", "P0", STAGE,
                                 f"{check.page_count} != {job.load()['page_count']}"))
    check.close()

    save_json(job.p("model", "regions.json"), model)
    save_json(job.p("render", "render_manifest.json"), manifest)
    job.mark_stage(STAGE, "done" if not manifest["partial"] else "partial")
    if job.status() == "TRANSLATED":
        job.set_status("RENDERED")
    n_painted = len(manifest["regions"])
    job.log_event(STAGE, "info", "PAINTED",
                  f"painted={n_painted} skipped={len(manifest['skipped'])}")
    job.write_summary("Chạy `qa_gates.py --job <job>` để chấm quality gates.")
    print(f"fit_paint: painted={n_painted} skipped={len(manifest['skipped'])} "
          f"issues={len(issues)} → {draft}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job", required=True)
    ap.add_argument("--pages", help="dev: chỉ paint các trang này, vd 0,1,2")
    ap.add_argument("--allow-partial", action="store_true")
    args = ap.parse_args()
    job = Job(args.job)
    try:
        job.verify_fingerprint()
        pages = set(int(p) for p in args.pages.split(",")) if args.pages else None
        with job.acquire_lock(STAGE):
            paint(job, pages, args.allow_partial)
    except BlockingError as e:
        exit_blocking(job, STAGE, e)


if __name__ == "__main__":
    main()
