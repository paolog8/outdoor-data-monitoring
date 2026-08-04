from datetime import date

import pandas as pd
import streamlit as st
from db import (
    cells_exist,
    current_sensors_for_cell,
    current_slot_for_cell,
    delete_connection_event,
    ensure_cell,
    insert_events,
    insert_sensor_association_events,
    link_cell_experiment,
    load_cell_by_id,
    load_cell_types,
    load_cells,
    load_experiments,
    load_groups,
    load_modes,
    load_polarities,
    load_scientists,
    load_sensors,
    load_slots,
    load_trackers,
    parse_board_channel,
    recent_connection_events,
    to_timestamptz,
    tracker_status_snapshot,
    update_cell_metadata,
    upsert_experiment,
    upsert_scientist,
)

SETUP_COLUMNS = [
    "cell_name",
    "connect_date",
    "board",
    "ch",
    "mode",
    "polarity",
    "temp_sensor",
    "irradiance_sensor",
    "cell_type",
    "area_cm2",
    "initial_pce",
    "structure",
    "owner",
    "producer",
    "group",
    "px",
    "experiment",
    "disconnect_date",
]


st.title("Cell Events")


def _default_mode():
    modes = load_modes()
    if not modes:
        return None, ""
    return modes[0][0], modes[0][1]


def _ensure_state():
    if "setup_rows" not in st.session_state:
        st.session_state.setup_rows = []
    if "setup_preset_sensor_ids" not in st.session_state:
        st.session_state.setup_preset_sensor_ids = []
    if "setup_preset_sensor_display" not in st.session_state:
        st.session_state.setup_preset_sensor_display = []
    if "teardown" not in st.session_state:
        st.session_state.teardown = []


def _batch_names(base_name, suffixes_raw):
    base_name = base_name.strip()
    if not base_name:
        return []
    suffixes = [suffix.strip() for suffix in suffixes_raw.split(",") if suffix.strip()]
    if not suffixes:
        return [base_name]
    return [f"{base_name}{suffix}" for suffix in suffixes]


def _add_setup_rows(names):
    """Seeds new grid rows. Cells that already exist in the registry get their
    current metadata (cell type, area, owner, ...) pre-filled so an untouched
    row round-trips the same values on submit instead of clobbering them with
    blanks; brand-new cells start with blank metadata."""
    cell_id_by_name = {name: cell_id for cell_id, name in load_cells()}
    existing_names = cells_exist(names)
    scientist_label_by_id = {v: k for k, v in _scientist_options().items()}
    group_label_by_id = {v: k for k, v in _group_options().items()}
    cell_type_label_by_id = {v: k for k, v in _cell_type_options().items()}
    _, default_mode_code = _default_mode()

    seen = {row["cell_name"] for row in st.session_state.setup_rows}
    for raw_name in names:
        cell_name = raw_name.strip()
        if not cell_name or cell_name in seen:
            continue
        row = {
            "cell_name": cell_name,
            "connect_date": None,
            "board": None,
            "ch": None,
            "mode": default_mode_code,
            "polarity": None,
            "temp_sensor": None,
            "irradiance_sensor": None,
            "cell_type": None,
            "area_cm2": None,
            "initial_pce": None,
            "structure": None,
            "owner": None,
            "producer": None,
            "group": None,
            "px": None,
            "experiment": None,
            "disconnect_date": None,
        }
        if cell_name in existing_names:
            cell_data = load_cell_by_id(cell_id_by_name[cell_name])
            row.update(
                cell_type=cell_type_label_by_id.get(cell_data["cell_type_id"]),
                area_cm2=cell_data["area_cm2"],
                initial_pce=cell_data["initial_pce"],
                structure=cell_data["structure"],
                owner=scientist_label_by_id.get(cell_data["owner_id"]),
                producer=scientist_label_by_id.get(cell_data["manufacturer_id"]),
                group=group_label_by_id.get(cell_data["group_id"]),
                px=cell_data["position_in_group"],
            )
        st.session_state.setup_rows.append(row)
        seen.add(cell_name)


def _add_teardown_rows(names):
    seen = {row["cell_name"] for row in st.session_state.teardown}
    for raw_name in names:
        cell_name = raw_name.strip()
        if not cell_name or cell_name in seen:
            continue
        st.session_state.teardown.append(
            {
                "cell_name": cell_name,
                "slot_id": None,
                "active_sensors": [],
                "sensors_to_dissociate": [],
            }
        )
        seen.add(cell_name)


def _scientist_options():
    options = {"(none)": None}
    for scientist_id, name, affiliation in load_scientists():
        label = name if not affiliation else f"{name} ({affiliation})"
        options[label] = scientist_id
    return options


