"""Stage 6 — Fit + safe paint: font resolve, constraint fitting, redact, insert, save.

Spec §6.8-6.10, §7, §8, §9. Output: render/draft.pdf, render/render_manifest.json.
Chạy: python3 fit_paint.py --job <job_dir> [--pages 0,1,2] [--allow-partial]
"""

from __future__ import annotations

import argparse
import collections
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


def has_alnum(text: str) -> bool:
    """Run có mang chữ hay số không. `isalnum` đúng cho cả CJK, nên `宋体` tính là có chữ;
    còn `：`, `（）`, dãy chấm dẫn của mục lục thì không — đó là thứ không mang danh tính
    kiểu chữ để truyền cho bản dịch."""
    return any(c.isalnum() for c in text)


def role_style(reg: dict, role: str) -> dict:
    """Style của role, lấy từ run ĐẦU TIÊN CÓ NÉT MỰC — không phải run đầu tiên khớp role.

    Bản gốc hay mở đầu một đoạn bằng span khoảng trắng thuộc font khác: ca thật đo được
    trong HV48100 user manual là run 0 = một dấu cách `AdobeSongStd-Light` (serif) rồi
    run 1 = 175 ký tự `ArialMT` (sans), cả hai role `body`. Lấy run đầu thì cả đoạn dịch
    ra Noto Serif trong khi nguồn là sans — 13 vùng / 7.738 ký tự trên riêng tài liệu đó,
    và một vùng nữa trên V5 datasheet đã phát hành.

    Cùng lớp lỗi "đệm space" mà `ink_base_x` (ngay dưới) sửa cho trục x từ 1.8.0/1.9.9:
    span khoảng trắng có advance nhưng không vẽ gì, nên nó không được quyền quyết định
    thứ gì về hình thức của chữ thật.

    Mọi run cùng role đều rỗng thì không có gì để so — giữ nguyên hành vi cũ, lấy run đầu
    khớp role, rồi mới lùi về `runs[0]`.
    """
    same = [r for r in reg["runs"] if r["role"] == role]
    for r in same:
        if r["text"].strip():
            return r
    return same[0] if same else reg["runs"][0]


def role_face(reg: dict, role: str) -> dict:
    """Run quyết định KIỂU CHỮ của role: run mang NHIỀU NÉT MỰC NHẤT, không phải run đầu.

    1.9.34 tước quyền quyết định của run rỗng, nhưng run có mực mà rất ngắn thì vẫn thắng.
    Ca thật: V16 Lite quick guide có run 0 = một dấu `：` font `AdobeSongStd-Light` (serif)
    rồi 210 ký tự `ArialMT` (sans) cùng role — một ký tự quyết định kiểu chữ cho cả đoạn,
    và bản đã phát hành ra 7,94% ký tự Noto Serif. Cùng cơ chế: dấu `≥` mở đầu ô
    `≥6000Cycles` của V5 datasheet, `(A)` của V5 Series manual.

    Bản dịch một run phải chọn MỘT kiểu chữ cho cả vùng, nên chọn kiểu phủ được nhiều chữ
    nguồn nhất là lệch ít nhất. Hoà thì `max` giữ run sớm hơn.

    Vì sao KHÔNG sửa thẳng `role_style`: hàm đó còn quyết định MÀU (chỗ gọi cuối `paint`),
    và ở bảng thông số datasheet nhãn là đen còn giá trị là xám — đo được 7 vùng mà run đa
    số đổi màu nhãn từ `#000101` sang `#585857`. Kiểu chữ thì lấy theo đa số là đúng, màu
    thì không; nên tách hai câu hỏi thành hai hàm thay vì nới một hàm cho cả hai.

    1.9.36 — **role suy biến**: có vùng mà role của bản dịch không mang ký tự chữ-số NÀO
    trong nguồn, toàn bộ chữ thật nằm ở role khác. Ca thật: ghi chú "Note：..." của V16 Lite
    có role `body` đúng một dấu `：` font Song, còn `Note` lẫn cả câu sau đều là `emphasis`
    `Arial-BoldMT`; bản dịch ra một run `body` nên cả câu vẽ bằng Noto Serif. Dấu câu không
    mang danh tính kiểu chữ, nên khi role rỗng nghĩa như vậy thì mượn HỌ CHỮ (`serif`/`mono`)
    của run nhiều mực nhất trong CẢ VÙNG.

    Họ chữ và độ đậm mượn từ HAI phép đo khác nhau, vì chúng là hai thuộc tính khác nhau:

    - **Họ chữ** lấy từ run nhiều mực nhất trong số run CÓ CHỮ-SỐ. Dấu câu không mang danh
      tính họ chữ; ô `（A）` của V5 Series chỉ có mỗi chữ `A` là sans, hai dấu ngoặc toàn rộng
      là Song, và họ chữ đúng của nó là sans.
    - **Độ đậm/nghiêng** lấy từ run nhiều mực nhất trong số MỌI run, không lọc dấu câu, vì
      độ đậm là thuộc tính của khối mực chứ không của chữ. Ca thật đối nghịch: dòng mục lục
      V16 Lite là tiêu đề chương ĐẬM 21 ký tự + dãy chấm THƯỜNG 38 ký tự, lấy theo run có
      chữ-số thì đậm nguyên dòng — hỏng 38 ký tự chấm để sửa 21 ký tự tiêu đề; lấy theo mọi
      run thì dãy chấm thắng và dòng vẫn thường, đúng như bản gốc. Ngược lại ghi chú
      "Note：..." là 4 ký tự đậm + 1 dấu `：` thường + 98 ký tự đậm, mọi run thì đậm thắng —
      cũng đúng như bản gốc, và khớp bốn câu ghi chú anh em cùng trang.
    """
    inked = [r for r in reg["runs"] if r["role"] == role and r["text"].strip()]
    if not inked:
        return role_style(reg, role)
    pick = max(inked, key=lambda r: len(r["text"].strip()))
    if not any(has_alnum(r["text"]) for r in inked):
        by_ink = [r for r in reg["runs"] if r["text"].strip()]
        alnum = [r for r in by_ink if has_alnum(r["text"])]
        longest = lambda pool: max(pool, key=lambda r: len(r["text"].strip()))
        face = longest(alnum) if alnum else pick
        mass = longest(by_ink) if by_ink else pick
        pick = {**pick, "serif": face["serif"], "mono": face.get("mono", False),
                "bold": mass["bold"], "italic": mass.get("italic", False)}
    return pick


