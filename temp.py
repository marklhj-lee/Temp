import asyncio
CONFIG_DATA: dict = asyncio.run(get_config())

async def save_to_db(data: dict) -> None:
    async with get_db() as db:
        res = await db.execute(select(Config).limit(1))
        existing_config = res.scalars().first()
        if not existing_config:
            db.add(Config(data=data, version=0))
        else:
            existing_config.data = data
            existing_config.updated_at = datetime.now()
            db.add(existing_config)
        await db.commit()


async def reset_config() -> None:
    async with get_db() as db:
        await db.execute(delete(Config))
        await db.commit()


async def get_config() -> dict:
    async with get_db() as db:
        res = await db.execute(select(Config).order_by(Config.id.desc()).limit(1))
        config_entry = res.scalars().first()
        return config_entry.data if config_entry else DEFAULT_CONFIG