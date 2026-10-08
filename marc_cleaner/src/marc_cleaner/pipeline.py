"""Record pipeline and file-level runs."""
import copy
import os
from datetime import datetime

import pandas as pd
from pymarc import MARCReader, MARCWriter, map_xml

from . import steps
from .lookups import Maps, load_maps
from .report import generate_html_report
from .validate import validate_record

LOG_COLUMNS = ["record_id", "title", "source_file", "field", "action", "detail",
               "old_value", "new_value"]

# Order matters:
#  - Follett detection happens in Context, before delete_fields removes 040/940.
#  - Diacritics are fixed first so later lookups see clean text.
#  - Subject normalization (Juvenile fiction -> Fiction, 655 -> 650) runs before
#    holdings, because holdings detects the category from those subjects.
STEPS = [
    steps.fix_diacritics,
    steps.delete_fields,
    steps.normalize_082,
    steps.clean_245c,
    steps.isbns,
    steps.lc_to_sears,
    steps.juvenile_fiction,
    steps.genre_655_to_650,
    steps.dedup_subjects,
    steps.holdings,
    steps.strip_852_subfields,
    steps.reading_levels,
    steps.prices,
    steps.delete_empty_fields,
    steps.add_stamp,
    steps.reorder_fields,
    steps.set_utf8,
]


class Context:
    """Per-record state shared by the steps."""

    def __init__(self, rec, rules, maps, changelog, source_file=""):
        self.rules, self.maps = rules, maps
        self.changelog = changelog
        self.source_file = source_file
        self.rid = steps.rec_id(rec)
        self.title = steps.rec_title(rec)
        self.follett = steps.is_follett(rec, rules)

    def log(self, field, action, old_value="", new_value="", detail=""):
        if self.changelog is None:
            return
        self.changelog.append({
            "record_id": self.rid, "title": self.title, "source_file": self.source_file,
            "field": field, "action": action, "detail": detail,
            "old_value": str(old_value)[:200], "new_value": str(new_value)[:200],
        })


def clean_record(rec, rules, maps=None, changelog=None, source_file=""):
    """Clean `rec` in place. Returns 'cleaned', or 'skipped' if it was already cleaned."""
    ctx = Context(rec, rules, maps or Maps(), changelog, source_file)
    if steps.has_stamp(rec, rules):
        ctx.log("record", "SKIPPED", detail="already_cleaned")
        return "skipped"
    for step in STEPS:
        step(rec, ctx)
    validate_record(rec, ctx)
    return "cleaned"


def _process_file(path, on_record):
    """Call on_record(record, raw_bytes, error) for each record in an ISO 2709 or MARCXML file.

    MARCXML is streamed record by record, so large files are not loaded into memory.
    """
    if path.lower().endswith(".xml"):
        try:
            map_xml(lambda rec: on_record(rec, None, None), path)
        except Exception as e:
            on_record(None, None, f"XML parse error (records after this point were not read): {e}")
        return
    with open(path, "rb") as fh:
        reader = MARCReader(fh, to_unicode=True, force_utf8=False,
                            utf8_handling="replace", permissive=True)
        for rec in reader:
            if rec is None:
                on_record(None, reader.current_chunk, str(reader.current_exception))
            else:
                on_record(rec, None, None)


def run_cleaning(input_files, rules, csv_dir=None, out_dir=".", log=print):
    """Clean one or more MARC files into a single output.

    Returns a dict with output paths (mrc, csv, html, rejected or None), totals,
    per-file counts and the changelog rows.
    Records that cannot be read or cleaned go to a separate __REJECTED.mrc file
    (raw bytes when unreadable, the original record when cleaning failed).
    """
    if isinstance(input_files, str):
        input_files = [input_files]
    os.makedirs(out_dir, exist_ok=True)
    maps = load_maps(rules, csv_dir, log=log)

    base = os.path.splitext(os.path.basename(input_files[0]))[0]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {k: os.path.join(out_dir, f"{base}__{name}_{ts}.{ext}")
           for k, name, ext in (("mrc", "CLEAN", "mrc"), ("csv", "CHANGELOG", "csv"),
                                ("html", "REPORT", "html"), ("rejected", "REJECTED", "mrc"))}

    changelog, file_counts = [], {}
    totals = {"in": 0, "out": 0, "skipped": 0, "errors": 0}
    rejects = []  # raw MARC bytes

    with open(out["mrc"], "wb") as fh_out:
        writer = MARCWriter(fh_out)
        for path in input_files:
            src = os.path.basename(path)
            c = {"in": 0, "out": 0, "skipped": 0, "errors": 0}
            log(f"Processing: {src}")

            def on_record(rec, raw, err, src=src, c=c):
                if rec is None:
                    c["errors"] += 1
                    if raw:  # an unreadable ISO 2709 record: keep its bytes
                        c["in"] += 1
                        rejects.append(raw)
                        where = f"record #{c['in']}"
                    else:  # MARCXML parse failure
                        where = f"after record #{c['in']}"
                    changelog.append(_error_row(src, where, "unreadable_record", err))
                    return
                c["in"] += 1
                original = copy.deepcopy(rec)
                try:
                    status = clean_record(rec, rules, maps, changelog, src)
                    writer.write(rec)
                except Exception as e:
                    c["errors"] += 1
                    try:
                        rejects.append(original.as_marc())
                    except Exception:
                        pass
                    changelog.append(_error_row(src, steps.rec_id(original) or f"record #{c['in']}",
                                                "clean_failed", f"{type(e).__name__}: {e}",
                                                steps.rec_title(original)))
                    return
                c["out"] += 1
                if status == "skipped":
                    c["skipped"] += 1

            _process_file(path, on_record)
            for k in totals:
                totals[k] += c[k]
            file_counts[src] = c
            log(f"  {src}: {c['in']} in, {c['out']} out, {c['skipped']} skipped, {c['errors']} errors")
        writer.close(close_fh=False)

    if rejects:
        with open(out["rejected"], "wb") as fh:
            fh.write(b"".join(rejects))
        log(f"Rejected records: {out['rejected']} ({len(rejects)})")
    else:
        out["rejected"] = None

    pd.DataFrame(changelog, columns=LOG_COLUMNS).to_csv(
        out["csv"], index=False, encoding="utf-8-sig")
    log(f"Change log: {out['csv']} ({len(changelog)} entries)")

    html = generate_html_report(changelog, file_counts, totals, input_files, out["mrc"],
                                max_rows=rules.get("report", {}).get("max_change_rows", 5000))
    with open(out["html"], "w", encoding="utf-8") as fh:
        fh.write(html)
    log(f"HTML report: {out['html']}")
    log(f"Total records read: {totals['in']} | written: {totals['out']} | "
        f"skipped (already cleaned): {totals['skipped']} | errors: {totals['errors']}")
    return {**out, "totals": totals, "file_counts": file_counts, "changelog": changelog}


def _error_row(src, rid, detail, message, title=""):
    return {"record_id": rid, "title": title, "source_file": src, "field": "record",
            "action": "ERROR", "detail": detail, "old_value": str(message)[:200], "new_value": ""}
