import base64
import datetime
import os
import time
from io import BytesIO

import pytest

# Import the functions to be tested.
from webdocstopdf.main import (
    setup_driver,
    apply_custom_css,
    expand_collapsible,
    get_doc_page_urls,
    get_index_links,
    generate_cover_page,
    generate_index_page,
    print_pdf_page,
    print_html_to_pdf,
    get_print_options,
    get_pages_as_pdf,
    get_index_pdf,
    merge_pdfs_to,
    get_cover_pdf,
    configure_cli,
    main,
)


# Dummy classes for simulating Selenium driver and elements.
class DummyDriver:
    def __init__(self):
        self.executed_scripts = []
        self.visited_urls = []
        self._print_page_return = None
        self.find_elements_return = []
        self.find_element_return = None
        self.raise_exception_in_find = False

    def execute_script(self, script):
        self.executed_scripts.append(script)

    def get(self, url):
        self.visited_urls.append(url)

    def print_page(self, pdf_params):
        # Return a base64 encoded dummy PDF content.
        if self._print_page_return is not None:
            return self._print_page_return
        return base64.b64encode(b"dummy_pdf").decode("utf-8")

    def find_elements(self, by, selector):
        return self.find_elements_return

    def find_element(self, by, selector):
        if self.raise_exception_in_find:
            raise Exception("Not found")
        return self.find_element_return


class DummyElement:
    def __init__(self, text, href):
        self.text = text
        self._href = href

    def get_attribute(self, attr):
        if attr == "href":
            return self._href
        if attr == "content":
            return self.text
        return None


# --- Tests for pure functions ---

def test_generate_cover_page_content():
    title = "Test Title"
    html = generate_cover_page(title)
    # Check that the title appears in the generated HTML
    assert title in html
    # Check that the current date (formatted as YYYY-MM-DD) is in the HTML
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    assert current_date in html


def test_generate_index_page_content():
    urls = ["http://example.com/page1", "http://example.com/page2"]
    html = generate_index_page(urls)
    for url in urls:
        assert f"<li>{url}</li>" in html


def test_get_print_options():
    opts = get_print_options()
    assert opts.background is True
    assert opts.scale == 0.9
    assert opts.orientation == "portrait"
    # The margin attributes should be set to 0.5
    assert hasattr(opts, "margin_top")
    assert opts.margin_top == 0.5


# --- Tests for functions that interact with a driver ---


def test_apply_custom_css():
    driver = DummyDriver()
    apply_custom_css(driver)
    # Verify that the script injected contains expected CSS identifiers.
    assert any("@media print" in script for script in driver.executed_scripts)
    assert any("style.innerHTML" in script for script in driver.executed_scripts)


def test_expand_collapsible():
    driver = DummyDriver()
    expand_collapsible(driver)
    # Check that a script with "details" and "setAttribute" was executed.
    assert any("details" in script and "setAttribute" in script for script in driver.executed_scripts)


def test_print_pdf_page():
    driver = DummyDriver()
    dummy_pdf = b"dummy_pdf_content"
    encoded_pdf = base64.b64encode(dummy_pdf).decode("utf-8")
    driver._print_page_return = encoded_pdf
    pdf_bytes = print_pdf_page(driver, pdf_params={})
    assert pdf_bytes == dummy_pdf


def test_print_html_to_pdf(monkeypatch):
    driver = DummyDriver()
    dummy_pdf = b"dummy_pdf_html"
    encoded_pdf = base64.b64encode(dummy_pdf).decode("utf-8")
    driver._print_page_return = encoded_pdf

    # Patch time.sleep to avoid an actual delay.
    monkeypatch.setattr(time, "sleep", lambda x: None)

    html = "<html><body>Test</body></html>"
    pdf_bytes = print_html_to_pdf(driver, html, print_options={})
    # Ensure that the driver was called with a data URL.
    assert any("data:text/html" in url for url in driver.visited_urls)
    assert pdf_bytes == dummy_pdf


def test_get_index_links():
    driver = DummyDriver()
    # Create dummy link elements.
    link1 = DummyElement("Link1", "http://example.com/1")
    link2 = DummyElement("Link2", "http://example.com/2")
    driver.find_elements_return = [link1, link2]
    links = get_index_links(driver)
    assert links == [link1, link2]


def test_get_doc_page_urls(monkeypatch):
    driver = DummyDriver()
    # Prepare dummy links, including a duplicate.
    dummy_links = [
        DummyElement("Page1", "http://example.com/page1"),
        DummyElement("Page1", "http://example.com/page1"),  # duplicate
        DummyElement("Page2", "http://example.com/page2"),
    ]
    # Monkeypatch get_index_links so it returns our dummy links.
    monkeypatch.setattr("webdocstopdf.get_index_links", lambda d: dummy_links)
    monkeypatch.setattr(time, "sleep", lambda x: None)
    urls = get_doc_page_urls(driver, "http://example.com")
    # Expect deduplication to leave only two unique entries.
    expected = [("Page1", "http://example.com/page1"), ("Page2", "http://example.com/page2")]
    assert urls == expected


