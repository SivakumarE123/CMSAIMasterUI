# ============================================================
# Streamlit UI for PII Protection and Mistral OCR
# ============================================================
# Two tabs:
#   1. PII Protection  - Upload text/docx, anonymize PII
#   2. Mistral OCR     - Upload PDF/image/txt, extract text
#
# Connects to MCP server at http://localhost:8080/mcp
# ============================================================

import streamlit as st
import os
from docx import Document
import json
import base64
import traceback
from io import BytesIO
from PIL import Image
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession
import asyncio
from dotenv import load_dotenv
# Load environment variables from .env file
load_dotenv()


MCP_URL = os.getenv("MCP_URL", "")


st.set_page_config(page_title="PII Protection & OCR", layout="wide")
st.title("🔐 PII Protection & OCR Tool")


# -----------------------------
# MCP Tool Call Helper
# -----------------------------
def call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    """Connect to the MCP server and invoke a tool by name."""
    async def _call():
        async with streamablehttp_client(MCP_URL) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)

                # Check for errors in result
                if result.isError:
                    error_msg = ""
                    for content in result.content:
                        if hasattr(content, "text"):
                            error_msg += content.text
                    raise Exception(f"MCP tool error: {error_msg}")

                for content in result.content:
                    if hasattr(content, "text"):
                        return json.loads(content.text)
                return {}

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_call())
    finally:
        loop.close()


# -----------------------------
# Text Extraction Helper
# -----------------------------
def extract_text(file):
    """Extract text from .txt or .docx files."""
    if file.name.endswith(".txt"):
        return file.read().decode("utf-8")

    elif file.name.endswith(".docx"):
        doc = Document(file)
        return "\n".join([para.text for para in doc.paragraphs])

    return ""


