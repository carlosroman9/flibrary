"""Optional CSV lookup tables, indexed once per run for fast matching.

All CSVs are read as text (never numbers), so ISBNs keep leading zeros and 'X'
check digits. ISBN keys are normalized on both sides before comparing.
"""
import os

import pandas as pd

from .isbn import normalize_isbn

CATEGORIES = {"fiction", "nonfiction", "graphic_novels", "everyone"}


def read_csv(path):
    """Read a CSV as all-text with lower-case, trimmed column names."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.apply(lambda col: col.str.strip())
    df = df[(df != "").any(axis=1)]
    if "id" not in df.columns and "001" in df.columns:
        df["id"] = df["001"]
    return df


class CsvLookup:
    """Rows of a CSV, findable by record 001 (`id` column) or by ISBN (`isbn` column)."""

    def __init__(self, df):
        self.df = df
        self.columns = set(df.columns)
        self.by_id, self.by_isbn = {}, {}
        for row in df.to_dict("records"):
            if row.get("id"):
                self.by_id.setdefault(row["id"], []).append(row)
            key = normalize_isbn(row.get("isbn"))
            if key:
                self.by_isbn.setdefault(key, []).append(row)

    def __len__(self):
        return len(self.df)

    def find(self, rid, isbns):
        """Matching rows: those matched by id first, then by ISBN; no duplicates."""
        rows, seen = [], set()
        candidates = list(self.by_id.get(str(rid), [])) if rid else []
        for i in isbns:
            candidates += self.by_isbn.get(i, [])
        for row in candidates:
            if id(row) not in seen:
                seen.add(id(row))
                rows.append(row)
        return rows


class Maps:
    """All lookup tables for one run. Missing CSVs are simply None."""

    def __init__(self, lc_to_sears=None, reading_levels=None, extra_isbns=None,
                 cat_overrides=None):
        self.lc_to_sears = lc_to_sears or {}
        self.reading_levels = reading_levels
        self.extra_isbns = extra_isbns
        self.cat_overrides = cat_overrides


def load_maps(rules, csv_dir, log=print):
    """Load the CSVs named in `rules` from `csv_dir` only (never the working directory)."""
    def load(fn):
        if not csv_dir:
            return None
        path = os.path.join(csv_dir, fn)
        if not os.path.exists(path):
            return None
        try:
            df = read_csv(path)
            log(f"Loaded CSV: {fn} ({len(df)} rows)")
            return df
        except Exception as e:
            log(f"Warning: failed to load {fn} -> {e}")
            return None

    maps = Maps()
    subj = rules.get("subjects", {})
    if subj.get("use_lc_to_sears_csv", True):
        df = load(subj.get("lc_to_sears_csv_filename", "lc_to_sears.csv"))
        if df is not None and {"lc", "sears"} <= set(df.columns):
            pairs = zip(df["lc"], df["sears"], strict=True)
            maps.lc_to_sears = {lc.lower(): s for lc, s in pairs if lc and s}

    df = load(rules.get("reading_levels", {}).get("csv_filename", "reading_levels.csv"))
    if df is not None:
        maps.reading_levels = CsvLookup(df)

    ex = rules.get("extra_isbns", {})
    if ex.get("use_csv", True):
        df = load(ex.get("csv_filename", "extra_isbns.csv"))
        if df is not None:
            if "extra_isbn" not in df.columns and "isbn" in df.columns:
                df["extra_isbn"] = df["isbn"]
            maps.extra_isbns = CsvLookup(df)

    ov = rules.get("categories", {}).get("overrides", {})
    if ov.get("use_csv", True):
        df = load(ov.get("csv_filename", "category_overrides.csv"))
        if df is not None:
            maps.cat_overrides = CsvLookup(df)
    return maps
