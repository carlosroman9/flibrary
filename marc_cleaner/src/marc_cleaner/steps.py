"""Individual cleaning steps. Each takes (rec, ctx) and logs its changes via ctx.log.

The order these run in is defined once, in pipeline.STEPS.
"""
import math
import re
import unicodedata

from pymarc import Field, Subfield

from .isbn import counterpart, fetch_isbns_online, normalize_isbn
from .lookups import CATEGORIES


# ---------------------------------------------------------------- helpers

def first_field(rec, tag):
    fs = rec.get_fields(tag)
    return fs[0] if fs else None


def rec_id(rec):
    f001 = first_field(rec, "001")
    return f001.data if f001 is not None and f001.data else ""


def rec_title(rec):
    f245 = first_field(rec, "245")
    if f245 is None:
        return "(no 245)"
    return " ".join(f245.get_subfields("a", "b"))[:80]


def field_content_str(f):
    if f.is_control_field():
        return str(f.data or "")
    return " ".join(f"${s.code} {s.value}" for s in f.subfields)


def own_isbns(rec):
    """Normalized ISBNs from 020 $a, in record order, without duplicates."""
    out = []
    for f in rec.get_fields("020"):
        for v in f.get_subfields("a"):
            nv = normalize_isbn(v)
            if nv and nv not in out:
                out.append(nv)
    return out


def _replace_values(f, codes, fn):
    """Apply fn(old)->new to subfields with a code in `codes`; yield (code, old, new) per change."""
    changes = []
    for i, s in enumerate(f.subfields):
        if s.code in codes and isinstance(s.value, str):
            new = fn(s.value)
            if new != s.value:
                f.subfields[i] = Subfield(s.code, new)
                changes.append((s.code, s.value, new))
    return changes


# Matches 'fiction' but not 'nonfiction'.
_FICTION = re.compile(r"(?<![\w-])fiction\b", re.I)


# ---------------------------------------------------------------- Follett detection

def is_follett(rec, rules):
    det = rules.get("detection", {}).get("follett_markers", {})
    f003 = first_field(rec, "003")
    if f003 is not None and (f003.data or "").strip() in set(det.get("any_003_in", [])):
        return True
    for f in rec.get_fields("040"):
        if any(v in s for s in f.get_subfields("d") for v in det.get("any_040_d_in", [])):
            return True
    for f in rec.get_fields("940"):
        text = " ".join(s.value for s in f.subfields).lower()
        if any(v.lower() in text for v in det.get("any_940_contains", [])):
            return True
    return False


# ---------------------------------------------------------------- diacritics

ACCENT_MAP = {
    "acute": {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú", "y": "ý",
              "A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú", "Y": "Ý"},
    "grave": {"a": "à", "e": "è", "i": "ì", "o": "ò", "u": "ù",
              "A": "À", "E": "È", "I": "Ì", "O": "Ò", "U": "Ù"},
    "circumflex": {"a": "â", "e": "ê", "i": "î", "o": "ô", "u": "û",
                   "A": "Â", "E": "Ê", "I": "Î", "O": "Ô", "U": "Û"},
    "tilde": {"a": "ã", "o": "õ", "n": "ñ", "A": "Ã", "O": "Õ", "N": "Ñ"},
    "uml": {"a": "ä", "e": "ë", "i": "ï", "o": "ö", "u": "ü", "y": "ÿ",
            "A": "Ä", "E": "Ë", "I": "Ï", "O": "Ö", "U": "Ü", "Y": "Ÿ"},
    "cedilla": {"c": "ç", "C": "Ç"},
}
_ACCENTS = "acute|grave|tilde|uml|circumflex|cedilla"


def fix_follett_diacritics_text(text):
    def prev(m):
        return ACCENT_MAP.get(m.group(2).lower(), {}).get(m.group(1), m.group(1))

    def nxt(m):
        return ACCENT_MAP.get(m.group(1).lower(), {}).get(m.group(2), m.group(2))

    text = re.sub(r"([A-Za-z])\{(" + _ACCENTS + r")\}", prev, text)
    text = re.sub(r"\{(" + _ACCENTS + r")\}([A-Za-z])", nxt, text)
    text = re.sub(r"\{(" + _ACCENTS + r")\}", "", text)
    return unicodedata.normalize("NFC", text)


