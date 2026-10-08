import pytest
from pymarc import Field, MARCWriter, Record, Subfield

from marc_cleaner import load_rules

F008 = "200101s2020    nyu    j      000 1 eng d"
assert len(F008) == 40


def make_record(*fields, rid="b1", title="A story", f008=F008):
    """Build a record. Each extra field is (tag, [ind1, ind2], [code, value, code, value, ...])."""
    r = Record()
    r.leader = "00000nam  2200000 i 4500"
    r.add_field(Field(tag="001", data=rid))
    if f008 is not None:
        r.add_field(Field(tag="008", data=f008))
    r.add_field(Field(tag="245", indicators=["0", "0"], subfields=[Subfield("a", title)]))
    r.add_field(Field(tag="300", indicators=[" ", " "], subfields=[Subfield("a", "32 p.")]))
    for tag, ind, flat in fields:
        subs = [Subfield(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]
        r.add_field(Field(tag=tag, indicators=ind, subfields=subs))
    return r


def write_mrc(path, records, raw_after=None):
    with open(path, "wb") as fh:
        w = MARCWriter(fh)
        for rec in records:
            w.write(rec)
        if raw_after:
            fh.write(raw_after)
        w.close(close_fh=False)
    return str(path)


@pytest.fixture
def rules():
    return load_rules()


def subfields(rec, tag, code):
    return [v for f in rec.get_fields(tag) for v in f.get_subfields(code)]
