from datetime import UTC, datetime, timedelta

import aiosqlite
from blendrender.db import SCHEMA, TELEMETRY_RETENTION, Database
from blendrender.models import Backend, JobStatus, TelemetrySample


async def test_running_job_becomes_interrupted_after_restart(settings) -> None:
    database = Database(settings.database_path)
    await database.initialize()
    job = await database.create_job(
        job_id="00000000-0000-4000-8000-000000000001",
        filename="scene.blend",
        mode="range",
        frame_start=1,
        frame_end=4,
        backend=Backend.OPTIX,
    )
    await database.update(job.id, status=JobStatus.RUNNING)
    await database.initialize()
    restarted = await database.get_job(job.id)
    assert restarted is not None
    assert restarted.status == JobStatus.INTERRUPTED
    assert "restarted" in (restarted.error or "")


async def test_fifo_queue_claim(settings) -> None:
    database = Database(settings.database_path)
    await database.initialize()
    first = await database.create_job(
        job_id="00000000-0000-4000-8000-000000000001",
        filename="first.blend",
        mode="still",
        frame_start=1,
        frame_end=1,
        backend=Backend.CUDA,
    )
    await database.create_job(
        job_id="00000000-0000-4000-8000-000000000002",
        filename="second.blend",
        mode="still",
        frame_start=1,
        frame_end=1,
        backend=Backend.CUDA,
    )
    claimed = await database.next_queued_job()
    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.status == JobStatus.RUNNING


async def test_existing_database_adds_optional_render_override_columns(settings) -> None:
    legacy_schema = SCHEMA
    for column in (
        "    samples INTEGER,\n",
        "    resolution_x INTEGER,\n",
        "    resolution_y INTEGER,\n",
        "    resolution_percentage INTEGER,\n",
    ):
        legacy_schema = legacy_schema.replace(column, "")
    settings.database_path.parent.mkdir(parents=True)
    async with aiosqlite.connect(settings.database_path) as connection:
        await connection.executescript(legacy_schema)
        await connection.commit()

    database = Database(settings.database_path)
    await database.initialize()
    async with aiosqlite.connect(settings.database_path) as connection:
        rows = await (await connection.execute("PRAGMA table_info(jobs)")).fetchall()
    columns = {str(row[1]) for row in rows}
    assert {
        "samples",
        "resolution_x",
        "resolution_y",
        "resolution_percentage",
    }.issubset(columns)


async def test_telemetry_is_persisted_in_order_and_pruned(settings) -> None:
    database = Database(settings.database_path)
    await database.initialize()
    now = datetime.now(UTC)
    old = TelemetrySample(
        captured_at=(now - TELEMETRY_RETENTION - timedelta(seconds=1)).isoformat(),
        cpu_utilization=10,
        gpu_utilization=None,
        memory_used_bytes=1,
        memory_total_bytes=2,
        vram_used_mb=None,
        vram_total_mb=None,
    )
    first = TelemetrySample(
        captured_at=(now - timedelta(seconds=2)).isoformat(),
        cpu_utilization=20,
        gpu_utilization=30,
        memory_used_bytes=2,
        memory_total_bytes=4,
        vram_used_mb=3,
        vram_total_mb=6,
    )
    latest = first.model_copy(update={"captured_at": now.isoformat(), "cpu_utilization": 40})

    await database.record_telemetry(old)
    await database.record_telemetry(first)
    await database.record_telemetry(latest)

    restarted = Database(settings.database_path)
    await restarted.initialize()
    samples = await restarted.list_telemetry()

    assert [sample.captured_at for sample in samples] == [first.captured_at, latest.captured_at]
    assert [sample.cpu_utilization for sample in samples] == [20, 40]


async def test_has_active_jobs_includes_queued_and_running_jobs(settings) -> None:
    database = Database(settings.database_path)
    await database.initialize()
    assert not await database.has_active_jobs()

    job = await database.create_job(
        job_id="00000000-0000-4000-8000-000000000010",
        filename="scene.blend",
        mode="still",
        frame_start=1,
        frame_end=1,
        backend=Backend.CPU,
    )
    assert await database.has_active_jobs()

    await database.update(job.id, status=JobStatus.RUNNING)
    assert await database.has_active_jobs()

    await database.update(job.id, status=JobStatus.COMPLETED)
    assert not await database.has_active_jobs()
