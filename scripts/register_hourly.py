from helios.alpha.hourly_round import register_hourly
from helios.common.db import get_engine
from helios.common.lineage import git_is_dirty

if __name__ == "__main__":
    if git_is_dirty():
        raise ValueError("definition registration requires committed source")
    with get_engine().begin() as connection:
        names = register_hourly(connection)
    print("Registered immutable version-1 definitions:", ", ".join(names))
