__version__ = "0.0.1"


def _install_runtime_patches():
	"""Wrap ERPNext's stock reports with this app's optional Barcode column.

	Reports are discovered by folder and v13 offers no override hook, so the five
	execute() functions are wrapped here -- the one point that runs in every process.
	Defensive: before erpnext is importable it does nothing, and must never break the
	import. See stock_barcode.py.
	"""
	try:
		from isoft_customization.stock_barcode import install_patches

		install_patches()
	except Exception:
		pass


_install_runtime_patches()