# -----------------------------
# Image Compression Helper
# -----------------------------
def compress_image(image_bytes, max_size_mb=3):
    """Resizes and compresses an image to stay under payload limits."""
    img = Image.open(BytesIO(image_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    output = BytesIO()
    img.save(output, format="JPEG", quality=80)

    while output.tell() > max_size_mb * 1024 * 1024:
        width, height = img.size
        img = img.resize((int(width * 0.8), int(height * 0.8)), Image.LANCZOS)
        output = BytesIO()
        img.save(output, format="JPEG", quality=70)
        if width < 500:
            break

    return output.getvalue()


# =============================================================
# Tabs
# =============================================================
tab_pii, tab_ocr = st.tabs(["🛡️ PII Protection", "📄 Mistral OCR"])


# =============================================================
# Tab 1: PII Protection
# =============================================================
with tab_pii:
    st.header("Detect & Anonymize PII")

    # ---- File Upload ----
    pii_file = st.file_uploader(
        "Upload a file (.txt or .docx)",
        type=["txt", "docx"],
        key="pii_upload"
    )

    # ---- Deny List Input ----
    st.subheader("Optional: Custom Deny List")

    deny_input = st.text_area(
        "Enter deny list in JSON format (e.g. {\"CUSTOM_NAME\": [\"John\", \"Alice\"]})",
        height=120,
        key="deny_input"
    )

    use_deny = st.checkbox("Use Custom Deny List", key="use_deny")

    # ---- Process Button ----
    if st.button("🚀 Process File", key="pii_btn"):

        if not pii_file:
            st.error("Please upload a file")
            st.stop()

        text = extract_text(pii_file)

        if not text.strip():
            st.error("File is empty")
            st.stop()

        try:
            if use_deny and deny_input.strip():
                raw_deny = json.loads(deny_input)

                # Normalize to dict format: {"ENTITY_NAME": ["val1", "val2"]}
                if isinstance(raw_deny, dict):
                    deny_dict = raw_deny
                elif isinstance(raw_deny, list):
                    deny_dict = {
                        item["name"]: item["values"]
                        for item in raw_deny
                    }
                else:
                    st.error("Deny list must be a JSON object or array")
                    st.stop()

                st.info(f"Calling protect_multi with {len(deny_dict)} deny list(s)...")

                # Send as JSON string since MCP tool expects str
                result = call_mcp_tool("protect_multi", {
                    "text": text,
                    "deny_lists": json.dumps(deny_dict)
                })
            else:
                result = call_mcp_tool("protect_multi", {
                    "text": text,
                    "deny_lists": json.dumps({})
                })

            # ---- Display Results Side-by-Side ----
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("📄 Original Text")
                st.text_area(
                    "Original Text",
                    result.get("original", ""),
                    height=400,
                    label_visibility="collapsed"
                )

            with col2:
                st.subheader("🔒 Anonymized Text")
                st.text_area(
                    "Anonymized Text",
                    result.get("anonymized", ""),
                    height=400,
                    label_visibility="collapsed"
                )

        except json.JSONDecodeError:
            st.error("Invalid JSON format in deny list")
        except Exception as e:
            st.error(f"Error: {str(e)}")
            st.code(traceback.format_exc())


# ...existing code...

# =============================================================
# Tab 2: Mistral OCR
# =============================================================
with tab_ocr:
    st.header("Extract Text from Documents")
    st.markdown("Upload a document and extract text using **Mistral Document AI** via MCP.")

    # ---- File Upload ----
    ocr_file = st.file_uploader(
        "Upload Document (PDF, PNG, JPG, JPEG, TXT)",
        type=["pdf", "png", "jpg", "jpeg", "txt"],
        key="ocr_upload"
    )

    if ocr_file:
        # ---- Preview & Result Layout ----
        col_preview, col_result = st.columns([1, 2])

        with col_preview:
            st.subheader("📎 Source Document")
            if "image" in ocr_file.type:
                st.image(ocr_file, use_container_width=True)
            elif ocr_file.type == "application/pdf":
                st.info(f"📄 PDF: {ocr_file.name}")
            elif ocr_file.type == "text/plain":
                st.info(f"📝 Text: {ocr_file.name}")
            else:
                st.info(f"📁 File: {ocr_file.name}")

        with col_result:
            st.subheader("📝 Extraction Results")

            if st.button("🚀 Run Analysis", type="primary", key="ocr_btn"):
                try:
                    # Read file bytes
                    file_bytes = ocr_file.getvalue()

                    # Determine MIME type from extension
                    ext = ocr_file.name.rsplit(".", 1)[-1].lower()
                    mime_map = {
                        "pdf": "application/pdf",
                        "txt": "text/plain",
                        "png": "image/png",
                        "jpg": "image/jpeg",
                        "jpeg": "image/jpeg"
                    }
                    mime_type = mime_map.get(ext, "application/octet-stream")

                    # Compress images to stay under payload limits
                    if ext in ["png", "jpg", "jpeg"]:
                        file_bytes = compress_image(file_bytes, max_size_mb=3)
                        mime_type = "image/jpeg"  # compress_image outputs JPEG

                    # Encode to base64
                    b64_data = base64.b64encode(file_bytes).decode("utf-8")

                    # Show file size for debugging
                    size_mb = len(file_bytes) / (1024 * 1024)
                    st.caption(f"📦 Sending {size_mb:.2f} MB ({mime_type})")

                    with st.status("🔍 Analyzing with Mistral Document AI...", expanded=True):
                        # Call MCP mistral_ocr tool
                        result = call_mcp_tool("mistral_ocr", {
                            "file_base64": b64_data,
                            "mime_type": mime_type
                        })

                        status = result.get("status", "unknown")
                        data = result.get("data", {})

                        if status == "success":
                            st.success("✅ Mistral analysis complete.")

                            # Display pages if available
                            pages = data.get("pages", [])
                            if isinstance(pages, list) and len(pages) > 0:
                                for page in pages:
                                    page_idx = page.get("index", 0)
                                    with st.expander(
                                        f"📄 Page {page_idx}",
                                        expanded=True
                                    ):
                                        st.markdown(
                                            page.get("markdown", "")
                                        )
                            else:
                                # Fallback: display text directly
                                extracted = data.get("text", str(data))
                                st.markdown("### Extracted Text")
                                st.markdown(extracted)

                            # Raw JSON output
                            with st.expander("🔧 Raw JSON Response"):
                                st.json(data)
                        else:
                            st.error(
                                f"❌ OCR failed: {data.get('error', 'Unknown error')}"
                            )

                except Exception as e:
                    st.error(f"Error: {str(e)}")
                    st.code(traceback.format_exc())

    else:
        st.info("Upload a document to extract text using Mistral Document AI.")