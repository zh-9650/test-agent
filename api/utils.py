import codecs
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


_ENCODING_FALLBACKS = ("gbk", "gb2312", "gb18030")
# Note: UTF-16 is NOT included here because it is ambiguous without BOM or
# explicit charset declaration.  UTF-16 content should always come with a BOM
# (handled above by _detect_encoding_by_bom) or an HTTP Content-Type charset.


def _detect_encoding_by_bom(content: bytes) -> str | None:
    """Detect encoding from Byte Order Mark. Returns encoding name or None.

    Uses Python's ``utf-16`` codec (which auto-strips BOM) for both
    little/big-endian BOMs so the decoded string is free of the BOM character.
    """
    if content.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if content.startswith(codecs.BOM_UTF16_LE) or content.startswith(codecs.BOM_UTF16_BE):
        return "utf-16"
    return None


def _decode_content(
    content: bytes,
    declared_charset: str | None = None,
) -> str:
    """Decode bytes to str with encoding detection.

    Priority:
    1. BOM (Byte Order Mark) — most reliable signal
    2. declared_charset — caller-provided hint (e.g. HTTP Content-Type)
    3. UTF-8 — the modern standard (rejected if result contains NUL chars,
       which suggests UTF-16 was decoded as UTF-8)
    4. GBK-family fallback — common for legacy Chinese documents
    5. Last resort: UTF-8 with replacement

    Note: UTF-16 without BOM or explicit charset declaration is ambiguous
    and therefore NOT supported by the fallback chain.  UTF-16 content MUST
    include a BOM or be accompanied by a charset hint.
    """
    bom_encoding = _detect_encoding_by_bom(content)
    if bom_encoding:
        return content.decode(bom_encoding)

    candidates: list[str] = []
    if declared_charset:
        if declared_charset.lower() in ("utf-8", "utf8"):
            # Skip declared UTF-8 to go through the NUL-check path
            pass
        else:
            candidates.append(declared_charset)
    candidates.append("utf-8")

    for enc in candidates:
        try:
            result = content.decode(enc)
            if "\x00" not in result:
                return result
        except (UnicodeDecodeError, LookupError):
            continue

    for enc in _ENCODING_FALLBACKS:
        try:
            result = content.decode(enc)
            if "\x00" not in result:
                return result
        except (UnicodeDecodeError, LookupError):
            continue

    return content.decode("utf-8", errors="replace")


@router.post("/parse-doc", response_model=ParseDocResponse)
async def parse_doc(file: UploadFile = File(...)):
    filename = file.filename or "unknown"
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    
    try:
        if ext in ["txt", "md", "json", "yaml", "yml"]:
            content = await file.read()
            text = _decode_content(content)
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
            # Prefer our own decoding over response.text (auto-detect) to
            # ensure consistent UTF-8 boundary behaviour.
            # Pass charset_encoding from Content-Type header as a hint.
            text = _decode_content(
                response.content,
                declared_charset=response.charset_encoding,
            )
            return FetchUrlResponse(text=text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {str(e)}")