def test_get_pages_as_pdf(monkeypatch):
    driver = DummyDriver()
    # Provide more than 2 pages; the function should only process the first 2.
    page_urls = [
        ("Page1", "http://example.com/page1"),
        ("Page2", "http://example.com/page2"),
        ("Page3", "http://example.com/page3"),
    ]
    dummy_pdf = b"page_pdf"
    encoded_pdf = base64.b64encode(dummy_pdf).decode("utf-8")
    driver._print_page_return = encoded_pdf
    monkeypatch.setattr(time, "sleep", lambda x: None)
    pages = get_pages_as_pdf(driver, page_urls, print_options={})
    assert len(pages) == 2
    assert all(page == dummy_pdf for page in pages)


def test_get_index_pdf(monkeypatch):
    driver = DummyDriver()
    dummy_pdf = b"index_pdf"
    encoded_pdf = base64.b64encode(dummy_pdf).decode("utf-8")
    driver._print_page_return = encoded_pdf
    monkeypatch.setattr(time, "sleep", lambda x: None)
    index_pdf = get_index_pdf(driver, ["http://example.com/page1", "http://example.com/page2"], print_options={})
    assert index_pdf == dummy_pdf


# --- Test for merge_pdfs_to ---

def test_merge_pdfs_to(tmp_path, monkeypatch):
    # Define a dummy PdfMerger to capture appended PDFs.
    class DummyPdfMerger:
        def __init__(self):
            self.pdfs = []

        def append(self, pdf_file):
            self.pdfs.append(pdf_file.read())

        def write(self, out_file):
            out_file.write(b"".join(self.pdfs))

        def close(self):
            pass

    # Override PdfMerger in the webdocstopdf module with our dummy.
    monkeypatch.setattr("webdocstopdf.PdfMerger", DummyPdfMerger)
    pdf1 = b"pdf1"
    pdf2 = b"pdf2"
    pdf_pages = [pdf1, pdf2]
    output_file = tmp_path / "merged.pdf"
    merge_pdfs_to(pdf_pages, str(output_file))
    with open(output_file, "rb") as f:
        content = f.read()
    assert content == pdf1 + pdf2


# --- Tests for get_cover_pdf ---


def test_get_cover_pdf_with_meta(monkeypatch):
    driver = DummyDriver()
    # Simulate a meta tag element with a custom title.
    custom_title = "Custom Site Name"
    meta_element = DummyElement(custom_title, None)
    driver.find_element_return = meta_element

    dummy_pdf = b"cover_pdf_meta"
    # Patch print_html_to_pdf so it returns our dummy PDF.
    monkeypatch.setattr("webdocstopdf.print_html_to_pdf", lambda d, html, opts: dummy_pdf)
    monkeypatch.setattr(time, "sleep", lambda x: None)
    cover_pdf = get_cover_pdf(driver, print_options={})
    assert cover_pdf == dummy_pdf


def test_get_cover_pdf_without_meta(monkeypatch):
    driver = DummyDriver()
    # Force find_element to raise an exception (simulate meta not found).
    driver.raise_exception_in_find = True

    dummy_pdf = b"cover_pdf_default"
    monkeypatch.setattr("webdocstopdf.print_html_to_pdf", lambda d, html, opts: dummy_pdf)
    monkeypatch.setattr(time, "sleep", lambda x: None)
    cover_pdf = get_cover_pdf(driver, print_options={})
    # When meta is missing, the default title "Project documentation" should be used.
    assert cover_pdf == dummy_pdf


# --- Test for CLI argument parsing ---


def test_configure_cli(monkeypatch):
    test_args = ["main.py", "http://example.com"]
    monkeypatch.setattr("sys.argv", test_args)
    args = configure_cli()
    assert args.url == "http://example.com"


# --- Integration test for main ---


def test_main(monkeypatch, tmp_path, capsys):
    dummy_driver = DummyDriver()
    # Override functions used in main to avoid real browser or file operations.
    monkeypatch.setattr("webdocstopdf.setup_driver", lambda browser="edge": dummy_driver)
    monkeypatch.setattr("webdocstopdf.get_doc_page_urls", lambda d, url: [
        ("Page1", "http://example.com/page1"),
        ("Page2", "http://example.com/page2"),
    ])
    dummy_print_options = {}
    monkeyatch = monkeypatch.setattr
    monkeyatch("webdocstopdf.get_print_options", lambda: dummy_print_options)
    dummy_pdf = b"dummy_pdf"
    monkeyatch("webdocstopdf.get_cover_pdf", lambda d, opts: dummy_pdf)
    monkeyatch("webdocstopdf.get_pages_as_pdf", lambda d, pages, opts: [dummy_pdf, dummy_pdf])
    monkeyatch("webdocstopdf.get_index_pdf", lambda d, pages, opts: dummy_pdf)

    # Override merge_pdfs_to to write a dummy merged file.
    output_pdf_path = str(tmp_path / "documentation_merged.pdf")

    def dummy_merge(pages, path):
        with open(path, "wb") as f:
            f.write(b"merged")
    monkeyatch("webdocstopdf.merge_pdfs_to", dummy_merge)

    # Ensure that quit() does nothing.
    dummy_driver.quit = lambda: None

    # Set CLI arguments.
    monkeypatch.setattr("sys.argv", ["main.py", "http://example.com"])
    main()
    captured = capsys.readouterr().out
    assert "DONE" in captured
    # Check that the dummy merged file was created and has the expected content.
    with open(output_pdf_path, "rb") as f:
        content = f.read()
    assert content == b"merged"
