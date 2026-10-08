"""Gradio UI. Each click works in its own folder with its own copy of the rules,
so simultaneous users never share settings, uploads or outputs."""
import json
import os
import shutil
import tempfile
import time

import gradio as gr
from pymarc import MARCReader

from .config import __version__, load_rules, with_options
from .pipeline import run_cleaning
from .report import text_summary

WORK_DIR = os.environ.get("MARC_CLEANER_WORKDIR",
                          os.path.join(tempfile.gettempdir(), "marc_cleaner_runs"))
LAST_RUN_FILE = os.path.join(WORK_DIR, "last_run.json")
KEEP_RUNS_HOURS = 24


def _path_of(f):
    return f if isinstance(f, str) else getattr(f, "name", str(f))


def _copy_in(files, dest):
    """Copy uploads into `dest` under their original base names; return new paths."""
    out = []
    for f in files or []:
        src = _path_of(f)
        target = os.path.join(dest, os.path.basename(src))
        shutil.copyfile(src, target)
        out.append(target)
    return out


def _prune_old_runs():
    """Delete run folders older than KEEP_RUNS_HOURS so uploads don't pile up."""
    cutoff = time.time() - KEEP_RUNS_HOURS * 3600
    for name in os.listdir(WORK_DIR):
        path = os.path.join(WORK_DIR, name)
        if name.startswith("run_") and os.path.isdir(path) and os.path.getmtime(path) < cutoff:
            shutil.rmtree(path, ignore_errors=True)


def _leader_ok(path):
    with open(path, "rb") as fh:
        return all(str(rec.leader)[9] == "a"
                   for rec in MARCReader(fh, permissive=True) if rec is not None)


def ui_clean(marc_files, csv_files, use_lookups, keep_655, adjust_price, base_rules=None):
    if marc_files and not isinstance(marc_files, list):
        marc_files = [marc_files]
    if csv_files and not isinstance(csv_files, list):
        csv_files = [csv_files]
    if not marc_files:
        msg = "Please upload one or more .mrc/.marc or MARCXML .xml files."
        return None, None, None, None, msg, None, None, None

    os.makedirs(WORK_DIR, exist_ok=True)
    _prune_old_runs()
    run_dir = tempfile.mkdtemp(prefix="run_", dir=WORK_DIR)
    in_dir, csv_dir, out_dir = (os.path.join(run_dir, d) for d in ("in", "csv", "out"))
    for d in (in_dir, csv_dir, out_dir):
        os.makedirs(d)

    logs = []
    inputs = _copy_in(marc_files, in_dir)
    logs += [f"Input: {os.path.basename(p)}" for p in inputs]
    logs += [f"CSV: {os.path.basename(p)}" for p in _copy_in(csv_files, csv_dir)]

    rules = with_options(base_rules or load_rules(), use_lookups=use_lookups,
                         keep_655=keep_655, adjust_price=adjust_price)
    result = run_cleaning(inputs, rules, csv_dir=csv_dir, out_dir=out_dir, log=logs.append)

    try:
        with open(LAST_RUN_FILE, "w") as fh:
            json.dump({k: result[k] for k in ("mrc", "csv", "html", "rejected")}, fh)
    except OSError:
        pass

    t = result["totals"]
    if len(inputs) > 1:
        logs.append(f"Batch: {len(inputs)} files merged")
    logs.append(f"Leader/09 set to 'a' for all? {'Yes' if _leader_ok(result['mrc']) else 'No'}")
    if result["rejected"]:
        logs.append(f"{t['errors']} record(s) could not be cleaned — see the Rejected file and report.")
    logs += ["", "--- CHANGE LOG SUMMARY ---", text_summary(result["changelog"], t)]

    paths = (result["mrc"], result["csv"], result["html"])
    return (*paths, result["rejected"], "\n".join(logs), *paths)


def build_demo(base_rules=None):
    with gr.Blocks(title=f"OPALS MARC Cleaner v{__version__}") as demo:
        gr.Markdown(f"## OPALS MARC Cleaner — v{__version__}")
        gr.Markdown("Upload one or more MARC files. If download is blocked in the Colab iframe, "
                    "use the public link or the Colab fallback cell.")
        with gr.Row():
            marc_files = gr.File(label="MARC input(s) (.mrc/.marc or .xml)",
                                 file_types=[".mrc", ".marc", ".xml"], file_count="multiple")
            csv_files = gr.File(label="Optional CSVs (lc_to_sears, reading_levels, extra_isbns, "
                                      "category_overrides)", file_count="multiple", file_types=[".csv"])
        with gr.Row():
            use_lookups = gr.Checkbox(label="Use public ISBN lookups (Open Library + Google Books)",
                                      value=False)
            keep_655 = gr.Checkbox(label="Keep original 655 after converting to 650", value=True)
            adjust_price = gr.Checkbox(label="Adjust 852 $9 price (ceil + $3)", value=True)
        btn = gr.Button("Clean", variant="primary")
        with gr.Row():
            out_mrc = gr.File(label="Cleaned MARC (.mrc)", interactive=False)
            out_csv = gr.File(label="Change Log (.csv)", interactive=False)
            out_html = gr.File(label="Report (.html)", interactive=False)
            out_rej = gr.File(label="Rejected records (.mrc)", interactive=False)
        out_log = gr.Textbox(label="Log", lines=14)
        with gr.Row():
            dl = gr.DownloadButton(label="⬇️ Cleaned .mrc", value=None)
            dl_csv = gr.DownloadButton(label="\U0001F4CB Change log .csv", value=None)
            dl_html = gr.DownloadButton(label="\U0001F4CA Report .html", value=None)

        def on_click(m, c, lk, k6, ap):
            return ui_clean(m, c, lk, k6, ap, base_rules=base_rules)

        btn.click(on_click, inputs=[marc_files, csv_files, use_lookups, keep_655, adjust_price],
                  outputs=[out_mrc, out_csv, out_html, out_rej, out_log, dl, dl_csv, dl_html])
    return demo


def launch(share=True, inbrowser=True, rules_path=None, **kwargs):
    """Launch the UI. Set MARC_CLEANER_USER and MARC_CLEANER_PASS to require a login."""
    user, pw = os.environ.get("MARC_CLEANER_USER"), os.environ.get("MARC_CLEANER_PASS")
    auth = (user, pw) if user and pw else None
    if share and not auth:
        print("Note: the public link has no login. Set MARC_CLEANER_USER and "
              "MARC_CLEANER_PASS to require one.")
    os.makedirs(WORK_DIR, exist_ok=True)
    demo = build_demo(load_rules(rules_path) if rules_path else None)
    return demo.launch(share=share, inbrowser=inbrowser, auth=auth,
                       allowed_paths=[WORK_DIR], **kwargs)
