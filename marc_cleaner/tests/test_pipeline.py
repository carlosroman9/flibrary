import os
from pathlib import Path

from conftest import make_record, write_mrc
from pymarc import MARCReader, XMLWriter

from marc_cleaner import pipeline, run_cleaning, steps


def read_all(path):
    with open(path, "rb") as fh:
        return [r for r in MARCReader(fh) if r is not None]


def quiet(*_):
    pass


def test_unreadable_record_is_rejected_and_batch_continues(rules, tmp_path):
    good = [make_record(rid="b1"), make_record(rid="b2")]
    body = b"nam  2200025   4500garbage-not-a-directory\x1e\x1d"
    bad = b"%05d" % (len(body) + 5) + body  # correct length, broken directory
    src = write_mrc(tmp_path / "in.mrc", good[:1], raw_after=bad)
    with open(src, "ab") as fh:
        fh.write(good[1].as_marc())

    res = run_cleaning(src, rules, out_dir=tmp_path / "out", log=quiet)
    assert [steps.rec_id(r) for r in read_all(res["mrc"])] == ["b1", "b2"]
    assert res["totals"] == {"in": 3, "out": 2, "skipped": 0, "errors": 1}
    with open(res["rejected"], "rb") as fh:
        assert fh.read() == bad


def test_cleaning_failure_rejects_original(rules, tmp_path, monkeypatch):
    src = write_mrc(tmp_path / "in.mrc", [make_record(rid="ok"), make_record(rid="boom")])

    def explode(rec, ctx):
        if ctx.rid == "boom":
            raise ValueError("bad data")
    monkeypatch.setattr(pipeline, "STEPS", [explode] + pipeline.STEPS)

    res = run_cleaning(src, rules, out_dir=tmp_path / "out", log=quiet)
    assert [steps.rec_id(r) for r in read_all(res["mrc"])] == ["ok"]
    rejected = read_all(res["rejected"])
    assert [steps.rec_id(r) for r in rejected] == ["boom"]
    assert not rejected[0].get_fields("999")  # the original, not a half-cleaned copy
    errors = [r for r in res["changelog"] if r["action"] == "ERROR"]
    assert errors[0]["detail"] == "clean_failed" and "bad data" in errors[0]["old_value"]


def test_csvs_only_come_from_csv_dir(rules, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "category_overrides.csv").write_text("id,category\nb1,everyone\n")
    src = write_mrc(tmp_path / "in.mrc", [make_record(rid="b1")])

    res = run_cleaning(src, rules, csv_dir=None, out_dir=tmp_path / "a", log=quiet)
    assert "14nf" in [v for f in read_all(res["mrc"])[0].get_fields("852")
                      for v in f.get_subfields("3")]

    csv_dir = tmp_path / "csvs"
    csv_dir.mkdir()
    (csv_dir / "category_overrides.csv").write_text("id,category\nb1,everyone\n")
    res = run_cleaning(src, rules, csv_dir=csv_dir, out_dir=tmp_path / "b", log=quiet)
    assert "14e" in [v for f in read_all(res["mrc"])[0].get_fields("852")
                     for v in f.get_subfields("3")]


def test_marcxml_input(rules, tmp_path):
    path = tmp_path / "in.xml"
    with open(path, "wb") as fh:
        w = XMLWriter(fh)
        w.write(make_record(rid="x1"))
        w.close(close_fh=False)
    res = run_cleaning(str(path), rules, out_dir=tmp_path / "out", log=quiet)
    assert [steps.rec_id(r) for r in read_all(res["mrc"])] == ["x1"]


def test_rerun_of_output_skips_everything(rules, tmp_path):
    src = write_mrc(tmp_path / "in.mrc", [make_record(("852", ["1", " "], ["9", "10.00"]))])
    first = run_cleaning(src, rules, out_dir=tmp_path / "1", log=quiet)
    second = run_cleaning(first["mrc"], rules, out_dir=tmp_path / "2", log=quiet)
    assert second["totals"]["skipped"] == 1
    with open(first["mrc"], "rb") as a, open(second["mrc"], "rb") as b:
        assert a.read() == b.read()


def test_report_counts_only_real_changes(rules, tmp_path):
    src = write_mrc(tmp_path / "in.mrc", [make_record()])
    rules["report"]["max_change_rows"] = 2
    res = run_cleaning(src, rules, out_dir=tmp_path / "out", log=quiet)
    n_changes = sum(r["action"] in ("ADDED", "DELETED", "MODIFIED") for r in res["changelog"])
    assert any(r["action"] == "DETECTED" for r in res["changelog"])
    html = Path(res["html"]).read_text(encoding="utf-8")
    assert f'<div class="n">{n_changes}</div><div class="l">Changes</div>' in html
    assert "Showing the first 2 of" in html
    assert os.path.getsize(res["csv"]) > 0
