import os
import requests
from dotenv import load_dotenv
from llama_cloud_services import LlamaParse
from markdownify import markdownify as md

# Load environment variables from the project's .env file
# This path navigates up one level from 'ingestion' to the project root.
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=dotenv_path)

def html_to_markdown(url: str) -> str | None:
    """
    Convert HTML content from a given URL to Markdown format.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
        html_content = response.text
        markdown_text = md(html_content, heading_style="ATX")
        return markdown_text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching the URL: {e}")
        return None

def parse_pdf(file_path: str) -> str | None:
    """
    Parses a PDF file using LlamaParse and returns its content as a markdown string.
    """
    api_key = os.environ.get("LLAMAPARSE_API")
    if not api_key:
        print("Error: LLAMAPARSE_API key not found in environment variables.")
        return None

    try:
        parser = LlamaParse(
            api_key=api_key,
            parse_mode="parse_page_with_llm",
            high_res_ocr=True,
            adaptive_long_table=True,
            outlined_table_extraction=True,
            output_tables_as_HTML=True,
        )
        print(f"Starting to parse {file_path}...")
        result = parser.parse(file_path)
        print("Parsing complete.")
        markdown_documents = result.get_markdown_documents(split_by_page=True)
        full_markdown = "\n".join(doc.text for doc in markdown_documents)
        return full_markdown
    except Exception as e:
        print(f"An error occurred during PDF parsing: {e}")
        return None

if __name__ == '__main__':
    # This example block is for testing the parsing functions directly.
    print("\n--- Testing PDF parsing ---")
    pdf_file_path = "/Users/himanshu/projects/journalling-assitant/Books/Medium Discourses/Middle-Discourses-sujato-2025-08-25-1.pdf"
    if os.path.exists(pdf_file_path):
        pdf_markdown_content = parse_pdf(pdf_file_path)
        if pdf_markdown_content:
            output_filename = 'parsed_pdf_from_script.md'
            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write(pdf_markdown_content)
            print(f"Successfully parsed PDF to '{output_filename}'")
        else:
            print("PDF parsing failed.")
    else:
        print(f"Error: PDF file not found at '{pdf_file_path}'")