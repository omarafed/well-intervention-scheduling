"""CP-SAT model extracted from Trial.ipynb; UI and job execution are separate.
The objective, compatibility constraints and distance-based transit match the notebook.
Contract end dates are advisory, as in the original model.
"""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import threading
import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

COST_UNIT_SCALE = 1000

def _as_nonnegative_int(value, field_name):
    numeric_value = float(value)
    if not np.isfinite(numeric_value) or numeric_value < 0 or not numeric_value.is_integer():
        raise ValueError(f"{field_name} must be a non-negative whole number.")
    return int(numeric_value)


def _cost_kusd_to_units(cost_kusd):
    try:
        cost = Decimal(str(cost_kusd))
    except Exception as exc:
        raise ValueError("Daily Cost (kUSD) must be a positive number.") from exc

    if not cost.is_finite() or cost <= 0:
        raise ValueError("Daily Cost (kUSD) must be a positive number.")
    cost_units = int((cost * COST_UNIT_SCALE).to_integral_value(rounding=ROUND_HALF_UP))
    if cost_units < 1:
        raise ValueError("Daily Cost (kUSD) must be at least 0.001.")
    return cost_units


def _well_cost_units(duration_days, mob_demob_days, daily_cost_kusd):
    return (duration_days + mob_demob_days) * _cost_kusd_to_units(daily_cost_kusd)


def _validate_optimization_inputs(df_candidates, fleet_specs):
    required_columns = {"Well_ID", "Job Category", "Duration_Days", "BOPD", "Lat", "Lon"}
    missing_columns = required_columns.difference(df_candidates.columns)
    if missing_columns:
        raise ValueError(f"Dataset is missing required column(s): {', '.join(sorted(missing_columns))}.")
    if not fleet_specs:
        raise ValueError("Add or upload at least one platform before optimizing.")

    candidates = df_candidates.copy().reset_index(drop=True)
    if candidates["Well_ID"].isna().any() or candidates["Well_ID"].astype(str).str.strip().eq("").any():
        raise ValueError("Every well must have a non-empty Well_ID.")
    candidates["Well_ID"] = candidates["Well_ID"].astype(str).str.strip()
    if candidates["Well_ID"].duplicated().any():
        raise ValueError("Well_ID values must be unique.")
    if candidates["Job Category"].isna().any() or candidates["Job Category"].astype(str).str.strip().eq("").any():
        raise ValueError("Every well must have a non-empty job category.")
    candidates["Job Category"] = candidates["Job Category"].astype(str).str.strip()

    for column in ["Duration_Days", "BOPD", "Lat", "Lon"]:
        candidates[column] = pd.to_numeric(candidates[column], errors="raise")
        if not np.isfinite(candidates[column]).all():
            raise ValueError(f"{column} contains an invalid number.")
    candidates["Duration_Days"] = candidates["Duration_Days"].map(
        lambda value: _as_nonnegative_int(value, "Duration_Days")
    )
    candidates["BOPD"] = candidates["BOPD"].map(
        lambda value: _as_nonnegative_int(value, "BOPD")
    )
    if ((candidates["Lat"] < -90) | (candidates["Lat"] > 90)).any():
        raise ValueError("Latitude must be between -90 and 90.")
    if ((candidates["Lon"] < -180) | (candidates["Lon"] > 180)).any():
        raise ValueError("Longitude must be between -180 and 180.")

    normalized_fleet = {}
    default_colors = ["#1f77b4", "#ff7f0e", "#d62728", "#2ca02c", "#9467bd", "#e377c2"]
    for idx, (platform_name, platform) in enumerate(fleet_specs.items()):
        categories = platform.get("Supported_Job_Categories") or []
        if not categories:
            raise ValueError(f"{platform_name} must support at least one job category.")
        color = platform.get("Color") or default_colors[idx % len(default_colors)]
        normalized_fleet[platform_name] = {
            **platform,
            "Mob_Demob_Days": _as_nonnegative_int(platform.get("Mob_Demob_Days"), f"{platform_name} Mob/Demob Days"),
            "Daily_Cost_kUSD": float(Decimal(str(platform.get("Daily_Cost_kUSD")))),
            "Supported_Job_Categories": list(categories),
            "Contract_End_Date": platform.get("Contract_End_Date", ""),
            "Color": color
        }
        _cost_kusd_to_units(normalized_fleet[platform_name]["Daily_Cost_kUSD"])

    return candidates, normalized_fleet

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat/2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon/2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
    return R * c


