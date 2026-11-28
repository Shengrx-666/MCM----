from steel_inputs import load_inputs


def main() -> None:
    inputs = load_inputs()
    example = inputs.jobs_for_cast("CC3", "6C0776")
    print(f"Planned heats: {len(inputs.jobs)}")
    print(f"Excluded plan rows: {len(inputs.rejected_plan_rows)}")
    print(f"History rows: {len(inputs.history)}")
    print(f"History rows without heat ID: {len(inputs.rejected_history_rows)}")
    print(f"Transport observations: {len(inputs.transport_samples)}")
    print(f"Example: CC3 / 6C0776, {len(example)} planned heats")
    for job in example[:3]:
        durations = [stage.planned_seconds for stage in job.stages]
        transport = [inputs.transport_seconds(edge) for edge in job.transport_edges]
        print(job.heat_id, job.cast_start, job.route_code, durations, transport)


if __name__ == "__main__":
    main()
