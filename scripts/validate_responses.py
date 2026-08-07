"""Stage 5 — Validate agent responses: schema, placeholder round-trip, NFC, glossary.

Spec §6.6 (reject rules), Gate 2 inputs. Cập nhật target vào model/regions.json.
Chạy: python3 validate_responses.py --job <job_dir>
"""

from __future__ import annotations

import argparse
import collections
import re

from _common import (RERUNNABLE_STATUSES, BlockingError, Job, authenticity_cfg,
                     authenticity_check, exit_blocking, load_glossary, load_json, make_issue,
                     nfc, read_jsonl, save_json)

STAGE = "validate"
PH_RE = re.compile(r"⟦([A-Z]+_\d+)⟧")
# Chuỗi chữ số liền nhau. So theo multiset chuỗi (không parse thành số) nên đổi dấu phân
# cách nghìn/thập phân "1,000" ↔ "1.000" không bị báo — cả hai đều cho {"1", "000"}.
DIGIT_RUN_RE = re.compile(r"\d+")
# Số mũ Unicode → chữ số thường, để dấu chú thích ("Retention³") đếm bằng "Retention3".
# Viết bằng escape vì 1/2/3 nằm ở khối Latin-1 (U+00B9/B2/B3) còn 0 và 4-9 ở U+2070 —
# gõ trực tiếp rất dễ lẫn hai bộ và mất tác dụng quy đổi.
_SUP_DIGITS = str.maketrans("\u2070\u00b9\u00b2\u00b3\u2074\u2075"
                            "\u2076\u2077\u2078\u2079",
                            "0123456789")

# Phủ định phía EN. Đo trên 7185 cặp của 14 job để loại từng nguồn báo oan:
# - "No." cột bảng (= Number) và "No.3492" địa chỉ → chỉ nhận "no" khi theo sau là từ
#   ("no heat source"); "NO" viết hoa cả cụm (Normally Open) không nhận vì nằm ngoài
#   nhóm (?i: ...).
# - "do not hesitate" là uyển ngữ lịch sự — VI dịch xuôi "vui lòng liên hệ" hợp lệ.
# - n't viết bằng nháy cong "won’t" lẫn nháy thẳng "won't" đều phải nhận.
EN_NEG_RE = re.compile(
    r"(?i:\b(?:not(?!\s+hesitate)|never|cannot|without|prohibited|forbidden)\b"
    r"|\b\w*n[’']t\b)"
    r"|\b[Nn]o(?=\s+[A-Za-z])")
VI_NEG_RE = re.compile(r"(?i)\b(?:không|cấm|chưa|đừng|tránh|ngừng|ngưng|chớ)\b")

# Từ Latin >=3 ký tự + ký tự có dấu tiếng Việt — dùng cho phép đo carry-through.
LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")
VI_DIACRITIC_RE = re.compile(
    r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọ"
    r"ốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", re.IGNORECASE)

# Ký hiệu mang nghĩa kỹ thuật phải sống sót qua bản dịch: lật ≤ thành ≥ ở dải nhiệt độ
# là đổi thông số an toàn. Fullwidth quy về ASCII trước khi so (nguồn hay dùng ＜).
_SYM_MAP = str.maketrans({"＜": "<", "＞": ">", "≦": "≤", "≧": "≥"})
_SYM_SET = "<>≤≥±"

# Địa chỉ bưu chính. `URL`/`EMAIL`/`STD` đã được protect() che thành placeholder nên
# round-trip qua PLACEHOLDER_MISMATCH; địa chỉ thì không — nó là văn xuôi thường, và đó
# đúng là lớp thực thể duy nhất còn hở.
_ADDR_STRUCT = r"(?:Road|Rd|Street|Avenue|Lane|District|DST|Province)"
# Nhánh 1: số nhà tới hết mệnh đề ("No. 3492 Jinqian Road", "No.3492 Jinqian Road").
# Nhánh 2: tên riêng + từ cấu trúc ("Fengxian District", "Fengxian DST").
_ADDR_SPAN_RE = re.compile(rf"\bNo\.?\s?\d+[^,\n]*|\b[A-Z][A-Za-z]+\s+{_ADDR_STRUCT}\b")
# Nhánh 3: thành phố đứng ngay sau từ cấu trúc, có thể có mã bưu chính chen giữa
# ("… District, 201406 Shanghai"). Không đi xa hơn thành phố: tên QUỐC GIA đứng sau đó
# được dịch là hợp lệ và vẫn nhất quán ("China" → "Trung Quốc" ở cả ba tài liệu).
_ADDR_CITY_RE = re.compile(rf"{_ADDR_STRUCT}\b[,，]\s*(?:\d+\s+)?([A-Z][A-Za-z]+)")
_ADDR_TOKEN_RE = re.compile(r"[A-Za-z]{2,}|\d+")