def optimize(data, on_progress=None, stop_event=None):
    on_progress = on_progress or (lambda update: None)
    time_limit = min(max(float(data.get("time_limit", 45)), .01), 45)
    on_progress({"phase": "building", "time_limit_seconds": time_limit, "solutions": 0})
    base_date = datetime.strptime(data["start_date"], "%Y-%m-%d")
    df_candidates = pd.DataFrame(data["wells"])
    fleet_specs = data["platforms"]
    df_candidates, fleet_specs = _validate_optimization_inputs(df_candidates, fleet_specs)
    dropped_wells = set(data.get("dropped_wells") or [])
    if not dropped_wells.issubset(set(df_candidates["Well_ID"])):
        raise ValueError("Dropped wells must exist in the dataset.")
    if df_candidates[~df_candidates["Well_ID"].isin(dropped_wells)].empty:
        raise ValueError("At least one well must remain active.")
    for _, row in df_candidates.iterrows():
        if row["Well_ID"] not in dropped_wells and not any(row["Job Category"] in p["Supported_Job_Categories"] for p in fleet_specs.values()):
            raise ValueError(f"No platform supports {row['Well_ID']}.")
    model = cp_model.CpModel()
    n_wells = len(df_candidates)
    horizon_days = 365
    platform_names = list(fleet_specs.keys())
    n_platforms = len(platform_names)

    performed, starts, ends, assigned_platform, actual_ends = {}, {}, {}, {}, []
    platform_active_vars = {}

    for i in range(n_wells):
        performed[i] = model.NewBoolVar(f"performed_{i}")
        starts[i] = model.NewIntVar(0, horizon_days, f"start_{i}")
        ends[i] = model.NewIntVar(0, horizon_days, f"end_{i}")
        assigned_platform[i] = model.NewIntVar(0, n_platforms - 1, f"platform_{i}")

        well_id = df_candidates.loc[i, "Well_ID"]
        duration = int(df_candidates.loc[i, "Duration_Days"])
        jcat = df_candidates.loc[i, "Job Category"]

        if well_id in dropped_wells:
            model.Add(performed[i] == 0)
            continue

        model.Add(performed[i] == 1)
        model.Add(starts[i] >= 0).OnlyEnforceIf(performed[i])

        platform_actives = []
        for r in range(n_platforms):
            platform_name = platform_names[r]
            supported_cats = fleet_specs[platform_name]["Supported_Job_Categories"]
            mob_demob = fleet_specs[platform_name]["Mob_Demob_Days"]
            total_well_time = duration + mob_demob

            platform_active = model.NewBoolVar(f"well_{i}_on_platform_{r}")
            platform_actives.append(platform_active)
            platform_active_vars[(i, r)] = platform_active

            if jcat not in supported_cats:
                model.Add(platform_active == 0)
            else:
                model.AddImplication(platform_active, performed[i])
                model.Add(assigned_platform[i] == r).OnlyEnforceIf(platform_active)
                model.Add(ends[i] == starts[i] + total_well_time).OnlyEnforceIf(platform_active)

        model.AddExactlyOne(platform_actives).OnlyEnforceIf(performed[i])

        actual_end = model.NewIntVar(0, horizon_days, f"actual_end_{i}")
        model.Add(actual_end == ends[i]).OnlyEnforceIf(performed[i])
        model.Add(actual_end == 0).OnlyEnforceIf(performed[i].Not())
        actual_ends.append(actual_end)

    # --- UNLOCKED ROUTING ---
    eligible_indices = [
        i for i in range(n_wells)
        if df_candidates.loc[i, "Well_ID"] not in dropped_wells
    ]
    node_by_well = {well_index: node_index + 1 for node_index, well_index in enumerate(eligible_indices)}
    transit_distance_terms = []

    for r, platform_name in enumerate(platform_names):
        route_arcs = []
        active_on_platform = [platform_active_vars[(i, r)] for i in eligible_indices]

        empty_route = model.NewBoolVar(f"platform_{r}_empty_route")
        model.Add(sum(active_on_platform) == 0).OnlyEnforceIf(empty_route)
        model.Add(sum(active_on_platform) >= 1).OnlyEnforceIf(empty_route.Not())
        route_arcs.append((0, 0, empty_route))

        efficiency_data = {}
        for i in eligible_indices:
            node_i = node_by_well[i]
            active_i = platform_active_vars[(i, r)]
            inactive_i = model.NewBoolVar(f"well_{i}_inactive_on_platform_{r}")
            model.Add(inactive_i + active_i == 1)
            route_arcs.append((node_i, node_i, inactive_i))

            first_arc = model.NewBoolVar(f"platform_{r}_first_well_{i}")
            last_arc = model.NewBoolVar(f"platform_{r}_last_well_{i}")
            model.AddImplication(first_arc, active_i)
            model.AddImplication(last_arc, active_i)
            route_arcs.extend([(0, node_i, first_arc), (node_i, 0, last_arc)])

            if df_candidates.loc[i, "Job Category"] in fleet_specs[platform_name]["Supported_Job_Categories"]:
                efficiency_data[i] = True

        for i in efficiency_data:
            for j in efficiency_data:
                if i == j:
                    continue

                distance_km = haversine(
                    df_candidates.loc[i, "Lat"], df_candidates.loc[i, "Lon"],
                    df_candidates.loc[j, "Lat"], df_candidates.loc[j, "Lon"],
                )
                transit_days = int(np.ceil(distance_km / 50.0)) + 1
                route_arc = model.NewBoolVar(f"platform_{r}_well_{i}_to_well_{j}")
                model.AddImplication(route_arc, platform_active_vars[(i, r)])
                model.AddImplication(route_arc, platform_active_vars[(j, r)])
                model.Add(starts[j] >= ends[i] + transit_days).OnlyEnforceIf(route_arc)
                route_arcs.append((node_by_well[i], node_by_well[j], route_arc))
                transit_distance_terms.append(route_arc * int(round(distance_km * 100)))

        model.AddCircuit(route_arcs)

    # --- TIME-TO-FIRST-OIL OBJECTIVE FUNCTION ---
    cumulative_oil_vars = []
    for i in eligible_indices:
        gain = int(df_candidates.loc[i, "BOPD"])
        production_days = model.NewIntVar(0, horizon_days, f"prod_days_{i}")
        model.Add(production_days == horizon_days - ends[i]).OnlyEnforceIf(performed[i])
        model.Add(production_days == 0).OnlyEnforceIf(performed[i].Not())

        cumulative_oil = model.NewIntVar(0, horizon_days * gain, f"cum_oil_{i}")
        model.AddMultiplicationEquality(cumulative_oil, [production_days, gain])
        cumulative_oil_vars.append(cumulative_oil)

    total_oil_produced = sum(cumulative_oil_vars) if cumulative_oil_vars else 0
    total_transit_units = sum(transit_distance_terms) if transit_distance_terms else 0

    model.Maximize((total_oil_produced * 100) - total_transit_units)

    def extract_schedule(reader):
        results = []
        for i in range(n_wells):
            if df_candidates.loc[i, "Well_ID"] in dropped_wells or not reader.Value(performed[i]):
                continue
            start_val = reader.Value(starts[i])
            end_val = reader.Value(ends[i])
            platform_val = reader.Value(assigned_platform[i])
            platform_n = platform_names[platform_val]
            duration = int(df_candidates.loc[i, "Duration_Days"])
            mob_demob = fleet_specs[platform_n]["Mob_Demob_Days"]
            cost = _well_cost_units(duration, mob_demob, fleet_specs[platform_n]["Daily_Cost_kUSD"]) / COST_UNIT_SCALE
            gain = int(df_candidates.loc[i, "BOPD"])
            bopd_per_cost = round(gain / cost, 4) if cost > 0 else 0.0

            results.append({
                "Well_ID": df_candidates.loc[i, "Well_ID"],
                "Platform_Assigned": platform_n,
                "Job Category": df_candidates.loc[i, "Job Category"],
                "Start_Day": start_val, "End_Day": end_val,
                "Start_Date": (base_date + timedelta(days=start_val)).strftime("%Y-%m-%d"),
                "End_Date": (base_date + timedelta(days=end_val)).strftime("%Y-%m-%d"),
                "Duration_Days": duration,
                "Mob_Demob_Days": mob_demob,
                "Lat": df_candidates.loc[i, "Lat"], "Lon": df_candidates.loc[i, "Lon"],
                "BOPD": gain,
                "Cost_kUSD": cost,
                "BOPD_per_kUSD": bopd_per_cost,
                "Contract_End_Date": fleet_specs[platform_n].get("Contract_End_Date", "N/A")
            })
        return results

    class SearchCallback(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.solutions = 0

        def on_solution_callback(self):
            if stop_event is not None and stop_event.is_set():
                self.StopSearch()
                return
            self.solutions += 1
            on_progress({
                "solutions": self.solutions,
                "objective": self.ObjectiveValue(),
                "best_bound": self.BestObjectiveBound(),
                "preview": summarize(extract_schedule(self), fleet_specs, "FEASIBLE", base_date, include_risk=False),
            })

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 4
    solver.best_bound_callback = lambda bound: on_progress({"best_bound": bound})
    on_progress({"phase": "searching"})
    finished = threading.Event()
    def watch_disconnect():
        while not finished.wait(.2):
            if stop_event.is_set():
                solver.StopSearch()
                return
    watcher = None
    if stop_event is not None:
        watcher = threading.Thread(target=watch_disconnect, daemon=True)
        watcher.start()
    try:
        status = solver.Solve(model, SearchCallback())
    finally:
        finished.set()
        if watcher:
            watcher.join()
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise ValueError(f"No feasible schedule found: {solver.StatusName(status)}")
    on_progress({"phase": "finalizing", "objective": solver.ObjectiveValue(), "best_bound": solver.BestObjectiveBound()})
    result = summarize(extract_schedule(solver), fleet_specs, solver.StatusName(status), base_date)
    result["objective"] = solver.ObjectiveValue()
    result["best_bound"] = solver.BestObjectiveBound()
    return result


def summarize(rows, platforms, status, base_date, include_risk=True):
    rows.sort(key=lambda r: (r["Platform_Assigned"], r["Start_Day"]))
    previous = {}
    warnings = []
    for row in rows:
        name = row["Platform_Assigned"]
        prev = previous.get(name)
        row["Transit_Dist_km"] = round(float(haversine(prev["Lat"], prev["Lon"], row["Lat"], row["Lon"])), 1) if prev else 0
        previous[name] = row
    for name, row in previous.items():
        end = platforms[name].get("Contract_End_Date")
        if end and row["End_Date"] > end:
            warnings.append(f"{name}: schedule extends beyond contract end {end}.")
    result = {"status": status, "schedule": rows, "warnings": warnings,
              "summary": {"wells": len(rows), "gain_bopd": sum(r["BOPD"] for r in rows), "cost_kusd": sum(r["Cost_kUSD"] for r in rows), "transit_km": sum(r["Transit_Dist_km"] for r in rows)}}
    if not include_risk:
        return result
    rng = np.random.default_rng(42)
    gains, costs = np.zeros(10000), np.zeros(10000)
    for row in rows:
        duration, gain = row["Duration_Days"], row["BOPD"]
        sampled_duration = rng.triangular(.8*duration, duration, 1.5*duration, 10000) if duration else np.zeros(10000)
        sampled_gain = rng.triangular(.7*gain, gain, 1.2*gain, 10000) if gain else np.zeros(10000)
        gains += sampled_gain
        costs += (sampled_duration + row["Mob_Demob_Days"]) * platforms[row["Platform_Assigned"]]["Daily_Cost_kUSD"]
    def distribution(values):
        counts, edges = np.histogram(values, bins=35)
        return {"x": ((edges[:-1]+edges[1:])/2).tolist(), "y": counts.tolist()}
    result.update({
        "risk": {"iterations": 10000, "gain": dict(zip(["p90", "p50", "p10"], np.percentile(gains, [10,50,90]).tolist())), "cost": dict(zip(["p10", "p50", "p90"], np.percentile(costs, [10,50,90]).tolist())), "gain_histogram": distribution(gains), "cost_histogram": distribution(costs)},
            "monte_carlo": {"gain_bopd": gains.tolist(), "cost_kusd": costs.tolist()}})
    return result