# Cụm nhì đạt tỷ lệ này so với cụm nhất thì coi là hoà — xem `ink_size`.
TIE_COUNT_RATIO = 0.8


def ink_size(reg: dict) -> float:
    """Cỡ chữ gốc của vùng: median cỡ theo từng ký tự CÓ NÉT MỰC.

    Trước 1.9.42 phép median đếm cả khoảng trắng. Bản gốc hay đệm một span dấu cách cỡ khác
    ngay đầu vùng, và span đó dài hơn phần chữ thật thì nó THẮNG phiếu.

    Ca thật 2026-08-09, `E-BOX 48100R Sol-Ark package` và `V5 Sol-Ark packages` trang 2, dòng
    cuối bảng thông số: run 0 = **20 dấu cách ở 13.6pt**, run 1 = `10 Years ` 9 ký tự ở 8.0pt.
    Median tính cả trắng ra 13.6 → `10 năm` vẽ to gần gấp đôi mọi dòng quanh nó và tràn lên
    4.99pt vào dòng `Kích thước` ở trên (`G4_OUT_OF_CONTAINER` + `G4_COLLISION`). Quét cả kho
    ra 10 vùng / 8 job, trong đó 6 job đã giao khách với mức lệch 1–2.6pt — đủ kín để lọt qua
    mọi lần duyệt trước.

    Cùng luật với `ink_base_x` (trục x, 1.8.0/1.9.9) và `role_style`/`role_face` (trục kiểu
    chữ, 1.9.34/1.9.35): **span khoảng trắng có advance nhưng không vẽ gì, nên nó không được
    quyết định thứ gì về hình thức của chữ thật.** Đây là trục thứ ba, và là trục cuối.

    Vùng toàn khoảng trắng thì không có gì để so — giữ nguyên hành vi cũ.

    **Luật hoà phiếu (1.9.43).** Median là thống kê sai cho vùng có HAI cỡ chữ thật gần bằng
    nhau về số ký tự: nó rơi về cụm đông hơn dù chỉ hơn một ký tự, nên một chênh lệch vô
    nghĩa lật cả cỡ chữ của vùng. Ca thật `V16 user manual` tr.11, ô
    `Integrated Thermal Aerosol Fire Suppression Module`: nhãn chính **45 ký tự ở 9.0pt**,
    dòng chú thích **46 ký tự ở 5.0pt** — 46 thắng 45, cả ô vẽ ở 5.0pt và nhãn chính nhỏ đi
    44% so với nguồn. Bản đã giao trước đó ra 7.0pt chỉ vì median khi ấy đếm cả khoảng trắng
    và rơi đúng vào giữa — ăn may, không phải luật.

    Khi cụm nhì đạt ≥ `TIE_COUNT_RATIO` số ký tự của cụm nhất thì không có bên nào thắng
    thật; lấy **cỡ LỚN HƠN** trong hai cụm. Nhãn chính là thứ mắt người đọc trước, và fitter
    còn quyền thu nhỏ nếu không vừa — thu từ cỡ đúng xuống thì an toàn hơn là phóng từ cỡ sai
    lên. Đo trên chính ô đó: src_size 9.0 → fit ra 8.96pt, 5 dòng, không sinh issue nào.
    """
    ink = [r["size"] for r in reg["runs"] for ch in r["text"] if ch.strip()]
    if not ink:
        allc = [r["size"] for r in reg["runs"] for _ in r["text"]]
        return statistics.median(allc) if allc else reg["runs"][0]["size"]

    by_size = collections.Counter(ink)
    top = by_size.most_common(2)
    if len(top) > 1 and top[1][1] >= TIE_COUNT_RATIO * top[0][1]:
        return max(top[0][0], top[1][0])
    return statistics.median(ink)


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
    # Kẹp "chỉ nâng, không hạ" áp theo TỪNG DÒNG rồi mới lấy min, chứ không kẹp cả vùng bằng
    # origin của dòng đầu. Mỗi vế giữ đúng một việc:
    #   `max(origin, ink)` của một dòng — chặn side-bearing âm (chữ như `J`, `f` nghiêng có
    #      nét thò trái hơn origin vài phần mười pt) kéo base_x đi lạc;
    #   `min(...)` qua các dòng — về mép trái nhất, tức lề thật của vùng.
    # Kẹp cả vùng bằng `max(span_x, …)` chỉ kích hoạt được khi dòng ĐẦU nằm phải hơn mực của
    # một dòng khác, và ở đúng ca đó nó luôn sai: ô bảng gộp mà thứ tự đọc bắt đầu ở cột PHẢI
    # thì base_x bị ghim vào cột phải, mọi thụt lề `x_i - base_x` hoá âm rồi clamp về 0, cả
    # khối dồn thành một chồng. Ca thật V5 p6, ô gộp hai hàng `DC Breaker`/`Cycle Life`: dòng
    # đầu `Dual Pole, 125Vdc,` ở x=297.2 còn `No` của cột giữa ở x=191.0 — base_x thành
    # 297.2 và `Không` bị nhét vào giữa hai dòng thông số của cột phải.
    # Đo trên các job: 7 vùng có dòng đầu không phải mép trái nhất.
    return min(max(l["spans"][0]["origin"][0], l["bbox"][0]) for l in lines)


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
    got = segment_source_lines(reg, n_seg)
    if not got:
        return [0.0] * max(1, n_seg)
    idx, pattern = got
    lines = reg["lines"]
    ind = [max(0.0, round(lines[i]["bbox"][0] - base_x, 2)) for i in idx]
    # Chặn thụt lề vô lý: vùng hai cột (nửa trái ngắn, nửa phải ở x lớn) khớp đếm theo hình
    # mẫu 3 nhưng cho ra 268pt trên khung 366pt. Thà không suy còn hơn ném đoạn ra giữa
    # trang. Hai hình mẫu đầu đo trực tiếp mức thụt nên không cần chốt này.
    if pattern == 3 and max(ind) > INDENT_MAX_FRAC * (
            max(l["bbox"][2] for l in lines) - base_x):
        return [0.0] * n_seg
    return ind


