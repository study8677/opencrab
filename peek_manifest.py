import json

with open('projects_manifest.json') as f:
    manifest = json.load(f)

for p in manifest.get('projects', []):
    print(f"[{p.get('status')}] {p.get('name')} - {p.get('delta', 'no delta')}")
