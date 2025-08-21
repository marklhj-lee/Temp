def save_to_db(data):
    async def _save():
        async with get_db() as db:
            res = await db.execute(select(Config).limit(1))
            existing_config = res.scalars().first()
            if not existing_config:
                new_config = Config(data=data, version=0)
                db.add(new_config)
            else:
                existing_config.data = data
                existing_config.updated_at = datetime.now()
                db.add(existing_config)
            await db.commit()
    return asyncio.run(_save())


def reset_config():
    async def _reset():
        async with get_db() as db:
            await db.execute(delete(Config))
            await db.commit()
    return asyncio.run(_reset())

def get_config():
    async def _get():
        async with get_db() as db:
            res = await db.execute(select(Config).order_by(Config.id.desc()).limit(1))
            config_entry = res.scalars().first()
            return config_entry.data if config_entry else DEFAULT_CONFIG
    return asyncio.run(_get())