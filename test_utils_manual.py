import asyncio
import httpx
from fastapi.testclient import TestClient
from api.app import app
import os
import docx

client = TestClient(app)

def test_parse_txt():
    with open("test.txt", "w", encoding="utf-8") as f:
        f.write("Hello Text")
    
    with open("test.txt", "rb") as f:
        response = client.post("/api/utils/parse-doc", files={"file": ("test.txt", f, "text/plain")})
    
    assert response.status_code == 200
    assert response.json()["text"] == "Hello Text"
    os.remove("test.txt")
    print("test_parse_txt passed")

def test_parse_docx():
    doc = docx.Document()
    doc.add_paragraph("Hello Docx")
    doc.save("test.docx")

    with open("test.docx", "rb") as f:
        response = client.post("/api/utils/parse-doc", files={"file": ("test.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    
    assert response.status_code == 200
    assert response.json()["text"] == "Hello Docx"
    os.remove("test.docx")
    print("test_parse_docx passed")

if __name__ == "__main__":
    test_parse_txt()
    test_parse_docx()
    print("All tests passed.")
