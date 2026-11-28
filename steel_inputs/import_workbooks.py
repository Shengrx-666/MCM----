"""Rebuild the normalized JSON from the contest workbooks."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
from statistics import median

from .loader import REFINING_ROUTES, load_inputs


CASTERS = {"A": "CC1", "B": "CC2", "C": "CC3"}
REFINING_UNITS = {"LF": ["LF1", "LF3"], "RH": ["RH1", "RH2"]}
EVENT_COLUMNS = {
    "empty_on_converter_car": 6,
    "tapping_start": 7,
    "tapping_end": 8,
    "loaded_pickup": 11,
    "lf_arrive": 15,
    "lf_process_start": 17,
    "lf_process_end": 19,
    "lf_pickup": 21,
    "rh_arrive": 24,
    "rh_process_start": 26,
    "rh_process_end": 27,
    "rh_pickup": 29,
    "caster_ladle_seated": 33,
    "casting_start": 34,
    "casting_end": 36,
    "empty_pickup": 38,
    "slag_start": 40,
    "slag_end": 42,
    "on_transfer_car": 53,
    "hot_repair_in": 58,
    "hot_repair_out": 60,
    "back_on_transfer_car": 61,
    "return_pickup": 65,
    "arrive_converter_c_car": 67,
}
HISTORY_CHECKS = (
    ("tapping_start", "tapping_end"),
    ("tapping_end", "loaded_pickup"),
    ("lf_arrive", "lf_process_start"),
    ("lf_process_start", "lf_process_end"),
    ("lf_process_end", "lf_pickup"),
    ("rh_arrive", "rh_process_start"),
    ("rh_process_start", "rh_process_end"),
    ("rh_process_end", "rh_pickup"),
    ("caster_ladle_seated", "casting_start"),
    ("casting_start", "casting_end"),
    ("casting_end", "empty_pickup"),
    ("slag_start", "slag_end"),
    ("hot_repair_in", "hot_repair_out"),
)
STATS_COLUMNS = ("resource", "metric", "unit", "sample_count", "p10", "median", "p90", "measurement")
TRUE_PROCESS_METRICS = {"精炼处理", "脱气处理", "浇铸", "吹炼", "出钢", "翻渣作业"}


def text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def integer(value):
    return int(text(value))


def timestamp(value, excel_date=None):
    if value in (None, ""):
        return None
    if excel_date is not None and isinstance(value, (int, float)):
        value = excel_date(value)
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(text(value))
    if stamp.microsecond >= 500_000:
        stamp += timedelta(seconds=1)
    return stamp.replace(microsecond=0).isoformat(sep=" ")


def positive_number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if 0 < result < float("inf") else None


def _stage(kind, candidates, start, end):
    return {"kind": kind, "candidates": candidates, "planned_start": start, "planned_end": end}


def normalize_plan_row(raw, row_number, excel_date):
    """Normalize one named row. The route code governs stage order."""
    heat = text(raw["熔炼号"])
    flag = integer(raw["配包flag"])
    if not heat or heat == "-2" or flag == -2:
        return None, {"source_row": row_number, "heat_id": heat, "pack_flag": flag, "reason": "placeholder"}
    route = text(raw["精炼路径"])
    if route not in REFINING_ROUTES:
        raise ValueError(f"Unknown route {route!r} in plan row {row_number}")
    caster = CASTERS[text(raw["连铸机号"])]
    converter = f"BOF_{text(raw['转炉设备号'])}"

    def dates(first, second):
        return timestamp(raw[first], excel_date), timestamp(raw[second], excel_date)

    slots = {
        "LF": dates("精炼1时间", "精炼2时间"),
        "RH": dates("精炼3时间", "精炼4时间"),
    }
    route_order = REFINING_ROUTES[route]
    issues = [f"unused_plan_slot:{kind}" for kind, slot in slots.items() if kind not in route_order and any(slot)]
    stages = [_stage("BOF", [converter], *dates("转炉开始时间", "转炉结束时间"))]
    stages.extend(_stage(kind, REFINING_UNITS[kind], *slots[kind]) for kind in route_order)
    stages.append(_stage("CC", [caster], *dates("浇铸开始时间", "浇铸结束时间")))
    if not stages[-1]["planned_start"]:
        raise ValueError(f"Missing casting start in plan row {row_number}")
    for stage in stages:
        start, end = stage["planned_start"], stage["planned_end"]
        if start is None or end is None:
            issues.append(f"missing_plan_interval:{stage['kind']}")
        elif end <= start:
            issues.append(f"nonpositive_plan_interval:{stage['kind']}")
    for first, second in zip(stages, stages[1:]):
        end, start = first["planned_end"], second["planned_start"]
        if end is not None and start is not None and start < end:
            issues.append(f"plan_overlap:{first['kind']}->{second['kind']}")

    return {
        "job_id": text(raw["制造命令号"]),
        "heat_id": heat,
        "route_code": route,
        "batch_id": text(raw["浇铸批号"]),
        "cast_id": text(raw["连连浇号"]),
        "cast_sub_id": text(raw["二级浇次号"]),
        "cast_sequence": integer(raw["浇次号"]),
        "caster": caster,
        "converter": converter,
        "steel_grade": text(raw["牌号"]),
        "replace_tundish": text(raw["更换中包"]) == "1",
        "rethread": text(raw["重引锭标志"]) == "T",
        "pack_flag": flag,
        "stages": stages,
        "source_row": row_number,
        "issues": issues,
    }, None


def read_plan(path):
    import xlrd

    book = xlrd.open_workbook(path)
    sheet = book.sheet_by_index(0)
    header = sheet.row_values(0)
    if len(header) != len(set(header)):
        raise ValueError("Duplicate plan column names")

    def excel_date(value):
        return xlrd.xldate_as_datetime(value, book.datemode)

    jobs, excluded = [], []
    for row in range(1, sheet.nrows):
        values = dict(zip(header, sheet.row_values(row), strict=True))
        job, issue = normalize_plan_row(values, row + 1, excel_date)
        (jobs if job else excluded).append(job if job else issue)
    return jobs, excluded, sheet.name


def read_history(sheet):
    rows = sheet.values
    headers = next(rows)
    required = {2: "熔炼号", 11: "重罐吊起时间", 24: "重罐吊起至RH旋转位时间",
                25: "重罐吊起至RH旋转位时间", 34: "开浇时间", 53: "空罐放下过渡平车时间"}
    if any(headers[col - 1] != label for col, label in required.items()):
        raise ValueError("Unexpected history column layout")
    history, excluded = [], []
    for row_number, row in enumerate(rows, 2):
        heat_id = text(row[1])
        if not heat_id:
            if any(value not in (None, "") for value in row):
                excluded.append({"source_row": row_number, "ladle_id": text(row[0]) or None,
                                 "reason": "missing_heat_id"})
            continue
        events, issues = {}, []
        for name, column in EVENT_COLUMNS.items():
            try:
                value = timestamp(row[column - 1])
            except (TypeError, ValueError):
                issues.append(f"unparsed_event:{name}")
                continue
            if value is not None:
                events[name] = value

        for first, second in HISTORY_CHECKS:
            if first in events and second in events and events[first] > events[second]:
                issues.append(f"reversed_events:{first}->{second}")
        history.append({
            "source_row": row_number,
            "heat_id": heat_id,
            "ladle_id": text(row[0]) or None,
            "converter": f"BOF_{text(row[3])}" if text(row[3]) else None,
            "lf": f"LF{text(row[13])}" if text(row[13]) else None,
            "rh": f"RH{text(row[22])}" if text(row[22]) else None,
            "caster": f"CC{text(row[31])}" if text(row[31]) else None,
            "gross_tonnes": positive_number(row[11]),
            "ladle_tare_tonnes": positive_number(row[4]),
            "events": events,
            "issues": issues,
        })
    counts = Counter(row["heat_id"] for row in history)
    for row in history:
        if counts[row["heat_id"]] > 1:
            row["issues"].append("repeated_historical_heat")
    return history, excluded


def transport_key(label):
    names = {"转炉": "BOF", "连铸": "CC", "LF": "LF", "RH": "RH"}
    start, end = (part.strip() for part in label.split("→"))
    return f"{names[start]}->{names[end]}"


def named_table(sheet, keys, first_row):
    return [
        {**dict(zip(keys, row[:len(keys)], strict=True)), "source_row": index}
        for index, row in enumerate(sheet.iter_rows(min_row=first_row, values_only=True), first_row)
        if row[0] not in (None, "")
    ]


def read_transport(parameters):
    summary_cols = ("route", "metric", "unit", "sample_count", "p10", "median", "p90", "measurement")
    transport = {transport_key(row["route"]): row for row in named_table(parameters["钢包运输"], summary_cols, 2)}
    samples = named_table(parameters["运输记录明细"],
                          ("heat_id", "history_row", "origin", "destination", "pickup", "arrival", "minutes", "route"), 2)
    grouped = defaultdict(list)
    for row in samples:
        row["route"] = transport_key(row["route"])
        row["pickup"] = timestamp(row["pickup"])
        row["arrival"] = timestamp(row["arrival"])
        if not row["pickup"] or not row["arrival"] or row["arrival"] <= row["pickup"] or row["minutes"] <= 0:
            raise ValueError(f"Invalid transport observation at row {row['source_row']}")
        grouped[row["route"]].append(row["minutes"])
    if set(grouped) != set(transport):
        raise ValueError("Transport summary and sample routes disagree")
    for route, row in transport.items():
        values = grouped[route]
        mid = Decimal(str(median(values))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        row["detail_sample_count"] = len(values)
        row["detail_median"] = float(mid)
        row["issues"] = []
        if len(values) != row["sample_count"]:
            row["issues"].append("summary_and_detail_count_differ")
        if abs(float(mid) - row["median"]) > 0.011:
            row["issues"].append("summary_and_detail_median_differ")
    return transport, samples


def casting_evidence(raw_dir, jobs, open_workbook):
    """Check the plan code mapping against the actual caster logs without joining jobs."""
    observed = defaultdict(set)
    for number in (1, 2, 3):
        with_workbook = open_workbook(raw_dir / f"{number}#连铸.xlsx")
        try:
            sheet = with_workbook.worksheets[0]
            sheet.reset_dimensions()
            for (value,) in sheet.iter_rows(min_row=2, min_col=2, max_col=2, values_only=True):
                if value:
                    observed[text(value)].add(f"CC{number}")
        finally:
            with_workbook.close()
    counts = Counter()
    for job in jobs:
        casters = observed.get(job["heat_id"])
        if not casters:
            counts["without_observation"] += 1
        elif casters == {job["caster"]}:
            counts["same_caster"] += 1
        else:
            counts["other_or_multiple_casters"] += 1
            job["issues"].append("plan_and_history_caster_disagree_or_ambiguous")
    return dict(counts)


def build(raw_dir, parameters_path, relations_path):
    from openpyxl import load_workbook

    def open_workbook(path):
        return load_workbook(path, read_only=True, data_only=True)

    plan_path = raw_dir / "出钢计划表单.xls"
    history_path = raw_dir / "工序时间信息.xlsx"
    jobs, rejected, plan_sheet = read_plan(plan_path)
    caster_check = casting_evidence(raw_dir, jobs, open_workbook)
    history_book = open_workbook(history_path)
    parameters = open_workbook(parameters_path)
    relations = open_workbook(relations_path)
    try:
        history_sheet = history_book.worksheets[0]
        history, excluded_history = read_history(history_sheet)
        transport, samples = read_transport(parameters)
        process = named_table(parameters["生产与等待耗时"], STATS_COLUMNS, 2)
        for item in process:
            item["kind"] = "process" if item["metric"] in TRUE_PROCESS_METRICS else "observed_interval"
        resources = {
            "converters": ["BOF_A", "BOF_B", "BOF_C"],
            "refining_candidates": REFINING_UNITS,
            "casters": list(CASTERS.values()),
            "caster_code_mapping": CASTERS,
            "caster_crosscheck": caster_check,
            "return_transfer_cars": [1, 2, 3],
            "reported_inventory": named_table(parameters["设备与运力"], ("name", "count", "unit", "basis"), 2),
            "dispatch_geometry": None,
        }
        return {
            "schema_version": 1,
            "sources": {
                "plan": {"file": plan_path.name, "sheet": plan_sheet},
                "history": {"file": history_path.name, "sheet": history_sheet.title},
                "parameters": {"file": parameters_path.name},
                "relations": {"file": relations_path.name},
                "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (
                    plan_path, history_path, parameters_path, relations_path,
                    *(raw_dir / f"{i}#连铸.xlsx" for i in (1, 2, 3)),
                )},
            },
            "jobs": jobs,
            "history": history,
            "transport": transport,
            "transport_samples": samples,
            "process_stats": process,
            "weight_stats": named_table(parameters["重量与装载量"], STATS_COLUMNS, 2),
            "resources": resources,
            "transport_rules": named_table(relations["运输关系"],
                                           ("state", "edge", "equipment", "time_window", "boundary"), 4),
            "waiting_rules": named_table(relations["等待发生在哪里"],
                                         ("location", "basis", "time_window", "boundary"), 4),
            "rejected_plan_rows": rejected,
            "rejected_history_rows": excluded_history,
        }
    finally:
        history_book.close()
        parameters.close()
        relations.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--parameters", type=Path, required=True)
    parser.add_argument("--relations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = build(args.raw_dir, args.parameters, args.relations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        file.write("\n")
    inputs = load_inputs(args.output)
    print(f"Saved {len(inputs.jobs)} jobs, {len(inputs.history)} history rows, "
          f"{len(inputs.transport_samples)} transport samples, and "
          f"{len(inputs.rejected_plan_rows)} excluded plan rows to {args.output}")


if __name__ == "__main__":
    main()
