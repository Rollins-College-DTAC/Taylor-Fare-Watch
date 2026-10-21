from dashboard.flowchart import STEPS, build_flow_dot, replay_frame


def test_every_step_appears_as_a_node():
    dot = build_flow_dot({}, outcome=None)
    for step in STEPS:
        assert f"{step} [label=" in dot


def test_waiting_steps_are_grey_and_running_step_is_blue():
    dot = build_flow_dot({"detect": {"status": "ok", "message": "done"},
                           "land": {"status": "running", "message": None}}, outcome=None)
    assert '#D9D9D9' in dot  # at least one waiting (unstarted) step
    assert "#4C72B0" in dot  # running


def test_undecided_outcome_dashes_both_branches():
    dot = build_flow_dot({}, outcome=None)
    assert "act -> publish [style=dashed" in dot
    assert "act -> hold [style=dashed" in dot


def test_publish_outcome_solidifies_the_publish_branch_only():
    dot = build_flow_dot({}, outcome="publish")
    assert "act -> publish [color=" in dot
    assert "act -> hold [style=dashed" in dot
    assert "act -> publish [style=dashed" not in dot


def test_hold_outcome_solidifies_the_hold_branch_only():
    dot = build_flow_dot({}, outcome="hold_and_alert")
    assert "act -> hold [color=" in dot
    assert "act -> publish [style=dashed" in dot
    assert "act -> hold [style=dashed" not in dot


def test_step_message_is_included_and_truncated():
    long_message = "x" * 100
    dot = build_flow_dot({"detect": {"status": "ok", "message": long_message}}, outcome=None)
    assert "x" * 50 in dot
    assert "x" * 51 not in dot


def test_edge_shows_row_count_when_known():
    dot = build_flow_dot({"land": {"status": "ok", "rows_in": 7}}, outcome=None)
    assert 'detect -> land [label="7 rows"]' in dot


def test_replay_reveals_one_step_per_tick_then_the_outcome():
    rows = {s: {"status": "ok", "message": s} for s in ("detect", "land", "decide")}
    first, outcome = replay_frame(rows, "publish", tick=0)
    assert first == {"detect": {"status": "running", "message": None}} and outcome is None

    second, _ = replay_frame(rows, "publish", tick=1)
    assert second["detect"]["status"] == "ok" and second["land"]["status"] == "running"
    assert "decide" not in second

    full, outcome = replay_frame(rows, "publish", tick=3)
    assert full == rows and outcome == "publish"
    assert replay_frame(rows, "publish", tick=5)[0] == first  # wraps around
