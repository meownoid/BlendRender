import aiosqlite
from blendqueue.db import SCHEMA, Database
from blendqueue.models import Backend, JobStatus


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