def _group_options():
    options = {"(standalone)": None}
    for group_id, name, group_code in load_groups():
        options[f"{name} [{group_code}]"] = group_id
    return options


def _experiment_options():
    options = {"(none)": None}
    for experiment_id, name in load_experiments():
        options[name] = experiment_id
    return options


def _cell_type_options():
    options = {"(none)": None}
    for type_id, code in load_cell_types():
        options[code] = type_id
    return options


def _polarity_options():
    options = {"(none)": None}
    for polarity_id, code in load_polarities():
        options[code] = polarity_id
    return options


def _clear_and_rerun():
    st.cache_data.clear()
    st.rerun()


def _sync_setup_rows_from_editor():
    """Folds the live setup_editor widget state (edits/adds/deletes made in
    the grid but not yet reflected in setup_rows) back into setup_rows.
    Needed before any rerun triggered from within the Setup tab (e.g.
    registering a new scientist/experiment) that changes a SelectboxColumn's
    options — that changes the data_editor's widget signature, which makes
    Streamlit drop its in-progress edit state and re-seed from setup_rows,
    silently wiping unsaved grid changes unless we capture them first."""
    editor_state = st.session_state.get("setup_editor")
    if not editor_state:
        return
    date_columns = {"connect_date", "disconnect_date"}
    df = pd.DataFrame(st.session_state.setup_rows, columns=SETUP_COLUMNS)
    for row_index, changes in editor_state.get("edited_rows", {}).items():
        for col, value in changes.items():
            if col in date_columns and isinstance(value, str):
                try:
                    value = _cell_date(value)
                except (TypeError, ValueError):
                    pass
            df.at[int(row_index), col] = value
    deleted_rows = editor_state.get("deleted_rows")
    if deleted_rows:
        df = df.drop(index=deleted_rows)
    added_rows = editor_state.get("added_rows")
    if added_rows:
        for added_row in added_rows:
            for col in date_columns:
                value = added_row.get(col)
                if isinstance(value, str):
                    try:
                        added_row[col] = _cell_date(value)
                    except (TypeError, ValueError):
                        pass
        added_df = pd.DataFrame(added_rows, columns=SETUP_COLUMNS)
        df = pd.concat([df, added_df], ignore_index=True)
    else:
        df = df.reset_index(drop=True)
    st.session_state.setup_rows = df.to_dict("records")


def _render_date_picker(prefix):
    def _set_today():
        st.session_state[f"{prefix}_event_date"] = date.today()

    col_date, col_btn = st.columns([2, 1])
    with col_date:
        event_date = st.date_input(
            "Event date",
            value=None,
            key=f"{prefix}_event_date",
        )
    with col_btn:
        st.write("")
        st.button("Set to today", key=f"{prefix}_set_today", on_click=_set_today)
    if event_date is None:
        st.markdown(
            '<p style="color:#ff4b4b; font-size:0.85em; margin-top:-0.5rem">⚠ Date is required</p>',
            unsafe_allow_html=True,
        )
    return event_date


def _render_batch_builder(existing_cells, add_callback, prefix):
    existing_names = {name for _, name in existing_cells}

    cell_name = st.text_input(
        "Cell / batch name",
        placeholder="e.g. SUB003_p — type alone for a single cell, add suffixes below for a batch",
        key=f"{prefix}_cell_name",
    )
    col_sfx, col_btn = st.columns([3, 1])
    with col_sfx:
        suffixes = st.text_input(
            "Suffixes (comma-separated, optional)",
            placeholder="A,B,C,D — leave empty for a single cell",
            key=f"{prefix}_suffixes",
        )
    with col_btn:
        st.write("")
        if st.button(
            "Add cell(s) to list →", key=f"{prefix}_add", use_container_width=True
        ):
            add_callback(_batch_names(cell_name, suffixes))

    names = _batch_names(cell_name, suffixes) if cell_name.strip() else []
    has_suffixes = bool(suffixes.strip())
    if names:
        lines = []
        for name in names:
            if name in existing_names:
                lines.append(
                    f'<span style="color:#ffa500">⚠ {name} — already in registry</span>'
                )
            else:
                lines.append(f'<span style="opacity:0.65">+ {name}</span>')
        st.markdown("<br>".join(lines), unsafe_allow_html=True)
        if has_suffixes and not cell_name.strip().endswith("_px"):
            st.markdown(
                '<p style="color:#f0a500; font-size:0.85em; margin-top:0.25rem">'
                "💡 Pixel batches should use a <code>_px</code> base name — e.g. <code>SUB003_px</code>"
                "</p>",
                unsafe_allow_html=True,
            )


