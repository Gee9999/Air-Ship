#!/usr/bin/env python3
"""process_invoice.py – v3.0.1
Now recognises 'DEC.' or 'DEC' as the description column.
"""

from __future__ import annotations
import argparse, csv, pathlib, re, sys
from typing import Dict, List

import pandas as pd
import pdfplumber
from rapidfuzz import fuzz, process as rf_process

NUM_RE = re.compile(r'[^0-9.]+')
PAIR_DUTY_RE = re.compile(r'\b(\d{1,2})\s?%\b')

COL_KEYWORDS = {
    "duty": ["duty", "tariff", "rate"],
    "unit price": ["unit price", "price", "item price", "price/unit"],
    "qty": ["qty", "quantity", "units", "pcs"],
    # Added 'dec' and 'dec.' so it matches your CSV header
    "description": ["description", "product", "item", "dec", "dec."],
}

def smart_float(val) -> float:
    return float(NUM_RE.sub("", str(val)) or 0)

def normalise(txt: str) -> str:
    return re.sub(r'[^a-z0-9 ]+', ' ', str(txt).lower()).strip()

def find_col(headers: List[str], logical: str) -> str:
    kws = COL_KEYWORDS[logical]
    for h in headers:
        h2 = normalise(h.replace("_", " "))
        if any(k in h2 for k in kws):
            return h
    raise SystemExit(f"Missing '{logical}' column – looked for {kws} in {headers}")

def parse_factor_flags(flags: List[str]) -> Dict[int, float]:
    mapping: Dict[int, float] = {}
    for item in flags:
        if "=" not in item:
            raise ValueError(f"Bad --factor '{item}', expected DUTY=FACTOR")
        k, v = item.split("=", 1)
        mapping[int(float(k))] = float(v)
    return mapping

def parse_customs_pdf(pdf_path: pathlib.Path) -> Dict[str, int]:
    duty_map: Dict[str, int] = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                m = PAIR_DUTY_RE.search(line)
                if not m:
                    continue
                duty = int(m.group(1))
                desc = normalise(line[:m.start()])
                if len(desc) < 4:
                    continue
                duty_map[desc] = duty
    if not duty_map:
        raise SystemExit("Could not extract description→duty pairs from worksheet.")
    return duty_map

def best_match(desc: str, ref: Dict[str, int], threshold: int = 70) -> int | None:
    if not desc:
        return None
    res = rf_process.extractOne(normalise(desc), ref.keys(), scorer=fuzz.token_set_ratio)
    if res and res[1] >= threshold:
        return ref[res[0]]
    return None

def process_invoice(inv: pathlib.Path, pdf: pathlib.Path, out: pathlib.Path,
                    factors: Dict[int, float]):
    with inv.open(newline="", encoding="utf-8-sig") as f:
        rdr = csv.DictReader(f)
        rows = list(rdr)
        headers = rdr.fieldnames or []
    if not rows:
        sys.exit("Invoice CSV empty.")

    price_col = find_col(headers, "unit price")
    qty_col   = find_col(headers, "qty")
    desc_col  = find_col(headers, "description")
    duty_col  = find_col(headers, "duty") if any(normalise(h).startswith("duty") for h in headers) else "duty"
    if duty_col not in headers:
        headers.append(duty_col)

    ref_map = parse_customs_pdf(pdf)

    for r in rows:
        duty = int(float(NUM_RE.sub("", r.get(duty_col, "")) or 0))
        if duty == 0:
            duty = best_match(r.get(desc_col, ""), ref_map) or 0
        if duty not in factors:
            raise SystemExit(f"No factor for duty {duty}% (desc: {r.get(desc_col)[:40]})")
        r[duty_col] = duty
        factor = factors[duty]
        value  = round(smart_float(r[price_col]) * factor, 2)
        total  = round(value * smart_float(r[qty_col]), 2)
        r["factor"] = factor
        r["value"]  = f"{value:.2f}"
        r["total"]  = f"{total:.2f}"

    for extra in ("factor", "value", "total"):
        if extra not in headers:
            headers.append(extra)

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)
    print(f"✓ Processed {len(rows)} rows → {out}")

def main():
    ap = argparse.ArgumentParser(description="Proto invoice processor v3.0.1")
    ap.add_argument("--invoice", required=True, type=pathlib.Path)
    ap.add_argument("--worksheet", required=True, type=pathlib.Path)
    ap.add_argument("-o", "--output", required=True, type=pathlib.Path)
    ap.add_argument("--factor", action="append", default=[])
    args = ap.parse_args()
    factors = parse_factor_flags(args.factor)
    if not factors:
        sys.exit("At least one --factor required.")
    process_invoice(args.invoice, args.worksheet, args.output, factors)

if __name__ == "__main__":
    main()
