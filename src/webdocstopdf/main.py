"""
CLI tool to export online documentation to a merged PDF.

Each page (cover, index, and documentation pages) is exported to PDF in memory
using Selenium's print_page method. The PDFs are then merged using pdfminer to
extract text and ReportLab to reassemble a new PDF (one page per extracted PDF).
Note: This merging approach extracts text and reassembles the PDF, losing the
original layout, images, and styling.
"""
import argparse
import os
import time
from PyPDF2 import PdfMerger
import base64
import urllib.parse
from collections import OrderedDict
from io import BytesIO
from tqdm import tqdm
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.print_page_options import PrintOptions


def setup_driver(browser: str="edge"):
    """Get a Selenium WebDriver instance for the specified browser."""
    if browser == "edge":
        from selenium.webdriver.edge.options import Options as EdgeOptions
        options = EdgeOptions()
        options.add_experimental_option("detach", True)
        options.add_argument("--headless=new")
        driver = webdriver.Edge(options=options)
        return driver
    else:
        raise ValueError("Unsupported browser")


def apply_custom_css(driver):
    """Injects custom styles better suited for printing."""
    css_rules = """
    @media print {
        @page {
            size: A4 portrait;
            margin: 1cm;
        }
        ::-webkit-scrollbar {
            display: none;
        }
        a.skip-link {
            display: none;
        }
    }
    """
    script = f"""
    var style = document.createElement('style');
    style.innerHTML = `{css_rules}`;
    document.head.appendChild(style);
    """
    driver.execute_script(script)


def expand_collapsible(driver) -> None:
    """
    Expands collapsible sections on the page if their first three words 
    do not contain the keyword 'reference'.
    """
    expand_script = r"""
    document.querySelectorAll('details').forEach(function(el) {
        const textContent = el.textContent.trim().split(/\s+/).slice(0, 3).join(' ').toLowerCase();
        if (!textContent.includes('reference')) {
            el.setAttribute('open', 'true');
        }
    });
    """
    driver.execute_script(expand_script)


def get_doc_page_urls(driver, base_url: str) -> list[tuple[str, str]]:
    """
    Retrieve documentation page URLs from a navigation element on the base page.

    This example assumes that documentation links are inside <nav> elements.
    """
    driver.get(base_url)
    time.sleep(2)  # Wait for the page to initialize any FE elements.
    expand_collapsible(driver)
    links = get_index_links(driver)
    urls = [
        (link.text ,link.get_attribute("href")) for link in links if link.get_attribute("href") and link.text != ""
    ]
    # Deduplication is needed when links refer to the same page but different section
    duplicated_urls = list(OrderedDict.fromkeys(urls))
    return duplicated_urls


def get_index_links(driver):
    """Retrieve all links from the navigation element on the base page.

    Different websites have different ways of representing navigation elements.
    We try different selectors until one works.
    """
    selectors = ["#pst-primary-sidebar a",]

    for selectors in selectors:
        links = driver.find_elements("css selector", selectors)
        if links:
            return links
    return []

def generate_cover_page(title):
    current_date = datetime.now().strftime("%Y-%m-%d")
    cover_html = f"""
    <html>
      <head><meta charset="utf-8"><title>Cover</title></head>
      <body style="text-align:center; margin-top:200px;">
        <h1>{title}</h1>
        <p>Documentation PDF</p>
        <p>Date: {current_date}</p>
      </body>
    </html>
    """
    return cover_html


def generate_index_page(urls):
    index_html = """
    <html>
      <head><meta charset="utf-8"><title>Index</title></head>
      <body>
        <h2>Index</h2>
        <ul>
    """
    for url in urls:
        index_html += f"<li>{url}</li>"
    index_html += """
        </ul>
      </body>
    </html>
    """
    return index_html

