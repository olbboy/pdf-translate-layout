"""Self-test các pure function chủ chốt. Chạy: python3 selftest.py (exit 0 = pass)."""

from __future__ import annotations

import unicodedata

from _common import STATUS_TRANSITIONS, nfc, new_job_id, slug
from fit_paint import wrap_lines
from translate_prep import NUMERIC_RE, PH_RE, protect, restore
from validate_responses import apply_punct_map

FAILURES = []


def check(name: str, cond: bool, detail: str = ""):
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

# ── revoke path trong state machine ──
check("RELEASED -> REVOKED allowed", "REVOKED" in _ST["RELEASED"])
check("REVOKED -> TRANSLATED allowed (re-run)", "TRANSLATED" in _ST["REVOKED"])
check("RELEASED -> REJECTED still illegal", "REJECTED" not in _ST["RELEASED"])
check("REVOKED not directly releasable",
      "RELEASED" not in _ST["REVOKED"] and "HUMAN_APPROVED" not in _ST["REVOKED"])

print()
if FAILURES:
    print(f"SELFTEST FAIL ({len(FAILURES)}):")
    for f in FAILURES:
        print(" -", f)
    raise SystemExit(1)
print("SELFTEST: ALL PASS")
