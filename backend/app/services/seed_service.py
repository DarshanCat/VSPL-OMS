from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.packing import PackingRecord
from app.models.dispatch import Dispatch
from app.models.nc import NCRecord
from app.services.oms_integration_service import calculate_stage_targets

def seed_database_if_empty(db: Session):
    # 1. Users with distinct RBAC roles (Seed / Upsert all demo users)
    users_data = [
        ("admin@vspl.com", "admin123", "Darshan Admin", UserRole.ADMIN, "ADM-001"),
        ("darshan@vspl.com", "admin123", "Darshan Admin", UserRole.ADMIN, "ADM-002"),
        ("pm@vspl.com", "pm123", "Ramesh Kumar", UserRole.PRODUCTION_MANAGER, "PRD-001"),
        ("prod.manager@vspl.com", "prod123", "Ramesh Kumar", UserRole.PRODUCTION_MANAGER, "PRD-002"),
        ("planner@vspl.com", "planner123", "Suresh Sharma", UserRole.PLANNER, "PLN-001"),
        ("qa@vspl.com", "qa123", "Anand Rao", UserRole.QA, "QA-001"),
        ("qa.lead@vspl.com", "qa123", "Anand Rao", UserRole.QA, "QA-002"),
        ("dispatch@vspl.com", "dispatch123", "Venkatesh Prasad", UserRole.DISPATCH, "DSP-001"),
        ("ceo@vspl.com", "ceo123", "Executive Director", UserRole.CEO, "EXE-001"),
        ("operator@vspl.com", "op123", "Devanand (Foundry)", UserRole.MACHINE_OPERATOR, "OP-001"),
        ("operator.f1@vspl.com", "oper123", "Devanand (Foundry)", UserRole.MACHINE_OPERATOR, "OP-F1"),
        ("operator.f2@vspl.com", "oper123", "Manjunath (CNC)", UserRole.MACHINE_OPERATOR, "OP-F2"),
    ]

    # Only create accounts that don't exist yet. Never overwrite an existing user's
    # password/role/active-status here: this function runs on every app startup, and
    # doing so would silently reset any real admin's credentials back to the seed
    # defaults on every restart/deploy.
    for email, pwd, name, role, emp_id in users_data:
        existing = db.query(User).filter(User.email == email).first()
        if not existing:
            u = User(
                email=email,
                hashed_password=get_password_hash(pwd),
                full_name=name,
                role=role,
                employee_id=emp_id,
                department="Manufacturing Operations",
                is_active=True
            )
            db.add(u)
    db.flush()

    # Check if orders already seeded
    if db.query(WorkOrder).first():
        db.commit()
        return

    # 2. Customers
    cust_data = [
        ("CUST-VALVE", "Flowserve Sanmar Ltd"),
        ("CUST-PUMP", "KSB Pumps & Valves Ltd"),
        ("CUST-HEAVY", "Bharat Heavy Electricals Ltd (BHEL)"),
        ("CUST-DEF", "Larsen & Toubro Heavy Eng"),
    ]
    cust_objs = []
    for code, name in cust_data:
        c = Customer(customer_code=code, name=name)
        db.add(c)
        cust_objs.append(c)
    db.flush()

    # 3. Parts (Centrifugal Cast Bronze Components)
    part_data = [
        ("BRZ-BUSH-100", "PB2 / CuSn11P", "Centrifugal Cast Bushing OD 120mm x ID 80mm"),
        ("BRZ-RING-250", "SAE 660 / RG7", "Wear Ring Seal 250mm x 20mm"),
        ("BRZ-SLV-400", "AB2 / CuAl10Fe5Ni5", "Heavy Duty Aluminium Bronze Sleeve 400mm"),
        ("BRZ-GEAR-150", "CuSn12", "Worm Gear Blank Bronze Casting 150mm"),
        ("BRZ-FLG-300", "LG2 / Gunmetal", "High Pressure Flanged Liner 300mm"),
    ]
    part_objs = []
    for pnum, grade, desc in part_data:
        p = Part(part_number=pnum, grade=grade, description=desc)
        db.add(p)
        part_objs.append(p)
    db.flush()

    # 4. Orders & Work Orders across manufacturing stages
    today = date.today()
    stages = ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"]

    orders_setup = [
        (cust_objs[0], part_objs[0], "PO-2026-901", 1000, 500, 10, [
            {"wo_num": "WO-1001", "qty": 500, "stage": "F2", "f1_ok": 500, "f2_ent": 500, "f2_avail": 480, "f2_rej": 20},
            {"wo_num": "WO-1002", "qty": 500, "stage": "F1", "f1_ent": 500, "f1_ok": 0, "f1_avail": 500, "f1_rej": 0},
        ]),
        (cust_objs[1], part_objs[1], "PO-2026-902", 800, 400, 5, [
            {"wo_num": "WO-1003", "qty": 400, "stage": "F3", "f1_ok": 400, "f2_ok": 390, "f2_rej": 10, "f3_ent": 390, "f3_avail": 380, "f3_rej": 10},
            {"wo_num": "WO-1004", "qty": 400, "stage": "SP", "f1_ok": 400, "f2_ok": 400, "f3_ok": 395, "f3_rej": 5, "sp_ent": 395, "sp_avail": 395, "sp_rej": 0},
        ]),
        (cust_objs[2], part_objs[2], "PO-2026-903", 600, 300, -2, [
            {"wo_num": "WO-1005", "qty": 300, "stage": "FI", "f1_ok": 300, "f2_ok": 300, "f3_ok": 295, "f3_rej": 5, "sp_ok": 295, "fi_ent": 295, "fi_avail": 290, "fi_rej": 5},
            {"wo_num": "WO-1006", "qty": 300, "stage": "PACKING", "f1_ok": 300, "f2_ok": 300, "f3_ok": 300, "sp_ok": 300, "fi_ok": 295, "fi_rej": 5, "packing_ent": 295, "packing_avail": 295, "packing_inproc": 95, "packing_onhand": 200, "packing_packed": 200, "packing_ready": 200, "packing_pending": 95},
        ]),
        (cust_objs[3], part_objs[3], "PO-2026-904", 450, 450, 15, [
            {"wo_num": "WO-1007", "qty": 450, "stage": "DISPATCH", "f1_ok": 450, "f2_ok": 445, "f2_rej": 5, "f3_ok": 445, "sp_ok": 445, "fi_ok": 440, "fi_rej": 5, "packing_ent": 440, "packing_ok": 400, "packing_avail": 40, "packing_onhand": 40, "packing_packed": 440, "packing_ready": 40, "packing_pending": 0, "dispatched": 400},
        ]),
    ]

    oar_idx = 1
    mov_counter = 1
    nc_counter = 1
    for cust, part, po_num, po_qty, batch_size, days_due, wos in orders_setup:
        delivery_dt = today + timedelta(days=days_due)
        oar_code = f"OAR-{oar_idx:04d}"
        oar_idx += 1

        order = Order(
            oar_number=oar_code,
            customer_id=cust.id,
            part_id=part.id,
            customer_po=po_num,
            po_qty=po_qty,
            max_batch_size=batch_size,
            delivery_date=delivery_dt,
            order_type="Standard",
            status=OrderStatus.ACCEPT
        )
        db.add(order)
        db.flush()

        for w_data in wos:
            wo_num = w_data["wo_num"]
            wo_qty = w_data["qty"]
            cur_stg = w_data["stage"]

            wo = WorkOrder(
                wo_number=wo_num,
                order_id=order.id,
                physical_wo_qty=wo_qty,
                current_stage=cur_stg,
                projected_final_good=wo_qty,
                shortfall="No",
                status=WOStatus.DISPATCHED if cur_stg == "DISPATCH" and w_data.get("dispatched", 0) >= wo_qty else (WOStatus.READY if cur_stg in ("PACKING", "DISPATCH") else WOStatus.IN_PRODUCTION),
                released_by="Lead Planner",
                release_date=datetime.now()
            )
            db.add(wo)
            db.flush()

            # Create WORoute
            cur_stg_idx = stages.index(cur_stg)
            targets = calculate_stage_targets(wo_qty, route=stages)

            for seq, stg in enumerate(stages, start=1):
                r_stg_idx = seq - 1
                stage_status = "Completed" if r_stg_idx < cur_stg_idx else ("In-Progress" if r_stg_idx == cur_stg_idx else "Pending")
                stg_ok = w_data.get(f"{stg.lower()}_ok", wo_qty if r_stg_idx < cur_stg_idx else 0)
                stg_rej = w_data.get(f"{stg.lower()}_rej", 0)
                stg_ent = w_data.get(f"{stg.lower()}_ent", wo_qty if r_stg_idx == 0 else (stg_ok + stg_rej if r_stg_idx <= cur_stg_idx else 0))
                
                r = WORoute(
                    work_order_id=wo.id,
                    stage=stg,
                    sequence=seq,
                    stage_target_qty=targets.get(stg, wo_qty),
                    cumulative_ent_qty=stg_ent,
                    cumulative_ok_qty=stg_ok,
                    cumulative_rej_qty=stg_rej,
                    cumulative_inproc_qty=stg_ent - stg_ok - stg_rej if r_stg_idx == cur_stg_idx else 0,
                    cumulative_onhand_qty=0,
                    stage_status=stage_status
                )
                db.add(r)

            # Create StageWIP
            for seq, stg in enumerate(stages, start=1):
                r_stg_idx = seq - 1
                avail = 0
                stg_ok = w_data.get(f"{stg.lower()}_ok", wo_qty if r_stg_idx < cur_stg_idx else 0)
                stg_rej = w_data.get(f"{stg.lower()}_rej", 0)
                stg_ent = w_data.get(f"{stg.lower()}_ent", wo_qty if r_stg_idx == 0 else (stg_ok + stg_rej if r_stg_idx <= cur_stg_idx else 0))

                inproc_val = 0
                onhand_val = 0

                if stg == cur_stg:
                    if stg == "F1":
                        avail = w_data.get("f1_avail", wo_qty)
                        inproc_val = avail
                    elif stg == "F2":
                        avail = w_data.get("f2_avail", 480)
                        inproc_val = avail
                    elif stg == "F3":
                        avail = w_data.get("f3_avail", 380)
                        inproc_val = avail
                    elif stg == "SP":
                        avail = w_data.get("sp_avail", 395)
                        inproc_val = avail
                    elif stg == "FI":
                        avail = w_data.get("fi_avail", 290)
                        inproc_val = avail
                    elif stg == "PACKING":
                        avail = w_data.get("packing_avail", 295)
                        inproc_val = w_data.get("packing_inproc", 95)
                        onhand_val = w_data.get("packing_onhand", 200)
                    elif stg == "DISPATCH":
                        avail = w_data.get("packing_avail", 40)
                        inproc_val = 0
                        onhand_val = 40

                wip = StageWIP(
                    work_order_id=wo.id,
                    stage=stg,
                    ent_qty=stg_ent,
                    ok_qty=stg_ok,
                    inproc_qty=inproc_val,
                    onhand_qty=onhand_val,
                    rejected_qty=stg_rej,
                    received_qty=stg_ent,
                    available_wip=avail,
                    moved_out_qty=stg_ok
                )
                db.add(wip)

            # Create Packing Record if stage reached FI, Packing, or Dispatch
            if cur_stg in ("FI", "PACKING", "DISPATCH"):
                fi_approved = w_data.get("fi_ok", wo_qty - 10)
                packed_qty = w_data.get("packing_packed", 0)
                ready_qty = w_data.get("packing_ready", 0)
                pending_qty = w_data.get("packing_pending", fi_approved - packed_qty)
                disp_qty = w_data.get("dispatched", 0)

                pr = PackingRecord(
                    work_order_id=wo.id,
                    fi_approved_qty=fi_approved,
                    available_for_packing=fi_approved,
                    received_qty=fi_approved,
                    packed_qty=packed_qty,
                    pending_qty=pending_qty,
                    ready_for_dispatch_qty=ready_qty,
                    dispatched_qty=disp_qty,
                    status="Fully-Dispatched" if disp_qty >= wo_qty else ("Ready-for-Dispatch" if ready_qty > 0 and pending_qty == 0 else "In-Packing")
                )
                db.add(pr)

            # Create Dispatch Record if dispatched
            if w_data.get("dispatched", 0) > 0:
                disp = Dispatch(
                    work_order_id=wo.id,
                    customer_po=po_num,
                    invoice_number=f"INV-2026-{1000 + oar_idx}",
                    dispatched_qty=w_data["dispatched"],
                    dispatch_date=datetime.now() - timedelta(days=1)
                )
                db.add(disp)

            # Create NC record if any stage has rejection
            for stg in stages:
                rej_val = w_data.get(f"{stg.lower()}_rej", 0)
                if rej_val > 0:
                    nc = NCRecord(
                        nc_number=f"NC-{nc_counter:05d}",
                        work_order_id=wo.id,
                        stage=stg,
                        defect_code="DEF-POROSITY" if stg in ("F1", "F2") else "DEF-DIM-OUT",
                        qty=rej_val,
                        root_cause=f"Rejection identified during {stg} inspection",
                        disposition="Scrap",
                        responsibility="Production",
                        status="Open"
                    )
                    db.add(nc)
                    nc_counter += 1

    db.commit()
