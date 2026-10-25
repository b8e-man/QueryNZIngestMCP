#!/bin/bash
# Second staggered extractor — same script as beehive_extract.py, runs on the
# off-phase (*/5 vs the primary job's :02:48 phase) so the pair delivers ~2x
# throughput without both scanning the ready pool at the same moment.
exec python3 /opt/data/scripts/beehive_extract.py
