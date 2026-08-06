"""Stage 2.5 — Translation Context Graph: nối các region thuộc về nhau.

Vì sao có stage này: PDF tách chữ thành ô nhỏ, thường một dòng một region. Model dịch từng
ô rời với ~80 ký tự hàng xóm nên câu tiếng Việt bị đóng khung theo trật tự tiếng Anh, không
đảo vế qua ranh giới ô được. Đo trên job V16 user manual (833 region): `continuation_*` = 0,
trong khi riêng trang thư ngỏ đã có 16 liên kết câu thật.

Graph KHÔNG dịch. Nó chỉ nói cho stage 3 (làm giàu context), stage 4 (không cắt batch giữa
chuỗi) và lint nhất quán biết **cái gì thuộc về nhau**. Toàn bộ luật là hình học + regex,
deterministic — đúng SKILL.md §1.6 (cấm mọi logic dịch nằm trong code).

Không đụng `region_id` (sinh từ `container` ở extract_group) nên `responses.jsonl` của job cũ
vẫn dùng được; chạy lại stage này là idempotent.

Chạy: python3 build_context_graph.py --job <job_dir>
"""

from __future__ import annotations

import argparse
import re
import statistics

from _common import BlockingError, Job, exit_blocking, load_json, save_json, utc_now

STAGE = "context_graph"
GRAPH_VERSION = "cg-1"

# Tiêu đề đánh số: "5.1.1  Safety Requirements". extract_group xếp chúng thành `list_item`
# vì LIST_RE khớp "5." ở đầu, nên KHÔNG lọc được bằng region_type — phải regex trên chữ.
HEADING_NUM_RE = re.compile(r"^\s*\d+(\.\d+)*[.\s]\s*\S")
# Dòng mục lục: "2.2  Packing List........... 9"
TOC_DOTS_RE = re.compile(r"\.{4,}")
# "Table 6-2 …" / "Figure 3-1 …" mở đầu một khối mới, không phải phần tiếp của câu trên.
TABFIG_RE = re.compile(r"^\s*(Table|Figure|Bảng|Hình)\s+\d")
# Dòng "Nhãn: giá trị" (Website:, Email:, Note:) luôn mở mục mới. Bắt được ca thật: chuỗi
# địa chỉ nhà máy nuốt luôn hai dòng Website/Email nằm dưới.
LABEL_VALUE_RE = re.compile(r"^\s*[A-Za-zÀ-ỹ][\w À-ỹ]{0,14}[:：]\s")
SENT_END_RE = re.compile(r"[.:;!?…。]['\"’”\)\]]?\s*$")

FLOW_TYPES = ("paragraph", "list_item")
LABEL_TYPES = ("figure_caption", "diagram_label")
# Đầu chuỗi văn xuôi phải là câu thật, không phải nhãn ngắn. Đo trên 2 job: mọi chuỗi sai
# ("Dry Contact"+"LINK 1 Port", "RS485"+mô tả, "Best regards,"+"Pytes") đều có đầu chuỗi
# dưới 4 từ; mọi chuỗi đúng đều từ 4 từ trở lên.
FLOW_MIN_WORDS = 4
# Khe giữa hai dòng của MỘT nhãn so với chiều cao một dòng. Đo thật: cụm nhãn đúng ở Lite
# p19 = 0.035; hai nhãn rời xếp chồng ở V16 p13 = 0.173 và 0.301. Ngưỡng 0.12 tách bạch.
LABEL_STACK_GAP_RATIO = 0.12


def soft_end(text: str) -> bool:
    """Câu chưa kết thúc → dòng sau có thể là phần tiếp."""
    return not SENT_END_RE.search(text.strip())


def is_heading_like(text: str) -> bool:
    return bool(HEADING_NUM_RE.match(text))


def size_of(reg: dict) -> float:
    return reg["runs"][0]["size"] if reg.get("runs") else 10.0


def line_height(regs: list[dict]) -> float:
    hs = [r["bbox"][3] - r["bbox"][1] for r in regs]
    return statistics.median(hs) if hs else 12.0


