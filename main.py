from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import fitz  # PyMuPDF
import openai
import os
import json
from dotenv import load_dotenv

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

# Load dummy license keys
with open("licenses.json") as f:
    VALID_KEYS = set(json.load(f))

openai.api_key = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI()

class MarkdownResponse(BaseModel):
    markdown: str

@app.post("/parse-cv", response_model=MarkdownResponse)
async def parse_cv(license: str = Form(...), file: UploadFile = File(...)):
    if license not in VALID_KEYS:
        raise HTTPException(status_code=403, detail="Invalid license key")

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
            model="gpt-4-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5
        )
        markdown = response.choices[0].message.content.strip()
# TODO pozbyć się znacznika ```markkdowan jaki zwraca gpt-4-turbo
        if markdown.startswith("```markdown"):
            markdown = markdown[11:].strip()
        if markdown.endswith("```"):
            markdown = markdown[:-3].strip()
              

        return {"markdown": markdown}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
