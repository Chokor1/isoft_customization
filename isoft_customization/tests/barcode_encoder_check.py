"""Barcode encoder check (pure Python, no site).

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/barcode_encoder_check.py
Reference values are the published GS1/ISO examples (EAN-13 5901234123457, UPC-A 036000291452,
EAN-8 96385074) and the ISO 15417 Code 128 start/stop/value-0 patterns.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from isoft_customization.barcode_labels import encoder as e  # noqa: E402

fails = 0


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, detail if not cond else "")
	fails += not cond


def bits(mods):
	return "".join(str(m) for m in mods)


def strip_quiet(mods):
	s = bits(mods)
	return s.strip("0")


# check digits
check("ean13_check_digit", e.ean_check_digit("590123412345") == 7)
check("upca_check_digit", e.ean_check_digit("03600029145") == 2)
check("ean8_check_digit", e.ean_check_digit("9638507") == 4)

# detection
check("detect_ean13", e.detect("5901234123457") == "EAN13")
check("detect_upca", e.detect("036000291452") == "UPCA")
check("detect_ean8", e.detect("96385074") == "EAN8")
check("detect_code128_text", e.detect("Wikipedia") == "CODE128")
check("bad_check_digit_falls_back", e.detect("5901234123458") == "CODE128")
check("letters_fall_back", e.detect("ABC-123") == "CODE128")
check("bad_upca_falls_back", e.detect("036000291453") == "CODE128")

# EAN-13 structure
core = bits(e.encode("5901234123457"))
core = core[core.index("101"):]  # drop leading quiet zone
core = core[:95]
check("ean13_95_modules", len(core) == 95, len(core))
check("ean13_start_guard", core[:3] == "101")
check("ean13_centre_guard", core[45:50] == "01010", core[45:50])
check("ean13_end_guard", core[92:95] == "101")
check("ean13_digit2_L9", core[3:10] == "0001011", core[3:10])  # first digit 5 -> parity LGGLLG
check("ean13_digit3_G0", core[10:17] == "0100111", core[10:17])
check("ean13_last_R7", core[85:92] == "1000100", core[85:92])
check("ean13_quiet_zones", bits(e.encode("5901234123457")).startswith("0" * 9))

# UPC-A == EAN-13 with a leading 0
check("upca_equals_ean13_0", e.encode("036000291452") == e.encode("0036000291452"))

# EAN-8
s8 = strip_quiet(e.encode("96385074"))
check("ean8_67_modules", len(s8) == 67, len(s8))

# Code 128 table sanity
check("code128_table_107", len(e.CODE128) == 107)
check("code128_widths_sum", all(sum(map(int, p)) == 11 for p in e.CODE128[:106]) and sum(map(int, e.CODE128[106])) == 13)
check("code128_unique", len(set(e.CODE128)) == 107)

# Code 128 symbols and patterns
check(
	"code128_wikipedia_symbols",
	e.code128_symbols("Wikipedia") == [104, 55, 73, 75, 73, 80, 69, 68, 73, 65, 88, 106],
	e.code128_symbols("Wikipedia"),
)
w = strip_quiet(e.encode("Wikipedia"))
check("code128_wikipedia_134_modules", len(w) == 134, len(w))
check("code128_start_b_pattern", w[:11] == "11010010000", w[:11])
check("code128_stop_pattern", w[-13:] == "1100011101011", w[-13:])
check("code128_value0_pattern", e.pattern_bits(e.CODE128[0]) == "11011001100")

c = e.code128_symbols("12345678")
check("code128_set_c_digits", c == [105, 12, 34, 56, 78, 47, 106], c)
check("code128_set_c_shorter", len(strip_quiet(e.encode("12345678"))) == 6 * 11 + 13 < len(strip_quiet(e.encode("1234567A"))))
check("code128_odd_digits_set_b", e.code128_symbols("12345")[0] == 104)

# SVG
svg = e.to_svg("5901234123457", height_mm=10, width_mm=40)
check("svg_root", svg.startswith("<svg"))
check("svg_bars", svg.count("<rect") >= 20, svg.count("<rect"))
check("svg_no_text", "<text" not in svg)
check("svg_preserve_aspect_none", 'preserveAspectRatio="none"' in svg)
check("svg_escapes_nothing_needed", "<svg" in e.to_svg("A&B<C"))

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
