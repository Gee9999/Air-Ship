#!/usr/bin/env python3
"""
process_invoice.py – v3.3  (multi‑line customs PDF support)

• Handles header‑less CSVs, DEC. header, wide duty formats (15, 15.00, 15 %, 15%).
• NEW: Many customs worksheets put the DESCRIPTION on **one line** and the
  DUTY (e.g. “15%” or “FREE”) on the **next** line.  This version captures that
  pattern:

      49081090               ← HS code (ignored)
      PATCHES                ← line remembered as description
      15%                    ← next non‑blank line → duty 15 % for “PATCHES”

  If the duty line is the word “FREE”, it is treated as 0 %.
"""
from __future__ import annotations
import argparse, csv, pathlib, re, sys, itertools, io
from typing import Dict, List

import pdfplumber
from rapidfuzz import fuzz, process as rf_process

NUM_RE = re.compile(r'[^0-9.]+')
DUTY_PAT = re.compile(r'\b(\d{1,2})(?:\s?%|\s?\.0{1,2})?\b')
FREE_PAT = re.compile(r'\bFREE\b', re.I)

COL_KEYWORDS = {
    "duty": ["duty", "tariff", "rate"],
    "unit price": ["unit price", "price", "item price", "price/unit"],
    "qty": ["qty", "quantity", "units", "pcs"],
    "description": ["description", "product", "item", "dec", "dec."],
}
FALLBACK_HEADER = ["C/NO.", "CODE", "DEC.", "QTY", "UNIT PRICE", "AMOUNT"]

def smart_float(v): return float(NUM_RE.sub("", str(v)) or 0)
def norm(t:str):   return re.sub(r'[^a-z0-9 ]+',' ',t.lower()).strip()
def header_like(r): return any(any(k in norm(c) for k in sum(COL_KEYWORDS.values(), [])) for c in r)

def read_invoice(p:pathlib.Path):
    rows=list(csv.reader(p.open(encoding='utf-8-sig')))
    if not rows: sys.exit("Invoice CSV empty.")
    if header_like(rows[0]):
        rdr=csv.DictReader(io.StringIO("\n".join(",".join(r) for r in rows)))
    else:
        rdr=csv.DictReader(itertools.chain([FALLBACK_HEADER], rows))
    return list(rdr), rdr.fieldnames or []

def find_col(hdr:List[str], key:str)->str:
    for h in hdr:
        if any(k in norm(h.replace('_',' ')) for k in COL_KEYWORDS[key]): return h
    raise SystemExit(f"Missing '{key}' column – looked for {COL_KEYWORDS[key]} in {hdr}")

def parse_factor_flags(flags:List[str])->Dict[int,float]:
    m={}
    for f in flags:
        if '=' not in f: raise ValueError("Bad --factor flag")
        k,v=f.split('=',1); m[int(float(k))]=float(v)
    return m

def parse_customs_pdf(pdf:pathlib.Path)->Dict[str,int]:
    mapping={}
    with pdfplumber.open(str(pdf)) as doc:
        prev_desc=""
        for page in doc.pages:
            for raw in (page.extract_text() or "").splitlines():
                line=raw.strip()
                if not line: continue
                # duty on same line?
                dm=DUTY_PAT.search(line) or FREE_PAT.search(line)
                if dm and prev_desc:
                    duty = 0 if dm.re is FREE_PAT or dm.group(0).upper()=="FREE" else int(dm.group(1))
                    mapping[norm(prev_desc)] = duty
                    prev_desc=""   # reset
                    continue
                # look for duty in same line as desc
                m=DUTY_PAT.search(line) or FREE_PAT.search(line)
                if m:
                    duty = 0 if m.re is FREE_PAT or m.group(0).upper()=="FREE" else int(m.group(1))
                    desc = norm(line[:m.start()])
                    if desc: mapping[desc]=duty
                else:
                    # line might just be description
                    if any(ch.isalpha() for ch in line):
                        prev_desc=line
    if not mapping:
        raise SystemExit("Could not extract description→duty pairs from worksheet.")
    return mapping

def best_match(desc:str, ref:Dict[str,int], thr:int=70):
    if not desc: return None
    res=rf_process.extractOne(norm(desc), ref.keys(), scorer=fuzz.token_set_ratio)
    if res and res[1]>=thr: return ref[res[0]]
    return None

def process_invoice(inv:pathlib.Path, pdf:pathlib.Path, out:pathlib.Path, factors:Dict[int,float]):
    rows, hdr = read_invoice(inv)
    price=find_col(hdr,"unit price"); qty=find_col(hdr,"qty"); desc=find_col(hdr,"description")
    duty=find_col(hdr,"duty") if any(norm(h).startswith("duty") for h in hdr) else "duty"
    if duty not in hdr: hdr.append(duty)
    ref=parse_customs_pdf(pdf)

    for r in rows:
        d=int(float(NUM_RE.sub("", r.get(duty,"")) or 0))
        if d==0: d=best_match(r.get(desc,""), ref) or 0
        if d not in factors: raise SystemExit(f"No factor for duty {d}% near '{r.get(desc)[:40]}'")
        r[duty]=d; f=factors[d]; val=round(smart_float(r[price])*f,2); tot=round(val*smart_float(r[qty]),2)
        r["factor"]=f; r["value"]=f"{val:.2f}"; r["total"]=f"{tot:.2f}"
    for extra in ("factor","value","total"):
        if extra not in hdr: hdr.append(extra)
    with out.open("w",newline='',encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=hdr); w.writeheader(); w.writerows(rows)
    print(f"✓ Processed {len(rows)} rows → {out}")

def main():
    ap=argparse.ArgumentParser(description="Proto invoice processor v3.3")
    ap.add_argument("--invoice",required=True,type=pathlib.Path)
    ap.add_argument("--worksheet",required=True,type=pathlib.Path)
    ap.add_argument("-o","--output",required=True,type=pathlib.Path)
    ap.add_argument("--factor",action='append',default=[])
    a=ap.parse_args(); fac=parse_factor_flags(a.factor)
    if not fac: sys.exit("Need at least one --factor")
    process_invoice(a.invoice,a.worksheet,a.output,fac)

if __name__=="__main__": main()