def flow_link(a: dict, b: dict, lh: float) -> float | None:
    """→ score nếu b là phần tiếp của a trong cùng một đoạn/câu, None nếu không.

    Guard bắt buộc: không có nó thì 9/10 chuỗi ngoài trang thư ngỏ là nối sai — tiêu đề đánh
    số dính vào thân bài ("5.1.1 Safety Requirements" + đoạn văn theo sau), dòng mục lục dính
    nhau, ghi chú dính tiêu đề bảng. Đo trên V16 user manual: 26 link thô → 17 link sạch.
    """
    if a["region_type"] not in FLOW_TYPES or b["region_type"] not in FLOW_TYPES:
        return None
    ta, tb = a["source_text"].strip(), b["source_text"].strip()
    if is_heading_like(ta) or TOC_DOTS_RE.search(ta) or TOC_DOTS_RE.search(tb):
        return None
    if TABFIG_RE.match(tb) or LABEL_VALUE_RE.match(tb):
        return None
    if not soft_end(ta):
        return None
    if len(ta.split()) < FLOW_MIN_WORDS:
        return None
    gap = b["bbox"][1] - a["bbox"][3]
    left = abs(a["bbox"][0] - b["bbox"][0])
    if not (0 <= gap <= 0.7 * lh and left <= 10):
        return None
    if abs(size_of(a) - size_of(b)) > 0.5:
        return None
    return round(1.0 - (gap / max(lh, 1.0)) * 0.3 - (left / 10.0) * 0.1, 3)


def label_stack_link(a: dict, b: dict) -> float | None:
    """→ score nếu a,b là hai dòng của MỘT nhãn chú thích nhiều dòng.

    Ca thật (V16 Lite p19): "Battery side" / "wall-mounted bracket" là một nhãn hai dòng với
    một đường chỉ dẫn duy nhất, phải dịch cả cụm rồi chia dòng ("Giá treo tường" / "phía pin").
    Dịch từng dòng máy móc sẽ hỏng nghĩa; so lint từng mảnh sẽ báo oan chính bản dịch đúng.
    """
    if a["region_type"] not in LABEL_TYPES or b["region_type"] not in LABEL_TYPES:
        return None
    gap = b["bbox"][1] - a["bbox"][3]
    # Chiều cao MỘT DÒNG của a, không phải cả bbox — nhãn nhiều dòng có bbox cao gấp đôi và
    # ngưỡng theo bbox sẽ nuốt cả khoảng cách giữa hai nhãn rời.
    per_line = max((a["bbox"][3] - a["bbox"][1]) / max(len(a.get("lines") or [1]), 1), 1.0)
    if not (-1.0 <= gap <= LABEL_STACK_GAP_RATIO * per_line):
        return None
    for pick in (lambda r: r["bbox"][0],                          # thẳng mép trái
                 lambda r: (r["bbox"][0] + r["bbox"][2]) / 2,     # thẳng tâm
                 lambda r: r["bbox"][2]):                         # thẳng mép phải
        if abs(pick(a) - pick(b)) <= 8:
            return 0.9
    return None


def co_figure_links(page_regs: list[dict]) -> list[tuple[str, str]]:
    """Nhãn cùng một hình: cùng trang, kề nhau theo reading order, không thuộc cùng chuỗi.
    Dùng để model thấy các nhãn anh em khi dịch một nhãn — chống gán nhầm nghĩa hàng xóm.
    """
    labels = [r for r in page_regs if r["region_type"] in LABEL_TYPES]
    out = []
    for a, b in zip(labels, labels[1:]):
        if abs(a["reading_index"] - b["reading_index"]) <= 2:
            out.append((a["region_id"], b["region_id"]))
    return out


