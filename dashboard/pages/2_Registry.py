import psycopg2
import streamlit as st

from db import (
    cells_exist,
    insert_cell,
    insert_group,
    link_cell_experiment,
    link_experiment_project,
    load_cell_by_id,
    load_cells,
    load_cells_full,
    load_experiment_cells,
    load_experiments,
    load_experiments_with_projects,
    load_group_types,
    load_groups,
    load_groups_full,
    load_projects,
    load_scientists,
    update_cell_metadata,
    update_group_cell_id,
    upsert_experiment,
    upsert_project,
    upsert_scientist,
)


st.set_page_config(page_title="Registry", layout="wide")
st.title("Registry")


def _ensure_state():
    if "registry_cell_batch" not in st.session_state:
        st.session_state.registry_cell_batch = []


def _clear_and_rerun():
    st.cache_data.clear()
    st.rerun()


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


def _parse_optional_float(value):
    stripped = value.strip()
    if not stripped:
        return None
    return float(stripped)


def _batch_names(base_name, suffixes_raw):
    base_name = base_name.strip()
    if not base_name:
        return []
    suffixes = [suffix.strip() for suffix in suffixes_raw.split(",") if suffix.strip()]
    if not suffixes:
        return [base_name]
    return [f"{base_name}{suffix}" for suffix in suffixes]


def _add_registry_cells(names):
    existing = {row["name"] for row in st.session_state.registry_cell_batch}
    existing_in_db = cells_exist(names)
    for raw_name in names:
        cell_name = raw_name.strip()
        if not cell_name or cell_name in existing:
            continue
        st.session_state.registry_cell_batch.append(
            {
                "name": cell_name,
                "exists": cell_name in existing_in_db,
            }
        )
        existing.add(cell_name)


def _render_scientists_tab():
    col_form, col_table = st.columns([1, 1])

    with col_form:
        st.subheader("Add scientist")
        name = st.text_input("Name", key="scientist_name")
        affiliation = st.text_input("Affiliation", key="scientist_affiliation")
        if st.button("Save scientist", key="save_scientist"):
            try:
                scientist_id = upsert_scientist(name, affiliation)
                st.success(f"Scientist saved with id {scientist_id}.")
                _clear_and_rerun()
            except Exception as exc:
                st.error(f"Database error: {exc}")

    with col_table:
        st.subheader("Scientists")
        scientist_rows = [
            {"id": row[0], "name": row[1], "affiliation": row[2]}
            for row in load_scientists()
        ]
        st.dataframe(scientist_rows, use_container_width=True)