def fix_diacritics(rec, ctx):
    if not ctx.rules.get("diacritics", {}).get("fix_follett_brace_codes", True):
        return
    for f in rec.get_fields():
        if f.is_control_field():
            if isinstance(f.data, str):
                new = fix_follett_diacritics_text(f.data)
                if new != f.data:
                    ctx.log(f.tag, "MODIFIED", f.data, new, "diacritic_fix")
                    f.data = new
        elif f.tag.isdigit() and 100 <= int(f.tag) < 900:
            all_codes = {s.code for s in f.subfields}
            for code, old, new in _replace_values(f, all_codes, fix_follett_diacritics_text):
                ctx.log(f"{f.tag} ${code}", "MODIFIED", old, new, "diacritic_fix")


# ---------------------------------------------------------------- field-level cleanup

def delete_fields(rec, ctx):
    for tag in ctx.rules.get("initial_tasks", {}).get("delete_fields", []):
        for f in rec.get_fields(tag):
            ctx.log(tag, "DELETED", field_content_str(f), detail="rule_delete")
            rec.remove_field(f)


def normalize_082(rec, ctx):
    for f in rec.get_fields("082"):
        for _, old, new in _replace_values(f, {"2"}, lambda v: v.split("/")[0].strip()):
            ctx.log("082 $2", "MODIFIED", old, new, "082_edition_normalize")


_245C_PREFIX = re.compile(r"^(?:author|written by|by|illustrated by|created by)\s+", re.I)


def clean_245c(rec, ctx):
    for f in rec.get_fields("245"):
        for _, old, new in _replace_values(f, {"c"}, lambda v: _245C_PREFIX.sub("", v).strip()):
            ctx.log("245 $c", "MODIFIED", old, new, "245c_prefix_strip")


# ---------------------------------------------------------------- ISBNs

def isbns(rec, ctx):
    """Add the missing ISBN-10/13 counterpart and any extra ISBNs.

    - Counterparts and extra_isbns.csv ISBNs belong to this item -> 020 $a.
    - 776 and online-lookup ISBNs may be other editions -> 020 $z (configurable).
    """
    rules = ctx.rules
    own = own_isbns(rec)
    present = set(own)
    for f in rec.get_fields("020"):
        for v in f.get_subfields("z"):
            nv = normalize_isbn(v)
            if nv:
                present.add(nv)

    add_a, add_rel = [], []  # (isbn, detail)

    def queue(target, isbn, detail):
        if isbn and isbn not in present:
            present.add(isbn)
            target.append((isbn, detail))

    if rules.get("initial_tasks", {}).get("ensure_isbn10_and_isbn13", True):
        for x in own:
            y = counterpart(x)
            queue(add_a, y, "isbn13_from_10" if len(x) == 10 else "isbn10_from_13")

    if ctx.maps.extra_isbns is not None:
        for row in ctx.maps.extra_isbns.find(ctx.rid, own):
            for col in ("isbn10", "isbn13", "extra_isbn"):
                queue(add_a, normalize_isbn(row.get(col)), "extra_isbns_csv")

    for f in rec.get_fields("776"):
        for v in f.get_subfields("z", "a"):
            queue(add_rel, normalize_isbn(v), "related_776")

    lookups = rules.get("online_lookups", {})
    if lookups.get("enabled"):
        for seed in own:
            for nv in sorted(fetch_isbns_online(seed, lookups.get("timeout_seconds", 8))):
                queue(add_rel, nv, "online_lookup")

    rel_code = rules.get("extra_isbns", {}).get("related_isbn_subfield", "z")
    for isbn, detail in add_a:
        ctx.log("020 $a", "ADDED", new_value=isbn, detail=detail)
        rec.add_field(Field(tag="020", indicators=[" ", " "], subfields=[Subfield("a", isbn)]))
    for isbn, detail in add_rel:
        ctx.log(f"020 ${rel_code}", "ADDED", new_value=isbn, detail=detail)
        rec.add_field(Field(tag="020", indicators=[" ", " "], subfields=[Subfield(rel_code, isbn)]))


