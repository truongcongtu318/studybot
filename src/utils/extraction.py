"""Hybrid PDF Extraction — AWS Cloud mode.
Tries pypdf first; checks text density. Fallback to AWS Textract for scanned pages.
"""
import io
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def extract_text(filename: str, data: bytes, aws_region: str = "ap-southeast-1") -> Dict[str, Any]:
    """Extracts text from PDF/TXT files using a hybrid approach.

    If PDF contains very little text (scanned), falls back to AWS Textract.
    """
    name = filename.lower()

    if not name.endswith(".pdf"):
        try:
            text = data.decode("utf-8", errors="replace")
            return {
                "text": text,
                "method": "plain_text",
                "pages": 1,
                "density": len(text),
            }
        except Exception as e:
            logger.error(f"Error decoding text file: {e}")
            return {"text": "", "method": "failed", "pages": 0, "density": 0}

    # PDF Processing
    try:
        from pypdf import PdfReader
    except ImportError:
        return {"text": "(pypdf not installed)", "method": "error", "pages": 0, "density": 0}

    try:
        reader = PdfReader(io.BytesIO(data))
        num_pages = len(reader.pages)
        pages_text = []

        for page in reader.pages:
            txt = page.extract_text() or ""
            pages_text.append(txt)

        full_text = "\n\n".join(pages_text)
        total_chars = len(full_text.strip())
        density = total_chars / max(1, num_pages)

        # Threshold: if average page has < 100 characters, it's likely scanned → Textract
        if density < 100:
            logger.info(f"Low text density ({density:.1f} chars/page). Falling back to AWS Textract...")
            return _extract_via_textract(data, num_pages, aws_region)

        return {"text": full_text, "method": "pypdf", "pages": num_pages, "density": density}

    except Exception as e:
        logger.error(f"Error processing PDF: {e}")
        return _extract_via_textract(data, 1, aws_region)


def _extract_via_textract(data: bytes, est_pages: int, aws_region: str) -> Dict[str, Any]:
    """Call AWS Textract synchronously for OCR extraction."""
    import boto3
    try:
        client = boto3.client("textract", region_name=aws_region)
        response = client.detect_document_text(Document={"Bytes": data})

        extracted_lines = []
        for item in response.get("Blocks", []):
            if item["BlockType"] == "LINE":
                extracted_lines.append(item["Text"])

        text = "\n".join(extracted_lines)
        return {
            "text": text,
            "method": "aws_textract",
            "pages": est_pages,
            "density": len(text) / max(1, est_pages),
        }
    except Exception as e:
        logger.error(f"AWS Textract fallback failed: {e}")
        return {
            "text": f"Error: Failed to process document. pypdf was empty and AWS Textract failed: {e}",
            "method": "failed",
            "pages": est_pages,
            "density": 0,
        }
