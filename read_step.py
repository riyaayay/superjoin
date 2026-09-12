import json

path = r"C:\Users\Admin\.gemini\antigravity-ide\brain\824df9c1-f97e-415a-a9d4-dee7d821fd20\.system_generated\logs\transcript_full.jsonl"
with open(path, "r", encoding="utf-8") as f:
    for line in f:
        if '"step_index":3419' in line:
            obj = json.loads(line)
            with open("step3419.md", "w", encoding="utf-8") as out:
                out.write(obj.get("content", ""))
            break
print("Wrote step3419.md")
