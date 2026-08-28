from blendqueue.progress import overall_progress, parse_renderer_line


def test_parses_machine_event() -> None:
    parsed = parse_renderer_line('BLENDQUEUE_EVENT {"type":"frame_started","frame":12}\n')
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
