"""List view bulk Print must POST the selection (public/js/bulk_print_post.js):
gunicorn refuses GET request lines above 4094 bytes ("Request Line is too large").

    env/bin/python apps/isoft_customization/isoft_customization/tests/bulk_print_post_check.py
Opens the Payment Entry list on dev, selects 160 submitted entries, runs the list's
own Print action and checks the download request. Nothing is written.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import browser_target_total as h  # noqa: E402

failures = 0
def check(cond, label, detail=""):
    global failures
    print("PASS" if cond else "FAIL", label, detail); failures += (0 if cond else 1)

def main():
    import frappe
    sid = h.mint_session()
    names = [r.name for r in frappe.get_all("Payment Entry", filters={"docstatus": 1}, fields=["name"], order_by="creation desc", limit=160)]
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(ignore_https_errors=True, viewport={"width": 1400, "height": 900}, accept_downloads=True)
            ctx.add_cookies([{"name": "sid", "value": sid, "domain": "dev.isoft.ao", "path": "/"}])
            seen, pages = [], []
            ctx.on("request", lambda r: seen.append(r) if "download_multi_pdf" in r.url else None)
            ctx.on("page", lambda p: pages.append(p))
            page = ctx.new_page()
            page.goto(f"{h.BASE_URL}/app/payment-entry?docstatus=1", wait_until="networkidle")
            page.wait_for_function("() => window.cur_list && cur_list.doctype === 'Payment Entry' && cur_list.data && cur_list.data.length", timeout=30000)
            # show enough rows, tick the first 160 submitted ones, then use the list's own Print action
            page.evaluate("() => { cur_list.page_length = 200; return cur_list.refresh(); }")
            page.wait_for_function("() => cur_list.data.length >= 160", timeout=30000)
            page.wait_for_timeout(800)
            names = page.evaluate("() => cur_list.data.filter(d => d.docstatus === 1).slice(0, 160).map(d => d.name)")
            page.evaluate("""(names) => {
                cur_list.$result.find('.list-row-checkbox').each(function () {
                    const name = cstr(unescape($(this).data().name));
                    if (names.includes(name)) { $(this).prop('checked', true); }
                });
                cur_list.on_row_checked();
            }""", names)
            n = page.evaluate("() => cur_list.get_checked_items().length")
            check(n >= 150, "160 submitted payment entries selected in the list", str(n))
            url_len = page.evaluate("(names) => ('/api/method/frappe.utils.print_format.download_multi_pdf?doctype=Payment%20Entry&name=' + encodeURIComponent(JSON.stringify(names))).length", names)
            check(url_len > 4094, "the equivalent GET line would exceed gunicorn's 4094-byte limit", str(url_len))
            page.evaluate("() => { const item = cur_list.get_actions_menu_items().find(i => i.label === __('Print')); item.action(); }")
            page.wait_for_selector(".modal:visible button.btn-primary:has-text('Print')", timeout=10000)
            page.click(".modal:visible button.btn-primary:has-text('Print')")
            for _ in range(60):  # the posted form opens in a new tab; watch the network instead
                if seen: break
                page.wait_for_timeout(500)
            page.wait_for_timeout(500)
            check(seen and seen[-1].method == "POST", "download_multi_pdf is requested with POST", seen[-1].method if seen else "no request seen")
            from urllib.parse import unquote_plus
            body = unquote_plus(seen[-1].post_data or "") if seen else ""
            check(names[0] in body and len(body) > 4094, "the names travel in the POST body", str(len(body)))
            # the PDF comes back with Content-Disposition, which Chromium turns into a download on the new tab
            try:
                download = pages[-1].wait_for_event("download", timeout=300000)
                fname = download.suggested_filename
                path = download.path()
                head = open(path, "rb").read(5) if path else b""
            except Exception as e:
                fname, head = repr(e)[:120], b""
            check(fname.lower().endswith(".pdf") and head == b"%PDF-", "server answers with a PDF download", f"{fname} {head!r}")
            b.close()
    finally:
        h.drop_session(sid)

if __name__ == "__main__":
    main(); print("failures:", failures); sys.exit(1 if failures else 0)