def _render_cells_tab():
    st.subheader("Register new cells")
    col_batch, col_single = st.columns([2, 1])

    with col_batch:
        base_name = st.text_input(
            "Base name", placeholder="SUB003_px", key="reg_cells_base"
        )
        suffixes = st.text_input(
            "Suffixes (comma-separated)",
            placeholder="A,B,C,D",
            key="reg_cells_suffixes",
        )
        if st.button("Add batch", key="reg_cells_add_batch"):
            _add_registry_cells(_batch_names(base_name, suffixes))

    with col_single:
        single_name = st.text_input("New cell name", key="reg_cells_single")
        if st.button("Add cell", key="reg_cells_add_single"):
            _add_registry_cells([single_name])

    scientist_options = _scientist_options()
    group_options = _group_options()
    area_text = st.text_input(
        "Area (cm²)", placeholder="e.g. 0.16", key="reg_cells_area"
    )
    mfr_label = st.selectbox(
        "Manufacturer", list(scientist_options.keys()), key="reg_cells_mfr"
    )
    owner_label = st.selectbox(
        "Owner", list(scientist_options.keys()), key="reg_cells_owner"
    )
    group_label = st.selectbox(
        "Group", list(group_options.keys()), key="reg_cells_group"
    )
    position = st.text_input("Position in group", key="reg_cells_position")

    if st.session_state.registry_cell_batch:
        st.caption("Batch")
        rows_to_remove = []
        for index, row in enumerate(st.session_state.registry_cell_batch):
            c_name, c_status, c_delete = st.columns([3, 2, 1])
            with c_name:
                updated_name = st.text_input(
                    "cell",
                    value=row["name"],
                    key=f"reg_batch_name_{index}",
                    label_visibility="collapsed",
                ).strip()
                row["name"] = updated_name
                row["exists"] = updated_name in cells_exist([updated_name])
            with c_status:
                st.caption("Already exists" if row["exists"] else "Will be inserted")
            with c_delete:
                if st.button("✕", key=f"reg_batch_delete_{index}"):
                    rows_to_remove.append(index)

        for index in reversed(rows_to_remove):
            st.session_state.registry_cell_batch.pop(index)
        if rows_to_remove:
            st.rerun()

    if st.button(
        "Register batch",
        type="primary",
        disabled=not st.session_state.registry_cell_batch,
    ):
        errors = []
        inserted = 0
        try:
            area_cm2 = _parse_optional_float(area_text) if area_text else None
        except ValueError:
            errors.append("Area must be a valid number.")
            area_cm2 = None

        if len({row["name"] for row in st.session_state.registry_cell_batch}) != len(
            st.session_state.registry_cell_batch
        ):
            errors.append("Batch contains duplicate names.")

        if errors:
            for error in errors:
                st.error(error)
        else:
            try:
                for row in st.session_state.registry_cell_batch:
                    if not row["name"]:
                        errors.append("Batch contains an empty cell name.")
                        continue
                    if row["exists"]:
                        errors.append(f"{row['name']}: already exists.")
                        continue
                    insert_cell(
                        row["name"],
                        area_cm2,
                        scientist_options[mfr_label],
                        scientist_options[owner_label],
                        group_options[group_label],
                        position.strip() or None,
                    )
                    inserted += 1
                if errors:
                    for error in errors:
                        st.error(error)
                if inserted:
                    st.success(f"Inserted {inserted} cell(s).")
                    st.session_state.registry_cell_batch = []
                    _clear_and_rerun()
            except Exception as exc:
                st.error(f"Database error: {exc}")

    st.divider()
    st.subheader("Edit existing cell")
    cells = load_cells()
    if not cells:
        st.info("No cells available to edit.")
    else:
        cell_labels = {cell_name: cell_id for cell_id, cell_name in cells}
        selected_name = st.selectbox(
            "Select cell", list(cell_labels.keys()), key="edit_cell_select"
        )
        cell_data = load_cell_by_id(cell_labels[selected_name])

        scientist_options = _scientist_options()
        group_options = _group_options()
        scientist_labels = list(scientist_options.keys())
        group_labels = list(group_options.keys())

        current_mfr = next(
            (
                label
                for label, scientist_id in scientist_options.items()
                if scientist_id == cell_data["manufacturer_id"]
            ),
            "(none)",
        )
        current_owner = next(
            (
                label
                for label, scientist_id in scientist_options.items()
                if scientist_id == cell_data["owner_id"]
            ),
            "(none)",
        )
        current_group = next(
            (
                label
                for label, group_id in group_options.items()
                if group_id == cell_data["group_id"]
            ),
            "(standalone)",
        )

        st.caption(f"Cell name: {cell_data['name']}")
        edit_area = st.text_input(
            "Area (cm²)",
            value="" if cell_data["area_cm2"] is None else str(cell_data["area_cm2"]),
            key=f"edit_area_{cell_data['id']}",
        )
        edit_mfr = st.selectbox(
            "Manufacturer",
            scientist_labels,
            index=scientist_labels.index(current_mfr),
            key=f"edit_mfr_{cell_data['id']}",
        )
        edit_owner = st.selectbox(
            "Owner",
            scientist_labels,
            index=scientist_labels.index(current_owner),
            key=f"edit_owner_{cell_data['id']}",
        )
        edit_group = st.selectbox(
            "Group",
            group_labels,
            index=group_labels.index(current_group),
            key=f"edit_group_{cell_data['id']}",
        )
        edit_position = st.text_input(
            "Position in group",
            value=cell_data["position_in_group"] or "",
            key=f"edit_position_{cell_data['id']}",
        )

        if st.button("Update cell", key=f"update_cell_{cell_data['id']}"):
            try:
                area_cm2 = _parse_optional_float(edit_area) if edit_area else None
                update_cell_metadata(
                    cell_data["id"],
                    area_cm2,
                    scientist_options[edit_mfr],
                    scientist_options[edit_owner],
                    group_options[edit_group],
                    edit_position.strip() or None,
                )
                st.success("Cell updated.")
                _clear_and_rerun()
            except ValueError:
                st.error("Area must be a valid number.")
            except Exception as exc:
                st.error(f"Database error: {exc}")

    st.divider()
    st.subheader("All cells")
    st.dataframe(load_cells_full(), use_container_width=True)


def _render_groups_tab():
    col_form, col_table = st.columns([1, 1])
    group_types = load_group_types()
    group_type_labels = [code for _, code, _ in group_types]
    group_type_id_by_label = {
        code: group_type_id for group_type_id, code, _ in group_types
    }
    scientist_options = _scientist_options()
    cells = load_cells()
    cell_labels = {"(none)": None}
    for cell_id, cell_name in cells:
        cell_labels[cell_name] = cell_id

    with col_form:
        st.subheader("Create group")
        group_name = st.text_input("Name", key="group_name")
        group_type = st.selectbox("Type", group_type_labels, key="group_type")
        has_fabrication_date = st.checkbox(
            "Set fabrication date", key="group_has_fabrication"
        )
        fabrication_date = None
        if has_fabrication_date:
            fabrication_date = st.date_input(
                "Fabrication date", key="group_fabrication"
            )
        manufacturer_label = st.selectbox(
            "Manufacturer",
            list(scientist_options.keys()),
            key="group_manufacturer",
        )
        notes = st.text_area("Notes", key="group_notes")
        representative_label = "(none)"
        if group_type == "tandem":
            representative_label = st.selectbox(
                "Full-device cell",
                list(cell_labels.keys()),
                key="group_representative_cell",
            )
        if st.button("Create group", key="create_group"):
            try:
                group_id = insert_group(
                    group_name,
                    group_type_id_by_label[group_type],
                    fabrication_date,
                    scientist_options[manufacturer_label],
                    notes.strip() or None,
                )
                representative_id = cell_labels[representative_label]
                if group_type == "tandem" and representative_id is not None:
                    update_group_cell_id(group_id, representative_id)
                st.success(f"Group created with id {group_id}.")
                _clear_and_rerun()
            except psycopg2.errors.UniqueViolation:
                st.error("Group name already exists.")
            except Exception as exc:
                st.error(f"Database error: {exc}")

    with col_table:
        st.subheader("Groups")
        st.dataframe(load_groups_full(), use_container_width=True)


