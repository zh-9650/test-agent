from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
import httpx
import docx

router = APIRouter(prefix="/api/utils", tags=["utils"])

class FetchUrlRequest(BaseModel):
    url: str

class FetchUrlResponse(BaseModel):
    text: str

class ParseDocResponse(BaseModel):
    filename: str
    text: str

@router.post("/parse-doc", response_model=ParseDocResponse)
async def parse_doc(file: UploadFile = File(...)):
    filename = file.filename or "unknown"
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    
    try:
        if ext in ["txt", "md", "json", "yaml", "yml"]:
            content = await file.read()
            text = content.decode("utf-8")
            return ParseDocResponse(filename=filename, text=text)
        elif ext == "docx":
            # Using python-docx
            content = await file.read()
            import io
            doc = docx.Document(io.BytesIO(content))
            text = "\n".join([para.text for para in doc.paragraphs])
            return ParseDocResponse(filename=filename, text=text)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported file extension: {ext}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse file: {str(e)}")

@router.post("/fetch-url", response_model=FetchUrlResponse)
async def fetch_url(req: FetchUrlRequest):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(req.url, timeout=10.0)
            response.raise_for_status()
            text = response.text
            return FetchUrlResponse(text=text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {str(e)}")