def build(job: Job) -> None:
    model = load_json(job.p("model", "regions.json"))
    if not model:
        raise BlockingError("chưa có regions.json — chạy extract_group trước")
    regions = model["regions"]
    by_page: dict[int, list[dict]] = {}
    for r in regions:
        by_page.setdefault(r["page"], []).append(r)

    edges: list[dict] = []
    nxt: dict[str, str] = {}
    prv: dict[str, str] = {}

    for pno, regs in sorted(by_page.items()):
        regs = sorted(regs, key=lambda r: r["reading_index"])
        lh = line_height(regs)
        for a, b in zip(regs, regs[1:]):
            if b["reading_index"] - a["reading_index"] != 1:
                continue
            score = flow_link(a, b, lh) or label_stack_link(a, b)
            if score is None:
                continue
            edges.append({"type": "continues", "from": a["region_id"],
                          "to": b["region_id"], "score": score})
            nxt[a["region_id"]] = b["region_id"]
            prv[b["region_id"]] = a["region_id"]
        for x, y in co_figure_links(regs):
            edges.append({"type": "co_figure", "from": x, "to": y, "score": 0.6})

    # Chuỗi cross-page do extract_group phát hiện vẫn là `continues` — giữ nguyên semantics
    # cũ, chỉ hợp nhất vào graph. KHÔNG ghi ngược vào `continuation_*` vì
    # `translate_prep.flush_batch` phụ thuộc semantics page-break của trường đó.
    for r in regions:
        nx = r.get("continuation_next")
        if nx and r["region_id"] not in nxt:
            edges.append({"type": "continues", "from": r["region_id"], "to": nx,
                          "score": 0.8, "cross_page": True})
            nxt[r["region_id"]] = nx
            prv[nx] = r["region_id"]

    by_id = {r["region_id"]: r for r in regions}
    chains = []
    for head in [rid for rid in nxt if rid not in prv]:
        ids = [head]
        while ids[-1] in nxt and len(ids) < 40:
            ids.append(nxt[ids[-1]])
        chains.append({
            "chain_id": f"p{by_id[head]['page']}-c{len(chains):03d}",
            "region_ids": ids,
            "source_joined": " ".join(by_id[i]["source_text"].strip() for i in ids),
            "kind": ("label_stack" if by_id[head]["region_type"] in LABEL_TYPES else "flow"),
        })

    # same_source: chỉ so các node KHÔNG thuộc chuỗi nào. So mảnh của một cụm nhiều dòng với
    # một nhãn độc lập trùng chữ sẽ báo oan — ca thật "Battery side" (mảnh của cụm ở p19) vs
    # "Battery side" (nhãn độc lập ở p21), hai bản dịch khác nhau và cả hai đều đúng.
    in_chain = {rid for c in chains for rid in c["region_ids"]}
    groups: dict[str, list[str]] = {}
    for r in regions:
        if r["region_id"] in in_chain or r.get("translation_action") != "translate":
            continue
        key = " ".join(r["source_text"].split())
        if 3 <= len(key) <= 80:
            groups.setdefault(key, []).append(r["region_id"])
    same_source = {k: v for k, v in groups.items() if len(v) > 1}

    # under_heading: heading typed HOẶC heading đánh số (extract xếp nhầm thành list_item).
    sections: dict[str, str] = {}
    for pno, regs in sorted(by_page.items()):
        cur = ""
        for r in sorted(regs, key=lambda x: x["reading_index"]):
            if r["region_type"] == "heading" or is_heading_like(r["source_text"]):
                cur = " ".join(r["source_text"].split())[:80]
            elif cur:
                sections[r["region_id"]] = cur

    chain_of = {rid: c["chain_id"] for c in chains for rid in c["region_ids"]}
    for r in regions:
        cid = chain_of.get(r["region_id"])
        if cid:
            r["chain_id"] = cid
        elif "chain_id" in r:
            del r["chain_id"]
    save_json(job.p("model", "regions.json"), model)

    graph = {
        "version": GRAPH_VERSION,
        "generated_at": utc_now(),
        "edges": edges,
        "chains": chains,
        "same_source": same_source,
        "under_heading": sections,
        "stats": {
            "regions": len(regions),
            "continues": sum(1 for e in edges if e["type"] == "continues"),
            "co_figure": sum(1 for e in edges if e["type"] == "co_figure"),
            "chains": len(chains),
            "chains_max_len": max((len(c["region_ids"]) for c in chains), default=0),
            "same_source_groups": len(same_source),
        },
    }
    save_json(job.p("model", "context_graph.json"), graph)
    job.mark_stage(STAGE)
    job.log_event(STAGE, "info", "GRAPH", " ".join(f"{k}={v}" for k, v in graph["stats"].items()))
    print("context_graph: " + " ".join(f"{k}={v}" for k, v in graph["stats"].items()))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job", required=True)
    args = ap.parse_args()
    job = Job(args.job)
    try:
        job.verify_fingerprint()
        with job.acquire_lock(STAGE):
            build(job)
    except BlockingError as e:
        exit_blocking(job, STAGE, e)


if __name__ == "__main__":
    main()
