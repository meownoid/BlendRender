from blendrender.progress import estimate_remaining_seconds, overall_progress, parse_renderer_line


def test_parses_machine_event() -> None:
    parsed = parse_renderer_line('BLENDRENDER_EVENT {"type":"frame_started","frame":12}\n')
    assert parsed.event == {"type": "frame_started", "frame": 12}


def test_parses_cycles_sample_progress() -> None:
    parsed = parse_renderer_line("Fra:1 Mem:10.00M | Time:00:01.00 | Sample 32/128")
    assert parsed.sample_current == 32
    assert parsed.sample_total == 128


def test_overall_progress_combines_frames_and_samples() -> None:
    assert overall_progress(
        completed_count=2,
        total_frames=4,
        sample_current=64,
        sample_total=128,
    ) == 62.5


def test_estimate_remaining_seconds_uses_sample_progress_for_a_single_frame() -> None:
    assert estimate_remaining_seconds(
        elapsed_seconds=20,
        completed_count=0,
        total_frames=1,
        sample_current=50,
        sample_total=100,
    ) == 20


def test_estimate_remaining_seconds_projects_the_current_frame_to_future_frames() -> None:
    assert estimate_remaining_seconds(
        elapsed_seconds=20,
        completed_count=0,
        total_frames=3,
        frame_remaining_seconds=40,
    ) == 160


def test_estimate_remaining_seconds_requires_frame_progress() -> None:
    assert estimate_remaining_seconds(
        elapsed_seconds=20,
        completed_count=0,
        total_frames=1,
    ) is None
