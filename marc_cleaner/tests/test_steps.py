"""Regression tests for the issues found in the v8 audit."""
import copy

from conftest import make_record, subfields

from marc_cleaner import clean_record, with_options
from marc_cleaner.isbn import normalize_isbn
from marc_cleaner.lookups import CsvLookup, Maps, read_csv
from marc_cleaner.steps import detect_category


def clean(rec, rules, maps=None):
    log = []
    status = clean_record(rec, rules, maps, log, "test.mrc")
    return status, log


def test_juvenile_fiction_is_categorized_as_fiction(rules):
    rec = make_record(("650", [" ", "0"], ["a", "Dogs", "v", "Juvenile fiction."]),
                      ("852", ["1", " "], ["h", "FIC SMI"]))
    clean(rec, rules)
    assert subfields(rec, "852", "3") == ["14f"]
    assert subfields(rec, "852", "k") == ["FIC"]


def test_nonfiction_genre_is_not_fiction(rules):
    rec = make_record(("655", [" ", "7"], ["a", "Nonfiction", "2", "local"]))
    assert detect_category(rec, rules, Maps())[0] == "nonfiction"


def test_follett_detected_by_040_before_it_is_deleted(rules, tmp_path):
    (tmp_path / "rl.csv").write_text("id,lexile\nb1,500L\n")
    maps = Maps(reading_levels=CsvLookup(read_csv(tmp_path / "rl.csv")))
    follett = make_record(("040", [" ", " "], ["a", "X", "d", "ICrlF"]))
    clean(follett, rules, maps)
    assert not follett.get_fields("040")
    assert not follett.get_fields("521")

    other = make_record()
    clean(other, rules, maps)
    assert subfields(other, "521", "a") == ["500L"]


def test_csv_isbns_match_when_numeric_or_hyphenated(rules, tmp_path):
    (tmp_path / "ov.csv").write_text(
        "isbn,category\n9780439023481,graphic_novels\n0-306-40615-2,everyone\n")
    df = read_csv(tmp_path / "ov.csv")
    assert df["isbn"].tolist() == ["9780439023481", "0-306-40615-2"]  # text, not numbers
    maps = Maps(cat_overrides=CsvLookup(df))

    a = make_record(("020", [" ", " "], ["a", "978-0-439-02348-1 (hbk.)"]))
    assert detect_category(a, rules, maps, "x") == ("graphic_novels", "category_overrides.csv")
    b = make_record(("020", [" ", " "], ["a", "0306406152"]))  # leading zero kept
    assert detect_category(b, rules, maps, "x")[0] == "everyone"


def test_655_to_650_indicators(rules):
    rec = make_record(("655", [" ", "0"], ["a", "Fairy tales."]),
                      ("655", [" ", "7"], ["a", "Graphic novels.", "2", "lcgft"]),
                      ("655", [" ", "4"], ["a", "Local genre"]))
    clean(rec, rules)
    got = {f.get_subfields("a")[0]: (f.indicator2, f.get_subfields("2"))
           for f in rec.get_fields("650")}
    assert got["Fairy tales."] == ("0", [])
    assert got["Graphic novels."] == ("7", ["sears"])
    assert got["Local genre"] == ("4", [])
    assert len(rec.get_fields("655")) == 3


def test_keep_655_checkbox_works(rules):
    rec = make_record(("655", [" ", "0"], ["a", "Fairy tales."]))
    clean(rec, with_options(rules, keep_655=False))
    assert not rec.get_fields("655")
    assert rec.get_fields("650")


def test_related_isbns_go_to_020z_with_correct_labels(rules):
    rec = make_record(("020", [" ", " "], ["a", "9780439023481"]),
                      ("776", ["0", "8"], ["z", "9780545229937"]))
    _, log = clean(rec, rules)
    assert sorted(subfields(rec, "020", "a")) == ["0439023483", "9780439023481"]
    assert subfields(rec, "020", "z") == ["9780545229937"]
    labels = {r["new_value"]: r["detail"] for r in log if r["field"].startswith("020")}
    assert labels == {"0439023483": "isbn10_from_13", "9780545229937": "related_776"}


def test_isbn_with_qualifier_gets_counterpart(rules):
    rec = make_record(("020", [" ", " "], ["a", "0439023483 (hardcover)"]))
    clean(rec, rules)
    assert "9780439023481" in subfields(rec, "020", "a")


def test_normalize_isbn():
    assert normalize_isbn("0-439-02348-3 (hbk.)") == "0439023483"
    assert normalize_isbn("9780439023481 :") == "9780439023481"
    assert normalize_isbn("123") is None
    assert normalize_isbn(None) is None


def test_second_run_is_skipped_and_price_unchanged(rules):
    rec = make_record(("852", ["1", " "], ["h", "FIC", "9", "12.50 USD"]))
    clean(rec, rules)
    assert subfields(rec, "852", "9") == ["16.00"]
    before = rec.as_marc()
    status, log = clean(rec, rules)
    assert status == "skipped"
    assert rec.as_marc() == before
    assert [r["action"] for r in log] == ["SKIPPED"]


def test_with_options_does_not_mutate_rules(rules):
    original = copy.deepcopy(rules)
    with_options(rules, use_lookups=True, keep_655=False, adjust_price=False)
    assert rules == original


def test_validation_warnings(rules):
    title_entry = make_record(("020", [" ", " "], ["a", "9780439023481"]),
                              ("852", ["1", " "], ["h", "FIC"]))
    _, log = clean(title_entry, rules)
    assert not [r for r in log if r["action"] == "WARNING"]

    rec = make_record(f008="200101s2020")
    rec.get_fields("245")[0].indicators = ["1", "0"]
    _, log = clean(rec, rules)
    warned = {r["field"]: r for r in log if r["action"] == "WARNING"}
    assert "40 characters" in warned["008"]["old_value"]
    assert "1XX" in warned
    assert all(r["source_file"] == "test.mrc" for r in warned.values())
