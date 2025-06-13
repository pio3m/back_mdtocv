from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
import io
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import fitz  # PyMuPDF
import openai
import os
import json
from dotenv import load_dotenv
import httpx
import textwrap
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
import markdown
from xhtml2pdf import pisa



app = FastAPI()
load_dotenv()


# Allow frontend origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Verify license key with Gumroad
async def verify_license_with_gumroad(license_key: str) -> bool:
    print(license_key)  # Debugging output
    product_id = os.getenv("GUMROAD_PRODUCT_ID")
    url = "https://api.gumroad.com/v2/licenses/verify"
    payload = {
        "product_id": product_id,
        "license_key": license_key
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=payload)
            result = response.json()
            print(f"License verification result: {result}")  # Debugging output
            return result.get("success") and not result.get("purchase", {}).get("refunded", False)
    except Exception as e:
        print(f"Error verifying license: {e}")
        return False
    

# Load dummy license keys
with open("licenses.json") as f:
    VALID_KEYS = set(json.load(f))

openai.api_key = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI()

class MarkdownResponse(BaseModel):
    markdown: str

async def _validate_license(license: str) -> str:
    if license in VALID_KEYS:
        return "local"

    try:
        with open("used_licenses.json") as f:
            used = set(json.load(f))
    except FileNotFoundError:
        used = set()

    is_valid = await verify_license_with_gumroad(license)
    if not is_valid:
        raise HTTPException(status_code=403, detail="Invalid or refunded license key")

    if license in used:
        raise HTTPException(status_code=403, detail="License key has already been used")

    return "gumroad"

@app.get("/ping", response_class=PlainTextResponse)
async def ping():
    return "pong"

@app.post("/parse-cv", response_model=MarkdownResponse)
async def parse_cv(license: str = Form(...), file: UploadFile = File(...)):
    license_type = await _validate_license(license)


    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="File must be a PDF")

    # Extract text from PDF
    pdf = await file.read()
    doc = fitz.open(stream=pdf, filetype="pdf")
    full_text = "\n".join(page.get_text() for page in doc)

    # Prompt OpenAI to convert text to markdown CV
    prompt = f"""
You are a CV formatter assistant. Your task is to take the raw text of a resume below and convert it into a structured Markdown CV. Use sections like:

## Summary
## Experience
## Education
## Skills

Make sure the markdown is clean and easy to customize.

Resume text:

{full_text.strip()}

Please return only the markdown content.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo-0125",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5
        )
        markdown = response.choices[0].message.content.strip()
        if markdown.startswith("```markdown"):
            markdown = markdown[11:].strip()
        if markdown.endswith("```"):
            markdown = markdown[:-3].strip()
              
        # Save the license as used
        if license_type == "gumroad":
            try:
                with open("used_licenses.json") as f:
                    used = set(json.load(f))
            except FileNotFoundError:
                used = set()
            used.add(license)
            with open("used_licenses.json", "w") as f:
                json.dump(list(used), f)


        # Return the markdown response
        return {"markdown": markdown}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download-guide")
async def download_guide():
    try:
        with open("guide.md", "r", encoding="utf-8") as f:
            markdown_text = f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="guide.md not found")

    # Convert markdown to HTML
    html = markdown.markdown(markdown_text)

    # Wrap HTML in minimal structure
    html = f"""
    <html>
      <head>
        <meta charset="UTF-8">
        <style>
          body {{ font-family: Helvetica, sans-serif; font-size: 12pt; }}
          h1, h2, h3 {{ color: #2a2a2a; }}
          pre {{ background: #f4f4f4; padding: 0.5em; }}
          code {{ font-family: monospace; }}
        </style>
      </head>
      <body>{html}</body>
    </html>
    """

    # Generate PDF from HTML
    buffer = io.BytesIO()
    pisa.CreatePDF(html, dest=buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=ai-cv-action-guide.pdf"}
    )
