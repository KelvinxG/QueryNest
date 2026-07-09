from __future__ import annotations

import logging
from typing import Any, Literal

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from config import get_llm_kwargs, get_settings
from graph_db import build_neo4j_manager

logger = logging.getLogger(__name__)

GOOGLE_API_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/presentations.readonly",
)


class DocumentStructure(BaseModel):
    category: str = Field(description="The single most relevant category for the document.")
    summary: str = Field(description="A short summary of the document.")
    related_topics: list[str] = Field(
        default_factory=list,
        description="Topics explicitly or implicitly related to the document.",
    )


class IngestedDocument(BaseModel):
    document_id: str
    title: str
    source_type: Literal["sheet", "slides"]
    extracted_text: str
    metadata: DocumentStructure


def _load_service_account_credentials() -> Credentials:
    settings = get_settings()

    try:
        credentials = Credentials.from_service_account_file(
            settings.GOOGLE_CREDENTIALS_FILE_PATH,
            scopes=list(GOOGLE_API_SCOPES),
        )
        return credentials
    except FileNotFoundError as exc:
        logger.exception("Google credentials file was not found.")
        raise RuntimeError("Google credentials file was not found.") from exc
    except Exception as exc:
        logger.exception("Failed to load Google service account credentials.")
        raise RuntimeError("Failed to load Google service account credentials.") from exc


def _build_google_service(service_name: str, version: str) -> Resource:
    try:
        credentials = _load_service_account_credentials()
        return build(service_name, version, credentials=credentials, cache_discovery=False)
    except Exception as exc:
        logger.exception("Failed to build Google API service %s:%s.", service_name, version)
        raise RuntimeError(f"Failed to build Google API service {service_name}:{version}.") from exc


def extract_sheet_text(spreadsheet_id: str) -> str:
    try:
        service = _build_google_service("sheets", "v4")
        response: dict[str, Any] = (
            service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, includeGridData=True)
            .execute()
        )

        chunks: list[str] = []
        for sheet in response.get("sheets", []):
            properties = sheet.get("properties", {})
            title = properties.get("title", "Untitled Sheet")
            chunks.append(f"Sheet: {title}")

            for row_data in sheet.get("data", []):
                for row in row_data.get("rowData", []):
                    cell_values: list[str] = []
                    for cell in row.get("values", []):
                        formatted_value = cell.get("formattedValue")
                        if formatted_value:
                            cell_values.append(str(formatted_value).strip())

                    if cell_values:
                        chunks.append(" | ".join(cell_values))

        return "\n".join(chunks).strip()
    except HttpError as exc:
        logger.exception("Google Sheets API request failed for spreadsheet %s.", spreadsheet_id)
        raise RuntimeError(f"Failed to extract text from spreadsheet {spreadsheet_id}.") from exc
    except Exception as exc:
        logger.exception("Unexpected error extracting spreadsheet %s.", spreadsheet_id)
        raise RuntimeError(f"Unexpected error extracting spreadsheet {spreadsheet_id}.") from exc


def _extract_text_runs(text_elements: list[dict[str, Any]]) -> list[str]:
    text_runs: list[str] = []
    for element in text_elements:
        text_run = element.get("textRun", {})
        content = text_run.get("content")
        if content:
            text_runs.append(str(content).strip())
    return text_runs


def extract_slides_text(presentation_id: str) -> str:
    try:
        service = _build_google_service("slides", "v1")
        response: dict[str, Any] = (
            service.presentations().get(presentationId=presentation_id).execute()
        )

        chunks: list[str] = []
        for index, slide in enumerate(response.get("slides", []), start=1):
            chunks.append(f"Slide {index}")
            for element in slide.get("pageElements", []):
                shape = element.get("shape", {})
                text_content = shape.get("text", {}).get("textElements", [])
                text_runs = _extract_text_runs(text_content)
                if text_runs:
                    chunks.append(" ".join(text_runs))

        return "\n".join(part for part in chunks if part).strip()
    except HttpError as exc:
        logger.exception("Google Slides API request failed for presentation %s.", presentation_id)
        raise RuntimeError(f"Failed to extract text from presentation {presentation_id}.") from exc
    except Exception as exc:
        logger.exception("Unexpected error extracting presentation %s.", presentation_id)
        raise RuntimeError(f"Unexpected error extracting presentation {presentation_id}.") from exc


def map_document_structure(document_text: str) -> DocumentStructure:
    if not document_text.strip():
        raise ValueError("Document text must not be empty.")

    try:
        llm = ChatOpenAI(
            temperature=0.0,
            **get_llm_kwargs(model=get_settings().OPENAI_SMALL_MODEL),
        )
        structured_llm = llm.with_structured_output(DocumentStructure)
        prompt = (
            "You extract a single structural category, a short summary, and related topics "
            "from internal business documents. Keep the category concise, the summary to a few "
            "sentences, and related topics specific.\n\n"
            f"Document text:\n{document_text}"
        )
        result = structured_llm.invoke(prompt)
        if isinstance(result, DocumentStructure):
            return result
        return DocumentStructure.model_validate(result)
    except Exception as exc:
        logger.exception("Failed to map document structure with the LLM.")
        raise RuntimeError("Failed to map document structure with the LLM.") from exc


def ingest_google_document(
    document_id: str,
    title: str,
    source_type: Literal["sheet", "slides"],
) -> IngestedDocument:
    if not document_id.strip():
        raise ValueError("Document ID must not be empty.")

    if not title.strip():
        raise ValueError("Document title must not be empty.")

    manager = build_neo4j_manager()
    try:
        normalized_document_id = document_id.strip()
        normalized_title = title.strip()

        if source_type == "sheet":
            extracted_text = extract_sheet_text(normalized_document_id)
        else:
            extracted_text = extract_slides_text(normalized_document_id)

        metadata = map_document_structure(extracted_text)
        manager.save_document_relationships(
            doc_id=normalized_document_id,
            title=normalized_title,
            metadata=metadata.model_dump(),
        )

        return IngestedDocument(
            document_id=normalized_document_id,
            title=normalized_title,
            source_type=source_type,
            extracted_text=extracted_text,
            metadata=metadata,
        )
    except Exception as exc:
        logger.exception(
            "Failed to ingest Google document %s from source type %s.",
            document_id,
            source_type,
        )
        raise RuntimeError(f"Failed to ingest Google document {document_id}.") from exc
    finally:
        manager.close()