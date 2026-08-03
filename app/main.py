"""Streamlit entry point for RetailFlow Analytics."""

import streamlit as st


def main() -> None:
    """Render the initial RetailFlow Analytics application page."""
    st.set_page_config(page_title="RetailFlow Analytics", page_icon="📊")
    st.title("RetailFlow Analytics")
    st.info("The application is under active development.")


if __name__ == "__main__":
    main()