def print_pdf_page(driver, pdf_params) -> bytes:
    """
    Use Selenium’s print_page method to export the currently loaded page to PDF.
    This method returns PDF bytes.
    Note: This requires a Selenium version (and browser driver) that supports print_page.
    """
    pdf_base64 = driver.print_page(pdf_params)
    pdf_bytes = base64.b64decode(pdf_base64)
    return pdf_bytes

def print_html_to_pdf(driver, html, print_options):
    """
    Load an HTML string via a data URL and export it to PDF.
    """
    encoded_html = urllib.parse.quote(html)
    driver.get("data:text/html;charset=utf-8," + encoded_html)
    time.sleep(1)  # Wait for the page to render.
    return print_pdf_page(driver, print_options)


def get_print_options():
    # The printing format is A4. Some browsers seem to be having problems with the native Selenium way
    # passing the size, so we're hardcoding the size instead.
    print_options = PrintOptions()
    print_options.background = True
    print_options.scale = 0.9
    print_options.orientation = "portrait"
    print_options.set_page_size({"height": 29.7, "width": 21.0})  # A4
    print_options.margin_top = 0.5
    print_options.margin_bottom = 0.5
    print_options.margin_left = 0.5
    print_options.margin_right = 0.5
    return print_options


def get_pages_as_pdf(driver, page_urls, print_options):
    page_urls = page_urls[:2]
    pages = list()
    for name, url in tqdm(page_urls, desc="Processing pages", unit="page", dynamic_ncols=True):
        driver.get(url)
        time.sleep(2)  # Wait for the page to load.
        expand_collapsible(driver)
        apply_custom_css(driver)
        page_pdf = print_pdf_page(driver, print_options)
        pages.append(page_pdf)
    return pages


def get_index_pdf(driver, page_urls, print_options):
    index_html = generate_index_page(page_urls)
    index_pdf = print_html_to_pdf(driver, index_html, print_options)
    return index_pdf


def merge_pdfs_to(pdf_pages: list[bytes], output_path: str) -> None:
    """
    Merge the PDF documents by concatenating them.

    This function uses PyPDF2 to append each PDF (from memory) into one final PDF,
    preserving the original layout and formatting.
    """

    merger = PdfMerger()
    for pdf_data in pdf_pages:
        merger.append(BytesIO(pdf_data))

    if os.path.exists(output_path):
        os.remove(output_path)

    with open(output_path, "wb") as out_file:
        merger.write(out_file)
    merger.close()


def main():
    args = configure_cli()

    print("Step 1 of 3: Analyzing website...")
    driver = setup_driver()
    page_urls = get_doc_page_urls(driver, args.url)
    print(f"Found {len(page_urls)} pages.")
    
    print_options = get_print_options()
    
    pdf_pages = [get_cover_pdf(driver, print_options)]

    print("Step 2 of 3: Generating PDFs...")
    pdf_pages.extend(get_pages_as_pdf(driver, page_urls, print_options))

    # Export the index page.
    pdf_pages.insert(1, get_index_pdf(driver, page_urls, print_options))
    driver.quit()

    output_pdf_path = os.path.abspath("documentation_merged.pdf")

    print("Step 3 of 3: Merging documents...")
    merge_pdfs_to(pdf_pages, output_pdf_path)
    print(f"Merged PDF saved to {output_pdf_path}")
    print("DONE")


def get_cover_pdf(driver, print_options):
    title = "Project documentation"
    try:
        meta_tag = driver.find_element("css selector", 'meta[property="og:site_name"]')
        title = meta_tag.get_attribute("content") or title
    except:
        pass
    cover_html = generate_cover_page(title)
    cover_pdf = print_html_to_pdf(driver, cover_html, print_options)
    return cover_pdf


def configure_cli() -> argparse.Namespace:
    """
    Parse and return command-line arguments.

    Returns:
        argparse.Namespace: Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Export online documentation as a single PDF"
    )
    parser.add_argument("url", help="URL of the documentation homepage")
    return parser.parse_args()


if __name__ == "__main__":
    main()