def _render_cell_picker(existing_cells, add_callback, prefix):
    already_added = {row["cell_name"] for row in st.session_state.get(prefix, [])}
    available = [name for _, name in existing_cells if name not in already_added]

    col_sel, col_btn = st.columns([4, 1])
    with col_sel:
        selected = st.multiselect(
            "Search and select cells",
            available,
            key=f"{prefix}_picker",
            placeholder="Type to search...",
        )
    with col_btn:
        st.write("")
        if st.button(
            "Add to list →",
            key=f"{prefix}_picker_add",
            use_container_width=True,
            disabled=not selected,
        ):
            add_callback(selected)
            del st.session_state[f"{prefix}_picker"]
            st.rerun()


def _is_blank(value):
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _cell_str(value):
    return "" if _is_blank(value) else str(value).strip()


def _cell_date(value):
    """Normalizes a data_editor date cell to a datetime.date. Values entered
    via the date picker come back as datetime/Timestamp objects, but pasted
    values can come back as plain strings — parse those explicitly instead
    of passing them through, or downstream code blows up on .year access."""
    if _is_blank(value):
        return None
    if isinstance(value, str):
        return pd.to_datetime(value).date()
    return value.date() if hasattr(value, "date") else value


def _cell_num(value):
    return None if _is_blank(value) else float(value)


def _row_is_empty(row):
    return all(_is_blank(row[col]) for col in SETUP_COLUMNS)


def _resolve_setup_rows(
    edited_df,
    use_board_channel,
    slot_by_board_channel,
    slot_id_by_code,
    mode_id_by_code,
    polarity_options,
    cell_type_options,
    scientist_options,
    group_options,
    experiment_options,
    temp_sensor_id_by_label,
    irradiance_sensor_id_by_label,
    preset_sensor_ids,
):
    """Validates and resolves the grid into DB-ready rows. Returns
    (errors, resolved_rows, preview_rows) — errors is a flat list of
    blocking problems, resolved_rows holds only error-free rows ready to
    write, preview_rows is a per-row summary (name, new/existing, status)
    for display regardless of whether that row had errors."""
    errors = []
    resolved_rows = []
    preview_rows = []
    names = []

    non_blank_rows = [row for _, row in edited_df.iterrows() if not _row_is_empty(row)]
    candidate_names = [
        _cell_str(row["cell_name"])
        for row in non_blank_rows
        if _cell_str(row["cell_name"])
    ]
    existing_names = cells_exist(candidate_names)

    for row in non_blank_rows:
        row_errors = []
        cell_name = _cell_str(row["cell_name"])
        if not cell_name:
            errors.append("One or more rows have an empty cell name.")
            continue
        names.append(cell_name)
        is_new = cell_name not in existing_names

        try:
            connect_date = _cell_date(row["connect_date"])
        except (TypeError, ValueError):
            row_errors.append("connect date is not a valid date")
            connect_date = None
        else:
            if connect_date is None:
                row_errors.append("connect date is required")

        try:
            disconnect_date = _cell_date(row["disconnect_date"])
        except (TypeError, ValueError):
            row_errors.append("disconnect date is not a valid date")
            disconnect_date = None

        if (
            connect_date is not None
            and disconnect_date is not None
            and disconnect_date < connect_date
        ):
            row_errors.append("disconnect date must be on or after the connect date")

        board_value = _cell_str(row["board"])
        slot_id = None
        if use_board_channel:
            ch_value = _cell_str(row["ch"])
            if bool(board_value) != bool(ch_value):
                row_errors.append("Board and CH must both be set, or both left blank")
            elif board_value and ch_value:
                try:
                    slot_id = slot_by_board_channel.get(
                        (int(board_value), int(ch_value))
                    )
                except ValueError:
                    slot_id = None
                if slot_id is None:
                    row_errors.append(
                        f"no slot for board {board_value} / ch {ch_value}"
                    )
        elif board_value:
            slot_id = slot_id_by_code.get(board_value)
            if slot_id is None:
                row_errors.append(f"unknown slot '{board_value}'")

        temp_sensor_label = _cell_str(row["temp_sensor"])
        temp_sensor_id = (
            temp_sensor_id_by_label.get(temp_sensor_label)
            if temp_sensor_label
            else None
        )
        irradiance_sensor_label = _cell_str(row["irradiance_sensor"])
        irradiance_sensor_id = (
            irradiance_sensor_id_by_label.get(irradiance_sensor_label)
            if irradiance_sensor_label
            else None
        )
        row_sensor_ids = set(preset_sensor_ids)
        if temp_sensor_id is not None:
            row_sensor_ids.add(temp_sensor_id)
        if irradiance_sensor_id is not None:
            row_sensor_ids.add(irradiance_sensor_id)

        if slot_id is None and not row_sensor_ids:
            row_errors.append("choose a slot, at least one sensor, or both")

        mode_code = _cell_str(row["mode"])
        mode_id = mode_id_by_code.get(mode_code) if mode_code else None
        if slot_id is not None and mode_id is None:
            row_errors.append("mode is required for a slot assignment")

        polarity_code = _cell_str(row["polarity"])
        polarity_id = polarity_options.get(polarity_code) if polarity_code else None

        cell_type_code = _cell_str(row["cell_type"])
        cell_type_id = cell_type_options.get(cell_type_code) if cell_type_code else None

        owner_label = _cell_str(row["owner"])
        owner_id = scientist_options.get(owner_label) if owner_label else None

        producer_label = _cell_str(row["producer"])
        manufacturer_id = (
            scientist_options.get(producer_label) if producer_label else None
        )

        group_label = _cell_str(row["group"])
        group_id = group_options.get(group_label) if group_label else None

        experiment_label = _cell_str(row["experiment"])
        experiment_id = (
            experiment_options.get(experiment_label) if experiment_label else None
        )

        try:
            area_cm2 = _cell_num(row["area_cm2"])
        except (TypeError, ValueError):
            row_errors.append("area must be a number")
            area_cm2 = None
        try:
            initial_pce = _cell_num(row["initial_pce"])
        except (TypeError, ValueError):
            row_errors.append("initial PCE must be a number")
            initial_pce = None

        preview_rows.append(
            {
                "cell_name": cell_name,
                "action": "new cell" if is_new else "existing cell (update)",
                "connect_date": connect_date,
                "disconnect_date": disconnect_date,
                "status": "ready" if not row_errors else "; ".join(row_errors),
            }
        )

        if row_errors:
            errors.extend(f"{cell_name}: {problem}" for problem in row_errors)
            continue

        resolved_rows.append(
            {
                "cell_name": cell_name,
                "connect_date": connect_date,
                "disconnect_date": disconnect_date,
                "slot_id": slot_id,
                "mode_id": mode_id,
                "polarity_id": polarity_id,
                "sensor_ids": row_sensor_ids,
                "cell_type_id": cell_type_id,
                "area_cm2": area_cm2,
                "initial_pce": initial_pce,
                "structure": _cell_str(row["structure"]) or None,
                "owner_id": owner_id,
                "manufacturer_id": manufacturer_id,
                "group_id": group_id,
                "position_in_group": _cell_str(row["px"]) or None,
                "experiment_id": experiment_id,
            }
        )

    if len(names) != len(set(names)):
        errors.append("Setup rows contain duplicate cell names.")

    return errors, resolved_rows, preview_rows


