#!/usr/bin/env python3
"""
process_invoice.py – v3.2

• Detects header‑less CSVs (injects fallback header).
• Accepts DEC/DEC. as description header.
• Fuzzy‑matches descriptions to customs PDF.
• Extracts duty as '15', '15.00', '15%' or '15 %'.
"""
from __future__ import annotations
import argparse, csv, pathlib, re, sys, itertools, io
from typing import Dict, List

import pandas as pd
import pdfplumber
from rapidfuzz import fuzz, process as rf_process

NUM_RE = re.compile(r'[^0-9.]+')
PAIR_DUTY_RE = re.compile(r'\b(\d{1,2})(?:\s?%|\s?\.0{1,2})?\b')

COL_KEYWORDS = {
    "duty": ["duty", "tariff", "rate"],
    "unit price": ["unit price", "price", "item price", "price/unit"],
    "qty": ["qty", "quantity", "units", "pcs"],
    "description": ["description", "product", "item", "dec", "dec."],
}

FALLBACK_HEADER = ["C/NO.", "CODE", "DEC.", "QTY", "UNIT PRICE", "AMOUNT"]

def smart_float(val)->float:
    return float(NUM_RE.sub("", str(val)) or 0)

def normalise(txt:str)->str:
    return re.sub(r'[^a-z0-9 ]+', ' ', txt.lower()).strip()

def looks_like_header(row:List[str])->bool:
    tokens=sum(COL_KEYWORDS.values(),[])
    return any(any(tok in normalise(c) for tok in tokens) for c in row)

def read_invoice(path:pathlib.Path):
    with path.open(newline='',encoding='utf-8-sig') as f:
        raw=list(csv.reader(f))
    if not raw:
        sys.exit("Invoice CSV empty.")
    if looks_like_header(raw[0]):
        reader=csv.DictReader(io.StringIO("\n".join(",".join(r) for r in raw)))
        return list(reader), reader.fieldnames or []
    reader=csv.DictReader(itertools.chain([FALLBACK_HEADER], raw))
    return list(reader), reader.fieldnames or []

def find_col(headers:List[str], logical:str)->str:
    for h in headers:
        if any(k in normalise(h.replace('_',' ')) for k in COL_KEYWORDS[logical]):
            return h
    raise SystemExit(f"Missing '{logical}' column – looked for {COL_KEYWORDS[logical]} in {headers}")

def parse_factor_flags(flags:List[str])->Dict[int,float]:
    d={}
    for f in flags:
        if '=' not in f: raise ValueError("Bad --factor flag")
        k,v=f.split('=',1)
        d[int(float(k))]=float(v)
    return d

def parse_customs_pdf(pdf:pathlib.Path)->Dict[str,int]:
    mapping={}
    with pdfplumber.open(str(pdf)) as doc:
        for page in doc.pages:
            for line in (page.extract_text() or "").splitlines():
                m=PAIR_DUTY_RE.search(line)
                if not m: continue
                duty=int(m.group(1))
                desc=normalise(line[:m.start()])
                if len(desc)>=3: mapping[desc]=duty
    if not mapping:
        raise SystemExit("No description→duty pairs in worksheet.")
    return mapping

def best_match(desc:str, ref:Dict[str,int], thr:int=70):
    if not desc: return None
    res=rf_process.extractOne(normalise(desc), ref.keys(), scorer=fuzz.token_set_ratio)
    if res and res[1]>=thr: return ref[res[0]]
    return None

def process_invoice(inv:pathlib.Path, pdf:pathlib.Path, out:pathlib.Path, factors:Dict[int,float]):
    rows, headers = read_invoice(inv)
    price_col=find_col(headers,"unit price")
    qty_col  =find_col(headers,"qty")
    desc_col =find_col(headers,"description")
    duty_col =find_col(headers,"duty") if any(normalise(h).startswith("duty") for h in headers) else "duty"
    if duty_col not in headers: headers.append(duty_col)
    ref_map=parse_customs_pdf(pdf)

    for r in rows:
        duty=int(float(NUM_RE.sub("", r.get(duty_col,"")) or 0))
        if duty==0:
            duty=best_match(r.get(desc_col,""), ref_map) or 0
        if duty not in factors:
            raise SystemExit(f"No factor for duty {duty}% (desc: {r.get(desc_col)[:40]})")
        r[duty_col]=duty
        factor=factors[duty]
        value=round(smart_float(r[price_col])*factor,2)
        total=round(value*smart_float(r[qty_col]),2)
        r["factor"]=factor
        r["value"]=f"{value:.2f}"
        r["total"]=f"{total:.2f}"
    for col in ("factor","value","total"):
        if col not in headers: headers.append(col)
    with out.open("w",newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=headers)
        w.writeheader(); w.writerows(rows)
    print(f"✓ Processed {len(rows)} rows → {out}")

def main():
    ap=argparse.ArgumentParser(description="Proto invoice processor v3.2")
    ap.add_argument("--invoice",required=True,type=pathlib.Path)
    ap.add_argument("--worksheet",required=True,type=pathlib.Path)
    ap.add_argument("-o","--output",required=True,type=pathlib.Path)
    ap.add_argument("--factor",action='append',default=[])
    args=ap.parse_args()
    factors=parse_factor_flags(args.factor)
    if not factors: sys.exit("At least one --factor required.")
    process_invoice(args.invoice,args.worksheet,args.output,factors)

if __name__=="__main__":
    main()
