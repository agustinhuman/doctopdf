# webdocstopdf

**webdocstopdf** is a CLI tool that exports online documentation (which may span multiple pages) to a merged PDF file. It uses Selenium to capture each page as a PDF and then concatenates them into a single PDF file with a cover and index. 

## Features

- **Multi-page Export:** Exports a cover page, index, and all documentation pages.
- **Full browser rendering:** Uses a fully fledged browser to render pdfs.
- **Custom CSS:** Applies custom stylesheets to mitigate common anoyances while printing, like having visible scrollbars or collapsible elements not expanded.
- **Easy Merging:** Concatenates PDFs to preserve layout and formatting.

## Installation

Install directly from PyPI:

```bash
pip install webdocstopdf
```

## TODO

- Allow setting the output path
- Admit other drivers
- Add tests
- Strip section data from url before deduplication