def _render_setup_tab():
    existing_cells = load_cells()
    existing_names = {name for _, name in existing_cells}
    sensors = load_sensors()
    sensor_labels = []
    sensor_id_by_label = {}
    temp_sensor_labels = []
    temp_sensor_id_by_label = {}
    irradiance_sensor_labels = []
    irradiance_sensor_id_by_label = {}
    for sensor_id, sensor_type, name, serial_number, location in sensors:
        detail_parts = [part for part in [serial_number, location] if part]
        detail_suffix = f" ({' | '.join(detail_parts)})" if detail_parts else ""
        label = f"[{sensor_type}] {name or f'Sensor {sensor_id}'}{detail_suffix}"
        sensor_labels.append(label)
        sensor_id_by_label[label] = sensor_id
        if sensor_type == "temperature":
            temp_label = f"{name or f'Sensor {sensor_id}'}{detail_suffix}"
            temp_sensor_labels.append(temp_label)
            temp_sensor_id_by_label[temp_label] = sensor_id
        elif sensor_type == "irradiance":
            irradiance_label = f"{name or f'Sensor {sensor_id}'}{detail_suffix}"
            irradiance_sensor_labels.append(irradiance_label)
            irradiance_sensor_id_by_label[irradiance_label] = sensor_id

    scientist_options = _scientist_options()
    group_options = _group_options()
    experiment_options = _experiment_options()
    cell_type_options = _cell_type_options()
    polarity_options = _polarity_options()
    polarity_names = list(polarity_options.keys())

    _render_batch_builder(existing_cells, _add_setup_rows, "setup")

    col_new_scientist, col_new_experiment = st.columns(2)
    with col_new_scientist, st.expander("+ Register new scientist"):
        new_sci_name = st.text_input("Name", key="setup_new_scientist_name")
        new_sci_affiliation = st.text_input(
            "Affiliation", key="setup_new_scientist_affiliation"
        )
        if st.button("Register scientist", key="setup_register_scientist"):
            if not new_sci_name.strip():
                st.error("Name is required.")
            else:
                _sync_setup_rows_from_editor()
                upsert_scientist(new_sci_name, new_sci_affiliation)
                _clear_and_rerun()
    with col_new_experiment, st.expander("+ Register new experiment"):
        new_experiment_name = st.text_input("Name", key="setup_new_experiment_name")
        if st.button("Register experiment", key="setup_register_experiment"):
            if not new_experiment_name.strip():
                st.error("Name is required.")
            else:
                _sync_setup_rows_from_editor()
                upsert_experiment(new_experiment_name)
                _clear_and_rerun()

    trackers = load_trackers()
    tracker_names = [tracker_name for _, tracker_name in trackers]
    selected_tracker_id = None
    slot_options = []
    slot_codes = []
    use_board_channel = False
    boards = []
    channels = []
    slot_by_board_channel = {}
    slot_id_by_code = {}
    board_options = []
    channel_options = []

    if trackers:
        tracker_name = st.selectbox("Tracker", tracker_names, key="setup_tracker")
        selected_tracker_id = next(
            tracker_id for tracker_id, name in trackers if name == tracker_name
        )

        with st.expander("Current tracker status"):
            status_rows = tracker_status_snapshot(selected_tracker_id)
            status_table = [
                {
                    "slot_code": row["slot_code"],
                    "is_connected": row["is_connected"],
                    "cell_name": row["cell_name"],
                    "mode_code": row["mode_code"],
                    "connected_since": row["connected_since"],
                    "polarity_code": row["polarity_code"],
                }
                for row in status_rows
            ]
            st.dataframe(status_table, use_container_width=True)

        slot_options = load_slots(selected_tracker_id)
        slot_codes = [slot_code for _, slot_code in slot_options]
        slot_id_by_code = {slot_code: slot_id for slot_id, slot_code in slot_options}
        parsed = [parse_board_channel(slot_code) for slot_code in slot_codes]
        use_board_channel = bool(parsed) and all(item is not None for item in parsed)
        if use_board_channel:
            boards = sorted({item[0] for item in parsed if item is not None})
            channels = sorted({item[1] for item in parsed if item is not None})
            slot_by_board_channel = {
                (item[0], item[1]): slot_id
                for (slot_id, _), item in zip(slot_options, parsed)
                if item is not None
            }
            board_options = [str(board) for board in boards]
            channel_options = [str(channel) for channel in channels]
        else:
            board_options = slot_codes
    else:
        st.warning(
            "No trackers found. Setup rows can still be used for sensor associations only."
        )

    preset_sensors = st.multiselect(
        "Sensor preset — apply to all rows:",
        sensor_labels,
        key="setup_preset_sensors",
    )
    if st.button("Apply to all rows", key="setup_apply_preset") and preset_sensors:
        _sync_setup_rows_from_editor()
        st.session_state.setup_preset_sensor_ids = [
            sensor_id_by_label[label] for label in preset_sensors
        ]
        st.session_state.setup_preset_sensor_display = preset_sensors[:]
        st.rerun()
    if st.session_state.setup_preset_sensor_display:
        st.caption(
            "Preset sensors applied to all rows: "
            + ", ".join(st.session_state.setup_preset_sensor_display)
        )

    st.divider()

    column_config = {
        "cell_name": st.column_config.TextColumn("Cell name", required=True),
        "connect_date": st.column_config.DateColumn("Connect date", required=True),
        "board": st.column_config.SelectboxColumn(
            "Board" if use_board_channel else "Slot", options=board_options
        ),
        "ch": st.column_config.SelectboxColumn("CH", options=channel_options),
        "mode": st.column_config.SelectboxColumn(
            "Mode", options=[code for _, code in load_modes()]
        ),
        "polarity": st.column_config.SelectboxColumn(
            "Pol", options=list(polarity_options.keys())
        ),
        "temp_sensor": st.column_config.SelectboxColumn(
            "Temp sensor", options=temp_sensor_labels
        ),
        "irradiance_sensor": st.column_config.SelectboxColumn(
            "Irradiance sensor", options=irradiance_sensor_labels
        ),
        "cell_type": st.column_config.SelectboxColumn(
            "Cell type", options=list(cell_type_options.keys())
        ),
        "area_cm2": st.column_config.NumberColumn("Area (cm²)", min_value=0.0),
        "initial_pce": st.column_config.NumberColumn("Init. PCE (%)", min_value=0.0),
        "structure": st.column_config.TextColumn("Structure"),
        "owner": st.column_config.SelectboxColumn(
            "Owner", options=list(scientist_options.keys())
        ),
        "producer": st.column_config.SelectboxColumn(
            "Producer", options=list(scientist_options.keys())
        ),
        "group": st.column_config.SelectboxColumn(
            "Group", options=list(group_options.keys())
        ),
        "px": st.column_config.TextColumn(
            "Position (if not in name)",
            help=(
                "solar_cell.position_in_group — leave blank if the cell name "
                "already encodes position (e.g. the _px suffix convention). "
                "Use this for labels not baked into the name, like tandem "
                "top/bottom."
            ),
        ),
        "experiment": st.column_config.SelectboxColumn(
            "Experiment", options=list(experiment_options.keys())
        ),
        "disconnect_date": st.column_config.DateColumn("Disconnect date"),
    }
    column_order = [col for col in SETUP_COLUMNS if use_board_channel or col != "ch"]

    edited_df = st.data_editor(
        pd.DataFrame(st.session_state.setup_rows, columns=SETUP_COLUMNS),
        column_config=column_config,
        column_order=column_order,
        num_rows="dynamic",
        key="setup_editor",
        use_container_width=True,
    )

    st.caption(
        "Metadata columns (Cell type, Area, Owner, ...) are pre-filled with a "
        "cell's current registry values when added via 'Add cell(s) to list' "
        "above, and are written back as-is unless you change them. Rows typed "
        "directly into the grid should only be used for genuinely new cells."
    )

    st.divider()

    if "setup_validation_snapshot" in st.session_state and not edited_df.equals(
        st.session_state.setup_validation_snapshot
    ):
        st.session_state.pop("setup_validation", None)
        st.session_state.pop("setup_validation_snapshot", None)

    if st.button("Validate rows", key="setup_validate"):
        mode_id_by_code = {code: mode_id for mode_id, code in load_modes()}
        errors, resolved_rows, preview_rows = _resolve_setup_rows(
            edited_df,
            use_board_channel,
            slot_by_board_channel,
            slot_id_by_code,
            mode_id_by_code,
            polarity_options,
            cell_type_options,
            scientist_options,
            group_options,
            experiment_options,
            temp_sensor_id_by_label,
            irradiance_sensor_id_by_label,
            st.session_state.setup_preset_sensor_ids,
        )
        st.session_state.setup_validation = {
            "errors": errors,
            "resolved_rows": resolved_rows,
            "preview_rows": preview_rows,
        }
        st.session_state.setup_validation_snapshot = edited_df.copy()

    validation = st.session_state.get("setup_validation")
    if validation is not None:
        preview_rows = validation["preview_rows"]
        if not preview_rows:
            st.info("No rows to submit.")
        else:
            n_new = sum(1 for row in preview_rows if row["action"] == "new cell")
            n_existing = len(preview_rows) - n_new
            st.caption(
                f"{len(preview_rows)} row(s) validated — {n_new} new cell(s) will "
                f"be created, {n_existing} existing cell(s) will be updated."
            )
            st.dataframe(preview_rows, use_container_width=True)
        if validation["errors"]:
            for error in validation["errors"]:
                st.error(error)
    else:
        st.caption("Run Validate rows before submitting.")

    can_submit = (
        validation is not None
        and not validation["errors"]
        and validation["resolved_rows"]
    )
    if st.button("Submit setup events", type="primary", disabled=not can_submit):
        resolved_rows = validation["resolved_rows"]
        db_rows_mpp = []
        db_rows_sensor = []

        try:
            for row in resolved_rows:
                cell_id = ensure_cell(row["cell_name"])
                update_cell_metadata(
                    cell_id,
                    row["area_cm2"],
                    row["manufacturer_id"],
                    row["owner_id"],
                    row["group_id"],
                    row["position_in_group"],
                    None,
                    row["cell_type_id"],
                    row["structure"],
                    row["initial_pce"],
                )
                if row["experiment_id"] is not None:
                    link_cell_experiment(cell_id, row["experiment_id"])

                if row["slot_id"] is not None:
                    db_rows_mpp.append(
                        {
                            "cell_id": cell_id,
                            "slot_id": row["slot_id"],
                            "event_type": "connection",
                            "mode_id": row["mode_id"],
                            "polarity_id": row["polarity_id"],
                            "timestamp": to_timestamptz(
                                row["connect_date"], "connection"
                            ),
                        }
                    )
                    if row["disconnect_date"] is not None:
                        db_rows_mpp.append(
                            {
                                "cell_id": cell_id,
                                "slot_id": row["slot_id"],
                                "event_type": "disconnection",
                                "mode_id": None,
                                "polarity_id": None,
                                "timestamp": to_timestamptz(
                                    row["disconnect_date"], "disconnection"
                                ),
                            }
                        )

                for sensor_id in row["sensor_ids"]:
                    db_rows_sensor.append(
                        {
                            "cell_id": cell_id,
                            "sensor_id": sensor_id,
                            "event_type": "association",
                            "specification": None,
                            "timestamp": to_timestamptz(
                                row["connect_date"], "association"
                            ),
                        }
                    )
                    if row["disconnect_date"] is not None:
                        db_rows_sensor.append(
                            {
                                "cell_id": cell_id,
                                "sensor_id": sensor_id,
                                "event_type": "dissociation",
                                "specification": None,
                                "timestamp": to_timestamptz(
                                    row["disconnect_date"], "dissociation"
                                ),
                            }
                        )

            insert_events(db_rows_mpp)
            insert_sensor_association_events(db_rows_sensor)
            n_disconnects = sum(
                1 for row in resolved_rows if row["disconnect_date"] is not None
            )
            msg = (
                f"Inserted {len(db_rows_mpp)} MPP event(s) and "
                f"{len(db_rows_sensor)} sensor event(s) for {len(resolved_rows)} cell(s)."
            )
            if n_disconnects:
                msg += (
                    f" ({n_disconnects} row(s) include disconnect/dissociate events.)"
                )
            st.success(msg)
            st.session_state.setup_rows = []
            st.session_state.setup_preset_sensor_ids = []
            st.session_state.setup_preset_sensor_display = []
            st.session_state.pop("setup_validation", None)
            st.session_state.pop("setup_validation_snapshot", None)
            _clear_and_rerun()
        except Exception as exc:
            st.error(f"Database error: {exc}")


