"""ISBN parsing and the optional online lookups."""
import re

import requests
from stdnum import isbn as std_isbn

# A run of digits/hyphens/spaces long enough to hold an ISBN-10 or ISBN-13.
_CANDIDATE = re.compile(r"[0-9][0-9\- ]{8,16}[0-9Xx]")


def normalize_isbn(value):
    """Return the compact, valid ISBN found in `value`, or None.

    Handles qualifiers such as '0-439-02348-3 (hardcover)' or '9780439023481 :'.
    """
    if value is None:
        return None
    for m in _CANDIDATE.finditer(str(value)):
        try:
            c = std_isbn.compact(m.group(0))
            if std_isbn.is_valid(c):
                return c
        except Exception:
            continue
    return None


def counterpart(isbn):
    """ISBN-13 for an ISBN-10 and vice versa (979 ISBN-13s have no ISBN-10)."""
    try:
        if len(isbn) == 10:
            return std_isbn.to_isbn13(isbn)
        if len(isbn) == 13 and isbn.startswith("978"):
            return std_isbn.to_isbn10(isbn)
    except Exception:
        pass
    return None


def fetch_isbns_openlibrary(isbn, timeout=8):
    out = set()
    try:
        r = requests.get(
            f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&jscmd=data&format=json",
            timeout=timeout)
        if r.status_code == 200:
            ids = r.json().get(f"ISBN:{isbn}", {}).get("identifiers", {})
            for ident in ids.get("isbn_10", []) + ids.get("isbn_13", []):
                nv = normalize_isbn(ident)
                if nv:
                    out.add(nv)
    except Exception:
        pass
    return out


def fetch_isbns_googlebooks(isbn, timeout=8):
    out = set()
    try:
        r = requests.get(f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}",
                         timeout=timeout)
        if r.status_code == 200:
            for item in r.json().get("items", []):
                for ident in item.get("volumeInfo", {}).get("industryIdentifiers", []):
                    nv = normalize_isbn(ident.get("identifier", ""))
                    if nv:
                        out.add(nv)
    except Exception:
        pass
    return out


def fetch_isbns_online(isbn, timeout=8):
    return fetch_isbns_openlibrary(isbn, timeout) | fetch_isbns_googlebooks(isbn, timeout)
