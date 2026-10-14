import argparse
import json
from pathlib import Path
from uuid import uuid4

from helios.alpha.search_effort import inventory_markdown, search_inventory
from helios.common.db import get_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Hash-verified complete hourly search inventory")
    parser.add_argument("--note", type=Path)
    args = parser.parse_args()
    with get_engine().connect() as connection:
        inventory = search_inventory(connection)
    destination = Path("reports_out/hourly_search") / str(uuid4())
    destination.mkdir(parents=True, exist_ok=False)
    path = destination / "inventory.json"
    with path.open("x") as handle:
        json.dump(inventory, handle, indent=2, sort_keys=True)
        handle.write("\n")
    note = inventory_markdown(inventory)
    (destination / "search_effort.md").write_text(note)
    if args.note is not None:
        with args.note.open("x") as handle:
            handle.write(note)
    print(path)


if __name__ == "__main__":
    main()