def segment_anchors(reg: dict, n_seg: int) -> list[float] | None:
    """Baseline nguồn của từng đoạn bản dịch, hoặc None nếu không suy được ánh xạ.

    Vì sao cần: dấu `•` `◇` `∘` KHÔNG nằm trong region — chúng là glyph riêng, neo cứng ở
    baseline của nguồn và không bị redact. Fitter thì rải dòng liên tục từ `base_y` với
    leading cố định, nên đoạn thứ i chỉ rơi đúng dấu của nó khi mọi đoạn trước đó chiếm đúng
    số dòng như nguồn. Tiếng Việt hiếm khi chia dòng y hệt tiếng Anh, nên cả khối lệch pha.
    Ca thật V5 p12 §5.2: nguồn 6 dòng / 3 mục `◇`, bản dịch 3 đoạn — ĐẾM ĐÃ KHỚP — nhưng
    đoạn 1 chỉ chiếm 3 dòng thay vì 4, thế là `◇` cuối rơi vào chỗ trống.
    """
    got = segment_source_lines(reg, n_seg)
    if not got:
        return None
    return [reg["lines"][i]["spans"][0]["origin"][1] for i in got[0]]


def line_baselines(line_seg: list, base_y: float, leading: float,
                   anchors: list | None) -> list[float]:
    """Baseline từng dòng đã fit. Không có `anchors` thì rải liên tục như cũ.

    Luật neo: dòng MỞ ĐOẠN tụt xuống baseline nguồn của đoạn đó, nhưng không bao giờ lùi lên
    trên dòng trước — `max(neo, trước + leading)`. Nhờ vế `max`, đoạn dịch dài hơn nguồn thì
    tự động chảy tiếp như cũ thay vì đè lên nhau; đoạn ngắn hơn thì phần dôi ra thành khoảng
    trắng đúng chỗ bản gốc có.
    """
    ys, prev_si = [], None
    for li, si in enumerate(line_seg):
        if li == 0:
            y = base_y
        elif anchors and si != prev_si and si < len(anchors):
            y = max(anchors[si], ys[-1] + leading)
        else:
            y = ys[-1] + leading
        ys.append(y)
        prev_si = si
    return ys


def segment_source_lines(reg: dict, n_seg: int) -> tuple[list[int], int] | None:
    """→ (dòng nguồn tương ứng với từng đoạn bản dịch, số hiệu hình mẫu), hoặc None.

    Thụt lề và neo baseline phải dùng CHUNG một ánh xạ, nếu không hai thứ nói về hai cấu
    trúc khác nhau trên cùng một vùng.

    Ba hình mẫu, thử đúng thứ tự này — hai cái đầu đo trực tiếp mức thụt nên chắc hơn:
    (1) số đoạn bằng số dòng nguồn: bản dịch giữ nguyên cấu trúc dòng, ánh xạ 1:1;
    (2) số đoạn bằng số mục thụt sâu, và các mục ấy cùng một mức;
    (3) số đoạn bằng số dòng MỞ ĐOẠN (`paragraph_starts`) — bắt được ca có mục bắt đầu ngay
        ở lề thân bài, thứ mà hai hình mẫu đếm-mức-thụt luôn trượt.
    """
    lines = reg.get("lines") or []
    if len(lines) < 2 or n_seg < 1:
        return None
    lv = [l["bbox"][0] for l in lines]
    # Hình mẫu 0 — DẤU GẠCH ĐẦU DÒNG, ưu tiên trên hết. Ba hình mẫu dưới đều SUY từ hình học
    # chữ; dấu thì được bản gốc vẽ ra, mỗi dấu một mục, không phải suy đoán. Phần đầu vùng
    # chưa có dấu (tiêu đề, đoạn dẫn) vẫn nhờ `paragraph_starts` chia.
    # Đo trên các job: nơi số mục khớp số đoạn dịch — 9 vùng trùng đúng ba hình mẫu cũ,
    # 3 vùng ba hình mẫu cũ chịu thua, **0 vùng mâu thuẫn**. Thuần bổ sung.
    bl = reg.get("bullet_lines")
    if bl:
        pre = [i for i in (paragraph_starts(lines) or []) if i < bl[0]]
        idx = sorted(set(pre) | set(bl))
        if len(idx) == n_seg:
            return idx, 0
    if n_seg == len(lv):
        return list(range(len(lv))), 1
    lo = min(lv)
    # Không dùng "đoạn cùng mức" vì hai mục gạch đầu dòng liền nhau cùng mức bị gộp làm một,
    # cho ra kết quả nham nhở — mục thụt, mục không.
    deep = [i for i, v in enumerate(lv) if v - lo >= 2.0]
    if deep and n_seg == len(deep) \
            and max(lv[i] for i in deep) - min(lv[i] for i in deep) < 2.0:
        return deep, 2
    st = paragraph_starts(lines)
    if st and len(st) == n_seg:
        return st, 3
    return None


HEADING_NUM_RE = re.compile(r"^\s*\d+(\.\d+)*[.\s]\s*\S")
# Tựa được coi là "căn giữa theo trang" khi tâm chữ nguồn lệch tâm trang không quá ngần này.
CENTERED_TOL_PT = 3.0
# Nửa khe tối thiểu giữa hai region cạnh nhau cùng được nới. Mỗi bên lùi chừng này khỏi
# điểm giữa, nên khoảng cách bảo đảm giữa hai cụm chữ là gấp đôi.
SIBLING_GAP_PT = 1.0


OCCLUSION_COVER = 0.85   # phần bbox phải nằm trong ảnh mới đáng bỏ công dựng ảnh thử
OCCLUSION_DPI = 150