def _render_teardown_tab():
    event_date = _render_date_picker("teardown")
    st.divider()
    existing_cells = load_cells()
    cell_id_by_name = {cell_name: cell_id for cell_id, cell_name in existing_cells}

    _render_cell_picker(existing_cells, _add_teardown_rows, "teardown")

    st.divider()
    if not st.session_state.teardown:
        st.info("No teardown rows yet.")
    else:
        header = st.columns([3, 2, 3, 3, 1])
        header[0].markdown("**Cell name**")
        header[1].markdown("**Current slot**")
        header[2].markdown("**Active sensors**")
        header[3].markdown("**Dissociate**")
        header[4].markdown("")

        rows_to_remove = []
        for index, row in enumerate(st.session_state.teardown):
            c_name, c_slot, c_sensors, c_dissociate, c_delete = st.columns(
                [3, 2, 3, 3, 1]
            )

            with c_name:
                cell_name = st.text_input(
                    "cell",
                    value=row["cell_name"],
                    key=f"teardown_name_{index}",
                    label_visibility="collapsed",
                ).strip()
                row["cell_name"] = cell_name

            cell_id = cell_id_by_name.get(row["cell_name"])
            active_sensors = []

            with c_slot:
                if cell_id is None:
                    st.caption("Cell not found")
                    row["slot_id"] = None
                else:
                    slot = current_slot_for_cell(cell_id)
                    if slot is None:
                        st.warning("Not connected")
                        row["slot_id"] = None
                    else:
                        st.text(slot[1])
                        row["slot_id"] = slot[0]

            with c_sensors:
                if cell_id is None:
                    st.caption("No active sensors")
                    row["active_sensors"] = []
                else:
                    active_sensors = current_sensors_for_cell(cell_id)
                    row["active_sensors"] = active_sensors
                    if active_sensors:
                        st.caption(
                            ", ".join(
                                sensor["name"] or f"Sensor {sensor['sensor_id']}"
                                for sensor in active_sensors
                            )
                        )
                    else:
                        st.caption("No active sensors")

            with c_dissociate:
                sensor_options = {
                    f"[{sensor['sensor_type']}] {sensor['name'] or f'Sensor {sensor['sensor_id']}'} ({sensor['sensor_id']})": sensor[
                        "sensor_id"
                    ]
                    for sensor in row.get("active_sensors", [])
                }
                default_selection = list(sensor_options.keys())
                selected = st.multiselect(
                    "dissociate",
                    list(sensor_options.keys()),
                    default=default_selection,
                    key=f"teardown_dissociate_{index}",
                    label_visibility="collapsed",
                )
                row["sensors_to_dissociate"] = [
                    sensor_options[label] for label in selected
                ]

            with c_delete:
                if st.button("✕", key=f"teardown_delete_{index}"):
                    rows_to_remove.append(index)

        for index in reversed(rows_to_remove):
            st.session_state.teardown.pop(index)
        if rows_to_remove:
            st.rerun()

    st.divider()
    if st.button(
        "Submit disconnect & dissociate events",
        type="primary",
        disabled=not st.session_state.teardown or event_date is None,
    ):
        errors = []
        db_rows_mpp = []
        db_rows_sensor = []
        names = []

        for row in st.session_state.teardown:
            cell_name = row["cell_name"].strip()
            if not cell_name:
                errors.append("One or more teardown rows have an empty cell name.")
                continue
            names.append(cell_name)
            if row.get("slot_id") is None and not row.get("sensors_to_dissociate"):
                errors.append(f"{cell_name}: nothing to disconnect or dissociate.")

        if len(names) != len(set(names)):
            errors.append("Teardown rows contain duplicate cell names.")

        if errors:
            for error in errors:
                st.error(error)
            return

        try:
            for row in st.session_state.teardown:
                cell_id = cell_id_by_name.get(row["cell_name"])
                if cell_id is None:
                    errors.append(f"{row['cell_name']}: cell not found.")
                    continue

                if row.get("slot_id") is not None:
                    db_rows_mpp.append(
                        {
                            "cell_id": cell_id,
                            "slot_id": row["slot_id"],
                            "event_type": "disconnection",
                            "mode_id": None,
                            "polarity_id": None,
                            "timestamp": to_timestamptz(event_date, "disconnection"),
                        }
                    )

                for sensor_id in row.get("sensors_to_dissociate", []):
                    db_rows_sensor.append(
                        {
                            "cell_id": cell_id,
                            "sensor_id": sensor_id,
                            "event_type": "dissociation",
                            "specification": None,
                            "timestamp": to_timestamptz(event_date, "dissociation"),
                        }
                    )

            if errors:
                for error in errors:
                    st.error(error)
                return

            insert_events(db_rows_mpp)
            insert_sensor_association_events(db_rows_sensor)
            st.success(
                f"Inserted {len(db_rows_mpp)} MPP event(s) and {len(db_rows_sensor)} sensor event(s) for {len(st.session_state.teardown)} cell(s)."
            )
            st.session_state.teardown = []
            _clear_and_rerun()
        except Exception as exc:
            st.error(f"Database error: {exc}")