# ---------------------------------------------------------------- subjects

def lc_to_sears(rec, ctx):
    subj = ctx.rules.get("subjects", {})
    table = ctx.maps.lc_to_sears
    if not subj.get("use_lc_to_sears_csv", True) or not table:
        return
    for f in rec.get_fields("650"):
        for _, old, new in _replace_values(f, {"a"}, lambda v: table.get(v.strip().lower(), v)):
            ctx.log("650 $a", "MODIFIED", old, new, "lc_to_sears")


_JUV_FICTION = re.compile(r"\s*Juvenile fiction\.?\s*", re.I)


def juvenile_fiction(rec, ctx):
    if not ctx.rules.get("subjects", {}).get("juvenile_fiction_to_fiction", True):
        return
    def fn(v):
        return "Fiction" if _JUV_FICTION.fullmatch(v) else v

    for f in rec.get_fields("650"):
        for _, old, new in _replace_values(f, {"v"}, fn):
            ctx.log("650 $v", "MODIFIED", old, new, "juv_to_fiction")


def genre_655_to_650(rec, ctx):
    """Copy each 655 $a into a 650 with valid indicators.

    655 _0 (LCSH)       -> 650 _0
    655 with any $2      -> 650 _7 $2 <subjects.genre_650_source>
    anything else        -> 650 _4 (local, no $2)
    """
    subj = ctx.rules.get("subjects", {})
    if not subj.get("convert_655_to_650", True):
        return
    keep = subj.get("converted_655_keep_source", True)
    source = subj.get("genre_650_source", "sears")
    for f in rec.get_fields("655"):
        a_vals = f.get_subfields("a")
        if not a_vals:
            continue
        if f.indicator2 == "0":
            new = Field(tag="650", indicators=[" ", "0"], subfields=[Subfield("a", a_vals[0])])
        elif f.get_subfields("2"):
            new = Field(tag="650", indicators=[" ", "7"],
                        subfields=[Subfield("a", a_vals[0]), Subfield("2", source)])
        else:
            new = Field(tag="650", indicators=[" ", "4"], subfields=[Subfield("a", a_vals[0])])
        rec.add_field(new)
        ctx.log("650", "ADDED", new_value=field_content_str(new), detail="655_to_650")
        if not keep:
            ctx.log("655", "DELETED", field_content_str(f), detail="655_converted")
            rec.remove_field(f)


def _normalize_heading(text):
    t = (text or "").strip().lower()
    t = re.sub(r"[.,:;/]+$", "", t)
    return re.sub(r"\s+", " ", t)


def dedup_subjects(rec, ctx):
    for tag in ("650", "651"):
        seen = set()
        for f in rec.get_fields(tag):
            key = "|".join(f"{s.code}:{_normalize_heading(s.value)}"
                           for s in f.subfields if s.code in "abxyzv")
            if key in seen:
                ctx.log(tag, "DELETED", field_content_str(f), detail="duplicate_subject")
                rec.remove_field(f)
            else:
                seen.add(key)


# ---------------------------------------------------------------- category + holdings