def occluded_by_image(doc, pno: int, bbox: list, img_rects: list) -> bool:
    """Chữ nguồn trong `bbox` có bị một ảnh vẽ ĐÈ LÊN nên không nhìn thấy được không?

    Vì sao cần: engine vẽ bản dịch SAU cùng, nên chữ mà bản gốc giấu dưới ảnh lại nổi lên
    trên ảnh ở bản dịch — bản dịch có chữ mà bản gốc không có, và không gate nào thấy: Gate
    3 tìm thấy chữ (nó có thật), Gate 4 thấy nằm trong khung, Gate 6 coi thay đổi đó là
    NẰM TRONG mask nên bỏ qua. Ca thật: Pi Station 261 EX trang 24 — trang là một ảnh phủ
    kín 100%, chú thích hình nằm dưới ảnh; bản dịch in "Hình 3.4 …" vắt ngang chân tủ.

    Phép thử là dựng ảnh chứ không đọc thứ tự content stream: một trang có nhiều stream,
    có form XObject lồng nhau, và trong suốt — đọc thứ tự thì phải mô phỏng lại cả trình
    vẽ. Dựng hai lần rồi so pixel trả lời đúng câu hỏi cần hỏi: xoá chữ đi thì trang có
    đổi không.

    Chỉ chạy cho vùng nằm gần trọn trong một ảnh (`OCCLUSION_COVER`) — đo trên 14 job:
    9 vùng lọt sàng lọc này, 2 vùng thật sự bị che. Nhãn vẽ TRÊN hình (ca thường gặp) đổi
    pixel nên không dính.
    """
    b = pymupdf.Rect(*bbox)
    if b.is_empty or not any((b & r).get_area() > OCCLUSION_COVER * b.get_area()
                             for r in img_rects):
        return False
    before = doc[pno].get_pixmap(dpi=OCCLUSION_DPI, clip=b).samples
    probe = pymupdf.open(doc.name)
    pp = probe[pno]
    pp.add_redact_annot(b)
    pp.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)   # bỏ chữ, giữ ảnh/vector
    after = pp.get_pixmap(dpi=OCCLUSION_DPI, clip=b).samples
    probe.close()
    return before == after


BACKDROP_PAD_PT = 1.0        # mép ngang: chữ thường nhô khỏi dải nền dưới 1pt
BACKDROP_COVER = 0.5         # mảnh nền phải phủ ít nhất nửa chiều cao vùng chữ
BACKDROP_TILE_GAP_PT = 1.0   # khe tối đa giữa hai mảnh vẫn coi là một dải liền


def backdrop_band(b: list, obstacles: list, share_gap: list = ()) -> tuple | None:
    """→ (x0, x1, các mảnh) của DẢI NỀN chạy sau vùng chữ `b`, hoặc None.

    Nền không nhất thiết là MỘT hình. Ca thật 2026-08-09: dải vàng sau tiêu đề mục của các
    hướng dẫn ghép biến tần được xuất thành **48 ô vẽ rời rộng 8pt** xếp liền nhau; ba ô
    nằm dưới chữ, số còn lại nằm bên phải. Xét từng ô thì ba ô đầu "chồng lên chữ" (chặn
    đứng phép nới) còn các ô sau "là vật cản bên phải" (kẹp mép phải về sát chữ) — cộng lại
    là không nới được một pt nào, dù cả dải rộng 428pt đang nằm sau chính chữ đó. Phải ghép
    các mảnh liền nhau lại rồi mới xét.

    Mảnh nền: phủ dọc ít nhất `BACKDROP_COVER` chiều cao vùng chữ, và KHÔNG phải bbox chữ
    của region khác (`share_gap` giữ đúng các object đó, so khớp theo identity). Ngưỡng phủ
    dọc là thứ tách nền khỏi **nét kẻ ngang cắt qua chữ**: nét dày dưới 1pt phủ ~3% chiều
    cao dòng, không đạt ngưỡng, nên vẫn chặn phép nới như trước.

    Dải trả về phải BAO được bề ngang của chữ (sai số `BACKDROP_PAD_PT` mỗi mép — dải nền
    thường bắt đầu đúng tại mép chữ, làm tròn đủ để trượt phép so chặt). Dải nào không bao
    được thì không phải nền của vùng này, các mảnh của nó vẫn là vật cản bình thường.
    """
    h = b[3] - b[1]
    if h <= 0:
        return None
    tiles = [ob for ob in obstacles
             if not any(ob is s for s in share_gap)
             and (min(ob[3], b[3]) - max(ob[1], b[1])) / h >= BACKDROP_COVER]
    if not tiles:
        return None

    bands: list[list] = []      # [x0, x1, [mảnh…]]
    for ob in sorted(tiles, key=lambda o: o[0]):
        if bands and ob[0] <= bands[-1][1] + BACKDROP_TILE_GAP_PT:
            bands[-1][1] = max(bands[-1][1], ob[2])
            bands[-1][2].append(ob)
        else:
            bands.append([ob[0], ob[2], [ob]])

    for x0, x1, members in bands:
        if x0 <= b[0] + BACKDROP_PAD_PT and x1 >= b[2] - BACKDROP_PAD_PT:
            return x0, x1, members
    return None


