"""Loading cleaning rules. Rules are plain dicts; each run gets its own copy."""
import copy
from importlib import resources

import yaml

__version__ = "9.0"


def load_rules(path=None):
    """Return a fresh rules dict from `path`, or the bundled rules.yaml."""
    if path:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    text = resources.files("marc_cleaner").joinpath("rules.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def with_options(rules, *, use_lookups=None, keep_655=None, adjust_price=None):
    """Copy of `rules` with the UI checkbox options applied. Never mutates `rules`."""
    r = copy.deepcopy(rules)
    if use_lookups is not None:
        r.setdefault("online_lookups", {})["enabled"] = bool(use_lookups)
    if keep_655 is not None:
        r.setdefault("subjects", {})["converted_655_keep_source"] = bool(keep_655)
    if adjust_price is not None:
        r.setdefault("prices", {})["adjust_852_9_price"] = bool(adjust_price)
    return r
