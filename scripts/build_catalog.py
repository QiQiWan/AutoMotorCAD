from pathlib import Path
import json

from motorcad_studio.mtt_parser import extract_defaults, template_name_from_filename

root = Path(__file__).resolve().parent.parent
seed = root / "motorcad_studio" / "seed_data"
inventory = json.loads((seed / "inventory.json").read_text(encoding="utf-8"))
for item in inventory:
    path = seed / "templates" / item["file"]
    item["template_name"] = template_name_from_filename(item["file"])
    item["defaults"] = extract_defaults(path)
(seed / "catalog.generated.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Generated {len(inventory)} template records")