def carry_through(source: str, target: str) -> tuple[int, int] | None:
    """→ (số từ chép nguyên, số từ tiếng Việt) nếu target chủ yếu là tiếng Anh chép từ
    source; None nếu không.

    Bắt find-replace: dịch bằng cách thay vài từ khoá rồi giữ nguyên phần còn lại. Ca thật
    2026-08-05, nằm trong bản đã RELEASED — nguyên quy trình khởi động/tắt máy:

        EN  Step 1. Turn on the DC breaker.  →  VI  Bước 1. Turn on the DC breaker.

    Chỉ chữ "Step" được đổi. Gate 2 `lang_suspect` không thấy vì nó đo tỷ lệ ký tự có dấu
    tiếng Việt và đòi dưới 5%; mấy chữ "Bước" đẩy khối này lên 6.9%, lọt sát nút.

    Chỉ đếm từ **thường** của source (`islower()`): tên riêng và mã model giữ nguyên là
    hợp lệ, nên "Công ty Shanghai PYTES Energy Co., Ltd." không bị bắt.

    Ngưỡng ≥3 từ thường VÀ nhiều hơn gấp đôi số từ tiếng Việt — đo trên 7185 cặp của 14
    job: 0 hit ở mọi bản dịch đạt, bắt trọn 3 khối quy trình của bản lỗi.
    """
    src = PH_RE.sub(" ", source)
    tgt = PH_RE.sub(" ", target)
    common = {w for w in LATIN_WORD_RE.findall(src) if w.islower()}
    carried = [w for w in LATIN_WORD_RE.findall(tgt) if w.lower() in common]
    vi_words = [w for w in tgt.split() if VI_DIACRITIC_RE.search(w)]
    if len(carried) >= 3 and len(carried) > 2 * max(len(vi_words), 0.5):
        return len(carried), len(vi_words)
    return None


def negation_drop(source: str, target: str) -> bool:
    """True nếu source có phủ định mà target không còn từ phủ định nào.

    Bắt lỗi rơi chữ "không/cấm" trong câu an toàn — audit 2026-08-05 tìm thấy bản Lite
    đã RELEASED mất nguyên câu "Batteries connected in series are forbidden" và
    "Do not short-circuit the Li-ion battery" mà ratio từ vẫn trên ngưỡng truncation.
    Chỉ xét chiều EN-có-VI-không; chiều ngược lại (VI thêm "không") luôn hợp lệ.
    """
    return bool(EN_NEG_RE.search(source)) and not VI_NEG_RE.search(target)


def symbol_drift(source: str, target: str) -> tuple[dict, dict] | None:
    """→ (thiếu, thừa) nếu multiset ký hiệu <>≤≥± của target khác source; None nếu khớp.

    Đo trên 7185 cặp: 0 lệch ở bản dịch đạt — mọi mismatch là lỗi thật đáng nhìn.
    """
    src = collections.Counter(c for c in source.translate(_SYM_MAP) if c in _SYM_SET)
    tgt = collections.Counter(c for c in target.translate(_SYM_MAP) if c in _SYM_SET)
    if src == tgt:
        return None
    return dict(src - tgt), dict(tgt - src)


