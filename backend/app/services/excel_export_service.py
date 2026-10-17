"""
VSPL Open OAR & Work Order Excel Export Service.
Generates an authoritative, beautifully styled multi-tab Excel workbook containing:
1. Open_OARs_Dump: Real-time dump of open and active OARs.
2. Open_Work_Orders_Dump: Real-time dump of all active shop-floor Work Orders.
3. Traceability_Matrix: Combined OAR-to-WO genealogy and WIP rollup.
4. Data_Capture_Specification: Standardized data capture format, column schemas, types, and validation rules.
5. Reference_Masters: Pre-configured allowed values, stages, classifications ('Production' vs 'NPD').
"""

import io
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from app.models.order import Order, Customer, Part
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import StageWIP, ProductionMovement
from app.models.production import ProductionUpdate
from app.models.master_data import POMaster
from app.services.work_order_service import STANDARD_STAGES, compute_wo_release_status, calculate_delivery_risk, resolve_order_customer_part_number


def build_open_orders_and_wos_workbook(db: Session, classification_filter: Optional[str] = None) -> openpyxl.Workbook:
    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # Styling Palettes
    navy_header_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
    gold_header_fill = PatternFill(start_color="7A4100", end_color="7A4100", fill_type="solid")
    teal_header_fill = PatternFill(start_color="0A4D4A", end_color="0A4D4A", fill_type="solid")
    gray_header_fill = PatternFill(start_color="374151", end_color="374151", fill_type="solid")
    
    npd_fill = PatternFill(start_color="FDE8E8", end_color="FDE8E8", fill_type="solid") # soft rose
    prod_fill = PatternFill(start_color="E6FFFA", end_color="E6FFFA", fill_type="solid") # soft mint
    npd_font = Font(name="Segoe UI", size=10, bold=True, color="9B1C1C")
    prod_font = Font(name="Segoe UI", size=10, bold=True, color="03543F")

    header_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    data_font = Font(name="Segoe UI", size=10)
    data_bold = Font(name="Segoe UI", size=10, bold=True)
    title_font = Font(name="Segoe UI", size=14, bold=True, color="1E3A8A")
    subtitle_font = Font(name="Segoe UI", size=9, italic=True, color="4B5563")

    thin_border = Border(
        left=Side(style='thin', color='D1D5DB'),
        right=Side(style='thin', color='D1D5DB'),
        top=Side(style='thin', color='D1D5DB'),
        bottom=Side(style='thin', color='D1D5DB')
    )

    center_align = Alignment(horizontal="center", vertical="center")
    left_align = Alignment(horizontal="left", vertical="center")
    right_align = Alignment(horizontal="right", vertical="center")

    # ==========================================
    # TAB 1: Open_OARs_Dump
    # ==========================================
    ws_oars = wb.create_sheet(title="Open_OARs_Dump")
    ws_oars.views.sheetView[0].showGridLines = True

    # Title block
    ws_oars.merge_cells("A1:Q1")
    ws_oars["A1"] = "VIJAY SPHEROIDALS - OPEN ORDER ACKNOWLEDGEMENT RECEIPTS (OAR) DUMP"
    ws_oars["A1"].font = title_font
    ws_oars["A1"].alignment = left_align

    ws_oars.merge_cells("A2:Q2")
    ws_oars["A2"] = f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Classification: {classification_filter or 'All (Production + NPD)'}"
    ws_oars["A2"].font = subtitle_font
    ws_oars["A2"].alignment = left_align

    oar_headers = [
        "OAR Number", "Classification", "Customer Code", "Customer Name", "Customer PO",
        "PO Date", "Customer Part Number", "Internal Part Number", "Part Description", "Grade", "PO Qty",
        "Allocated WO Qty", "Balance to Plan", "Produced Good Qty", "Dispatched Qty",
        "Rejection Qty", "Delivery Date", "OAR Status"
    ]

    for col_idx, header in enumerate(oar_headers, 1):
        cell = ws_oars.cell(row=4, column=col_idx, value=header)
        cell.fill = navy_header_fill
        cell.font = header_font
        cell.alignment = center_align
        cell.border = thin_border
    ws_oars.row_dimensions[4].height = 26

    # Fetch OARs (all active or open)
    oar_query = db.query(Order).join(Customer).join(Part).order_by(Order.created_at.desc())
    if classification_filter:
        oar_query = oar_query.filter(Order.order_type.ilike(f"{classification_filter.strip()}%"))
    
    orders = oar_query.all()
    current_row = 5

    for order in orders:
        classification = getattr(order, "order_type", None) or "Production"
        # Gather WO allocations
        wos = db.query(WorkOrder).filter(WorkOrder.order_id == order.id).all()
        alloc_qty = sum(w.physical_wo_qty for w in wos)
        unalloc_qty = max(0, (order.po_qty or 0) - alloc_qty)

        # Gather good and rejection
        wo_ids = [w.id for w in wos]
        total_good = 0
        total_rej = 0
        if wo_ids:
            prod_updates = db.query(ProductionUpdate).filter(ProductionUpdate.work_order_id.in_(wo_ids)).all()
            total_good = sum(p.good_qty or 0 for p in prod_updates)
            total_rej = sum(p.reject_qty or 0 for p in prod_updates)

        # PO Date lookup
        po_date_str = ""
        if order.customer_po:
            po_rec = db.query(POMaster).filter(
                POMaster.customer_id == order.customer_id,
                POMaster.po_number == order.customer_po.strip()
            ).first()
            if po_rec and po_rec.po_date:
                po_date_str = po_rec.po_date.strftime("%Y-%m-%d")

        deliv_date_str = order.delivery_date.strftime("%Y-%m-%d") if order.delivery_date else ""
        cust_pn = resolve_order_customer_part_number(db, order) or (order.part.part_number if order.part else "N/A")
        internal_pn = order.part.part_number if order.part else "N/A"

        row_data = [
            order.oar_number or "N/A",
            classification,
            order.customer.customer_code if order.customer else "N/A",
            order.customer.name if order.customer else "N/A",
            order.customer_po or "",
            po_date_str,
            cust_pn,
            internal_pn,
            order.part.description if order.part else "",
            order.part.grade if order.part else "",
            order.po_qty or 0,
            alloc_qty,
            unalloc_qty,
            total_good,
            getattr(order, "dispatched_qty", 0) or 0,
            total_rej,
            deliv_date_str,
            order.status.upper() if order.status else "ACCEPT"
        ]

        for col_idx, val in enumerate(row_data, 1):
            cell = ws_oars.cell(row=current_row, column=col_idx, value=val)
            cell.font = data_font
            cell.border = thin_border
            
            # Alignments
            if col_idx in [1, 2, 3, 5, 6, 7, 9, 16, 17]:
                cell.alignment = center_align
            elif col_idx in [10, 11, 12, 13, 14, 15]:
                cell.alignment = right_align
            else:
                cell.alignment = left_align

            # Highlight NPD vs Production in column 2
            if col_idx == 2:
                if classification.upper() == "NPD":
                    cell.fill = npd_fill
                    cell.font = npd_font
                else:
                    cell.fill = prod_fill
                    cell.font = prod_font

        ws_oars.row_dimensions[current_row].height = 20
        current_row += 1

    # ==========================================
    # TAB 2: Open_Work_Orders_Dump
    # ==========================================
    ws_wos = wb.create_sheet(title="Open_Work_Orders_Dump")
    ws_wos.views.sheetView[0].showGridLines = True

    ws_wos.merge_cells("A1:Q1")
    ws_wos["A1"] = "VIJAY SPHEROIDALS - OPEN SHOP-FLOOR WORK ORDERS (WO) DUMP"
    ws_wos["A1"].font = title_font
    ws_wos["A1"].alignment = left_align

    ws_wos.merge_cells("A2:Q2")
    ws_wos["A2"] = f"Real-time Work Orders in active production | Classification: {classification_filter or 'All (Production + NPD)'}"
    ws_wos["A2"].font = subtitle_font
    ws_wos["A2"].alignment = left_align

    wo_headers = [
        "WO Number", "OAR Number", "Classification", "Customer Code", "Customer Part Number", "Internal Part Number",
        "Grade", "WO Plan Qty", "Current Stage", "Available Stage WIP", "Produced OK",
        "Stage Rejections", "Heat / Melt Number", "WO Status", "Release Status",
        "Delivery Risk", "Target Date", "WO Created At"
    ]

    for col_idx, header in enumerate(wo_headers, 1):
        cell = ws_wos.cell(row=4, column=col_idx, value=header)
        cell.fill = gold_header_fill
        cell.font = header_font
        cell.alignment = center_align
        cell.border = thin_border
    ws_wos.row_dimensions[4].height = 26

    wo_query = db.query(WorkOrder).join(Order).join(Customer).join(Part).order_by(WorkOrder.created_at.desc())
    if classification_filter:
        wo_query = wo_query.filter(
            or_(
                WorkOrder.classification.ilike(f"{classification_filter.strip()}%"),
                Order.order_type.ilike(f"{classification_filter.strip()}%")
            )
        )

    all_wos = wo_query.all()
    current_row = 5

    for wo in all_wos:
        order = wo.order
        classification = getattr(wo, "classification", None) or (order.order_type if order else "Production")
        cur_stage = wo.current_stage or "F1"
        
        # Stage WIP
        stg_wip = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == cur_stage).first()
        avail_wip = stg_wip.available_wip if stg_wip else 0

        # Produced & rejections
        updates = db.query(ProductionUpdate).filter(ProductionUpdate.work_order_id == wo.id).all()
        produced_ok = sum(u.good_qty or 0 for u in updates)
        rejected = sum(u.reject_qty or 0 for u in updates)

        rel_status = compute_wo_release_status(wo)
        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        route_stages = [r.stage for r in routes] if routes else STANDARD_STAGES
        risk = calculate_delivery_risk(order.delivery_date if order else None, cur_stage, wo.status.value, route_stages)

        target_date_str = order.delivery_date.strftime("%Y-%m-%d") if (order and order.delivery_date) else ""
        wo_created_str = wo.created_at.strftime("%Y-%m-%d") if wo.created_at else ""
        wo_cust_pn = resolve_order_customer_part_number(db, order) or (order.part.part_number if (order and order.part) else "N/A")
        wo_internal_pn = order.part.part_number if (order and order.part) else "N/A"

        row_data = [
            wo.wo_number,
            order.oar_number if order else "N/A",
            classification,
            order.customer.customer_code if (order and order.customer) else "N/A",
            wo_cust_pn,
            wo_internal_pn,
            order.part.grade if (order and order.part) else "",
            wo.physical_wo_qty,
            cur_stage,
            avail_wip,
            produced_ok,
            rejected,
            getattr(wo, "heat_number", "") or "",
            wo.status.value.upper() if wo.status else "OPEN",
            rel_status,
            risk,
            target_date_str,
            wo_created_str
        ]

        for col_idx, val in enumerate(row_data, 1):
            cell = ws_wos.cell(row=current_row, column=col_idx, value=val)
            cell.font = data_font
            cell.border = thin_border

            # Alignments
            if col_idx in [1, 2, 3, 4, 5, 6, 8, 12, 13, 14, 15, 16, 17]:
                cell.alignment = center_align
            elif col_idx in [7, 9, 10, 11]:
                cell.alignment = right_align
            else:
                cell.alignment = left_align

            # Classification highlight
            if col_idx == 3:
                if classification.upper() == "NPD":
                    cell.fill = npd_fill
                    cell.font = npd_font
                else:
                    cell.fill = prod_fill
                    cell.font = prod_font

        ws_wos.row_dimensions[current_row].height = 20
        current_row += 1

    # ==========================================
    # TAB 3: Traceability_Matrix
    # ==========================================
    ws_trace = wb.create_sheet(title="Traceability_Matrix")
    ws_trace.views.sheetView[0].showGridLines = True

    ws_trace.merge_cells("A1:M1")
    ws_trace["A1"] = "VIJAY SPHEROIDALS - END-TO-END TRACEABILITY MATRIX (OAR -> WO -> ROUTE WIP)"
    ws_trace["A1"].font = title_font
    ws_trace["A1"].alignment = left_align

    ws_trace.merge_cells("A2:M2")
    ws_trace["A2"] = "Complete audit trail separating Regular Production series from NPD trials with stage movements"
    ws_trace["A2"].font = subtitle_font
    ws_trace["A2"].alignment = left_align

    trace_headers = [
        "Classification", "OAR Number", "Customer", "Customer PO", "Customer Part Number", "Internal Part Number",
        "PO Qty", "WO Number", "WO Qty", "Current Stage", "Stage Available WIP",
        "Heat / Heat Code", "WO Status", "Fulfillment Status"
    ]

    for col_idx, header in enumerate(trace_headers, 1):
        cell = ws_trace.cell(row=4, column=col_idx, value=header)
        cell.fill = teal_header_fill
        cell.font = header_font
        cell.alignment = center_align
        cell.border = thin_border
    ws_trace.row_dimensions[4].height = 26

    current_row = 5
    for order in orders:
        classification = getattr(order, "order_type", None) or "Production"
        order_cust_pn = resolve_order_customer_part_number(db, order) or (order.part.part_number if order.part else "N/A")
        order_internal_pn = order.part.part_number if order.part else "N/A"
        order_wos = db.query(WorkOrder).filter(WorkOrder.order_id == order.id).order_by(WorkOrder.wo_number.asc()).all()

        if not order_wos:
            # Show unallocated OAR row
            row_data = [
                classification,
                order.oar_number,
                order.customer.customer_code if order.customer else "N/A",
                order.customer_po or "",
                order_cust_pn,
                order_internal_pn,
                order.po_qty or 0,
                "[NO WORK ORDERS YET]",
                0,
                "AWAITING WO RELEASE",
                0,
                "-",
                "PENDING PLANNING",
                "0% FULFILLED"
            ]
            for col_idx, val in enumerate(row_data, 1):
                cell = ws_trace.cell(row=current_row, column=col_idx, value=val)
                cell.font = data_font
                cell.border = thin_border
                cell.alignment = center_align if col_idx in [1, 2, 3, 4, 5, 6, 8, 10, 12, 13, 14] else (right_align if col_idx in [7, 9, 11] else left_align)
                if col_idx == 1:
                    cell.fill = npd_fill if classification.upper() == "NPD" else prod_fill
                    cell.font = npd_font if classification.upper() == "NPD" else prod_font
            ws_trace.row_dimensions[current_row].height = 20
            current_row += 1
        else:
            for wo in order_wos:
                stg = wo.current_stage or "F1"
                sw = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == stg).first()
                avail = sw.available_wip if sw else 0
                row_data = [
                    classification,
                    order.oar_number,
                    order.customer.customer_code if order.customer else "N/A",
                    order.customer_po or "",
                    order_cust_pn,
                    order_internal_pn,
                    order.po_qty or 0,
                    wo.wo_number,
                    wo.physical_wo_qty,
                    stg,
                    avail,
                    getattr(wo, "heat_number", "") or "-",
                    wo.status.value.upper(),
                    "IN PRODUCTION" if wo.status == WOStatus.IN_PRODUCTION else ("DISPATCHED" if wo.status == WOStatus.DISPATCHED else "PLANNED")
                ]
                for col_idx, val in enumerate(row_data, 1):
                    cell = ws_trace.cell(row=current_row, column=col_idx, value=val)
                    cell.font = data_font
                    cell.border = thin_border
                    cell.alignment = center_align if col_idx in [1, 2, 3, 4, 5, 6, 8, 10, 12, 13, 14] else (right_align if col_idx in [7, 9, 11] else left_align)
                    if col_idx == 1:
                        cell.fill = npd_fill if classification.upper() == "NPD" else prod_fill
                        cell.font = npd_font if classification.upper() == "NPD" else prod_font
                ws_trace.row_dimensions[current_row].height = 20
                current_row += 1

    # ==========================================
    # TAB 4: Data_Capture_Specification
    # ==========================================
    ws_spec = wb.create_sheet(title="Data_Capture_Specification")
    ws_spec.views.sheetView[0].showGridLines = True

    ws_spec.merge_cells("A1:F1")
    ws_spec["A1"] = "DATA CAPTURE SPECIFICATION & FORMAT MANUAL"
    ws_spec["A1"].font = title_font
    ws_spec["A1"].alignment = left_align

    ws_spec.merge_cells("A2:F2")
    ws_spec["A2"] = "Technical specifications for uploading, capturing, and migrating OARs, Work Orders, and Classification (Production vs NPD)"
    ws_spec["A2"].font = subtitle_font
    ws_spec["A2"].alignment = left_align

    spec_headers = ["Field Name", "Level / Stage", "Data Type", "Mandatory?", "Allowed Values / Examples", "Validation Rule & Purpose"]
    for col_idx, header in enumerate(spec_headers, 1):
        cell = ws_spec.cell(row=4, column=col_idx, value=header)
        cell.fill = gray_header_fill
        cell.font = header_font
        cell.alignment = center_align
        cell.border = thin_border
    ws_spec.row_dimensions[4].height = 26

    specs = [
        ("classification", "OAR & WO", "Text (Enum)", "MANDATORY", "Production | NPD", "Strictly 'Production' for regular series or 'NPD' for New Product Development / sample / pilot lot. Controls isolated traceability."),
        ("oar_number", "OAR Header", "Text (Alphanumeric)", "MANDATORY", "OAR-2024-001, OAR-NPD-042", "Unique Order Acknowledgement Receipt identifier. Generated automatically or from PO intake."),
        ("customer_code", "OAR Header", "Text (Uppercase)", "MANDATORY", "CUST-001, TOYOTA, BOSCH", "Must exist in Customer Master data. Linked to billing and dispatch."),
        ("customer_po", "OAR Header", "Text", "MANDATORY", "PO-2024-9842, SCH-OCT-24", "Customer's official purchase order number or schedule reference."),
        ("po_date", "OAR Header", "Date (YYYY-MM-DD)", "OPTIONAL", "2024-10-15", "Date when the customer placed the PO."),
        ("delivery_date", "OAR Header", "Date (YYYY-MM-DD)", "MANDATORY", "2024-11-20", "Committed customer shipment delivery date. Used to compute delivery risk score."),
        ("customer_part_number", "OAR & WO", "Text", "RECOMMENDED", "1000180955, DWG-8821-B", "Customer's official part/drawing number as printed on PO. Displayed as primary identifier."),
        ("part_number", "OAR & WO", "Text", "INTERNAL CODE", "SMX4, WND31, BRZ-BUSH-100", "VSPL internal part code mapped to customer drawing."),
        ("po_qty", "OAR Header", "Integer (> 0)", "MANDATORY", "500, 1000", "Total pieces ordered by customer under this line."),
        ("unit_price", "OAR Header", "Decimal (>= 0)", "OPTIONAL", "145.50, 2800.00", "Per piece rate. System automatically calculates total PO value = po_qty * unit_price."),
        ("wo_number", "Work Order", "Text", "MANDATORY", "WO-00100, WO-NPD-005", "Unique Work Order code tracking the physical metal batch through the foundry."),
        ("physical_wo_qty", "Work Order", "Integer (> 0)", "MANDATORY", "250, 500", "Quantity allocated to this physical batch. Sum of WOs must not exceed OAR PO Qty without amendment."),
        ("heat_number", "Work Order", "Text", "OPTIONAL / CONDITIONAL", "H-24-9081, MELT-04", "Furnace heat / melt heat number. Mandatory for aerospace/automotive critical traceability."),
        ("current_stage", "Shop Floor", "Text (Stage Code)", "MANDATORY", "F1, F2, F3, SP, FI, PACKING / BSR, DISPATCH", "Current physical manufacturing stage holding the balance pieces."),
        ("available_wip", "Shop Floor", "Integer (>= 0)", "SYSTEM CALCULATED", "250", "Net usable inventory waiting to be processed or transferred to the next stage."),
        ("good_qty", "Production Update", "Integer (>= 0)", "MANDATORY on Movement", "240", "Pcs that passed stage inspection and moved forward."),
        ("reject_qty", "Production Update", "Integer (>= 0)", "MANDATORY on Movement", "10", "Pcs rejected/scrapped at this stage. Automatically logged in NC / MRB log.")
    ]

    current_row = 5
    for s in specs:
        for col_idx, val in enumerate(s, 1):
            cell = ws_spec.cell(row=current_row, column=col_idx, value=val)
            cell.font = data_font
            cell.border = thin_border
            if col_idx in [2, 3, 4]:
                cell.alignment = center_align
            else:
                cell.alignment = left_align
            
            if col_idx == 4 and val == "MANDATORY":
                cell.font = Font(name="Segoe UI", size=10, bold=True, color="B91C1C")
        ws_spec.row_dimensions[current_row].height = 22
        current_row += 1

    # ==========================================
    # TAB 5: Reference_Masters
    # ==========================================
    ws_ref = wb.create_sheet(title="Reference_Masters")
    ws_ref.views.sheetView[0].showGridLines = True

    ws_ref.merge_cells("A1:E1")
    ws_ref["A1"] = "REFERENCE MASTERS & VALIDATION LOOKUPS"
    ws_ref["A1"].font = title_font
    ws_ref["A1"].alignment = left_align

    # Column A: Classifications
    ws_ref.cell(row=3, column=1, value="Classification").font = Font(name="Segoe UI", size=11, bold=True, color="1E3A8A")
    ws_ref.cell(row=3, column=2, value="Description").font = Font(name="Segoe UI", size=11, bold=True, color="1E3A8A")
    ws_ref.cell(row=4, column=1, value="Production").font = prod_font
    ws_ref.cell(row=4, column=1).fill = prod_fill
    ws_ref.cell(row=4, column=2, value="Regular series mass-production against confirmed production POs. Fully approved tooling & PPAP.")
    ws_ref.cell(row=5, column=1, value="NPD").font = npd_font
    ws_ref.cell(row=5, column=1).fill = npd_fill
    ws_ref.cell(row=5, column=2, value="New Product Development, sample trial, pilot batch, or prototype. Isolated traceability & testing.")

    # Process Stages
    ws_ref.cell(row=8, column=1, value="Standard Stage Code").font = Font(name="Segoe UI", size=11, bold=True, color="1E3A8A")
    ws_ref.cell(row=8, column=2, value="Stage Full Description").font = Font(name="Segoe UI", size=11, bold=True, color="1E3A8A")
    stage_data = [
        ("F1", "Fettling 1: Knockout, Gate Cutting, Riser Cut-Off"),
        ("F2", "Fettling 2: Shot Blasting & Coarse Grinding"),
        ("F3", "Fettling 3: Fine Finishing, Chipping, Dressing"),
        ("SP", "Special Processing: Heat Treatment, Primer Painting, or Rough Machining"),
        ("FI", "Final Inspection: Dimensional, Hardness, Visual & MPI Testing"),
        ("PACKING / BSR", "Bonded Store / Final Packing & Palletizing"),
        ("DISPATCH", "Outbound Shipping, DC & Tax Invoicing")
    ]
    for idx, (code, desc) in enumerate(stage_data, 9):
        ws_ref.cell(row=idx, column=1, value=code).font = data_bold
        ws_ref.cell(row=idx, column=1).alignment = center_align
        ws_ref.cell(row=idx, column=2, value=desc).font = data_font

    # Set column widths for all sheets
    for ws in [ws_oars, ws_wos, ws_trace, ws_spec, ws_ref]:
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.row in [1, 2]:
                    continue
                if cell.value is not None:
                    max_len = max(max_len, len(str(cell.value)))
            ws.column_dimensions[col_letter].width = max(max_len + 4, 13)

    return wb


def generate_excel_bytes(db: Session, classification_filter: Optional[str] = None) -> bytes:
    wb = build_open_orders_and_wos_workbook(db, classification_filter=classification_filter)
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.getvalue()
