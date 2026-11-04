"""The reading of Te Haeata's answers: pure, no network, no model.

Te Haeata's records (settlements, commitments) sit behind a login on 22
October 2026: every records address answers with the same page, "Please log
in", an email and password form and "Create new account". There is no
reader of records here, by design: the lane holds none (hard limit 6; its
position). This module only recognises the wall, so the watch can say the
day it falls.

  wall     the login page: Drupal's `user-login-form` and the words "Please log in"
  open     a page of the site that is not the wall (its about, copyright, terms and privacy pages; or a records
           page the day the wall falls)
"""
import re

PROFILE = "tehaeata-login-wall"
PROFILE_VERSION = 1


class NotTheShape(ValueError):
    """Not a page of Te Haeata."""


def recognise(body: bytes) -> str:
    page = (body or b"").decode("utf-8", "replace")
    if "| Te Haeata</title>" not in page:
        raise NotTheShape("not a Te Haeata page (no Te Haeata title)")
    if 'data-drupal-selector="user-login-form"' in page and re.search(r"Please log in", page):
        return "wall"
    return "open"