def digit_drift(source: str, target: str) -> tuple[dict, dict] | None:
    """→ (thiếu, thừa) nếu tập chữ số của target khác source, None nếu khớp.

    Bắt lỗi model viết ra nội dung không có trong nguồn. Ca thật: một model dịch mục lục
    thành mục lục khác — đổi cả số mục lẫn tên mục ("3 Interface and Components" →
    "3.1 Dụng cụ"), 8 dòng liền. Bản dịch trôi chảy, không trùng source, không phải tiếng
    Anh, nên Gate 2 authenticity im lặng; chỉ tập chữ số là lệch.

    So trên dạng placeholder: số nằm trong ⟦MEAS_n⟧ không tính, chỉ số hiện trên mặt chữ.

    Chữ số dạng SỐ MŨ được quy về chữ số thường trước khi đếm. Nguồn in dấu chú thích
    bằng span cỡ nhỏ ("Energy Retention³"), mà engine vẽ một cỡ chữ cho cả region nên bản
    dịch phải dùng ký tự số mũ Unicode để dấu không tụt xuống thành chữ thường. Không quy
    đổi thì mọi dấu chú thích đều bị báo thiếu chữ số — 8 báo giả trên riêng Terms of
    Warranty, và waive cả mã sẽ che mất một ca lệch số thật.
    """
    src = collections.Counter(DIGIT_RUN_RE.findall(source.translate(_SUP_DIGITS)))
    tgt = collections.Counter(DIGIT_RUN_RE.findall(target.translate(_SUP_DIGITS)))
    if src == tgt:
        return None
    return dict(src - tgt), dict(tgt - src)


