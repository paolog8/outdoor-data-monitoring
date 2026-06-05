from datetime import date

import streamlit as st

from db import (
    cells_exist,
    current_sensors_for_cell,
    current_slot_for_cell,
    ensure_cell,
    insert_events,
    insert_sensor_association_events,
    link_cell_experiment,
    load_cell_types,
    load_cells,
    load_experiments,
    load_polarities,
    load_groups,
    load_modes,
    load_scientists,
    load_sensors,
    load_slots,
    load_trackers,
    parse_board_channel,
    to_timestamptz,
    tracker_status_snapshot,
    update_cell_metadata,
)


st.title("Cell Events")


def _default_mode():
    modes = load_modes()
    if not modes:
        return None, ""
    return modes[0][0], modes[0][1]


def _ensure_state():
    if "setup" not in st.session_state:
        st.session_state.setup = []
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
    default_mode_id, default_mode_code = _default_mode()
    existing_names = cells_exist(names)
    seen = {row["cell_name"] for row in st.session_state.setup}
    for raw_name in names:
        cell_name = raw_name.strip()
        if not cell_name or cell_name in seen:
            continue
        st.session_state.setup.append(
            {
                "cell_name": cell_name,
                "is_new": cell_name not in existing_names,
                "slot_id": None,
                "slot_code": "",
                "mode_id": default_mode_id,
                "mode_code": default_mode_code,
                "sensor_ids": [],
                "sensor_display": [],
            }
        )
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


def _parse_optional_float(value):
    stripped = value.strip()
    if not stripped:
        return None
    return float(stripped)


def _clear_and_rerun():
    st.cache_data.clear()
    st.rerun()


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


