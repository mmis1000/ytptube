"""
Add task subtitle workflow columns.
"""

from sqlalchemy import text


async def upgrade(c):
    result = await c.execute(text("PRAGMA table_info(tasks)"))
    columns = {row[1] for row in result.fetchall()}

    if "download_mode" not in columns:
        await c.execute(text("ALTER TABLE tasks ADD COLUMN download_mode TEXT NOT NULL DEFAULT 'download'"))

    if "subtitle_mode" not in columns:
        await c.execute(text("ALTER TABLE tasks ADD COLUMN subtitle_mode TEXT NOT NULL DEFAULT 'none'"))


async def downgrade(c):
    pass
