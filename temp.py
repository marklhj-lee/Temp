from open_webui.internal.config import initialize_config_from_disk_then_db
    from open_webui.env import DATA_DIR
    await initialize_config_from_disk_then_db(DATA_DIR)

async def initialize_config_from_disk_then_db(DATA_DIR: Path) -> None:
    """
    1) If DATA_DIR/config.json exists, migrate it into DB and rename to old_config.json
    2) Load CONFIG_DATA from DB into memory
    """
    global CONFIG_DATA

    cfg_path = DATA_DIR / "config.json"
    if cfg_path.exists():
        with open(cfg_path, "r") as f:
            data = json.load(f)
        await save_to_db(data)
        cfg_path.rename(DATA_DIR / "old_config.json")

    CONFIG_DATA = await get_config()