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
import yaml
import re
import fnmatch

from selenium import webdriver
from selenium.webdriver.common.print_page_options import PrintOptions


def setup_driver(browser: str = None):
    """Get a Selenium WebDriver instance for the specified browser."""
    if browser is None:
        browser = "chrome"

    if browser == "edge":
        from selenium.webdriver.edge.options import Options as EdgeOptions
        options = EdgeOptions()
        options.add_argument("--headless=new")
        driver = webdriver.Edge(options=options)
        return driver
    elif browser == "chrome":
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        import undetected_chromedriver as uc
        from selenium_stealth import stealth

        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.6998.35 Safari/537.36"
        chrome_options = uc.ChromeOptions()
        #chrome_options.add_argument('--headless=new')
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("user-agent={}".format(user_agent))
        driver = uc.Chrome(options=chrome_options)
        stealth(driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True
                )
        return driver
    else:
        raise ValueError("Unsupported browser. Supported browsers: 'edge', 'chrome'")


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

        
        * {
            overflow: hidden !important;
            scrollbar-width: none !important;
        }
        
        
        a.skip-link,
        .layers-root,
        .md-consent,
        .giscus,
        .md-code__nav{
            display: none !important;
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


def read_links_from_file(file_path: str, selector=None) -> list[tuple[str, str]]:
    """Reads links from a YAML file."""

    def list_to_pair(data):
        return [("", item) for item in data]

    if os.path.isfile(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as yaml_file:
                data = yaml.safe_load(yaml_file)
                if isinstance(data, list):
                    return list_to_pair(data)
                elif isinstance(data, dict):
                    if selector is None:
                        return list_to_pair([item for sublist in data.values() for item in sublist])
                    elif selector:
                        matching_keys = [key for key in data.keys() if fnmatch.fnmatch(key, selector)]
                        merged_values = [item for key in matching_keys for item in data[key]]
                        return list_to_pair(merged_values)
                raise ValueError("Invalid YAML structure: Expected list or dict of lists.")
        except Exception as e:
            raise ValueError(f"Error loading YAML file '{file_path}': {e}")
    else:
        raise ValueError(f"The input parameter appears to be a YAML file, but the file does not exist.")


def get_doc_page_urls(driver, input_path: str, selector: None) -> list[tuple[str, str]]:
    """
    Retrieve documentation page URLs from a navigation element on the base page.

    This example assumes that documentation links are inside <nav> elements.
    """

    from_file = input_path.lower().endswith((".yaml", ".yml"))
    if from_file:
        links = read_links_from_file(input_path, selector)
    else:
        links = read_links_from_web(driver, input_path, selector)
    
    deduplicated_links = remove_duplicates(links)
    return deduplicated_links


def remove_duplicates(links):
    urls = []
    urls_set = set()
    for (name, url) in links:
        url = url.split("#")[0]
        
        if url in urls_set:
            continue
        urls_set.add(url)
        urls.append((name, url))
    return urls


def read_links_from_web(driver, input_path: str, selector: str = None):
    """Retrieve all links from the navigation element on the base page.

    Different websites have different ways of representing navigation elements.
    We try different selectors until one works.
    """
    driver.get(input_path)
    input("Make sure the website content is cleary accesible. Press Enter to continue...")
    expand_collapsible(driver)
    selectors = [".sidebar-primary-item nav a", ".side-nav-section a", "nav a"]

    links = []
    for selectors in selectors:
        links_detected = driver.find_elements("css selector", selectors)
        if links_detected:
            links = links_detected
            break
    urls = []
    base_domain = urllib.parse.urlparse(input_path).netloc
    for link in links:
        text = link.get_attribute("text") or ""
        href = link.get_attribute("href")

        if href and text != "" and urllib.parse.urlparse(href).netloc == base_domain:
            urls.append((text, href))
    return urls

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
        <h2>Table of contents</h2>
        <ul>
    """
    for url in urls:
        index_html += f"<li>{url[0]} - {url[1]}</li>"
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
    page_urls = page_urls[:]
    pages = list()
    for name, url in tqdm(page_urls, desc="Processing pages", unit="page", dynamic_ncols=True):
        driver.get(url)
        time.sleep(1)  # Wait for the page to load.
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
    for pdf_data in tqdm(pdf_pages, desc="Merging pages", unit="page", dynamic_ncols=True):
        merger.append(BytesIO(pdf_data))

    if os.path.exists(output_path):
        os.remove(output_path)

    with open(output_path, "wb") as out_file:
        merger.write(out_file)
    merger.close()


def main():
    args = configure_cli()

    print("Step 1 of 3: Analyzing website...")
    driver = setup_driver(args.browser)
    page_urls = get_doc_page_urls(driver, args.input, args.selector)
    print(f"Found {len(page_urls)} pages.")
    
    print_options = get_print_options()
    
    pdf_pages = [
        get_cover_pdf(driver, print_options, args.title),
        get_index_pdf(driver, page_urls, print_options)
    ]

    print("Step 2 of 3: Generating PDFs...")
    pdf_pages.extend(get_pages_as_pdf(driver, page_urls, print_options))
    
    driver.quit()

    output_pdf_path = os.path.abspath(args.output)

    print("Step 3 of 3: Merging documents...")
    merge_pdfs_to(pdf_pages, output_pdf_path)
    print(f"Merged PDF saved to {output_pdf_path}")
    print("DONE")


def get_cover_pdf(driver, print_options, title: str = ""):
    if title == "":
        # Try to guess from the website meta
        selectors = ['meta[property="og:site_name"]', 'meta[property="og:title']
        for selector in selectors:
            try:
                meta_tag = driver.find_element("css selector", selector)
                title = meta_tag.get_attribute("content")
            except:
                continue
            if title != "":
                break
    if title == "":
        title = "Documentation"

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
    parser.add_argument("input", help="URL of the documentation homepage or a YAML document with links")
    parser.add_argument(
        "output",
        nargs="?",
        help="Filename for the merged PDF. Defaults to 'documentation_merged.pdf' in the current directory.",
        default="documentation_merged.pdf",
    )
    parser.add_argument(
        "--browser", "-b",
        help="Browser to use for generating PDFs",
        choices=["chrome", "edge"],
        default="chrome",
    )

    parser.add_argument(
        "--selector", "-s",
        help="Asks to tool to only use the links for a particular key on the YAML file.",
        default=None,
    )

    parser.add_argument(
        "--title", "-t",
        help="Optionally pass a custom title for the cover.",
        default="Documentation",
    )

    return parser.parse_args()


if __name__ == "__main__":
    main()
