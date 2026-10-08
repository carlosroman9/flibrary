"""Printable HTML run report."""
import os
from collections import Counter
from datetime import datetime
from html import escape

from .config import __version__

CHANGE_ACTIONS = ("ADDED", "DELETED", "MODIFIED")
ACTION_ORDER = ("ADDED", "DELETED", "MODIFIED", "WARNING", "DETECTED", "SKIPPED", "ERROR")
ACTION_COLORS = {"ADDED": "#28a745", "DELETED": "#dc3545", "MODIFIED": "#fd7e14",
                 "WARNING": "#ffc107", "DETECTED": "#6c757d", "SKIPPED": "#17a2b8",
                 "ERROR": "#8b0000"}
ACTION_CLASS = {"ADDED": "a-A", "DELETED": "a-D", "MODIFIED": "a-M", "WARNING": "a-W",
                "DETECTED": "a-E", "SKIPPED": "a-E", "ERROR": "a-D"}
CAT_COLORS = {"fiction": "#4a90d9", "nonfiction": "#50b848", "graphic_novels": "#9b59b6",
              "everyone": "#e67e22"}

CSS = """
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;max-width:960px;margin:0 auto;padding:24px;color:#333;background:#fff}
h1{color:#1a1a2e;border-bottom:3px solid #16213e;padding-bottom:8px;font-size:22px}
h2{color:#16213e;margin-top:32px;font-size:17px;border-bottom:1px solid #dee2e6;padding-bottom:6px}
.meta{background:#f0f4f8;border-radius:6px;padding:14px 18px;margin:16px 0;font-size:14px;line-height:1.8}
.meta b{color:#16213e}
.sg{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:16px 0}
.sc{background:#f8f9fa;border:1px solid #dee2e6;border-radius:8px;padding:16px;text-align:center}
.sc .n{font-size:28px;font-weight:700;color:#16213e}.sc .l{font-size:12px;color:#666;margin-top:4px}
.br{display:flex;align-items:center;margin:4px 0;font-size:13px}
.bl{width:200px;text-align:right;padding-right:10px;font-weight:500}
.bb{height:20px;border-radius:3px;display:inline-block;min-width:2px}
.bc{padding-left:8px;color:#555;font-weight:600}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}
th{background:#16213e;color:white;padding:8px 10px;text-align:left;position:sticky;top:0}
td{padding:6px 10px;border-bottom:1px solid #e8e8e8}
tr:nth-child(even){background:#fafafa}tr:hover{background:#f0f4f8}
.wr{background:#fff8e1 !important}
.a-A{color:#28a745;font-weight:600}.a-D{color:#dc3545;font-weight:600}
.a-M{color:#fd7e14;font-weight:600}.a-W{color:#e65100;font-weight:600}.a-E{color:#6c757d;font-weight:600}
.tr{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wb{background:#fff3cd;border-left:4px solid #ffc107;padding:8px 14px;margin:4px 0;border-radius:0 4px 4px 0;font-size:13px}
.wb b{color:#856404}
.eb{background:#f8d7da;border-left:4px solid #8b0000;padding:8px 14px;margin:4px 0;border-radius:0 4px 4px 0;font-size:13px}
.note{font-size:13px;color:#666}
footer{margin-top:40px;padding-top:12px;border-top:1px solid #dee2e6;font-size:11px;color:#aaa}
@media print{body{padding:12px}.sc .n{font-size:22px}th{background:#333!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


def _esc(v):
    return escape(str(v), quote=True)


def _bars(h, counts, colors=None, default="#4a6fa5", label=lambda k: k):
    if not counts:
        return
    top = max(counts.values())
    for k, c in counts.items():
        w = int(c / top * 300)
        clr = (colors or {}).get(k, default)
        h.append(f'<div class="br"><span class="bl">{_esc(label(k))}</span>'
                 f'<span class="bb" style="width:{w}px;background:{clr}"></span>'
                 f'<span class="bc">{c}</span></div>')


def generate_html_report(changelog, file_counts, totals, input_files, out_mrc, max_rows=5000):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    actions = Counter(r["action"] for r in changelog)
    n_changes = sum(actions[a] for a in CHANGE_ACTIONS)
    change_types = Counter(r["detail"] for r in changelog if r["action"] in CHANGE_ACTIONS)
    cat_rows = [r for r in changelog if r["action"] == "DETECTED" and r["field"] == "category"]
    cats = Counter(r["new_value"] for r in cat_rows)
    reasons = Counter(r["detail"] for r in cat_rows)
    warnings = [r for r in changelog if r["action"] == "WARNING"]
    errors = [r for r in changelog if r["action"] == "ERROR"]

    h = ['<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">',
         '<title>OPALS MARC Cleaner Report</title>', f"<style>{CSS}</style></head><body>",
         "<h1>OPALS MARC Cleaner &mdash; Run Report</h1>",
         '<div class="meta">',
         f"<b>Generated:</b> {_esc(ts)}<br>",
         f"<b>Input:</b> {_esc(', '.join(os.path.basename(f) for f in input_files))}<br>",
         f"<b>Output:</b> {_esc(os.path.basename(out_mrc))}</div>",
         '<div class="sg">']
    for n, label in ((totals["in"], "Records In"), (totals["out"], "Records Out"),
                     (n_changes, "Changes"), (len(warnings), "Warnings"),
                     (totals.get("skipped", 0), "Skipped (already cleaned)"),
                     (totals.get("errors", 0), "Errors")):
        h.append(f'<div class="sc"><div class="n">{n}</div><div class="l">{label}</div></div>')
    h.append("</div>")

    if errors:
        h.append("<h2>&#10060; Errors (records in the REJECTED file)</h2>")
        for r in errors:
            h.append(f'<div class="eb"><b>{_esc(r["source_file"])} {_esc(r["record_id"])}</b> '
                     f'{_esc(r["title"])} &mdash; {_esc(r["detail"])}: {_esc(r["old_value"])}</div>')

    if len(file_counts) > 1:
        h.append("<h2>File Breakdown</h2><table><tr><th>File</th><th>In</th><th>Out</th>"
                 "<th>Skipped</th><th>Errors</th></tr>")
        for fname, c in file_counts.items():
            h.append(f"<tr><td>{_esc(fname)}</td><td>{c['in']}</td><td>{c['out']}</td>"
                     f"<td>{c['skipped']}</td><td>{c['errors']}</td></tr>")
        h.append("</table>")

    if actions:
        h.append("<h2>Log Entries by Action</h2>")
        _bars(h, {a: actions[a] for a in ACTION_ORDER if actions[a]}, ACTION_COLORS)

    if cats:
        h.append("<h2>Category Breakdown</h2>")
        order = ["fiction", "nonfiction", "graphic_novels", "everyone"]
        _bars(h, {c: cats[c] for c in order if cats[c]}, CAT_COLORS,
              label=lambda k: k.replace("_", " ").title())
        h.append("<h2>Detection Reasons</h2>")
        _bars(h, dict(reasons.most_common()), default="#7f8c8d", label=lambda k: k[:40])

    if change_types:
        h.append("<h2>Top Change Types</h2>")
        _bars(h, dict(change_types.most_common(10)))

    if warnings:
        h.append("<h2>&#9888;&#65039; Validation Warnings</h2>")
        for r in warnings:
            h.append(f'<div class="wb"><b>{_esc(r["record_id"])}</b> ({_esc(str(r["title"])[:50])}) '
                     f'&mdash; <b>{_esc(r["field"])}</b>: {_esc(r["old_value"])}</div>')

    h.append("<h2>Full Change Log</h2>")
    if changelog:
        cols = ["record_id", "field", "action", "detail", "old_value", "new_value"]
        if len(file_counts) > 1:
            cols = ["source_file"] + cols
        shown = changelog[:max_rows]
        if len(changelog) > len(shown):
            h.append(f'<p class="note">Showing the first {len(shown)} of {len(changelog)} entries. '
                     "The change log CSV has all of them.</p>")
        h.append('<div style="max-height:600px;overflow-y:auto;border:1px solid #dee2e6;border-radius:4px">')
        h.append("<table><tr>" + "".join(f"<th>{_esc(c)}</th>" for c in cols) + "</tr>")
        for r in shown:
            cells = []
            for c in cols:
                v = str(r.get(c, ""))
                if c == "action":
                    cells.append(f'<td class="{ACTION_CLASS.get(v, "")}">{_esc(v)}</td>')
                elif c in ("old_value", "new_value"):
                    cells.append(f'<td class="tr" title="{_esc(v)}">{_esc(v[:60])}</td>')
                else:
                    cells.append(f"<td>{_esc(v)}</td>")
            rcls = ' class="wr"' if r["action"] == "WARNING" else ""
            h.append(f"<tr{rcls}>{''.join(cells)}</tr>")
        h.append("</table></div>")
    else:
        h.append("<p>No changes recorded.</p>")

    h.append(f"<footer>OPALS MARC Cleaner v{__version__} &mdash; Fletcher Library, PAUSD<br>"
             f"Report generated {_esc(ts)}</footer></body></html>")
    return "\n".join(h)


def text_summary(changelog, totals):
    """Short plain-text summary for the UI log box."""
    if not changelog:
        return "No changes recorded."
    actions = Counter(r["action"] for r in changelog)
    lines = [f"Changes: {sum(actions[a] for a in CHANGE_ACTIONS)}",
             "Log entries: " + ", ".join(f"{a} ({actions[a]})" for a in ACTION_ORDER if actions[a])]
    cat_rows = [r for r in changelog if r["action"] == "DETECTED" and r["field"] == "category"]
    if cat_rows:
        lines.append("Categories: " + ", ".join(
            f"{c} ({n})" for c, n in Counter(r["new_value"] for r in cat_rows).most_common()))
        lines.append("Detection reasons: " + ", ".join(
            f"{c} ({n})" for c, n in Counter(r["detail"] for r in cat_rows).most_common()))
    if totals.get("skipped"):
        lines.append(f"Skipped (already cleaned): {totals['skipped']}")
    for label, action in (("Errors", "ERROR"), ("Warnings", "WARNING")):
        rows = [r for r in changelog if r["action"] == action]
        if rows:
            lines.append(f"{label}: {len(rows)}")
            lines += [f"  ! {r['record_id']} — {r['field']}: {r['old_value']}" for r in rows]
    dupes = sum(1 for r in changelog if r["detail"] == "duplicate_subject")
    if dupes:
        lines.append(f"Duplicate subjects removed: {dupes}")
    types = Counter(r["detail"] for r in changelog if r["action"] in CHANGE_ACTIONS)
    if types:
        lines.append("Top change types: " + ", ".join(f"{d} ({c})" for d, c in types.most_common(8)))
    return "\n".join(lines)
