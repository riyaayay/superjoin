import urllib.request, json, mimetypes, os, time
from pathlib import Path

pdf_path = Path("data/demo_pdfs/04-unseen-meridian-coop-notice.pdf")
boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
body = []
body.append(f"--{boundary}\r\n".encode("utf-8"))
body.append(f'Content-Disposition: form-data; name="file"; filename="{pdf_path.name}"\r\n'.encode("utf-8"))
body.append(b"Content-Type: application/pdf\r\n\r\n")
body.append(pdf_path.read_bytes())
body.append(b"\r\n")
body.append(f"--{boundary}--\r\n".encode("utf-8"))
body = b"".join(body)

req = urllib.request.Request(
    "http://localhost:8000/api/documents",
    data=body,
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    method="POST"
)

t0 = time.monotonic()
r = urllib.request.urlopen(req, timeout=120)
res = json.loads(r.read())
doc_id = res["document_id"]
print("Upload response:", res)

# Poll until complete
while True:
    req_status = urllib.request.urlopen(f"http://localhost:8000/api/documents/{doc_id}", timeout=10)
    doc_data = json.loads(req_status.read())
    status = doc_data["status"]
    print(f"Status: {status} ({time.monotonic()-t0:.1f}s)")
    if status in ("complete", "failed"):
        break
    time.sleep(2)

print("Final doc data:")
print("Status:", doc_data.get("status"))
print("Stats:", doc_data.get("stats"))