def _render_corrections_tab():
    st.subheader("Correct a mistaken event")
    st.warning(
        "The event log is append-only by design. As a safety measure, only the "
        "most recent event of each slot can be deleted — removing an older event "
        "would silently change how measurements between events are attributed "
        "to cells."
    )

    events = recent_connection_events(25)
    if not events:
        st.info("No connection events recorded yet.")
        return

    st.dataframe(
        [
            {
                "timestamp": event["timestamp"],
                "event": event["event_type"],
                "cell": event["cell_name"],
                "tracker": event["tracker_name"],
                "slot": event["slot_code"],
                "mode": event["mode_code"],
                "polarity": event["polarity_code"],
                "deletable": event["is_latest_for_slot"],
            }
            for event in events
        ],
        use_container_width=True,
    )

    deletable = [event for event in events if event["is_latest_for_slot"]]
    if not deletable:
        st.caption("None of the recent events can be deleted.")
        return

    event_labels = {
        (
            f"{event['timestamp']:%Y-%m-%d %H:%M} — {event['event_type']} — "
            f"{event['cell_name']} @ {event['tracker_name']}/{event['slot_code']}"
        ): event["id"]
        for event in deletable
    }
    selected_label = st.selectbox(
        "Event to delete", list(event_labels.keys()), key="corrections_event"
    )
    confirmed = st.checkbox(
        "I understand this permanently deletes the event and changes how "
        "measurements are attributed to the cell.",
        key="corrections_confirm",
    )
    if st.button(
        "Delete event", type="primary", disabled=not confirmed, key="corrections_delete"
    ):
        try:
            if delete_connection_event(event_labels[selected_label]):
                st.success("Event deleted.")
                _clear_and_rerun()
            else:
                st.error(
                    "Event is no longer the most recent on its slot — "
                    "refresh and try again."
                )
        except Exception as exc:
            st.error(f"Database error: {exc}")


_ensure_state()

tab_setup, tab_teardown, tab_corrections = st.tabs(
    ["Connect & Associate", "Disconnect & Dissociate", "Corrections"]
)

with tab_setup:
    _render_setup_tab()

with tab_teardown:
    _render_teardown_tab()

with tab_corrections:
    _render_corrections_tab()