def address_entity_drift(source: str, target: str) -> list[str]:
    """→ danh sách token của địa chỉ bưu chính trong source mà target không còn; [] nếu đủ.

    Địa chỉ bị dịch thì không gửi thư tới được. Ca thật nằm trong bản Lite đã RELEASED
    (p32): `No. 3492 Jinqian Road, Fengxian District, 201406 Shanghai` ra
    `Số 3492 Đường Jinqian, Quận Fengxian, 201406 Thượng Hải` — trong khi p1 của **cùng
    tài liệu** giữ nguyên tiếng Anh, nên bản in mang hai dạng địa chỉ khác nhau.

    `CONSISTENCY_DRIFT` không thấy vì nó chỉ so các region có nguồn khớp TUYỆT ĐỐI, mà
    nguồn p1 (`…Shanghai, China`) khác nguồn p32 (`…201406 Shanghai,`). Luật này so theo
    thực thể nên không phụ thuộc nguồn có khớp nhau hay không.

    Chỉ soi ĐÚNG một lớp thực thể — địa chỉ bưu chính. Bản thiết kế rộng hơn (gom mọi
    thực thể: chuẩn, thương hiệu, URL) đo được 0 đúng / 3 oan vì nó gom nhầm `UN3480`,
    `IEC62619`, `UL1015` vào một nhóm. Đo luật hẹp này trên 1947 region của ba tài liệu:
    **fire đúng 5 region — cả 5 đều là địa chỉ nhà máy thật, 0 oan**; bản dịch hiện hành
    không thiếu token nào, còn bản dịch lỗi của p32 bị bắt với 4 token thiếu.

    Nhãn phía trước dấu hai chấm KHÔNG bị soi: `Factory Address` → `Địa chỉ nhà máy` là
    bản dịch đúng, chỉ phần thân địa chỉ mới phải giữ nguyên.
    """
    tokens: list[str] = []
    for span in _ADDR_SPAN_RE.findall(source):
        tokens += _ADDR_TOKEN_RE.findall(span)
    if not tokens:
        return []
    tokens += _ADDR_CITY_RE.findall(source)
    return [w for w in dict.fromkeys(tokens)
            if not re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", target)]


def apply_punct_map(text: str, pmap: dict) -> tuple[str, bool]:
    """Punctuation allowlist — áp trên dạng placeholder nên token không bị chạm."""
    out = text
    for k, v in pmap.items():
        out = out.replace(k, v)
    out = re.sub(r"  +", " ", out)
    return out, out != text


def validate(job: Job) -> None:
    model = load_json(job.p("model", "regions.json"))
    if not model:
        raise BlockingError("chưa có regions.json")
    regions = {r["region_id"]: r for r in model["regions"]}
    requests = {r["region_id"]: r for r in read_jsonl(job.p("translation", "requests.jsonl"))}
    responses = read_jsonl(job.p("translation", "responses.jsonl"))
    if not responses:
        raise BlockingError("translation/responses.jsonl trống — agent chưa dịch")

    # Append-workflow: chỉ validate DÒNG CUỐI của mỗi region — dòng cũ bị ghi đè
    # là lịch sử, không phát issue/fail cho chúng (ghi nhận P2 DUPLICATE_RESPONSE).
    latest: dict[str, dict] = {}
    n_dup = 0
    for resp in responses:
        rid = resp.get("region_id", "")
        if rid in latest:
            n_dup += 1
        latest[rid] = resp
    responses = list(latest.values())

    cfg = job.config
    pmap = cfg["unicode"]["punctuation_map"]
    _gloss = load_glossary(job)
    locked = [g for g in _gloss if g["type"] == "locked"]
    keep_terms = [g["term"] for g in _gloss if g["type"] == "keep"]
    auth = authenticity_cfg(cfg)
    target_lang = cfg["languages"]["target"]
    issues: list[dict] = []
    n_ok = n_fail = n_drift = n_neg = n_sym = n_trunc = n_carry = 0
    seen: set[str] = set()
    # Authenticity theo TRẠNG THÁI CUỐI của từng region — không đếm theo dòng.
    # Workflow chuẩn cho phép append bản sửa (bản sau ghi đè bản trước): dòng cũ
    # identical không được tính nữa khi đã có bản sửa hợp lệ phía sau.
    auth_flags: dict[str, tuple[str | None, int | None]] = {}

    for resp in responses:
        rid = resp.get("region_id", "")
        reg = regions.get(rid)
        req = requests.get(rid)

        def fail(code: str, detail: str, sev: str = "P1"):
            issues.append(make_issue(code, sev, STAGE, detail,
                                     page=(reg or {}).get("page"), region_id=rid))

        if reg is None or req is None:
            # orphan từ layout version cũ — warning, không chặn khi mọi region
            # hiện hành đều có bản dịch hợp lệ
            issues.append(make_issue("ORPHAN_RESPONSE", "P2", STAGE,
                                     "response cho region không còn tồn tại (layout cũ)",
                                     region_id=rid))
            continue
        seen.add(rid)

        runs = resp.get("target_runs")
        if not isinstance(runs, list) or not runs or \
                not all(isinstance(r, dict) and r.get("role") and isinstance(r.get("text"), str)
                        for r in runs):
            fail("SCHEMA_INVALID", "target_runs sai schema"); n_fail += 1; continue

        target_pl = "".join(r["text"] for r in runs)
        if not target_pl.strip():
            fail("EMPTY_TARGET", "target rỗng — chỉ reviewer được quyết định delete (spec §5.6)")
            n_fail += 1; continue

        req_roles = set(req["style_roles"])
        resp_roles = {r["role"] for r in runs}
        if not resp_roles <= req_roles:
            fail("UNKNOWN_ROLE", f"role lạ: {sorted(resp_roles - req_roles)}"); n_fail += 1; continue
        if "label" in req_roles and "label" not in resp_roles:
            fail("MISSING_STYLE_ROLE", "request có label nhưng response mất role label")
            n_fail += 1; continue

        # placeholder round-trip 1:1 theo multiset (spec Gate 2)
        src_counts: dict[str, int] = {}
        for m in PH_RE.finditer(req["source_text"]):
            src_counts[m.group(1)] = src_counts.get(m.group(1), 0) + 1
        tgt_counts: dict[str, int] = {}
        for m in PH_RE.finditer(target_pl):
            tgt_counts[m.group(1)] = tgt_counts.get(m.group(1), 0) + 1
        if src_counts != tgt_counts:
            missing = {k: v for k, v in src_counts.items() if tgt_counts.get(k) != v}
            extra = {k: v for k, v in tgt_counts.items() if src_counts.get(k) != v}
            fail("PLACEHOLDER_MISMATCH", f"thiếu/lệch {missing} thừa {extra}")
            n_fail += 1; continue

        # Chữ số phải round-trip. Cảnh báo, KHÔNG chặn: nội dung trải dài qua nhiều region
        # có thể dồn/tách số hợp lệ giữa các region liền nhau. Người đọc detail quyết định.
        drift = digit_drift(req["source_text"], target_pl)
        if drift:
            miss, extra = drift
            n_drift += 1
            issues.append(make_issue(
                "NUMBER_DRIFT", "P1", STAGE,
                f"chữ số không khớp source — thiếu {miss} thừa {extra}; nếu không phải do "
                "nội dung dồn sang region khác thì đây là nội dung bịa, dịch lại region này",
                page=reg.get("page"), region_id=rid))

        # Copy-through: target chủ yếu là tiếng Anh chép nguyên từ source. §1.6 xếp loại
        # này là pseudo-translation — P0, approve.py chặn, không waive được.
        ct = carry_through(req["source_text"], target_pl)
        if ct:
            n_carry += 1
            issues.append(make_issue(
                "TRANSLATION_CARRY_THROUGH", "P0", STAGE,
                f"target giữ nguyên {ct[0]} từ thường của source, chỉ có {ct[1]} từ tiếng "
                "Việt — dấu hiệu find-replace thay vì dịch (SKILL.md §1.6). Dịch lại "
                "region này",
                page=reg.get("page"), region_id=rid))

        # Phủ định phải sống sót. Cảnh báo, không chặn — reviewer đối chiếu source.
        if negation_drop(req["source_text"], target_pl):
            n_neg += 1
            issues.append(make_issue(
                "NEGATION_DROP", "P1", STAGE,
                "source có phủ định (not/never/forbidden/without…) nhưng target không còn "
                "từ phủ định nào (không/cấm/chưa/đừng/tránh…) — kiểm xem câu cấm/cảnh báo "
                "có bị rơi hoặc dịch lật nghĩa không",
                page=reg.get("page"), region_id=rid))

        # Ký hiệu so sánh/± phải round-trip. Cảnh báo, không chặn.
        sdrift = symbol_drift(req["source_text"], target_pl)
        if sdrift:
            smiss, sextra = sdrift
            n_sym += 1
            issues.append(make_issue(
                "SYMBOL_DRIFT", "P1", STAGE,
                f"ký hiệu <>≤≥± không khớp source — thiếu {smiss} thừa {sextra}; "
                "lật dấu là đổi thông số kỹ thuật, sửa lại cho khớp",
                page=reg.get("page"), region_id=rid))

        # NFC + punctuation allowlist (áp trước khi restore → token nguyên vẹn)
        norm_runs = []
        punct_applied = False
        for r in runs:
            t = nfc(r["text"])
            t, changed = apply_punct_map(t, pmap)
            punct_applied |= changed
            norm_runs.append({"role": r["role"], "text": t})
        target_pl = "".join(r["text"] for r in norm_runs)

        for g in locked:
            if re.search(rf"(?i)(?<![a-z]){re.escape(g['term'])}(?![a-z])",
                         req["source_text"]) and g["target"] not in target_pl:
                fail("GLOSSARY_LOCKED_VIOLATION", f"thiếu thuật ngữ khóa: {g['term']} → {g['target']}")
                n_fail += 1
                break
        else:
            # Authenticity (chống copy-through — sự cố 2026-08-04): ghi flag theo
            # region, dòng sau ghi đè dòng trước; phát issue sau vòng lặp.
            auth_flags[rid] = (authenticity_check(req["source_text"], target_pl,
                                                  target_lang, auth["min_words"],
                                                  keep_terms),
                               reg.get("page"))
            mapping = reg.get("placeholders", {})
            reg["target_runs"] = norm_runs
            reg["target_text"] = nfc(PH_RE.sub(
                lambda m: mapping.get(m.group(1), m.group(0)), target_pl))
            reg["translation_meta"] = {
                "provider": cfg["translation"]["provider_model_version"],
                "prompt_version": cfg["translation"]["prompt_version"],
                "punctuation_normalized": punct_applied,
                # Đóng dấu bản dịch này thuộc về ĐÚNG phiên bản nguồn nào. Đổi layout model
                # (vd lg-basic-3 → lg-basic-4 gộp đoạn) làm nhiều region đổi source_text mà
                # region_id vẫn y nguyên, nên `responses.jsonl` cũ được nạp lại một cách âm
                # thầm và region mang bản dịch của NỬA nội dung. Ca thật đo được khi migrate
                # job V16 manual: 2 region dính, một bị PLACEHOLDER_MISMATCH chặn, một lọt
                # vì tỉ lệ từ 0.69 vẫn trên sàn truncation 0.60.
                "source_hash": reg.get("source_hash"),
                "notes": resp.get("notes", []),
            }
            n_ok += 1

    # Phát per-region authenticity issue theo trạng thái cuối (sau mọi ghi đè).
    n_ident = n_lang = 0
    for rid, (flag, page) in auth_flags.items():
        if flag == "identical":
            n_ident += 1
            issues.append(make_issue("TRANSLATION_IDENTICAL", "P1", STAGE,
                                     "region đáng dịch nhưng target trùng source (chưa dịch)",
                                     page=page, region_id=rid))
        elif flag == "lang_suspect":
            n_lang += 1
            issues.append(make_issue("TARGET_LANG_SUSPECT", "P1", STAGE,
                                     f"target gần như không có chữ tiếng {target_lang} — "
                                     "nghi chưa dịch/dịch máy lỗi", page=page, region_id=rid))
        elif flag == "truncated":
            n_trunc += 1
            issues.append(make_issue("TRANSLATION_TRUNCATED", "P1", STAGE,
                                     "target mất khối lượng nội dung so với source (<45% số từ) "
                                     "— nghi dịch nuốt ý; dịch lại ĐẦY ĐỦ region này",
                                     page=page, region_id=rid))

    # Job-level authenticity gate — P0, KHÔNG waive được (approve.py chặn mọi P0).
    n_resp = max(1, len(seen))
    ident_ratio, lang_ratio = n_ident / n_resp, n_lang / n_resp
    auth_block = None
    if ident_ratio > auth["identical_ratio_max"]:
        auth_block = (f"TRANSLATION_COVERAGE_FAIL: {n_ident}/{n_resp} regions "
                      f"({ident_ratio:.0%}) target trùng source — vượt ngưỡng "
                      f"{auth['identical_ratio_max']:.0%}. Bản dịch phải do model của session "
                      "sinh ra cho TỪNG region; cấm script/dictionary/find-replace.")
        issues.append(make_issue("TRANSLATION_COVERAGE_FAIL", "P0", STAGE, auth_block))
    if lang_ratio > auth["lang_suspect_ratio_max"]:
        detail = (f"TARGET_LANG_FAIL: {n_lang}/{n_resp} regions ({lang_ratio:.0%}) "
                  f"không phải tiếng {target_lang} — vượt ngưỡng "
                  f"{auth['lang_suspect_ratio_max']:.0%}.")
        issues.append(make_issue("TARGET_LANG_FAIL", "P0", STAGE, detail))
        auth_block = auth_block or detail

    # Nhất quán thuật ngữ: cùng một nguồn mà ra hai bản dịch khác nhau thì ít nhất một bản
    # sai, hoặc có lý do cần ghi lại. Cảnh báo P2, KHÔNG chặn.
    # So theo NHÓM ĐÃ LỌC CHUỖI của context_graph: mảnh của một cụm nhiều dòng trùng chữ với
    # một nhãn độc lập là khác biệt HỢP LỆ. Ca thật: "Battery side" là mảnh của cụm
    # "Battery side wall-mounted bracket" (p19) vs nhãn độc lập cùng chữ (p21) — hai bản dịch
    # khác nhau và cả hai đều đúng. So mảnh trần sẽ báo oan đúng chỗ dịch hay nhất.
    # Bản dịch còn thuộc về đúng phiên bản nguồn không. Chỉ so được khi bản dịch đã được
    # đóng dấu `source_hash` (từ 1.7.0) — job dịch trước đó không có dấu, lần migrate đầu
    # tiên sau khi nâng engine phải đối chiếu source_hash bằng tay.
    n_stale = 0
    for rid, reg in regions.items():
        stamped = (reg.get("translation_meta") or {}).get("source_hash")
        if stamped and reg.get("source_hash") and stamped != reg["source_hash"]:
            n_stale += 1
            issues.append(make_issue(
                "STALE_TRANSLATION", "P1", STAGE,
                "region đổi source_text sau khi đã dịch (thường do đổi layout model) nhưng "
                "vẫn mang bản dịch cũ — dịch lại region này theo nguồn hiện tại",
                page=reg.get("page"), region_id=rid))

    # Thực thể không được dịch — hiện chỉ địa chỉ bưu chính (xem address_entity_drift).
    # So trên dạng ĐÃ RESTORE: token nằm trong placeholder thì đã round-trip nguyên vẹn.
    n_entity = 0
    for rid, reg in regions.items():
        if not reg.get("target_text"):
            continue
        miss = address_entity_drift(reg.get("source_text", ""), reg["target_text"])
        if miss:
            n_entity += 1
            issues.append(make_issue(
                "CONSISTENCY_ENTITY", "P1", STAGE,
                f"địa chỉ bưu chính bị dịch — target thiếu {miss}; địa chỉ đã dịch thì "
                "không gửi thư tới được, và cùng tài liệu sẽ mang hai dạng địa chỉ khác "
                "nhau. Giữ nguyên thân địa chỉ như nguồn (chỉ nhãn 'Address' được dịch)",
                page=reg.get("page"), region_id=rid))

    graph = load_json(job.p("model", "context_graph.json"), {}) or {}
    n_cdrift = 0
    for src_key, rids in (graph.get("same_source") or {}).items():
        variants: dict[str, list[str]] = {}
        for rid in rids:
            reg = regions.get(rid)
            if reg and reg.get("target_text"):
                variants.setdefault(" ".join(reg["target_text"].split()), []).append(rid)
        if len(variants) > 1:
            n_cdrift += 1
            issues.append(make_issue(
                "CONSISTENCY_DRIFT", "P2", STAGE,
                f"nguồn {src_key[:40]!r} có {len(variants)} bản dịch khác nhau: "
                + " | ".join(f"{v[:40]!r}×{len(r)}" for v, r in variants.items()),
                region_id=rids[0]))

    if n_dup:
        issues.append(make_issue("DUPLICATE_RESPONSE", "P2", STAGE,
                                 f"{n_dup} dòng cũ bị ghi đè bởi bản mới hơn (append-workflow)"))
    pending = [rid for rid, r in regions.items()
               if r["translation_action"] == "translate" and "target_text" not in r]
    save_json(job.p("model", "regions.json"), model)
    save_json(job.p("model", "validate_issues.json"), issues)
    job.mark_stage("translate", "done" if not pending else f"partial:{len(pending)}")
    if auth_block:
        job.mark_stage(STAGE, f"failed:authenticity ident={n_ident} lang={n_lang}")
        raise BlockingError(auth_block)
    job.mark_stage(STAGE, "done" if n_fail == 0 else f"failed:{n_fail}")
    if not pending and n_fail == 0 and job.status() in RERUNNABLE_STATUSES:
        job.set_status("TRANSLATED", "100% translate-regions có target hợp lệ")
        job.write_summary("Chạy `fit_paint.py --job <job>` để render draft.")
    else:
        job.write_summary(
            f"Validate: {n_ok} OK, {n_fail} fail, {len(pending)} region chưa dịch. "
            "Agent bổ sung/sửa responses.jsonl rồi chạy lại validate_responses.py.")
    warn_bits = [f"{k}={v}" for k, v in (("number_drift", n_drift), ("negation_drop", n_neg),
                                          ("symbol_drift", n_sym), ("truncated", n_trunc),
                                          ("carry_through", n_carry),
                                          ("address_translated", n_entity)) if v]
    warn_note = (" " + " ".join(warn_bits)) if warn_bits else ""
    print(f"validate: ok={n_ok} fail={n_fail} pending={len(pending)}{warn_note}")
    if n_carry:
        print(f"  P0 TRANSLATION_CARRY_THROUGH: {n_carry} region giữ nguyên tiếng Anh của "
              "source (find-replace, §1.6) — KHÔNG phát hành được cho tới khi dịch lại")
    if warn_bits:
        print("  CẢNH BÁO NỘI DUNG: có region lệch chữ số / rơi phủ định / lệch ký hiệu / "
              "mất khối lượng / địa chỉ bị dịch — xem model/validate_issues.json, đối chiếu "
              "source từng region "
              "trước khi fit; đây là loại lỗi từng lọt vào bản RELEASED")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job", required=True)
    args = ap.parse_args()
    job = Job(args.job)
    try:
        # Chốt vào cổng, giống `extract_group`/`translate_prep`. Thiếu nó thì stage này ghi
        # được `target_text` vào `model/regions.json` của job ĐÃ PHÁT HÀNH — model thôi mô tả
        # đúng bản đã duyệt, tức mất dấu vết kiểm chứng. Xảy ra thật ngày 2026-08-07: một
        # vòng lặp chạy trên hai job không kiểm trạng thái, ba stage kia chặn, stage này lọt.
        # Lần đó nội dung không đổi (đầu vào y hệt, hàm idempotent) nên không mất gì — nhưng
        # đó là may, không phải hàng rào.
        if job.status() not in RERUNNABLE_STATUSES:
            raise BlockingError(f"status {job.status()} — cần một trong "
                                f"{', '.join(RERUNNABLE_STATUSES)} (§11.5)")
        job.verify_fingerprint()
        with job.acquire_lock(STAGE):
            validate(job)
    except BlockingError as e:
        exit_blocking(job, STAGE, e)


if __name__ == "__main__":
    main()
