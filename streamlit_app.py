# streamlit_app.py – Proto Trading landed‑cost calculator front‑end
# Upload invoice + customs worksheet; enter factors; download processed CSV.

import tempfile, pathlib, textwrap, streamlit as st
from process_invoice import process_invoice, parse_factor_flags

st.set_page_config(page_title="Proto Invoice Tool", page_icon="📦")
st.title("📦 Proto Trading – Landed‑Cost Calculator (auto‑duty)")

st.markdown(textwrap.dedent("""
1. **Upload invoice CSV** and the **Customs worksheet PDF** for the same shipment.  
2. Enter *every* duty→factor pair below (0 %, 15 %, 20 %, etc.).  
3. Click **Process** and download your fully‑costed CSV.
"""))

inv_file  = st.file_uploader("Invoice CSV", type=["csv"])
ws_file   = st.file_uploader("Customs worksheet PDF", type=["pdf"])

st.subheader("Duty → Factor mappings (one per line, e.g. `15=25.91`)")
factor_text = st.text_area("Overrides", "", height=120)

if st.button("🚀 Process"):

    if not inv_file or not ws_file:
        st.error("Please upload both the invoice CSV and customs PDF.")
        st.stop()

    if not factor_text.strip():
        st.error("Enter at least one duty=factor mapping.")
        st.stop()

    tmpdir = tempfile.TemporaryDirectory()
    inv_path = pathlib.Path(tmpdir.name) / "invoice.csv"
    ws_path  = pathlib.Path(tmpdir.name) / "worksheet.pdf"

    inv_path.write_bytes(inv_file.getbuffer())
    ws_path.write_bytes(ws_file.getbuffer())

    try:
        factors = parse_factor_flags([l for l in factor_text.splitlines() if l.strip()])
    except ValueError as e:
        st.error(str(e)); st.stop()

    out_path = pathlib.Path(tmpdir.name) / "processed.csv"
    try:
        process_invoice(inv_path, ws_path, out_path, factors)
    except SystemExit as e:
        st.error(str(e)); st.stop()

    st.success("✅ Done! Download below.")
    st.download_button("📥 Download processed CSV", data=out_path.read_bytes(),
                       file_name="processed_invoice.csv", mime="text/csv")
