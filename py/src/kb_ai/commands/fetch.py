"""Fetch and extract readable content from web URLs using trafilatura."""

import json
import sys
from datetime import date

import trafilatura


def fetch_url(url: str) -> dict:
    """Fetch a URL and extract readable markdown content.
    Returns dict with keys: title, content, date, url.
    Raises ValueError if extraction fails.
    """
    downloaded = trafilatura.fetch_url(url)
    if downloaded is None:
        raise ValueError(f"failed to download: {url}")

    content = trafilatura.extract(
        downloaded,
        output_format="markdown",
        include_links=True,
        include_tables=True,
    )
    if not content:
        raise ValueError(f"failed to extract content from: {url}")

    metadata = trafilatura.extract_metadata(downloaded)
    title = metadata.title if metadata and metadata.title else url.rstrip("/").split("/")[-1] or url
    doc_date = metadata.date if metadata and metadata.date else date.today().isoformat()

    return {
        "title": title,
        "content": content,
        "date": doc_date,
        "url": url,
    }


def run_fetch_url():
    """Bridge entrypoint: read JSON from stdin, fetch URL, write JSON to stdout."""
    from kb_ai._protocol import read_input, respond_ok

    input_data = read_input()
    url = input_data["url"]

    result = fetch_url(url)
    respond_ok(data=result)