def _render_experiments_tab():
    tab_projects, tab_experiments, tab_assignments = st.tabs(
        ["Projects", "Experiments", "Cell Assignments"]
    )

    with tab_projects:
        col_form, col_table = st.columns([1, 1])
        with col_form:
            project_name = st.text_input("Project name", key="project_name")
            if st.button("Save project", key="save_project"):
                try:
                    project_id = upsert_project(project_name)
                    st.success(f"Project saved with id {project_id}.")
                    _clear_and_rerun()
                except Exception as exc:
                    st.error(f"Database error: {exc}")
        with col_table:
            project_rows = [{"id": row[0], "name": row[1]} for row in load_projects()]
            st.dataframe(project_rows, use_container_width=True)

    with tab_experiments:
        col_form, col_table = st.columns([1, 1])
        project_options = {
            project_name: project_id for project_id, project_name in load_projects()
        }
        with col_form:
            experiment_name = st.text_input("Experiment name", key="experiment_name")
            selected_projects = st.multiselect(
                "Projects",
                list(project_options.keys()),
                key="experiment_projects",
            )
            if st.button("Save experiment", key="save_experiment"):
                try:
                    experiment_id = upsert_experiment(experiment_name)
                    for project_name in selected_projects:
                        link_experiment_project(
                            experiment_id, project_options[project_name]
                        )
                    st.success(f"Experiment saved with id {experiment_id}.")
                    _clear_and_rerun()
                except Exception as exc:
                    st.error(f"Database error: {exc}")
        with col_table:
            st.dataframe(load_experiments_with_projects(), use_container_width=True)

    with tab_assignments:
        experiments = load_experiments()
        if not experiments:
            st.info("Create an experiment first.")
            return

        experiment_options = {
            experiment_name: experiment_id
            for experiment_id, experiment_name in experiments
        }
        selected_experiment = st.selectbox(
            "Experiment",
            list(experiment_options.keys()),
            key="assignment_experiment",
        )
        experiment_id = experiment_options[selected_experiment]

        assigned_cells = load_experiment_cells(experiment_id)
        assigned_names = [cell_name for _, cell_name in assigned_cells]
        if assigned_names:
            st.caption("Assigned cells: " + ", ".join(assigned_names))
        else:
            st.caption("Assigned cells: none")

        all_cells = load_cells()
        unassigned = [
            cell_name
            for _, cell_name in all_cells
            if cell_name not in set(assigned_names)
        ]
        selected_existing = st.multiselect(
            "Select from list",
            unassigned,
            key="assignment_existing_cells",
        )
        base_name = st.text_input(
            "Base name", placeholder="SUB003_px", key="assignment_base"
        )
        suffixes = st.text_input(
            "Suffixes (comma-separated)",
            placeholder="A,B,C",
            key="assignment_suffixes",
        )

        if st.button("Assign cells", key="assign_cells"):
            typed_names = _batch_names(base_name, suffixes)
            all_requested = set(selected_existing) | set(typed_names)
            available_names = {cell_name for _, cell_name in all_cells}
            missing = sorted(
                name for name in all_requested if name not in available_names
            )
            assigned = 0
            if missing:
                st.error("These cells do not exist: " + ", ".join(missing))
            else:
                cell_id_by_name = {
                    cell_name: cell_id for cell_id, cell_name in all_cells
                }
                try:
                    for cell_name in sorted(all_requested):
                        link_cell_experiment(cell_id_by_name[cell_name], experiment_id)
                        assigned += 1
                    st.success(f"Linked {assigned} cell(s) to {selected_experiment}.")
                    _clear_and_rerun()
                except Exception as exc:
                    st.error(f"Database error: {exc}")


_ensure_state()

tab_scientists, tab_cells, tab_groups, tab_experiments = st.tabs(
    ["Scientists", "Cells", "Groups", "Experiments"]
)

with tab_scientists:
    _render_scientists_tab()

with tab_cells:
    _render_cells_tab()

with tab_groups:
    _render_groups_tab()

with tab_experiments:
    _render_experiments_tab()
