#!/usr/bin/env bash
# Copy new export folders from the measurement PC into ./data/mppt_temp_irr.
# (Each folder is one export: the date in its name is the export day, and it holds
# everything recorded since the previous export.)
# One-way (PC -> laptop), only adds or updates files, never deletes anything.
set -e

rsync -az --partial --info=progress2 \
    --include='data_*/***' --include='all_*/***' --exclude='*' \
    outdoor-wsl:outdoor-data-monitoring/data/mppt_temp_irr/ \
    "$(dirname "$0")/../data/mppt_temp_irr/"
