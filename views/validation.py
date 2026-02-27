"""
Validation page.

UI entrypoint for chunk/TOC integrity validation.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import streamlit as st

from scripts.validate_chunk_toc_integrity import (
    FAIL,
    PASS,
    WARN,
    execute_validation,
    render_markdown_report,
    summarize_document_checks,
)

MODE_RANDOM = "Random sample"
MODE_SINGLE = "Single document"
MODE_MULTIPLE = "Multiple documents"


def _inject_styles() -> None:
    """Inject page-local styles for validation reporting."""
    st.markdown(
        """
        <style>
        .validation-banner {
            border: 1px solid #c7d2fe;
            background: linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%);
            border-radius: 12px;
            padding: 12px 14px;
            margin-bottom: 12px;
        }
        .validation-banner p {
            margin: 0;
            color: #1e293b;
            font-size: 0.95rem;
        }
        .validation-badge {
            display: inline-block;
            border-radius: 999px;
            padding: 2px 10px;
            font-size: 0.75rem;
            border: 1px solid transparent;
            font-weight: 600;
            margin-left: 8px;
        }
        .validation-badge.pass {
            color: #065f46;
            background: #d1fae5;
            border-color: #a7f3d0;
        }
        .validation-badge.warn {
            color: #92400e;
            background: #fef3c7;
            border-color: #fde68a;
        }
        .validation-badge.fail {
            color: #991b1b;
            background: #fee2e2;
            border-color: #fecaca;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _badge_html(status: str) -> str:
    """Return status badge HTML."""
    css_class = {
        PASS: "pass",
        WARN: "warn",
        FAIL: "fail",
    }.get(status, "warn")
    return f"<span class='validation-badge {css_class}'>{status}</span>"


def _parse_doc_ids(raw_ids: str) -> tuple[list[int], str | None]:
    """Parse comma/newline/space-separated doc IDs."""
    tokens = [token.strip() for token in re.split(r"[\s,]+", raw_ids.strip()) if token.strip()]
    if not tokens:
        return [], "Please provide at least one document ID."

    parsed: list[int] = []
    for token in tokens:
        if not token.isdigit():
            return [], f"Invalid document ID '{token}'. Use numeric IDs only."
        parsed.append(int(token))

    return sorted(set(parsed)), None


def _render_how_to_run() -> None:
    """Show CLI commands for validator and tests."""
    with st.expander("How To Run From CLI", expanded=False):
        st.code(
            "poetry run python scripts/validate_chunk_toc_integrity.py \\\n"
            "  --sample-size 5 --seed 42 --chunk-sample-per-doc 3 \\\n"
            "  --check-embeddings --output reports/chunk_toc_validation.md",
            language="bash",
        )
        st.code(
            "poetry run pytest tests/test_chunk_toc_validation.py",
            language="bash",
        )


def _render_summary_cards(result: dict[str, Any]) -> None:
    """Render global summary metrics."""
    summary = result["summary"]
    verdicts = summary["doc_verdict_counts"]
    checks = summary["global_check_counts"]

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Documents", summary["documents_analyzed"])
    col2.metric("Doc PASS", verdicts[PASS])
    col3.metric("Doc WARN", verdicts[WARN])
    col4.metric("Doc FAIL", verdicts[FAIL])
    col5.metric("Checks", summary["global_check_count"])
    col6.metric("Check WARN", checks[WARN])


def _build_doc_table_rows(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build compact per-document summary table rows."""
    rows: list[dict[str, Any]] = []
    for doc in documents:
        counts = summarize_document_checks(doc["checks"])
        rows.append(
            {
                "Doc ID": doc["doc_id"],
                "Title": doc["title"],
                "Verdict": doc["verdict"],
                "Chunks": doc["chunk_stats"]["count"],
                "Similarity": f"{doc['reconstruction']['similarity']:.6f}",
                "Check PASS": counts[PASS],
                "Check WARN": counts[WARN],
                "Check FAIL": counts[FAIL],
            }
        )
    return rows


def _render_document_detail(doc: dict[str, Any]) -> None:
    """Render detailed validation for a single document."""
    counts = summarize_document_checks(doc["checks"])
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Chunks", doc["chunk_stats"]["count"])
    col2.metric("Similarity", f"{doc['reconstruction']['similarity']:.6f}")
    col3.metric("Check WARN", counts[WARN])
    col4.metric("Check FAIL", counts[FAIL])

    tab_checks, tab_chunks, tab_headers = st.tabs(["Checks", "Chunk Samples", "Header Coverage"])

    with tab_checks:
        check_rows = [
            {"Check": check.name, "Status": check.status, "Message": check.message}
            for check in doc["checks"]
        ]
        st.dataframe(check_rows, use_container_width=True, hide_index=True)

    with tab_chunks:
        if doc["chunk_inspections"]:
            chunk_rows = []
            for chunk in doc["chunk_inspections"]:
                chunk_rows.append(
                    {
                        "Chunk Index": chunk["chunk_index"],
                        "Verdict": chunk["verdict"],
                        "Chars": chunk["char_count"],
                        "Words": chunk["word_count"],
                        "Header Paths": ", ".join(chunk["header_paths"]) or "(none)",
                        "Notes": chunk["notes"],
                        "Preview": chunk["preview"],
                    }
                )
            st.dataframe(chunk_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No chunk samples available.")

    with tab_headers:
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Missing Markdown Headers In TOC**")
            if doc["missing_toc_paths"]:
                for path in doc["missing_toc_paths"]:
                    st.code(path)
            else:
                st.success("None")
        with col_b:
            st.markdown("**Extra TOC Paths Not In Markdown**")
            if doc["extra_toc_paths"]:
                for path in doc["extra_toc_paths"]:
                    st.code(path)
            else:
                st.success("None")

        st.markdown("**Chunk Paths Unmatched To Markdown**")
        if doc["unmatched_chunk_paths"]:
            for chunk_index, path in doc["unmatched_chunk_paths"][:50]:
                st.write(f"- chunk `{chunk_index}`: `{path}`")
            if len(doc["unmatched_chunk_paths"]) > 50:
                st.caption(f"... plus {len(doc['unmatched_chunk_paths']) - 50} more")
        else:
            st.success("None")


def _run_validation_unit_tests() -> tuple[int, str]:
    """Run validator unit tests and return (exit_code, output)."""
    repo_root = Path(__file__).resolve().parent.parent
    process = subprocess.run(
        ["poetry", "run", "pytest", "tests/test_chunk_toc_validation.py"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    combined_output = (process.stdout or "") + ("\n" + process.stderr if process.stderr else "")
    return process.returncode, combined_output.strip()


def render() -> None:
    """Render validation page."""
    _inject_styles()
    st.header("Chunk + TOC Validation")
    st.markdown(
        """
        <div class="validation-banner">
            <p>Run chunk ordering, reconstruction, TOC/header coverage, and metadata integrity checks directly from UI.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    mode_col, config_col = st.columns([1, 2])
    with mode_col:
        mode = st.radio(
            "Validation mode",
            [MODE_RANDOM, MODE_SINGLE, MODE_MULTIPLE],
            index=0,
        )

    selected_doc_ids: list[int] | None = None
    sample_size = 5
    seed = 42

    with config_col:
        if mode == MODE_RANDOM:
            c1, c2 = st.columns(2)
            with c1:
                sample_size = int(
                    st.number_input("Sample size", min_value=1, max_value=50, value=5, step=1)
                )
            with c2:
                seed = int(st.number_input("Random seed", min_value=0, value=42, step=1))
        elif mode == MODE_SINGLE:
            single_id = int(st.number_input("Document ID", min_value=1, value=1, step=1))
            selected_doc_ids = [single_id]
            sample_size = 1
        else:
            raw_ids = st.text_area(
                "Document IDs",
                placeholder="Example: 17, 19, 27",
                height=80,
            )
            parsed_ids, parse_error = _parse_doc_ids(raw_ids)
            if parse_error:
                st.warning(parse_error)
            else:
                st.caption(f"Selected {len(parsed_ids)} unique document IDs.")
                selected_doc_ids = parsed_ids
                sample_size = len(parsed_ids)

    c3, c4, c5 = st.columns([1, 1, 2])
    with c3:
        chunk_sample_per_doc = int(
            st.number_input("Chunk samples/doc", min_value=1, max_value=20, value=3, step=1)
        )
    with c4:
        check_embeddings = st.checkbox("Check embeddings", value=False)
    with c5:
        output_path = st.text_input(
            "Markdown output path",
            value="reports/chunk_toc_validation.md",
        )

    run_clicked = st.button("Run Validation", type="primary")
    if run_clicked:
        if mode == MODE_MULTIPLE and not selected_doc_ids:
            st.error("Please provide valid document IDs for Multiple documents mode.")
        else:
            try:
                with st.spinner("Running validation checks..."):
                    result = execute_validation(
                        doc_ids=selected_doc_ids,
                        sample_size=sample_size,
                        seed=seed,
                        chunk_sample_per_doc=chunk_sample_per_doc,
                        check_embeddings=check_embeddings,
                    )
                    markdown_report = render_markdown_report(
                        documents=result["documents"],
                        sampled_doc_ids=result["sampled_doc_ids"],
                        seed=seed,
                        sample_size=sample_size,
                        chunk_sample_per_doc=chunk_sample_per_doc,
                        check_embeddings=check_embeddings,
                    )

                    resolved_path = Path(output_path)
                    resolved_path.parent.mkdir(parents=True, exist_ok=True)
                    resolved_path.write_text(markdown_report, encoding="utf-8")

                    st.session_state.validation_result = result
                    st.session_state.validation_markdown = markdown_report
                    st.session_state.validation_output_path = str(resolved_path)

                summary = result["summary"]
                if summary["has_fail"]:
                    st.error(
                        f"Validation finished with FAIL findings. Report written to {resolved_path}"
                    )
                else:
                    st.success(
                        f"Validation finished with no FAIL findings. Report written to {resolved_path}"
                    )
            except Exception as exc:
                st.error(f"Validation failed: {exc}")

    result = st.session_state.get("validation_result")
    markdown_report = st.session_state.get("validation_markdown")
    saved_path = st.session_state.get("validation_output_path")

    if result:
        st.markdown("---")
        st.subheader("Validation Summary")
        _render_summary_cards(result)

        documents = result["documents"]
        table_rows = _build_doc_table_rows(documents)
        st.dataframe(table_rows, use_container_width=True, hide_index=True)

        st.markdown("### Per-Document Details")
        for doc in documents:
            label = f"[{doc['doc_id']}] {doc['title']}"
            label_html = f"{label} {_badge_html(doc['verdict'])}"
            with st.expander(label, expanded=(doc["verdict"] != PASS)):
                st.markdown(label_html, unsafe_allow_html=True)
                _render_document_detail(doc)

        if markdown_report:
            st.download_button(
                "Download Markdown Report",
                data=markdown_report,
                file_name=Path(saved_path or "chunk_toc_validation.md").name,
                mime="text/markdown",
            )
            with st.expander("Raw Markdown Report", expanded=False):
                st.code(markdown_report, language="markdown")

    _render_how_to_run()

    with st.expander("Developer: Run Validation Unit Tests", expanded=False):
        if st.button("Run tests/test_chunk_toc_validation.py"):
            with st.spinner("Running pytest..."):
                return_code, output = _run_validation_unit_tests()
            if return_code == 0:
                st.success("Unit tests passed.")
            else:
                st.error(f"Unit tests failed with exit code {return_code}.")
            st.code(output or "(no output)", language="text")
