"""greystar.co.nz — Greymouth Star, also the online home of the Hokitika
Guardian and West Coast Messenger (their domains redirect here). See
alliedwp for the shared WP REST discovery + tagDiv extraction."""
from __future__ import annotations

from . import alliedwp

SOURCE = "greystar.co.nz"
discover = alliedwp.make_discover("https://www.greystar.co.nz")
extract = alliedwp.extract