def expand_container(reg: dict, need_w: float, obstacles: list, page_rect: list,
                     margins: tuple[float, float], align: str,
                     share_gap: list = ()) -> tuple[list, str | None] | None:
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

    `share_gap`: bbox của những region CŨNG có thể tự nới (chữ dịch của cùng trang, so khớp
    theo identity). Vật cản trong danh sách này chỉ chặn tới GIỮA khe chứ không tới mép của
    nó — xem `SIBLING_GAP_PT`. Vật cản không nằm trong danh sách (hình, vector, nét kẻ) là
    cố định nên chặn tới đúng mép.
    """
    b = reg["bbox"]
    y0, y1 = b[1], b[3]
    left_lim, right_lim = margins

    # Dải nền chạy sau chữ (xem `backdrop_band`) không phải vật cản: nới ngang trong lòng
    # nó không đụng thêm vào cái gì. Nó chỉ đóng vai giới hạn — chữ không nên tràn ra khỏi
    # dải màu của chính mình.
    band = backdrop_band(b, obstacles, share_gap)
    skip = ()
    if band:
        left_lim = max(left_lim, band[0])
        right_lim = min(right_lim, band[1])
        skip = band[2]

    for ob in obstacles:
        if ob[3] <= y0 or ob[1] >= y1:      # không giao dải dọc của heading
            continue
        if any(ob is s for s in skip):
            continue
        # Hàng xóm là chữ dịch thì CHÍNH NÓ cũng nới được về phía mình. Chặn tới mép bbox
        # NGUỒN của nó là không đủ: cả hai đều thấy khe trống theo bbox nguồn, cả hai cùng
        # lấn vào, cộng lại thành chồng chữ. Ca thật: dải nhãn hình dưới một hàng ảnh —
        # nhãn trái nới phải tới 107.99 trong khi nhãn kế nới trái tới 106.39, đè 1.60pt,
        # mà xét riêng từng region thì cả hai đều "tôn trọng vật cản".
        # Mỗi bên chỉ được lấn tới giữa khe → hai bên cùng nới vẫn cách nhau
        # 2*SIBLING_GAP_PT, và kết quả không phụ thuộc thứ tự paint.
        movable = any(ob is s for s in share_gap)
        if ob[2] <= b[0]:
            lim = (ob[2] + b[0]) / 2 + SIBLING_GAP_PT if movable else ob[2]
            left_lim = max(left_lim, lim)
        elif ob[0] >= b[2]:
            lim = (b[2] + ob[0]) / 2 - SIBLING_GAP_PT if movable else ob[0]
            right_lim = min(right_lim, lim)
        else:
            return None                      # vật cản chồng lên chính chữ → không nới
    pad = 1.0
    c = reg["container"]
    cx_page = (page_rect[0] + page_rect[2]) / 2
    centered = abs((b[0] + b[2]) / 2 - cx_page) <= CENTERED_TOL_PT
    want = need_w + pad

    def ok(x0: float, x1: float) -> bool:
        # Mép nào KHÔNG dịch ra khỏi khung cũ thì không phải xin phép hàng xóm: nó có lấn
        # vào đâu mà chặn. Thiếu vế `>= c[0]` thì vùng có hàng xóm DÍNH SÁT mép trái không
        # bao giờ nới được — `lim` của khe rộng 0 rơi vào `c[0] + SIBLING_GAP_PT`, lớn hơn
        # chính mép trái của nó, nên cả hai phương án đều trượt dù bên phải trống trơn.
        # Ca thật: tiêu đề bị nguồn xé làm hai text object giữa từ (`3.6.4. PCS vie` + `w`,
        # `Chapter 2 System Introductio` + `n`) — mảnh sau chỉ nới sang PHẢI, không đụng gì
        # tới mảnh trước, mà vẫn bị ép thu cỡ chữ.
        left_ok = x0 >= left_lim or x0 >= c[0]
        right_ok = x1 <= right_lim or x1 <= c[2]
        return left_ok and right_ok and x1 - x0 > c[2] - c[0]

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
    if reg.get("no_expand") or reg["rotation"] != 0 or len(reg["lines"]) != 1:
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


def target_segments(reg: dict) -> list[tuple[str, str]]:
    """[(chữ, role)] của từng đoạn ngăn bằng "\\n", nối qua mọi target run.

    Không dùng `"\\n".join(run.text)`: run là đơn vị STYLE, không phải đơn vị đoạn. Nối bằng
    "\\n" sẽ chèn thêm một ranh giới đoạn giữa mỗi cặp run, nên target có tiêu đề in đậm +
    phần còn lại bị đếm thừa đoạn. Ranh giới đoạn nằm trong CHỮ, ranh giới run thì không —
    role của đoạn lấy theo run mở đầu đoạn đó.
    """
    segs: list[list] = [["", reg["target_runs"][0]["role"] if reg["target_runs"] else "body"]]
    for run in reg["target_runs"]:
        parts = run["text"].split("\n")
        segs[-1][0] += parts[0]
        for p in parts[1:]:
            segs.append([p, run["role"]])
    return [(t, r) for t, r in segs]


def _runs_for_spans(reg: dict, cell_spans: list) -> list[dict] | None:
    """Các run nguồn phủ đúng những dải ký tự đã cho, hoặc None nếu offset không khớp.

    `make_region` dựng `runs` từ CHÍNH danh sách span của region theo thứ tự, nên nối chữ hai
    bên phải bằng nhau — cắt run theo offset ký tự là phép chiếu chính xác, không phải dò
    theo chuỗi. Lệch độ dài nghĩa là bất biến đó đã hỏng: trả None, không đoán.
    """
    lines = reg["lines"]
    off, pos = {}, 0
    for li, ln in enumerate(lines):
        for si, sp in enumerate(ln["spans"]):
            off[(li, si)] = pos
            pos += len(sp["text"])
    if pos != sum(len(r["text"]) for r in reg["runs"]):
        return None
    want = sorted((off[(li, si)] + c0, off[(li, si)] + c1) for li, si, c0, c1 in cell_spans)
    out, rpos = [], 0
    for r in reg["runs"]:
        a, b = rpos, rpos + len(r["text"])
        rpos = b
        piece = "".join(r["text"][max(a, s) - a:min(b, e) - a]
                        for s, e in want if s < b and e > a)
        if piece:
            out.append({**r, "text": piece})
    return out or None


def _cell_line(line: dict, si: int, c0: int, c1: int) -> dict:
    """Dòng con chỉ chứa dải ký tự `[c0, c1)` của span `si`, bbox bó đúng nét mực của nó.

    Giữ bbox và span của dòng gốc thì chúng trải hết hàng, và `ink_base_x` — vốn lấy
    `max(origin, bbox[0])` để chặn side-bearing âm — không nâng nổi origin có đệm space lên
    mép mực: ô trị số bị vẽ tụt vào giữa hàng, đè lên nhãn. `build_masks` cũng đọc bbox này,
    giữ bbox gốc thì mỗi ô mask cả hàng.
    """
    sp = line["spans"][si]
    chars = sp["chars"][c0:c1]
    ink = [c["bbox"] for c in chars if not c["c"].isspace()] or [c["bbox"] for c in chars]
    x0, x1 = min(b[0] for b in ink), max(b[2] for b in ink)
    sub = {**sp, "text": sp["text"][c0:c1], "chars": chars,
           "origin": [x0, sp["origin"][1]], "bbox": [x0, sp["bbox"][1], x1, sp["bbox"][3]]}
    return {**line, "spans": [sub], "bbox": [x0, line["bbox"][1], x1, line["bbox"][3]]}


def spec_grid(reg: dict) -> list[dict] | None:
    """Bảng thông số hai cột căn bằng space → một sub-region cho mỗi Ô; None nếu không phải ca đó.

    Lưới do stage 2 đo và ghi vào `reg["spec_cells"]` (xem `spec_grid_cells`) — ở đây chỉ
    dựng khung vẽ, không đo lại: stage 3 hứa với model bao nhiêu ô thì stage 6 phải đặt đúng
    ngần ấy ô, nếu không hợp đồng đếm là vô nghĩa.

    Hợp đồng với bản dịch: mỗi đoạn ngăn bằng "\\n" ứng với một ô, theo thứ tự đọc trái→phải
    rồi xuống hàng. Lệch số đoạn → None, giữ nguyên hành vi cũ (dồn một cột); stage 5 đã bắn
    P1 `SPEC_GRID_DROPPED` để người dịch sửa, engine không tự đoán.

    Khung mỗi ô cao đúng MỘT hàng — từ mép trên hàng tới mép trên hàng kế. Ngân sách chật thế
    khiến `fit_region` thu cỡ chữ để giữ một dòng thay vì tràn xuống hàng dưới, và nếu vẫn
    không vừa ở sàn `minimum_ratio` thì bắn `FIT_IMPOSSIBLE` — báo to còn hơn đè chữ lên hàng
    kế mà không ai thấy.
    """
    cells = reg.get("spec_cells")
    if not cells or reg["rotation"] != 0 or not reg.get("target_runs"):
        return None
    segs = target_segments(reg)
    if len(segs) != len(cells):
        return None

    lines, c = reg["lines"], reg["container"]
    anchor = reg["spec_anchor_x"]
    rows = sorted({cell["row"] for cell in cells})
    top = {r: min(lines[li]["bbox"][1] for cell in cells if cell["row"] == r
                  for li, *_ in cell["spans"]) for r in rows}
    subs = []
    for (text, role), cell in zip(segs, cells):
        runs = _runs_for_spans(reg, cell["spans"])
        if runs is None:
            return None
        r = cell["row"]
        nxt = [q for q in rows if q > r]
        sub = dict(reg)
        sub["lines"] = [_cell_line(lines[li], si, c0, c1)
                        for li, si, c0, c1 in cell["spans"]]
        sub["runs"] = runs
        sub["container"] = [min(l["bbox"][0] for l in sub["lines"]),
                            top[r],
                            anchor if cell["col"] == 0 else c[2],
                            top[nxt[0]] if nxt else c[3]]
        sub["alignment"] = "left"
        sub["target_runs"] = [{"role": role, "text": text}]
        sub["column_index"] = cell["col"]
        # Ô đã bị hàng xóm trong lưới khoá bốn phía; nới khung ở đây chỉ đè lên ô bên cạnh.
        # `expand_container` không thấy điều đó vì bbox của region cha bị lọc khỏi vật cản.
        sub["no_expand"] = True
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
    key, _ = pack.key_for(role_face(reg, reg["target_runs"][-1]["role"]))
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


DOT_TAIL_RE = re.compile(r"^(.*?)(\.{4,})$")
DOT_LEADER_MIN = 4        # dãy chấm ngắn hơn ngần này thì không phải gạch dẫn


def dot_leader_token(reg: dict, tokens: list) -> int | None:
    """Chỉ số token là dãy dấu CHẤM gạch dẫn của dòng mục lục, hoặc None. Có thể tách token.

    Vì sao cần: mục lục HV48100 gõ gạch dẫn bằng ký tự `.` ngay trong text — 85 dấu chấm
    trong một dòng — chứ không vẽ line-art như V5. `leader_run` (1.9.18) đi tìm stroke nên
    không thấy gì, `leader_split` (1.9.13) đòi khe ≥4 space nên cũng không khớp. Hệ quả
    ngược với V5: không có chữ đè lên nét, nhưng model giữ nguyên xấp xỉ số chấm cũ (85 →
    86) trong khi tiêu đề tiếng Việt dài ngắn khác tiếng Anh, nên cột số trang răng cưa —
    đo trên HV48100: biên độ mép phải nguồn 1.8pt, bản dịch **23.3pt**.

    Chữ ký: region MỘT dòng, token cuối là số trang 1-3 chữ số, token liền trước kết thúc
    bằng ≥4 dấu chấm. Dấu chấm dính liền tiêu đề thì tách ra thành token riêng.
    """
    if len(reg["lines"]) != 1 or len(tokens) < 3:
        return None
    tail = tokens[-1]["text"].strip()
    if not (tail.isdigit() and len(tail) <= 3):
        return None
    m = DOT_TAIL_RE.match(tokens[-2]["text"])
    if not m:
        return None
    head, dots = m.groups()
    if head:
        tokens[-2] = {**tokens[-2], "text": head}
        tokens.insert(len(tokens) - 1, {**tokens[-2], "text": dots, "br": False})
    return len(tokens) - 2


MARK_MAX_PT = 8.0     # dấu gạch đầu dòng nhỏ hơn ngần này mỗi chiều
MARK_BAND_PT = 30.0   # và nằm trong ngần này kể từ mép trái vùng
MARK_LIFT_PT = 7.0    # tâm dấu nằm TRÊN baseline dòng nó đánh, không quá ngần này


def bullet_marks(reg: dict, drawings: list) -> list[tuple[int, dict]]:
    """[(chỉ số dòng nguồn, hình vẽ dấu)] — dấu gạch đầu dòng của vùng, ghép với dòng nó đánh.

    Cùng chữ ký với `extract_group.bullet_lines`, nhưng ở đây cần chính HÌNH VẼ để còn dời
    được nó. `reg["bullet_lines"]` (stage 2) là danh sách dòng đã chốt; hàm này chỉ tìm lại
    hình vẽ tương ứng.
    """
    want = reg.get("bullet_lines") or []
    if not want:
        return []
    b, ink = reg["bbox"], [l["bbox"] for l in reg["lines"]]
    base = [l["spans"][0]["origin"][1] for l in reg["lines"]]
    out = []
    for d in drawings:
        r = d["rect"]
        if r.width > MARK_MAX_PT or r.height > MARK_MAX_PT:
            continue
        if not b[0] - 2 <= r.x0 <= b[0] + MARK_BAND_PT:
            continue
        cy = (r.y0 + r.y1) / 2
        if not b[1] - 4 <= cy <= b[3] + 4:
            continue
        if any(i[0] - 1 <= r.x0 <= i[2] and i[1] <= cy <= i[3] for i in ink):
            continue
        cand = [i for i in want if 0 <= base[i] - cy <= MARK_LIFT_PT]
        if cand:
            out.append((min(cand, key=lambda i: base[i] - cy), d))
    return out


def redraw_mark(page, d: dict, dy: float) -> None:
    """Vẽ lại một dấu gạch đầu dòng, dời xuống `dy`. Chép nguyên đường path của bản gốc.

    Không dựng lại bằng hình tròn/thoi tự chế: nguồn dùng `•` `∘` `◇` `▪` khác nhau, đoán sai
    hình là thấy ngay. Bốn đoạn bezier của bản gốc chép nguyên, chỉ cộng `dy`.
    """
    off = pymupdf.Point(0, dy)
    sh = page.new_shape()
    for it in d["items"]:
        op = it[0]
        if op == "l":
            sh.draw_line(it[1] + off, it[2] + off)
        elif op == "c":
            sh.draw_bezier(it[1] + off, it[2] + off, it[3] + off, it[4] + off)
        elif op == "re":
            sh.draw_rect(it[1] + pymupdf.Rect(0, dy, 0, dy))
        elif op == "qu":
            sh.draw_quad(it[1] + pymupdf.Quad(*[p + off for p in it[1]])
                         if False else pymupdf.Quad(*[p + off for p in it[1]]))
    sh.finish(color=d.get("color"), fill=d.get("fill"), width=d.get("width") or 0,
              closePath=d.get("closePath", True))
    sh.commit()


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

    `expand_ctx` (optional): `{"obstacles": [...], "page_rect": [...], "margins": (l, r),
    "share_gap": [...]}` cho phép nới khung heading khi bản dịch không vừa — xem
    `expand_container`. `share_gap` là bbox của các region chữ cùng trang, tức những vật cản
    tự chúng cũng nới được.
    """
    issues = []
    tokens = tokenize(reg)
    if not tokens:
        return None, [("EMPTY_TOKENS", "P1", "target không có token")]
    # Dãy chấm gạch dẫn co lại còn tối thiểu TRƯỚC khi fit: cỡ chữ phải do tiêu đề và số
    # trang quyết định, không do dãy chấm thừa của bản gốc. Phát lại đúng số chấm sau khi
    # biết cỡ chữ.
    dots_at = (dot_leader_token(reg, tokens)
               if cfg.get("layout", {}).get("dot_leader", True) else None)
    if dots_at is not None:
        tokens[dots_at]["text"] = "." * DOT_LEADER_MIN

    for fname in {SUBSET_PREFIX_RE.sub("", r["font"]) for r in reg["runs"]}:
        if fname and not any(k in fname.lower() for k in KNOWN_FAMILIES):
            issues.append(("FONT_DISPLAY_FALLBACK", "P1",
                           f"display font {fname!r} map sang bundle theo style class — "
                           "reviewer xác nhận (spec §11.4)"))
            break

    src_size = ink_size(reg)
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
        base_key, deg = pack.key_for(role_face(reg, t["role"]))
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
    # Neo baseline giữ chữ khớp dấu khi dấu ĐỨNG YÊN. Vùng nào dời được dấu thì thôi neo —
    # neo mà đoạn dịch ngắn hơn nguồn sẽ để lại khoảng trắng đúng bằng phần dôi ("nhảy dòng").
    anchors = (segment_anchors(reg, n_seg)
               if reg["rotation"] == 0 and n_seg > 1 and not reg.get("bullet_lines")
               and cfg.get("layout", {}).get("paragraph_anchor", True) else None)

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
        # Đo bằng CHÍNH công thức baseline mà bước vẽ dùng: neo đoạn có thể đẩy dòng cuối
        # xuống thấp hơn cách rải liên tục, fitter phải thấy đúng phần đó chứ không được đo
        # một đằng vẽ một nẻo.
        ys = line_baselines(line_seg, base_y, leading_ratio * s, anchors)
        if ys[-1] - base_y > budget:
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
                               expand_ctx["page_rect"], expand_ctx["margins"], align,
                               expand_ctx.get("share_gap", ()))
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

    # Phát lại dãy chấm cho dòng kết thúc đúng mép phải dòng NGUỒN — toạ độ lấy từ nguồn,
    # không phải engine tự đặt. Chỉ áp cho dòng căn trái một dòng: đó là hình dạng duy nhất
    # của dòng mục lục gõ bằng dấu chấm.
    dot_leader_n = 0
    if dots_at is not None and align == "left" and len(best["lines"]) == 1:
        idxs0 = best["lines"][0]
        lw0 = (sum(best["widths"][i] for i in idxs0)
               + sum(best["space_ws"][i] for i in idxs0[:-1]))
        dot_w = pack.font(tok_font[dots_at]).text_length(".", fontsize=s_fit)
        if dot_w > 0:
            n = DOT_LEADER_MIN + int((reg["lines"][0]["bbox"][2] - base_x - lw0) // dot_w)
            if n > DOT_LEADER_MIN:
                tokens[dots_at]["text"] = "." * n
                refit = layout_at(s_fit)
                if refit is not None and len(refit["lines"]) == 1:
                    best = refit
                    dot_leader_n = n
                else:                       # không vừa thì trả về dãy tối thiểu
                    tokens[dots_at]["text"] = "." * DOT_LEADER_MIN

    # dựng line segments với alignment + sub-run theo font
    leading = leading_ratio * s_fit
    baselines = line_baselines(best.get("line_seg") or [0] * len(best["lines"]),
                               base_y, leading, anchors)
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
        y = baselines[li]
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
            # Gate 3 so chuỗi nguyên văn, mà dãy chấm đã bị phát lại — phải khai ra để gate
            # chuẩn hoá đúng vùng này, không nới lỏng phép so cho vùng khác.
            **({"dot_leader": dot_leader_n} if dot_leader_n else {}),
            # Dòng nào thuộc đoạn nào — bước paint cần để dời dấu gạch đầu dòng theo chữ.
            "line_seg": list(best.get("line_seg") or [0] * len(out_lines)),
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
                "toc_leaders": [], "bullet_moves": 0,
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
            text_boxes = [r["bbox"] for r in regions if r["page"] == pno]
            obstacles = list(text_boxes)
            obstacles += [list(d["rect"]) for d in page.get_drawings()]
            obstacles += [list(page.get_image_bbox(i)) for i in page.get_images(full=True)]
            # `share_gap` giữ ĐÚNG các object bbox trong `text_boxes` — `expand_container`
            # so khớp bằng identity, nên copy giá trị sẽ vô hiệu hoá luật chia đôi khe.
            expand_ctx = {"obstacles": obstacles, "page_rect": list(page.rect),
                          "margins": doc_margins, "share_gap": text_boxes}

        fitted: list[tuple[dict, dict]] = []
        # Ô bảng gộp nhiều cột được tách thành sub-region trước khi fit, mỗi cột giữ đúng
        # `base_x` của nó. Sub-region mang nguyên region_id của cha nên mask, `painted_ids`
        # và Gate 3/4 vẫn chấm theo khung cha — tách chỉ là chuyện nội bộ của paint.
        expanded: list[dict] = []
        for reg in regs:
            subs = spec_grid(reg) if reg.get("target_runs") else None
            if subs:
                issues.append(make_issue(
                    "SPEC_GRID_COLUMNS", "P2", STAGE,
                    f"bảng thông số hai cột — vẽ {len(subs)} ô tại đúng cột và hàng nguồn",
                    page=pno, region_id=reg["region_id"]))
            elif reg.get("spec_cells") and reg.get("target_runs"):
                issues.append(make_issue(
                    "SPEC_GRID_DROPPED", "P1", STAGE,
                    f"bản dịch không khớp lưới {len(reg['spec_cells'])} ô — vẽ dồn về một "
                    "cột trái như bản gốc không có", page=pno, region_id=reg["region_id"]))
            if not subs:
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

        img_rects = [page.get_image_bbox(i) for i in page.get_images(full=True)]
        for reg in regs:
            if img_rects and occluded_by_image(doc, pno, reg["bbox"], img_rects):
                issues.append(make_issue(
                    "SOURCE_TEXT_OCCLUDED", "P2", STAGE,
                    "chữ nguồn bị ảnh vẽ đè lên nên bản gốc không nhìn thấy — không vẽ bản "
                    "dịch, nếu không bản dịch sẽ có chữ mà bản gốc không có. Chữ trong ảnh "
                    "là việc của bước DTP",
                    page=pno, region_id=reg["region_id"]))
                manifest["skipped"].append({"region_id": reg["region_id"],
                                            "reason": "SOURCE_TEXT_OCCLUDED"})
                continue
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
        # Dấu gạch đầu dòng đi theo chữ: xoá dấu cũ ở lượt redaction, vẽ lại sau khi đặt
        # chữ, dời đúng bằng chênh lệch baseline. Nhờ vậy chữ được chảy liên tục mà dấu vẫn
        # đứng cạnh mục của nó — không còn phải neo baseline, tức không còn khoảng trắng dôi
        # ("nhảy dòng") khi đoạn dịch ngắn hơn đoạn nguồn.
        moves = []
        for reg, fr in ok_regions:
            mk = bullet_marks(reg, page_draw) if page_draw else []
            if not mk:
                continue
            got = segment_source_lines(reg, max(fr["line_seg"]) + 1)
            if not got or got[1] != 0:
                continue          # không ánh xạ được theo dấu thì đừng dời dấu
            where = {src: si for si, src in enumerate(got[0])}
            src_base = [l["spans"][0]["origin"][1] for l in reg["lines"]]
            for li, d in mk:
                si = where.get(li)
                if si is None:
                    continue
                first = next((k for k, s2 in enumerate(fr["line_seg"]) if s2 == si), None)
                if first is None:
                    continue
                dy = fr["lines"][first]["y"] - src_base[li]
                if abs(dy) >= 0.05:
                    moves.append((d, dy))

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
        if leaders or moves:
            for _, _, run in leaders:
                for r in run["rects"]:
                    page.add_redact_annot(r, fill=False)
            for d, _ in moves:
                page.add_redact_annot(d["rect"] + (-0.4, -0.4, 0.4, 0.4), fill=False)
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
                **({"dot_leader": fr["dot_leader"]} if "dot_leader" in fr else {}),
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
        for d, dy in moves:
            redraw_mark(page, d, dy)
        manifest["bullet_moves"] += len(moves)
        manifest["toc_leaders"] += drawn
        # Dải khai cho Gate 6 phải là HỢP của khung cũ và mới: tiêu đề dịch dài hơn thì
        # nét mới bắt đầu phải hơn nét cũ, và đoạn ở giữa mất chấm — vẫn là pixel đổi.
        leader_bands = [[min(d["old"][0], d["new"][0]), d["new"][1],
                         max(d["old"][2], d["new"][2]), d["new"][3]] for d in drawn]
        # Dấu đã dời: khai HỢP khung cũ và mới cho Gate 6, cùng cách với gạch dẫn.
        leader_bands += [[d["rect"].x0 - 0.6, min(d["rect"].y0, d["rect"].y0 + dy) - 0.6,
                          d["rect"].x1 + 0.6, max(d["rect"].y1, d["rect"].y1 + dy) + 0.6]
                         for d, dy in moves]

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
