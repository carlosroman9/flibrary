# OPALS MARC Cleaner (v9)

Cleans vendor MARC records (ISO 2709 `.mrc` or MARCXML `.xml`) for import into OPALS,
and writes a change log (CSV) and a printable HTML report.

## Use it in Colab

Open `Marc_cleaner_9.ipynb` in Colab and follow the steps in its first cell.

## Use it from Python

```bash
pip install "marc-cleaner[ui] @ git+https://github.com/carlosroman9/flibrary.git#subdirectory=marc_cleaner"
```

```python
from marc_cleaner import load_rules, with_options, run_cleaning

rules = with_options(load_rules(), adjust_price=True)
result = run_cleaning(["batch1.mrc", "batch2.mrc"], rules, csv_dir="csvs", out_dir="out")
print(result["mrc"], result["csv"], result["html"], result["rejected"], result["totals"])
```

## Layout

| File | What it does |
|---|---|
| `src/marc_cleaner/rules.yaml` | All cleaning rules. Edit this, not the code. |
| `src/marc_cleaner/steps.py` | One function per cleaning step. |
| `src/marc_cleaner/pipeline.py` | `STEPS` (the order steps run in), `clean_record`, `run_cleaning`. |
| `src/marc_cleaner/lookups.py` | Loads the optional CSVs. |
| `src/marc_cleaner/validate.py` | Post-clean warnings. |
| `src/marc_cleaner/report.py` | HTML report and text summary. |
| `src/marc_cleaner/ui.py` | Gradio UI. |
| `tests/` | Regression tests (`pip install -e ".[ui,test]" && pytest`). |

## Optional CSVs

Upload them with the MARC files. Each run only uses the CSVs uploaded with it.
All columns are read as text. ISBNs may be written with or without hyphens.

| File | Columns |
|---|---|
| `lc_to_sears.csv` | `lc`, `sears` |
| `reading_levels.csv` | `id` or `isbn`, plus any of `fp_level`, `reading_level`, `interest_level`, `lexile` |
| `extra_isbns.csv` | `id` (or `001`) or `isbn`, plus any of `isbn10`, `isbn13`, `extra_isbn` |
| `category_overrides.csv` | `id` or `isbn`, `category` (`fiction`, `nonfiction`, `graphic_novels`, `everyone`) |

## Behaviour notes

- **Already-cleaned records** carry `999 $a OPALS MARC Cleaner v9.0` and are passed through
  unchanged on a re-run (so prices are not raised twice).
- **Records that can't be read or cleaned** are written to `…__REJECTED_….mrc` and listed
  under Errors in the report. The rest of the batch still runs.
- **ISBNs:** the record's missing ISBN-10/13 counterpart and `extra_isbns.csv` ISBNs are added
  as `020 $a`. ISBNs from 776 and online lookups may be other editions, so they are added as
  `020 $z`.
- **655 → 650:** `655 _0` becomes `650 _0`; a 655 with `$2` becomes `650 _7 $2 sears`;
  anything else becomes `650 _4`.
- **Login:** set `MARC_CLEANER_USER` and `MARC_CLEANER_PASS` (Colab secrets) to require a
  login on the public link.

## Changes from v8

1. Fiction with only `650 $v Juvenile fiction.` was categorized as nonfiction (detection ran
   before the Juvenile fiction → Fiction rewrite).
2. Follett detection through 040 `$d` / 940 never worked (those fields were deleted first).
3. CSV ISBN matching silently failed (ISBNs were read as numbers).
4. 655 → 650 produced `650 _7` with no `$2`.
5. 776 / online-lookup ISBNs were added as `020 $a` and labeled as derived ISBNs.
6. Re-running a cleaned file raised prices again and duplicated 521/020/650 fields.
7. ISBNs with a qualifier (`0439023483 (hardcover)`) were ignored.
8. The "Keep original 655" checkbox did nothing.
9. One unreadable record crashed the whole batch.
10. UI settings and uploaded CSVs were shared between users and between runs.
11. Report counted DETECTED/WARNING rows as changes; 008 and 1XX warnings had false positives.
12. Logic lived in notebook cells with no tests; dependencies were unpinned.
