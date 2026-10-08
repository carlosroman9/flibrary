import os
from pathlib import Path

import pytest
from conftest import make_record, write_mrc

pytest.importorskip("gradio")
from marc_cleaner import ui  # noqa: E402


def test_each_run_gets_its_own_folder_and_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setattr(ui, "LAST_RUN_FILE", str(tmp_path / "work" / "last_run.json"))
    src = write_mrc(tmp_path / "in.mrc", [make_record(("852", ["1", " "], ["9", "10.00"]))])

    a = ui.ui_clean([src], None, False, True, True)
    b = ui.ui_clean([src], None, False, True, False)
    assert os.path.dirname(a[0]) != os.path.dirname(b[0])
    assert a[3] is None  # no rejected file
    assert "13.00" in Path(a[1]).read_text(encoding="utf-8-sig")
    assert "13.00" not in Path(b[1]).read_text(encoding="utf-8-sig")
    assert os.path.exists(ui.LAST_RUN_FILE)


def test_build_demo():
    assert ui.build_demo() is not None