def _render_setup_tab():
    event_date = _render_date_picker("setup")
    st.divider()
    existing_cells = load_cells()
    existing_names = {name for _, name in existing_cells}
    sensors = load_sensors()
    sensor_labels = []
    sensor_id_by_label = {}
    label_by_sensor_id = {}
    for sensor_id, sensor_type, name, serial_number, location in sensors:
        detail_parts = [part for part in [serial_number, location] if part]
        detail_suffix = f" ({' | '.join(detail_parts)})" if detail_parts else ""
        label = f"[{sensor_type}] {name or f'Sensor {sensor_id}'}{detail_suffix}"
        sensor_labels.append(label)
        sensor_id_by_label[label] = sensor_id
        label_by_sensor_id[sensor_id] = label

    scientist_options = _scientist_options()
    group_options = _group_options()
    experiment_options = _experiment_options()
    cell_type_options = _cell_type_options()
    polarity_options = _polarity_options()
    polarity_names = list(polarity_options.keys())

    _render_batch_builder(existing_cells, _add_setup_rows, "setup")

    trackers = load_trackers()
    tracker_names = [tracker_name for _, tracker_name in trackers]
    selected_tracker_id = None
    slot_options = []
    slot_codes = []
    use_board_channel = False
    boards = []
    channels = []
    slot_by_board_channel = {}

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
        preset_ids = [sensor_id_by_label[label] for label in preset_sensors]
        for row in st.session_state.setup:
            row["sensor_ids"] = preset_ids[:]
            row["sensor_display"] = preset_sensors[:]
        st.rerun()

    st.divider()
    new_count = sum(1 for row in st.session_state.setup if row["is_new"])
    existing_count = len(st.session_state.setup) - new_count
    st.caption(
        f"{len(st.session_state.setup)} rows — {new_count} new cells, {existing_count} existing"
    )

    if not st.session_state.setup:
        st.info("No setup rows yet.")
    else:
        modes = load_modes()
        mode_names = [mode_code for _, mode_code in modes]
        mode_id_by_code = {mode_code: mode_id for mode_id, mode_code in modes}

        if use_board_channel:
            header = st.columns([3, 1, 2, 2, 2, 3, 1, 1])
            header[0].markdown("**Cell name**")
            header[1].markdown("**Board**")
            header[2].markdown("**Ch**")
            header[3].markdown("**Mode**")
            header[4].markdown("**Polarity**")
            header[5].markdown("**Sensors**")
            header[6].markdown("**Metadata**")
            header[7].markdown("")
        else:
            header = st.columns([3, 2, 2, 2, 3, 1, 1])
            header[0].markdown("**Cell name**")
            header[1].markdown("**Slot**")
            header[2].markdown("**Mode**")
            header[3].markdown("**Polarity**")
            header[4].markdown("**Sensors**")
            header[5].markdown("**Metadata**")
            header[6].markdown("")

        rows_to_remove = []
        board_options = ["-"] + [str(board) for board in boards]
        channel_options = ["-"] + [str(channel) for channel in channels]
        slot_select_options = ["(none)"] + slot_codes

        for index, row in enumerate(st.session_state.setup):
            if use_board_channel:
                c_name, c_board, c_channel, c_mode, c_polarity, c_sensors, c_meta, c_delete = (
                    st.columns([3, 1, 2, 2, 2, 3, 1, 1])
                )
            else:
                c_name, c_slot, c_mode, c_polarity, c_sensors, c_meta, c_delete = st.columns(
                    [3, 2, 2, 2, 3, 1, 1]
                )

            with c_name:
                new_name = st.text_input(
                    "cell",
                    value=row["cell_name"],
                    key=f"setup_name_{index}",
                    label_visibility="collapsed",
                ).strip()
                row["cell_name"] = new_name
                row["is_new"] = bool(new_name) and new_name not in existing_names
                if row["is_new"]:
                    st.caption("New cell")

            if use_board_channel:
                current_board_channel = parse_board_channel(row.get("slot_code", ""))
                selected_board = "-"
                selected_channel = "-"
                if current_board_channel is not None:
                    current_board, current_channel = current_board_channel
                    if str(current_board) in board_options:
                        selected_board = str(current_board)
                    if str(current_channel) in channel_options:
                        selected_channel = str(current_channel)

                with c_board:
                    selected_board = st.selectbox(
                        "board",
                        board_options,
                        index=board_options.index(selected_board),
                        key=f"setup_board_{index}",
                        label_visibility="collapsed",
                    )
                with c_channel:
                    selected_channel = st.selectbox(
                        "channel",
                        channel_options,
                        index=channel_options.index(selected_channel),
                        key=f"setup_channel_{index}",
                        label_visibility="collapsed",
                    )
                if selected_board == "-" or selected_channel == "-":
                    row["slot_id"] = None
                    row["slot_code"] = ""
                else:
                    slot_id = slot_by_board_channel.get(
                        (int(selected_board), int(selected_channel))
                    )
                    row["slot_id"] = slot_id
                    row["slot_code"] = (
                        next(
                            (
                                slot_code
                                for candidate_slot_id, slot_code in slot_options
                                if candidate_slot_id == slot_id
                            ),
                            "",
                        )
                        if slot_id is not None
                        else ""
                    )
            else:
                with c_slot:
                    current_slot_code = row.get("slot_code", "")
                    selected_slot_code = (
                        current_slot_code
                        if current_slot_code in slot_codes
                        else "(none)"
                    )
                    selected_slot_code = st.selectbox(
                        "slot",
                        slot_select_options,
                        index=slot_select_options.index(selected_slot_code),
                        key=f"setup_slot_{index}",
                        label_visibility="collapsed",
                    )
                    if selected_slot_code == "(none)":
                        row["slot_id"] = None
                        row["slot_code"] = ""
                    else:
                        row["slot_code"] = selected_slot_code
                        row["slot_id"] = next(
                            slot_id
                            for slot_id, slot_code in slot_options
                            if slot_code == selected_slot_code
                        )

            with c_mode:
                if mode_names:
                    default_mode_code = row.get("mode_code") or mode_names[0]
                    selected_mode = st.selectbox(
                        "mode",
                        mode_names,
                        index=mode_names.index(default_mode_code)
                        if default_mode_code in mode_names
                        else 0,
                        key=f"setup_mode_{index}",
                        label_visibility="collapsed",
                    )
                    row["mode_code"] = selected_mode
                    row["mode_id"] = mode_id_by_code[selected_mode]
                else:
                    row["mode_code"] = ""
                    row["mode_id"] = None
                    st.caption("No modes available")

            with c_polarity:
                selected_polarity = st.selectbox(
                    "polarity",
                    polarity_names,
                    key=f"setup_polarity_{index}",
                    label_visibility="collapsed",
                )
                row["polarity_id"] = polarity_options[selected_polarity]

            with c_sensors:
                selected_sensor_labels = st.multiselect(
                    "sensors",
                    sensor_labels,
                    default=[
                        label_by_sensor_id[sensor_id]
                        for sensor_id in row["sensor_ids"]
                        if sensor_id in label_by_sensor_id
                    ],
                    key=f"setup_sensors_{index}",
                    label_visibility="collapsed",
                )
                row["sensor_display"] = selected_sensor_labels
                row["sensor_ids"] = [
                    sensor_id_by_label[label] for label in selected_sensor_labels
                ]

            with c_meta:
                if row["is_new"]:
                    _has_meta = (
                        bool(
                            st.session_state.get(f"setup_meta_area_{index}", "").strip()
                        )
                        or st.session_state.get(
                            f"setup_meta_manufacturer_{index}", "(none)"
                        )
                        != "(none)"
                        or st.session_state.get(f"setup_meta_owner_{index}", "(none)")
                        != "(none)"
                        or st.session_state.get(
                            f"setup_meta_group_{index}", "(standalone)"
                        )
                        != "(standalone)"
                        or bool(
                            st.session_state.get(
                                f"setup_meta_position_{index}", ""
                            ).strip()
                        )
                        or bool(
                            st.session_state.get(
                                f"setup_meta_nomad_{index}", ""
                            ).strip()
                        )
                        or st.session_state.get(
                            f"setup_meta_experiment_{index}", "(none)"
                        )
                        != "(none)"
                        or st.session_state.get(
                            f"setup_meta_cell_type_{index}", "(none)"
                        )
                        != "(none)"
                        or bool(
                            st.session_state.get(
                                f"setup_meta_structure_{index}", ""
                            ).strip()
                        )
                        or bool(
                            st.session_state.get(
                                f"setup_meta_pce_{index}", ""
                            ).strip()
                        )
                    )
                    with st.popover("📋✓" if _has_meta else "📋"):
                        st.caption(f"Metadata for **{row['cell_name']}**")
                        st.selectbox(
                            "Cell type",
                            list(cell_type_options.keys()),
                            key=f"setup_meta_cell_type_{index}",
                        )
                        st.text_input(
                            "Area (cm²)",
                            placeholder="e.g. 0.16",
                            key=f"setup_meta_area_{index}",
                        )
                        st.text_input(
                            "Initial PCE (%)",
                            placeholder="e.g. 18.5",
                            key=f"setup_meta_pce_{index}",
                        )
                        st.text_input(
                            "Structure",
                            placeholder="e.g. ITO/NiOx/Pero/C60/BCP/Ag",
                            key=f"setup_meta_structure_{index}",
                        )
                        st.selectbox(
                            "Owner",
                            list(scientist_options.keys()),
                            key=f"setup_meta_owner_{index}",
                        )
                        st.selectbox(
                            "Manufacturer",
                            list(scientist_options.keys()),
                            key=f"setup_meta_manufacturer_{index}",
                        )
                        st.selectbox(
                            "Experiment",
                            list(experiment_options.keys()),
                            key=f"setup_meta_experiment_{index}",
                        )
                        st.selectbox(
                            "Group",
                            list(group_options.keys()),
                            key=f"setup_meta_group_{index}",
                        )
                        st.text_input(
                            "Position in group",
                            placeholder="P1, top, ...",
                            key=f"setup_meta_position_{index}",
                        )
                        st.text_input(
                            "NOMAD entry URL", key=f"setup_meta_nomad_{index}"
                        )

            with c_delete:
                if st.button("✕", key=f"setup_delete_{index}"):
                    rows_to_remove.append(index)

        for index in reversed(rows_to_remove):
            st.session_state.setup.pop(index)
        if rows_to_remove:
            st.rerun()

    st.divider()
    if st.button(
        "Submit setup events",
        type="primary",
        disabled=not st.session_state.setup or event_date is None,
    ):
        errors = []
        db_rows_mpp = []
        db_rows_sensor = []

        names = []
        for row in st.session_state.setup:
            cell_name = row["cell_name"].strip()
            if not cell_name:
                errors.append("One or more setup rows have an empty cell name.")
                continue
            names.append(cell_name)
            if row["slot_id"] is None and not row["sensor_ids"]:
                errors.append(
                    f"{cell_name}: choose a slot, at least one sensor, or both."
                )
            if row["slot_id"] is not None and row.get("mode_id") is None:
                errors.append(
                    f"{cell_name}: no connection mode is available for a slot assignment."
                )

        if len(names) != len(set(names)):
            errors.append("Setup rows contain duplicate cell names.")

        row_meta = []
        for i, row in enumerate(st.session_state.setup):
            area_text = st.session_state.get(f"setup_meta_area_{i}", "")
            try:
                area_cm2 = (
                    _parse_optional_float(area_text) if area_text.strip() else None
                )
            except ValueError:
                errors.append(f"{row['cell_name']}: area must be a valid number.")
                area_cm2 = None
            pce_text = st.session_state.get(f"setup_meta_pce_{i}", "")
            try:
                initial_pce = (
                    _parse_optional_float(pce_text) if pce_text.strip() else None
                )
            except ValueError:
                errors.append(f"{row['cell_name']}: initial PCE must be a valid number.")
                initial_pce = None
            row_meta.append(
                {
                    "area_cm2": area_cm2,
                    "manufacturer_id": scientist_options.get(
                        st.session_state.get(f"setup_meta_manufacturer_{i}", "(none)")
                    ),
                    "owner_id": scientist_options.get(
                        st.session_state.get(f"setup_meta_owner_{i}", "(none)")
                    ),
                    "group_id": group_options.get(
                        st.session_state.get(f"setup_meta_group_{i}", "(standalone)")
                    ),
                    "position": st.session_state.get(
                        f"setup_meta_position_{i}", ""
                    ).strip()
                    or None,
                    "nomad_url": st.session_state.get(
                        f"setup_meta_nomad_{i}", ""
                    ).strip()
                    or None,
                    "experiment_id": experiment_options.get(
                        st.session_state.get(f"setup_meta_experiment_{i}", "(none)")
                    ),
                    "cell_type_id": cell_type_options.get(
                        st.session_state.get(f"setup_meta_cell_type_{i}", "(none)")
                    ),
                    "structure": st.session_state.get(
                        f"setup_meta_structure_{i}", ""
                    ).strip()
                    or None,
                    "initial_pce": initial_pce,
                }
            )

        if errors:
            for error in errors:
                st.error(error)
            return

        try:
            for i, row in enumerate(st.session_state.setup):
                cell_id = ensure_cell(row["cell_name"])
                if row["is_new"]:
                    meta = row_meta[i]
                    if any(v is not None for v in meta.values()):
                        update_cell_metadata(
                            cell_id,
                            meta["area_cm2"],
                            meta["manufacturer_id"],
                            meta["owner_id"],
                            meta["group_id"],
                            meta["position"],
                            meta["nomad_url"],
                            meta["cell_type_id"],
                            meta["structure"],
                            meta["initial_pce"],
                        )
                    if meta["experiment_id"] is not None:
                        link_cell_experiment(cell_id, meta["experiment_id"])

                if row["slot_id"] is not None:
                    db_rows_mpp.append(
                        {
                            "cell_id": cell_id,
                            "slot_id": row["slot_id"],
                            "event_type": "connection",
                            "mode_id": row["mode_id"],
                            "polarity_id": row.get("polarity_id"),
                            "occurred_at": to_timestamptz(event_date, "connection"),
                        }
                    )

                for sensor_id in row["sensor_ids"]:
                    db_rows_sensor.append(
                        {
                            "cell_id": cell_id,
                            "sensor_id": sensor_id,
                            "event_type": "association",
                            "specification": None,
                            "occurred_at": to_timestamptz(event_date, "association"),
                        }
                    )

            insert_events(db_rows_mpp)
            insert_sensor_association_events(db_rows_sensor)
            st.success(
                f"Inserted {len(db_rows_mpp)} MPP event(s) and {len(db_rows_sensor)} sensor event(s) for {len(st.session_state.setup)} cell(s)."
            )
            st.session_state.setup = []
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
                            "occurred_at": to_timestamptz(event_date, "disconnection"),
                        }
                    )

                for sensor_id in row.get("sensors_to_dissociate", []):
                    db_rows_sensor.append(
                        {
                            "cell_id": cell_id,
                            "sensor_id": sensor_id,
                            "event_type": "dissociation",
                            "specification": None,
                            "occurred_at": to_timestamptz(event_date, "dissociation"),
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


_ensure_state()

tab_setup, tab_teardown = st.tabs(["Connect & Associate", "Disconnect & Dissociate"])

with tab_setup:
    _render_setup_tab()

with tab_teardown:
    _render_teardown_tab()
