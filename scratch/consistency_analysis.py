import openpyxl
import pandas as pd
from collections import defaultdict
import json

excel_path = r"C:\Users\Darshan\.gemini\antigravity\brain\9283038f-a0e0-4fca-b665-b36c5e21dba1\.user_uploaded\media_1791441452333.xlsx"
wb = openpyxl.load_workbook(excel_path, data_only=True)
ws = wb['Sheet1']

rows = []
for r in range(2, ws.max_row + 1):
    row_data = [ws.cell(row=r, column=c).value for c in range(1, 23)]
    if not any(row_data):
        continue
    rows.append(row_data)

print(f"Total Rows: {len(rows)}")

headers = [
    'wo', 'ts', 'oar', 'cust', 'cust_code', 'uniq_prod_id',
    'part_no', 'internal_part_code', 'internal_id', 'region',
    'grade', 'cust_grade', 'order_type', 'order_cat',
    'po_num', 'del_date', 'po_rate', 'po_qty', 'wo_qty',
    'remarks', 'wo_type', 'status'
]

data = [dict(zip(headers, r)) for r in rows]

# Consistency Checks:
# A. WO without OAR
wo_without_oar = [d for d in data if not d['oar']]
# B. OAR without PO
oar_without_po = [d for d in data if not d['po_num']]
# C. PO without customer
po_without_cust = [d for d in data if not d['cust'] or not d['cust_code']]
# D. WO without PO
wo_without_po = [d for d in data if not d['po_num']]
# E. Duplicate PO numbers
po_counts = defaultdict(list)
for d in data:
    po_counts[str(d['po_num']).strip()].append(d)
# F. Duplicate OAR IDs
oar_counts = defaultdict(list)
for d in data:
    oar_counts[str(d['oar']).strip()].append(d)
# G. Duplicate WO IDs
wo_counts = defaultdict(list)
for d in data:
    wo_counts[str(d['wo']).strip()].append(d)
duplicate_wos = {k: v for k, v in wo_counts.items() if len(v) > 1}

# H. Same WO linked to multiple OARs
wo_multiple_oars = {}
for wo, recs in wo_counts.items():
    oars = set(r['oar'] for r in recs)
    if len(oars) > 1:
        wo_multiple_oars[wo] = oars

# I. Same WO linked to multiple POs
wo_multiple_pos = {}
for wo, recs in wo_counts.items():
    pos = set(r['po_num'] for r in recs)
    if len(pos) > 1:
        wo_multiple_pos[wo] = pos

# J. Same OAR linked to multiple POs
oar_multiple_pos = {}
for oar, recs in oar_counts.items():
    pos = set(r['po_num'] for r in recs)
    if len(pos) > 1:
        oar_multiple_pos[oar] = pos

# K. PO quantity inconsistencies (same PO line having different PO qty)
po_line_qty_inconsistencies = []
# Group by (po_num, internal_id)
po_part_groups = defaultdict(list)
for d in data:
    key = (str(d['po_num']).strip(), str(d['internal_id']).strip())
    po_part_groups[key].append(d)

for (po_num, int_id), recs in po_part_groups.items():
    p_qtys = set(r['po_qty'] for r in recs)
    if len(p_qtys) > 1:
        po_line_qty_inconsistencies.append((po_num, int_id, p_qtys, [r['wo'] for r in recs]))

# L. WO quantity greater than PO quantity
wo_gt_po = []
# Check per line: total WO qty vs PO qty
for (po_num, int_id), recs in po_part_groups.items():
    tot_wo_qty = sum(float(r['wo_qty'] or 0) for r in recs)
    first_po_qty = float(recs[0]['po_qty'] or 0)
    if tot_wo_qty > first_po_qty:
        wo_gt_po.append((po_num, int_id, first_po_qty, tot_wo_qty, [r['wo'] for r in recs]))

# Individual WO qty > PO qty
indiv_wo_gt_po = [d for d in data if float(d['wo_qty'] or 0) > float(d['po_qty'] or 0)]

# M. Missing Part No
missing_part_no = [d for d in data if not d['part_no']]
# N. Missing Internal Part Code
missing_internal_code = [d for d in data if not d['internal_part_code']]
# O. Missing Customer Code
missing_cust_code = [d for d in data if not d['cust_code']]
# P. Missing WO Type
missing_wo_type = [d for d in data if not d['wo_type']]
# Q. Missing Status
missing_status = [d for d in data if not d['status']]
# R. Invalid dates
invalid_dates = []
for d in data:
    dt = str(d['del_date'])
    if not dt or dt == 'None':
        invalid_dates.append(d)
# S. Blank/invalid PO numbers
invalid_pos = [d for d in data if not d['po_num'] or str(d['po_num']).strip() == '']

print("==================================================")
print("CONSISTENCY CHECK RESULTS")
print("==================================================")
print(f"A. WO without OAR: {len(wo_without_oar)}")
print(f"B. OAR without PO: {len(oar_without_po)}")
print(f"C. PO without customer: {len(po_without_cust)}")
print(f"D. WO without PO: {len(wo_without_po)}")
print(f"E. Unique PO numbers count: {len(po_counts)}")
print(f"F. Unique OAR IDs count: {len(oar_counts)}")
print(f"G. Duplicate WO IDs count: {len(duplicate_wos)}")
print(f"H. Same WO linked to multiple OARs: {len(wo_multiple_oars)}")
print(f"I. Same WO linked to multiple POs: {len(wo_multiple_pos)}")
print(f"J. Same OAR linked to multiple POs (CROSS_PO_OAR): {len(oar_multiple_pos)}")
if oar_multiple_pos:
    print("   CROSS_PO_OAR details:", oar_multiple_pos)
print(f"K. PO quantity inconsistencies across same PO+Part: {len(po_line_qty_inconsistencies)}")
if po_line_qty_inconsistencies:
    for inc in po_line_qty_inconsistencies:
        print(f"   PO: {inc[0]} | Part: {inc[1]} | PO Qtys found: {inc[2]} | WOs: {inc[3]}")
print(f"L. Cumulative WO qty > PO qty: {len(wo_gt_po)}")
if wo_gt_po:
    for w in wo_gt_po:
        print(f"   PO: {w[0]} | Part: {w[1]} | PO Qty: {w[2]} | Total WO Qty: {w[3]} | WOs: {w[4]}")
print(f"   Individual WO qty > PO qty: {len(indiv_wo_gt_po)}")
if indiv_wo_gt_po:
    for d in indiv_wo_gt_po:
        print(f"   WO: {d['wo']} | PO: {d['po_num']} | Part: {d['internal_id']} | PO Qty: {d['po_qty']} | WO Qty: {d['wo_qty']}")

print(f"M. Missing Part No: {len(missing_part_no)}")
print(f"N. Missing Internal Part Code: {len(missing_internal_code)}")
print(f"O. Missing Customer Code: {len(missing_cust_code)}")
print(f"P. Missing WO Type: {len(missing_wo_type)}")
print(f"Q. Missing Status: {len(missing_status)} (blank in {len(missing_status)} rows)")
print(f"R. Invalid/Missing delivery dates: {len(invalid_dates)}")
print(f"S. Blank/invalid PO numbers: {len(invalid_pos)}")

# Check customer codes list:
print("\nCustomer code summary:")
for c in set(d['cust_code'] for d in data):
    cust_rows = [d for d in data if d['cust_code'] == c]
    print(f"  Code: {c} | Rows: {len(cust_rows)} | Names: {set(d['cust'] for d in cust_rows)}")
