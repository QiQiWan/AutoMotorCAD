from pathlib import Path
import json

from motorcad_studio.mtt_parser import extract_defaults, template_name_from_filename

root = Path(__file__).resolve().parent.parent
inventory = json.loads((root / "data/inventory.json").read_text(encoding="utf-8"))
for item in inventory:
    path = root / "data/templates" / item["file"]
    item["template_name"] = template_name_from_filename(item["file"])
    item["defaults"] = extract_defaults(path)
(root / "data/catalog.generated.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Generated {len(inventory)} template records")
