"""Self-contained barcode encoder: EAN-13, EAN-8, UPC-A and Code 128, drawn as SVG.

No dependency on purpose: production deploys with git pull + migrate only.
`encode()` returns the module pattern (1 = bar, 0 = space) including quiet zones;
`to_svg()` turns it into an SVG of plain <rect> bars that wkhtmltopdf renders exactly.
"""

QUIET = 10  # modules of white on each side

# EAN/UPC digit codes (left odd "L"; right "R" is its complement; left even "G" is R reversed)
_L = ("0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011")
_R = tuple("".join("1" if b == "0" else "0" for b in code) for code in _L)
_G = tuple(code[::-1] for code in _R)
# EAN-13 parity of the six left digits, chosen by the first (implicit) digit
_PARITY = ("LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL")

# Code 128 bar/space widths for values 0..106 (103 start A, 104 start B, 105 start C, 106 stop)
CODE128 = (
	"212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
	"221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
	"221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
	"212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
	"231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
	"231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
	"314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
	"112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
	"111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
	"214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
	"114131", "311141", "411131", "211412", "211214", "211232", "2331112",
)
_START_B, _START_C, _STOP = 104, 105, 106


def ean_check_digit(digits):
	"""GS1 check digit for a 7, 11 or 12 digit body (EAN-8, UPC-A, EAN-13)."""
	total = 0
	for i, ch in enumerate(reversed(digits)):
		total += int(ch) * (3 if i % 2 == 0 else 1)
	return (10 - total % 10) % 10


def _valid_gs1(value, length):
	return len(value) == length and value.isdigit() and ean_check_digit(value[:-1]) == int(value[-1])


def detect(value):
	value = (value or "").strip()
	if _valid_gs1(value, 13):
		return "EAN13"
	if _valid_gs1(value, 12):
		return "UPCA"
	if _valid_gs1(value, 8):
		return "EAN8"
	return "CODE128"


def pattern_bits(widths):
	"""'211214' -> '11010010000' (bar first, alternating)."""
	out, bar = [], True
	for w in widths:
		out.append(("1" if bar else "0") * int(w))
		bar = not bar
	return "".join(out)


def _ean13_core(value):
	parity = _PARITY[int(value[0])]
	left = "".join((_L if p == "L" else _G)[int(d)] for p, d in zip(parity, value[1:7]))
	right = "".join(_R[int(d)] for d in value[7:13])
	return "101" + left + "01010" + right + "101"


def _ean8_core(value):
	left = "".join(_L[int(d)] for d in value[:4])
	right = "".join(_R[int(d)] for d in value[4:8])
	return "101" + left + "01010" + right + "101"


def code128_symbols(value):
	"""Symbol values incl. start, check and stop. Set C for an even run of >=4 digits, else set B."""
	if len(value) >= 4 and len(value) % 2 == 0 and value.isdigit():
		symbols = [_START_C] + [int(value[i:i + 2]) for i in range(0, len(value), 2)]
	else:
		symbols = [_START_B]
		for ch in value:
			code = ord(ch)
			if code < 32 or code > 127:
				ch = "?"  # outside set B (accents etc.): never fail a label over one character
				code = ord(ch)
			symbols.append(code - 32)
	check = (symbols[0] + sum(v * i for i, v in enumerate(symbols[1:], 1))) % 103
	return symbols + [check, _STOP]


def encode(value, kind=None):
	value = (value or "").strip()
	kind = kind or detect(value)
	if kind == "EAN13":
		core = _ean13_core(value)
	elif kind == "UPCA":
		core = _ean13_core("0" + value)
	elif kind == "EAN8":
		core = _ean8_core(value)
	else:
		core = "".join(pattern_bits(CODE128[s]) for s in code128_symbols(value))
	return [int(b) for b in "0" * QUIET + core + "0" * QUIET]


def to_svg(value, kind=None, height_mm=10, width_mm=40):
	"""SVG of the bars only (digits are printed by the label template as text)."""
	mods = encode(value, kind)
	rects, i, n = [], 0, len(mods)
	while i < n:
		if mods[i]:
			j = i
			while j < n and mods[j]:
				j += 1
			rects.append('<rect x="%d" y="0" width="%d" height="1"/>' % (i, j - i))
			i = j
		else:
			i += 1
	return (
		'<svg xmlns="http://www.w3.org/2000/svg" width="%smm" height="%smm" viewBox="0 0 %d 1" '
		'preserveAspectRatio="none" shape-rendering="crispEdges" fill="#000">%s</svg>'
		% (round(width_mm, 2), round(height_mm, 2), n, "".join(rects))
	)