def detect_category(rec, rules, maps, rid=""):
    """Return (category, reason)."""
    if maps.cat_overrides is not None:
        for row in maps.cat_overrides.find(rid, own_isbns(rec)):
            cat = (row.get("category") or "").strip().lower()
            if cat in CATEGORIES:
                return cat, "category_overrides.csv"

    def joined(f, *codes):
        return " ".join(f.get_subfields(*codes))

    det = rules.get("categories", {}).get("detection", {})
    gd = det.get("graphic_novels", {})
    if gd:
        for f in rec.get_fields("655"):
            if any(t.lower() in joined(f, "a").lower() for t in gd.get("any_655a_contains", [])):
                return "graphic_novels", "655 $a contains graphic novel"
        for f in rec.get_fields("650"):
            if any(t.lower() in joined(f, "a").lower() for t in gd.get("any_650a_contains", [])):
                return "graphic_novels", "650 $a contains graphic novels"
        for f in rec.get_fields("082"):
            if any(joined(f, "a").startswith(p) for p in gd.get("any_082a_prefix", [])):
                return "graphic_novels", "082 $a prefix 741.5"
        for f in rec.get_fields("852"):
            if any(s.startswith(p) for s in f.get_subfields("h") for p in gd.get("any_852h_prefix", [])):
                return "graphic_novels", "852 $h prefix GN/741.5"
    ed = det.get("everyone", {})
    if ed:
        for f in rec.get_fields("650"):
            for term in ed.get("any_650a_contains", []):
                if term.lower() in joined(f, "a").lower():
                    return "everyone", f"650 $a contains {term}"
        for f in rec.get_fields("852"):
            if any(s == e for s in f.get_subfields("h") for e in ed.get("any_852h_equals", [])):
                return "everyone", "852 $h equals E"
    fd = det.get("fiction", {})
    if fd.get("check_082_for_fic", True):
        for f in rec.get_fields("082"):
            if any("Fic" in s for s in f.get_subfields("a", "b", "q", "2")):
                return "fiction", "082 contains Fic"
    if fd.get("check_650v_for_Fiction", True):
        for f in rec.get_fields("650"):
            if any(_FICTION.search(s) for s in f.get_subfields("v")):
                return "fiction", "650 $v contains Fiction"
    if fd.get("check_655_contains_fiction", True):
        for f in rec.get_fields("655"):
            if _FICTION.search(joined(f, "a")):
                return "fiction", "655 $a contains fiction"
    return "nonfiction", "default (no fiction/GN/everyone markers)"


def holdings(rec, ctx):
    rules = ctx.rules
    fields = rec.get_fields("852")
    if not fields:
        f852 = Field(tag="852", indicators=["1", " "], subfields=[])
        rec.add_field(f852)
        fields = [f852]
        ctx.log("852", "ADDED", detail="new_holdings_field")

    category, reason = detect_category(rec, rules, ctx.maps, ctx.rid)
    ctx.log("category", "DETECTED", new_value=category, detail=reason)

    init = rules.get("initial_tasks", {})
    catmap = init.get("category_holds", {})
    catvals = catmap.get(category, catmap.get("nonfiction", {}))
    sub3, subk = catvals.get("sub3"), catvals.get("subk")
    q_default = init.get("holdings_defaults", {}).get("q_default", "hdbk")

    for f in fields:
        codes = {s.code for s in f.subfields}
        if sub3 and "3" not in codes:
            ctx.log("852 $3", "ADDED", new_value=sub3, detail="category_hold")
            f.add_subfield("3", sub3)
        h_vals = f.get_subfields("h")
        h_val = h_vals[0].strip() if h_vals else ""
        if re.match(r"^\d", h_val):
            is_bio = h_val.startswith("921")
            k, k_detail = ("BIO", "dewey_bio_921") if is_bio else ("NF", "dewey_nonfiction")
        else:
            k, k_detail = subk, "category_hold"
        if k and "k" not in codes:
            ctx.log("852 $k", "ADDED", new_value=k, detail=k_detail)
            f.add_subfield("k", k)
        if "741.5" in h_val and "c" not in codes:
            ctx.log("852 $c", "ADDED", new_value="Graphic Novel", detail="gn_location")
            f.add_subfield("c", "Graphic Novel")
        if q_default and "q" not in codes:
            ctx.log("852 $q", "ADDED", new_value=q_default, detail="binding_default")
            f.add_subfield("q", q_default)


def strip_852_subfields(rec, ctx):
    for f in rec.get_fields("852"):
        kept = []
        for s in f.subfields:
            if s.code in ("5", "8", "x"):
                ctx.log(f"852 ${s.code}", "DELETED", s.value, detail=f"strip_852_{s.code}")
            else:
                kept.append(s)
        f.subfields = kept


