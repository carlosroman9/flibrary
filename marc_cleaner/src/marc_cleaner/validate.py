"""Post-clean checks. Warnings are logged; records are never changed here."""
from .steps import first_field


def validate_record(rec, ctx):
    warnings = []

    def warn(field, msg):
        warnings.append(msg)
        ctx.log(field, "WARNING", msg, detail="validation")

    f245 = first_field(rec, "245")
    if f245 is None:
        warn("245", "Missing 245 (no title)")

    f008 = first_field(rec, "008")
    if f008 is None or not f008.data:
        warn("008", "Missing 008 (no fixed-length data element)")
    elif len(f008.data) != 40:
        warn("008", f"008 should be 40 characters (found {len(f008.data)})")

    if not any(f.get_subfields("a") for f in rec.get_fields("020")):
        warn("020", "No ISBNs found after cleaning")

    for f in rec.get_fields("852"):
        if not f.get_subfields("h"):
            warn("852 $h", "852 missing $h (no call number)")

    # 245 first indicator 1 means a 1XX main entry exists; 0 is a legitimate title main entry.
    has_1xx = any(rec.get_fields(t) for t in ("100", "110", "111", "130"))
    if f245 is not None and f245.indicator1 == "1" and not has_1xx:
        warn("1XX", "245 indicator 1 is '1' but there is no main entry (100/110/111/130)")

    if not rec.get_fields("300"):
        warn("300", "Missing 300 (no physical description)")

    n_852 = len(rec.get_fields("852"))
    if n_852 > 1:
        warn("852", f"Multiple 852 fields ({n_852}) -- possible duplicate holdings")

    bad = sorted({f.tag for f in rec.get_fields() if not f.is_control_field()
                  and any("�" in s.value for s in f.subfields)})
    if bad:
        warn("encoding", f"Unreadable characters replaced with '�' in {', '.join(bad)}")

    return warnings