# ---------------------------------------------------------------- reading levels + prices

def reading_levels(rec, ctx):
    rl = ctx.rules.get("reading_levels", {})
    if not rl.get("add_521_for_non_follett", True) or ctx.follett:
        return
    lookup = ctx.maps.reading_levels
    if lookup is None:
        return
    rows = lookup.find(ctx.rid, own_isbns(rec))
    if not rows:
        return
    r0 = rows[0]

    def add(ind2, subs, value, detail):
        ctx.log("521", "ADDED", new_value=value, detail=detail)
        rec.add_field(Field(tag="521", indicators=[" ", ind2],
                                    subfields=[Subfield(c, v) for c, v in subs]))

    if r0.get("fp_level"):
        fp = rl["fountas_pinnell"]
        b = f"{fp['sub_b']}: {r0['fp_level']}"
        add(" ", [("a", fp["pattern"]), ("b", b)], f"{fp['pattern']} {b}", "reading_level_fp")
    if r0.get("reading_level"):
        add(rl["reading_level"]["indicator2"], [("a", r0["reading_level"])],
            r0["reading_level"], "reading_level_rl")
    if r0.get("interest_level"):
        il = rl["interest_level"]
        add(il["indicator2"], [("a", r0["interest_level"]), ("b", il["sub_b"])],
            r0["interest_level"], "reading_level_il")
    if r0.get("lexile"):
        lx = rl["lexile"]
        add(lx["indicator2"], [("a", r0["lexile"]), ("b", lx["sub_b"])], r0["lexile"],
            "reading_level_lexile")


def prices(rec, ctx):
    pr = ctx.rules.get("prices", {})
    strip_usd = pr.get("strip_usd_in_852_3_and_9", True)
    adjust = pr.get("adjust_852_9_price", True)

    def fix(code):
        def fn(val):
            new = re.sub(r"\s*usd\s*", "", val, flags=re.I) if strip_usd else val
            if code == "9" and adjust:
                m = re.search(r"([0-9]+(?:\.[0-9]+)?)", new)
                if m:
                    base = float(m.group(1))
                    if pr.get("rounding_mode", "ceil") == "ceil":
                        base = math.ceil(base)
                    adj = base + float(pr.get("processing_add", 3))
                    new = f"{adj:.2f}" if pr.get("format", "2dp") == "2dp" else str(int(adj))
            return new
        return fn

    for f in rec.get_fields("852"):
        for code in ("3", "9"):
            for c, old, new in _replace_values(f, {code}, fix(code)):
                ctx.log(f"852 ${c}", "MODIFIED", old, new, "price_adjust")


# ---------------------------------------------------------------- finishing

def delete_empty_fields(rec, ctx):
    for f in list(rec.get_fields()):
        empty = (not f.data) if f.is_control_field() else (not f.subfields)
        if empty:
            ctx.log(f.tag, "DELETED", "(empty)", detail="empty_field")
            rec.remove_field(f)


def has_stamp(rec, rules):
    st = rules.get("stamp", {})
    if not st.get("enabled", True):
        return False
    return any(st.get("text") in v for f in rec.get_fields(st.get("tag", "999"))
               for v in f.get_subfields(st.get("subfield", "a")))


def add_stamp(rec, ctx):
    st = ctx.rules.get("stamp", {})
    if not st.get("enabled", True):
        return
    from .config import __version__
    text = f"{st.get('text')} v{__version__}"
    rec.add_field(Field(tag=st.get("tag", "999"), indicators=[" ", " "],
                                subfields=[Subfield(st.get("subfield", "a"), text)]))


def reorder_fields(rec, ctx):
    rec.fields = sorted(rec.fields, key=lambda f: f.tag)


def set_utf8(rec, ctx):
    rec.force_utf8 = True
    ldr = str(rec.leader).ljust(24)[:24]
    rec.leader = ldr[:9] + "a" + ldr[10:]
