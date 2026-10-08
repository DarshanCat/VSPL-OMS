-- =====================================================================================================
-- VSPL OMS - DEMO DATA CLEANUP, PHASE 2: READ-ONLY DRY RUN
-- Target database: vspl_smes (production)    Backup taken before this script: 1791192535042
--
-- THIS SCRIPT ONLY READS. It runs inside one READ ONLY transaction and ends with a ROLLBACK. It contains no
-- statement that changes data, structure or permissions, and no temporary tables.
-- Demo scope: OAR-0001, OAR-0002, OAR-0003, OAR-0004, OAR-0005, OAR-0006, OAR-0007, OAR-0008 and the Work Orders created from them. PO 223 only if Section 3 proves it is demo-only.
-- OUT OF SCOPE (never selected for removal): OAR-0009 .. OAR-0016, all master data, all Continuous Casting (cc_*) data.
-- Run with psql, saving the output:   psql -X -f demo_cleanup_dryrun.sql -o demo_cleanup_dryrun_output.txt
-- =====================================================================================================
BEGIN;
SET TRANSACTION READ ONLY;

-- ===== SECTION 0: ENVIRONMENT CHECK (expect database = vspl_smes, transaction_read_only = on) =====
SELECT current_database() AS database, current_setting('transaction_read_only') AS transaction_read_only,
       current_setting('server_version') AS server_version, now() AS run_at;

-- ===== SECTION 1: OAR VERIFICATION (expect exactly 8 rows found, 0 missing) =====
-- (orders has no updated_at column in the application schema, so only created_at is shown)
WITH wanted(oar_number) AS (VALUES ('OAR-0001'), ('OAR-0002'), ('OAR-0003'), ('OAR-0004'), ('OAR-0005'), ('OAR-0006'), ('OAR-0007'), ('OAR-0008'))
SELECT wanted.oar_number AS expected_oar, (o.id IS NOT NULL) AS found, o.id AS order_id, c.customer_code, c.name AS customer_name,
       o.customer_po, o.po_line_id, o.schedule_id, o.source_type, p.part_number, o.part_id, o.po_qty AS quantity,
       o.status, o.order_type, o.created_at
FROM wanted
LEFT JOIN orders o ON o.oar_number = wanted.oar_number
LEFT JOIN customers c ON c.id = o.customer_id
LEFT JOIN parts p ON p.id = o.part_id
ORDER BY wanted.oar_number;

-- Any other OARs, shown only to prove they are NOT in scope (no numbers outside OAR-0001..0008 are selected for removal)
SELECT oar_number, status, customer_po, created_at AS out_of_scope_oar_for_reference
FROM orders WHERE oar_number NOT IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008') OR oar_number IS NULL ORDER BY oar_number;

-- ===== SECTION 2: WORK ORDERS OF THE DEMO OARS (and self-references) =====
-- 2A. Every demo WO, with where its source_wo_id points
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po))
SELECT o.oar_number, w.wo_number, w.id AS wo_id, w.order_id, w.status, w.is_replacement, w.created_at,
       w.source_wo_id, sw.wo_number AS source_wo_number,
       CASE WHEN w.source_wo_id IS NULL THEN 'no source WO'
            WHEN w.source_wo_id IN (SELECT id FROM demo_wos) THEN 'source is another DEMO WO'
            ELSE 'SOURCE IS OUTSIDE DEMO SCOPE  <== BLOCKER' END AS source_classification
FROM work_orders w
JOIN orders o ON o.id = w.order_id
LEFT JOIN work_orders sw ON sw.id = w.source_wo_id
WHERE w.id IN (SELECT id FROM demo_wos)
ORDER BY o.oar_number, w.wo_number;

-- 2B. NON-demo work orders that point at a demo WO (must return 0 rows)
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po))
SELECT w.wo_number AS non_demo_wo_pointing_at_demo_wo, w.id, w.order_id, w.source_wo_id, sw.wo_number AS demo_source_wo
FROM work_orders w JOIN work_orders sw ON sw.id = w.source_wo_id
WHERE w.source_wo_id IN (SELECT id FROM demo_wos) AND w.id NOT IN (SELECT id FROM demo_wos);

-- 2C. Number of demo WOs per OAR
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po))
SELECT o.oar_number, count(w.id) AS wo_count, string_agg(w.wo_number, ', ' ORDER BY w.wo_number) AS wo_numbers
FROM demo_orders o LEFT JOIN demo_wos w ON w.order_id = o.id GROUP BY o.oar_number ORDER BY o.oar_number;

-- ===== SECTION 3: PURCHASE ORDER 223 =====
-- 3A. Candidates: how PO 223 is actually spelled in the data (if no row has po_number exactly '223',
--     search-and-replace '223' in the lines marked EDIT HERE with the real po_number text)
SELECT 'po_master' AS source, po_number AS value, id::text AS id, created_at FROM po_master WHERE po_number LIKE '%223%'
UNION ALL
SELECT 'orders.customer_po', customer_po, oar_number, created_at FROM orders WHERE customer_po LIKE '%223%'
ORDER BY 1, 2;

-- 3B. PO 223: header, lines and the orders that use each line
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po))
SELECT p.po_number, p.id AS po_master_id, p.customer_id, p.status AS po_status, p.created_at AS po_created_at,
       l.id AS po_line_id, l.part_id, l.po_qty AS line_qty,
       o.oar_number AS order_using_line, (o.id IN (SELECT id FROM demo_orders)) AS order_is_demo
FROM po_master p
LEFT JOIN po_lines l ON l.po_id = p.id
LEFT JOIN orders o ON o.po_line_id = l.id
WHERE p.id IN (SELECT id FROM po)
ORDER BY p.po_number, l.id, o.oar_number;

-- 3C. Which orders reference PO 223's lines: demo vs non-demo (non-demo must be 0 for PO 223 to be removable)
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po))
SELECT CASE WHEN o.id IN (SELECT id FROM demo_orders) THEN 'DEMO order' ELSE 'NON-DEMO order  <== SHARED' END AS referenced_by,
       o.oar_number, o.status, o.customer_po, o.po_line_id
FROM orders o WHERE o.po_line_id IN (SELECT id FROM po_ln)
ORDER BY 1, 2;

-- 3D. Orders outside the demo scope whose customer_po text equals 223 (a text reference, not a foreign key)
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po))
SELECT o.oar_number AS non_demo_order_with_this_customer_po, o.status, o.customer_po, o.po_line_id
FROM orders o WHERE o.customer_po = '223' AND o.id NOT IN (SELECT id FROM demo_orders);   -- EDIT HERE with the PO number

-- 3E. Schedule links of the demo orders (schedule_master is NOT in the cleanup set; shown so leftovers are known)
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po))
SELECT o.oar_number, s.schedule_number, s.po_status AS schedule_status, o.oar_po_status
FROM orders o LEFT JOIN schedule_master s ON s.id = o.schedule_id
WHERE o.id IN (SELECT id FROM demo_orders) AND o.schedule_id IS NOT NULL ORDER BY o.oar_number;

-- ===== SECTION 4: CONVERSIONS =====
-- 4A. Every conversion touching the demo scope, with the three sides classified (any OUTSIDE value is a BLOCKER)
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po))
SELECT c.id AS conversion_id, c.conversion_wo_number,
       sw.wo_number AS source_wo, (c.source_wo_id IN (SELECT id FROM demo_wos)) AS source_wo_is_demo,
       cw.wo_number AS conversion_wo, CASE WHEN c.conversion_wo_id IS NULL THEN NULL
                                          ELSE (c.conversion_wo_id IN (SELECT id FROM demo_wos)) END AS conversion_wo_is_demo,
       dord.oar_number AS destination_order, (c.destination_order_id IN (SELECT id FROM demo_orders)) AS destination_order_is_demo,
       c.nc_record_id, (c.nc_record_id IN (SELECT id FROM demo_nc)) AS nc_record_is_demo,
       CASE WHEN c.source_wo_id IN (SELECT id FROM demo_wos)
             AND (c.conversion_wo_id IS NULL OR c.conversion_wo_id IN (SELECT id FROM demo_wos))
             AND c.destination_order_id IN (SELECT id FROM demo_orders)
            THEN 'entirely inside demo scope' ELSE 'CROSSES THE DEMO BOUNDARY  <== BLOCKER' END AS classification
FROM conversions c
LEFT JOIN work_orders sw ON sw.id = c.source_wo_id
LEFT JOIN work_orders cw ON cw.id = c.conversion_wo_id
LEFT JOIN orders dord ON dord.id = c.destination_order_id
WHERE c.id IN (SELECT id FROM demo_conv)
ORDER BY c.conversion_wo_number, sw.wo_number;

-- 4B. The two conversions named in the brief (WO-1017, WO-1019): wherever they appear
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po))
SELECT c.id AS conversion_id, c.conversion_wo_number, sw.wo_number AS source_wo, cw.wo_number AS conversion_wo,
       dord.oar_number AS destination_order, (c.id IN (SELECT id FROM demo_conv)) AS in_demo_conversion_set
FROM conversions c
LEFT JOIN work_orders sw ON sw.id = c.source_wo_id
LEFT JOIN work_orders cw ON cw.id = c.conversion_wo_id
LEFT JOIN orders dord ON dord.id = c.destination_order_id
WHERE sw.wo_number IN ('WO-1017', 'WO-1019') OR cw.wo_number IN ('WO-1017', 'WO-1019')
   OR c.conversion_wo_number IN ('WO-1017', 'WO-1019');

-- 4C. Conversions OUTSIDE the demo set that still point at a demo rejection record (must return 0 rows)
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po))
SELECT c.id AS outside_conversion_using_demo_nc, c.conversion_wo_number, c.nc_record_id
FROM conversions c WHERE c.nc_record_id IN (SELECT id FROM demo_nc) AND c.id NOT IN (SELECT id FROM demo_conv);

-- 4D. Rejection dispositions that name a demo WO only by text (destination_wo_number has no foreign key) but are outside the cleanup set
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po))
SELECT d.id AS disposition_outside_set, d.action, d.destination_wo_number, d.nc_record_id, d.conversion_id
FROM rejection_dispositions d
WHERE d.destination_wo_number IN (SELECT wo_number FROM demo_wos)
  AND d.nc_record_id NOT IN (SELECT id FROM demo_nc)
  AND (d.conversion_id IS NULL OR d.conversion_id NOT IN (SELECT id FROM demo_conv));

-- 4E. Dispositions that straddle the boundary (rejection record is demo but its conversion is not, or the reverse) - must return 0 rows
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po))
SELECT d.id AS straddling_disposition, d.nc_record_id, d.conversion_id,
       (d.nc_record_id IN (SELECT id FROM demo_nc)) AS nc_is_demo, (d.conversion_id IN (SELECT id FROM demo_conv)) AS conversion_is_demo
FROM rejection_dispositions d
WHERE (d.nc_record_id IN (SELECT id FROM demo_nc)) <> COALESCE(d.conversion_id IN (SELECT id FROM demo_conv), d.nc_record_id IN (SELECT id FROM demo_nc))
  AND (d.nc_record_id IN (SELECT id FROM demo_nc) OR d.conversion_id IN (SELECT id FROM demo_conv));

-- ===== SECTION 5: DEPENDENT TRANSACTION COUNTS FOR THE DEMO WORK ORDERS =====
-- Each count is limited to rows that point at the demo Work Orders / demo conversions / demo rejection records.
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po))
SELECT t.table_name, t.rows_in_scope FROM (
  SELECT 1 AS ord, 'rejection_dispositions' AS table_name,
         (SELECT count(*) FROM rejection_dispositions WHERE nc_record_id IN (SELECT id FROM demo_nc)
                                                         OR conversion_id IN (SELECT id FROM demo_conv)) AS rows_in_scope
  UNION ALL SELECT 2, 'conversions', (SELECT count(*) FROM demo_conv)
  UNION ALL SELECT 3, 'dispatches', (SELECT count(*) FROM dispatches WHERE work_order_id IN (SELECT id FROM demo_wos))
  UNION ALL SELECT 4, 'packing_transactions', (SELECT count(*) FROM packing_transactions WHERE work_order_id IN (SELECT id FROM demo_wos))
  UNION ALL SELECT 5, 'packing_records', (SELECT count(*) FROM packing_records WHERE work_order_id IN (SELECT id FROM demo_wos))
  UNION ALL SELECT 6, 'nc_records', (SELECT count(*) FROM demo_nc)
  UNION ALL SELECT 7, 'production_movements', (SELECT count(*) FROM production_movements WHERE work_order_id IN (SELECT id FROM demo_wos))
  UNION ALL SELECT 8, 'production_updates', (SELECT count(*) FROM production_updates WHERE work_order_id IN (SELECT id FROM demo_wos))
  UNION ALL SELECT 9, 'stage_wips', (SELECT count(*) FROM stage_wips WHERE work_order_id IN (SELECT id FROM demo_wos))
  UNION ALL SELECT 10, 'wo_routes', (SELECT count(*) FROM wo_routes WHERE work_order_id IN (SELECT id FROM demo_wos))
  UNION ALL SELECT 11, 'work_orders', (SELECT count(*) FROM demo_wos)
  UNION ALL SELECT 12, 'orders', (SELECT count(*) FROM demo_orders)
) t ORDER BY t.ord;

-- ===== SECTION 6: AUDIT LOGS (reported only; audit_logs is never removed) =====
-- audit_logs.user_id is the only foreign key (to users). entity / entity_id / details are plain text, so a log row
-- can mention a demo OAR or WO without any foreign key to it.
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po)),
ids AS (SELECT oar_number AS ref FROM demo_orders UNION SELECT wo_number FROM demo_wos),
hits AS (
  SELECT a.id, a.entity, a.entity_id, a.action, a.created_at,
         (a.entity_id IN (SELECT ref FROM ids)) AS matched_by_entity_id,
         EXISTS (SELECT 1 FROM ids WHERE (coalesce(a.details,'') || ' ' || coalesce(a.new_value,'') || ' ' || coalesce(a.old_value,''))
                 ~ ('(^|[^A-Za-z0-9-])' || ids.ref || '([^A-Za-z0-9-]|$)')) AS matched_in_text
  FROM audit_logs a
)
SELECT count(*) FILTER (WHERE matched_by_entity_id OR matched_in_text) AS audit_rows_mentioning_demo_records,
       count(*) FILTER (WHERE matched_by_entity_id) AS matched_by_entity_id_text,
       count(*) FILTER (WHERE matched_in_text) AS matched_in_details_or_values,
       (SELECT count(*) FROM audit_logs) AS audit_rows_total
FROM hits;

-- 6B. Which kinds of audit rows they are
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po)),
ids AS (SELECT oar_number AS ref FROM demo_orders UNION SELECT wo_number FROM demo_wos)
SELECT a.entity, a.action, count(*) AS rows
FROM audit_logs a
WHERE a.entity_id IN (SELECT ref FROM ids)
   OR EXISTS (SELECT 1 FROM ids WHERE (coalesce(a.details,'') || ' ' || coalesce(a.new_value,'') || ' ' || coalesce(a.old_value,''))
              ~ ('(^|[^A-Za-z0-9-])' || ids.ref || '([^A-Za-z0-9-]|$)'))
GROUP BY a.entity, a.action ORDER BY rows DESC, a.entity, a.action;

-- 6C. Sample of the matching rows (20 newest)
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po)),
ids AS (SELECT oar_number AS ref FROM demo_orders UNION SELECT wo_number FROM demo_wos)
SELECT a.created_at, a.entity, a.entity_id, a.action, left(coalesce(a.details, a.new_value, ''), 80) AS detail_preview
FROM audit_logs a
WHERE a.entity_id IN (SELECT ref FROM ids)
   OR EXISTS (SELECT 1 FROM ids WHERE (coalesce(a.details,'') || ' ' || coalesce(a.new_value,'') || ' ' || coalesce(a.old_value,''))
              ~ ('(^|[^A-Za-z0-9-])' || ids.ref || '([^A-Za-z0-9-]|$)'))
ORDER BY a.created_at DESC LIMIT 20;

-- ===== SECTION 7: MASTER DATA BASELINE (these counts must be identical before and after any future cleanup) =====
-- None of these tables is in the cleanup set (see Section 10). A table that does not exist shows NULL instead of failing.
SELECT t.table_name, CASE WHEN pt.tablename IS NULL THEN NULL ELSE (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM public.%I', t.table_name), false, true, '')))[1]::text::bigint END AS row_count,
       (t.table_name IN ('rejection_dispositions', 'conversions', 'dispatches', 'packing_transactions', 'packing_records', 'nc_records', 'production_movements', 'production_updates', 'stage_wips', 'wo_routes', 'work_orders', 'orders', 'po_lines', 'po_master')) AS in_cleanup_set_must_be_false
FROM (VALUES ('customers'), ('parts'), ('users'), ('machines'), ('operators'), ('shifts'), ('rejection_types')) AS t(table_name)
LEFT JOIN pg_tables pt ON pt.schemaname = 'public' AND pt.tablename = t.table_name
ORDER BY t.table_name;

-- ===== SECTION 8: CONTINUOUS CASTING (CHINA) SAFETY =====
-- 8A. China tables that exist and their row counts (reported only; nothing here is in the cleanup set)
SELECT pt.tablename AS china_table,
       (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM public.%I', pt.tablename), false, true, '')))[1]::text::bigint AS row_count,
       (pt.tablename IN ('rejection_dispositions', 'conversions', 'dispatches', 'packing_transactions', 'packing_records', 'nc_records', 'production_movements', 'production_updates', 'stage_wips', 'wo_routes', 'work_orders', 'orders', 'po_lines', 'po_master')) AS in_cleanup_set_must_be_false
FROM pg_tables pt WHERE pt.schemaname = 'public' AND pt.tablename LIKE 'cc\_%' ORDER BY pt.tablename;

-- 8B. China rows that point at the demo scope through a foreign key (every row must show 0; a China table appearing with
--     rows_pointing_into_scope > 0 is a BLOCKER because it would stop the cleanup or be damaged by it)
WITH sweep AS (
    -- one row per foreign key into a cleanup parent. Composite keys are handled: cols aggregates EVERY column of the
    -- key (child side and parent side, paired by position), not just the first.
    SELECT n.nspname AS child_schema, cl.relname AS child_table, pcl.relname AS parent_table,
           cols.child_columns, cols.parent_columns, cols.column_count,
           CASE c.confdeltype WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT' WHEN 'c' THEN 'CASCADE'
                              WHEN 'n' THEN 'SET NULL' WHEN 'd' THEN 'SET DEFAULT' END AS on_removal_rule,
           (cl.relname IN ('rejection_dispositions', 'conversions', 'dispatches', 'packing_transactions', 'packing_records', 'nc_records', 'production_movements', 'production_updates', 'stage_wips', 'wo_routes', 'work_orders', 'orders', 'po_lines', 'po_master')) AS child_in_cleanup_set,
           CASE pcl.relname WHEN 'work_orders' THEN 'SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')' WHEN 'orders' THEN 'SELECT id FROM orders WHERE oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')'
                            WHEN 'nc_records' THEN 'SELECT id FROM nc_records WHERE work_order_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008''))' WHEN 'conversions' THEN 'SELECT c.id FROM conversions c WHERE c.source_wo_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')) OR c.conversion_wo_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')) OR c.destination_order_id IN (SELECT id FROM orders WHERE oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008''))'
                            WHEN 'rejection_dispositions' THEN 'SELECT id FROM rejection_dispositions WHERE nc_record_id IN (SELECT id FROM nc_records WHERE work_order_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008''))) OR conversion_id IN (SELECT c.id FROM conversions c WHERE c.source_wo_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')) OR c.conversion_wo_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')) OR c.destination_order_id IN (SELECT id FROM orders WHERE oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')))'
                            WHEN 'po_lines' THEN 'SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po_master WHERE po_number = ''223'')' WHEN 'po_master' THEN 'SELECT id FROM po_master WHERE po_number = ''223''' END AS parent_scope_sql
    FROM pg_constraint c
    JOIN pg_class cl ON cl.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = cl.relnamespace
    JOIN pg_class pcl ON pcl.oid = c.confrelid
    JOIN pg_namespace pn ON pn.oid = pcl.relnamespace
    CROSS JOIN LATERAL (
      SELECT string_agg(format('%I', ca.attname), ', ' ORDER BY k.ord) AS child_columns,
             string_agg(format('%I', pa.attname), ', ' ORDER BY k.ord) AS parent_columns,
             count(*) AS column_count
      FROM unnest(c.conkey, c.confkey) WITH ORDINALITY AS k(child_attnum, parent_attnum, ord)
      JOIN pg_attribute ca ON ca.attrelid = c.conrelid AND ca.attnum = k.child_attnum
      JOIN pg_attribute pa ON pa.attrelid = c.confrelid AND pa.attnum = k.parent_attnum
    ) cols
    WHERE c.contype = 'f' AND n.nspname = 'public' AND pn.nspname = 'public'
      AND pcl.relname IN ('work_orders', 'orders', 'nc_records', 'conversions', 'rejection_dispositions', 'po_lines', 'po_master')
  ),
  sweep_counts AS (
    -- counts child rows whose whole key (all columns together) points at an in-scope parent row
    SELECT s.*,
           (xpath('/row/c/text()', query_to_xml(
              format('SELECT count(*) AS c FROM %I.%I WHERE (%s) IN (SELECT %s FROM public.%I WHERE id IN (%s))',
                     s.child_schema, s.child_table, s.child_columns, s.parent_columns, s.parent_table, s.parent_scope_sql),
              false, true, '')))[1]::text::bigint AS rows_pointing_into_scope
    FROM sweep s
  )
SELECT child_table, child_columns, parent_table, parent_columns, rows_pointing_into_scope
FROM sweep_counts WHERE child_table LIKE 'cc\_%' ORDER BY child_table, child_columns;

-- ===== SECTION 9: FOREIGN KEYS (from pg_constraint; on_removal_rule is what the database does to a child row when its parent row is removed) =====
-- 9A. Every foreign key where one of the 14 tables is the child or the parent
SELECT cl.relname AS child_table, ca.attname AS child_column, pcl.relname AS parent_table, pa.attname AS parent_column,
       CASE c.confdeltype WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT' WHEN 'c' THEN 'CASCADE'
                          WHEN 'n' THEN 'SET NULL' WHEN 'd' THEN 'SET DEFAULT' END AS on_removal_rule,
       c.conname AS constraint_name, array_length(c.conkey, 1) AS columns_in_key
FROM pg_constraint c
JOIN pg_class cl ON cl.oid = c.conrelid
JOIN pg_namespace n ON n.oid = cl.relnamespace
JOIN pg_class pcl ON pcl.oid = c.confrelid
JOIN pg_attribute ca ON ca.attrelid = c.conrelid AND ca.attnum = c.conkey[1]
JOIN pg_attribute pa ON pa.attrelid = c.confrelid AND pa.attnum = c.confkey[1]
WHERE c.contype = 'f' AND n.nspname = 'public' AND (cl.relname IN ('orders', 'work_orders', 'po_master', 'po_lines', 'production_updates', 'production_movements', 'stage_wips', 'wo_routes', 'nc_records', 'packing_records', 'packing_transactions', 'dispatches', 'conversions', 'rejection_dispositions') OR pcl.relname IN ('orders', 'work_orders', 'po_master', 'po_lines', 'production_updates', 'production_movements', 'stage_wips', 'wo_routes', 'nc_records', 'packing_records', 'packing_transactions', 'dispatches', 'conversions', 'rejection_dispositions'))
ORDER BY pcl.relname, cl.relname, ca.attname;

-- 9B. Dependency sweep: every table in the database that has a foreign key (single or composite) into the cleanup parents
--     (work_orders, orders, nc_records, conversions, rejection_dispositions, po_lines, po_master), with how many of its rows
--     point into the demo scope. child_in_cleanup_set = false with rows_pointing_into_scope > 0 is a BLOCKER (an unexpected dependent).
WITH sweep AS (
    -- one row per foreign key into a cleanup parent. Composite keys are handled: cols aggregates EVERY column of the
    -- key (child side and parent side, paired by position), not just the first.
    SELECT n.nspname AS child_schema, cl.relname AS child_table, pcl.relname AS parent_table,
           cols.child_columns, cols.parent_columns, cols.column_count,
           CASE c.confdeltype WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT' WHEN 'c' THEN 'CASCADE'
                              WHEN 'n' THEN 'SET NULL' WHEN 'd' THEN 'SET DEFAULT' END AS on_removal_rule,
           (cl.relname IN ('rejection_dispositions', 'conversions', 'dispatches', 'packing_transactions', 'packing_records', 'nc_records', 'production_movements', 'production_updates', 'stage_wips', 'wo_routes', 'work_orders', 'orders', 'po_lines', 'po_master')) AS child_in_cleanup_set,
           CASE pcl.relname WHEN 'work_orders' THEN 'SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')' WHEN 'orders' THEN 'SELECT id FROM orders WHERE oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')'
                            WHEN 'nc_records' THEN 'SELECT id FROM nc_records WHERE work_order_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008''))' WHEN 'conversions' THEN 'SELECT c.id FROM conversions c WHERE c.source_wo_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')) OR c.conversion_wo_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')) OR c.destination_order_id IN (SELECT id FROM orders WHERE oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008''))'
                            WHEN 'rejection_dispositions' THEN 'SELECT id FROM rejection_dispositions WHERE nc_record_id IN (SELECT id FROM nc_records WHERE work_order_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008''))) OR conversion_id IN (SELECT c.id FROM conversions c WHERE c.source_wo_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')) OR c.conversion_wo_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')) OR c.destination_order_id IN (SELECT id FROM orders WHERE oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')))'
                            WHEN 'po_lines' THEN 'SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po_master WHERE po_number = ''223'')' WHEN 'po_master' THEN 'SELECT id FROM po_master WHERE po_number = ''223''' END AS parent_scope_sql
    FROM pg_constraint c
    JOIN pg_class cl ON cl.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = cl.relnamespace
    JOIN pg_class pcl ON pcl.oid = c.confrelid
    JOIN pg_namespace pn ON pn.oid = pcl.relnamespace
    CROSS JOIN LATERAL (
      SELECT string_agg(format('%I', ca.attname), ', ' ORDER BY k.ord) AS child_columns,
             string_agg(format('%I', pa.attname), ', ' ORDER BY k.ord) AS parent_columns,
             count(*) AS column_count
      FROM unnest(c.conkey, c.confkey) WITH ORDINALITY AS k(child_attnum, parent_attnum, ord)
      JOIN pg_attribute ca ON ca.attrelid = c.conrelid AND ca.attnum = k.child_attnum
      JOIN pg_attribute pa ON pa.attrelid = c.confrelid AND pa.attnum = k.parent_attnum
    ) cols
    WHERE c.contype = 'f' AND n.nspname = 'public' AND pn.nspname = 'public'
      AND pcl.relname IN ('work_orders', 'orders', 'nc_records', 'conversions', 'rejection_dispositions', 'po_lines', 'po_master')
  ),
  sweep_counts AS (
    -- counts child rows whose whole key (all columns together) points at an in-scope parent row
    SELECT s.*,
           (xpath('/row/c/text()', query_to_xml(
              format('SELECT count(*) AS c FROM %I.%I WHERE (%s) IN (SELECT %s FROM public.%I WHERE id IN (%s))',
                     s.child_schema, s.child_table, s.child_columns, s.parent_columns, s.parent_table, s.parent_scope_sql),
              false, true, '')))[1]::text::bigint AS rows_pointing_into_scope
    FROM sweep s
  )
SELECT parent_table, child_table, child_columns, parent_columns, column_count, on_removal_rule, child_in_cleanup_set, rows_pointing_into_scope
FROM sweep_counts ORDER BY parent_table, child_table, child_columns;

-- ===== SECTION 10: FUTURE REMOVAL IMPACT (counts only; nothing is removed) =====
-- po_lines / po_master rows are counted only for PO 223; po_223_status says whether they may be included.
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po)),
po_check AS (
  SELECT (SELECT count(*) FROM po) AS po_found,
         (SELECT count(*) FROM orders o WHERE o.po_line_id IN (SELECT id FROM po_ln) AND o.id NOT IN (SELECT id FROM demo_orders)) AS nondemo_line_refs,
         (SELECT count(*) FROM orders o WHERE o.customer_po = '223' AND o.id NOT IN (SELECT id FROM demo_orders)) AS nondemo_text_refs,   -- EDIT HERE with the PO number
         (SELECT count(*) FROM orders o WHERE o.po_line_id IN (SELECT id FROM po_ln) AND o.oar_number = 'OAR-0008') AS oar_0008_line_refs
)
SELECT t.table_name, t.rows_that_would_be_removed, t.note FROM (
  SELECT 1 AS ord, 'rejection_dispositions' AS table_name,
         (SELECT count(*) FROM rejection_dispositions WHERE nc_record_id IN (SELECT id FROM demo_nc) OR conversion_id IN (SELECT id FROM demo_conv)) AS rows_that_would_be_removed, '' AS note
  UNION ALL SELECT 2, 'conversions', (SELECT count(*) FROM demo_conv), ''
  UNION ALL SELECT 3, 'dispatches', (SELECT count(*) FROM dispatches WHERE work_order_id IN (SELECT id FROM demo_wos)), ''
  UNION ALL SELECT 4, 'packing_transactions', (SELECT count(*) FROM packing_transactions WHERE work_order_id IN (SELECT id FROM demo_wos)), ''
  UNION ALL SELECT 5, 'packing_records', (SELECT count(*) FROM packing_records WHERE work_order_id IN (SELECT id FROM demo_wos)), ''
  UNION ALL SELECT 6, 'nc_records', (SELECT count(*) FROM demo_nc), ''
  UNION ALL SELECT 7, 'production_movements', (SELECT count(*) FROM production_movements WHERE work_order_id IN (SELECT id FROM demo_wos)), ''
  UNION ALL SELECT 8, 'production_updates', (SELECT count(*) FROM production_updates WHERE work_order_id IN (SELECT id FROM demo_wos)), ''
  UNION ALL SELECT 9, 'stage_wips', (SELECT count(*) FROM stage_wips WHERE work_order_id IN (SELECT id FROM demo_wos)), ''
  UNION ALL SELECT 10, 'wo_routes', (SELECT count(*) FROM wo_routes WHERE work_order_id IN (SELECT id FROM demo_wos)), ''
  UNION ALL SELECT 11, 'work_orders', (SELECT count(*) FROM demo_wos), ''
  UNION ALL SELECT 12, 'orders', (SELECT count(*) FROM demo_orders), ''
  UNION ALL SELECT 13, 'po_lines', (SELECT count(*) FROM po_ln),
         (SELECT CASE WHEN po_found = 0 THEN 'PO NOT FOUND - exclude' WHEN nondemo_line_refs + nondemo_text_refs > 0 THEN 'SHARED - EXCLUDE PO' ELSE 'only if PO is a SAFE DEMO PO' END FROM po_check)
  UNION ALL SELECT 14, 'po_master', (SELECT count(*) FROM po),
         (SELECT CASE WHEN po_found = 0 THEN 'PO NOT FOUND - exclude' WHEN nondemo_line_refs + nondemo_text_refs > 0 THEN 'SHARED - EXCLUDE PO' ELSE 'only if PO is a SAFE DEMO PO' END FROM po_check)
) t ORDER BY t.ord;

-- ===== SECTION 11: SAFETY VERDICT =====
-- Every blocker column must be 0 and oars_found must be 8 for the cleanup scope to be READY.
WITH demo_orders AS (
    SELECT id, oar_number FROM orders WHERE oar_number IN ('OAR-0001', 'OAR-0002', 'OAR-0003', 'OAR-0004', 'OAR-0005', 'OAR-0006', 'OAR-0007', 'OAR-0008')
  ),
  demo_wos AS (
    SELECT w.id, w.wo_number, w.order_id FROM work_orders w WHERE w.order_id IN (SELECT id FROM demo_orders)
  ),
  demo_nc AS (
    SELECT id FROM nc_records WHERE work_order_id IN (SELECT id FROM demo_wos)
  ),
  demo_conv AS (
    SELECT c.id FROM conversions c
    WHERE c.source_wo_id IN (SELECT id FROM demo_wos)
       OR c.conversion_wo_id IN (SELECT id FROM demo_wos)
       OR c.destination_order_id IN (SELECT id FROM demo_orders)
  ),
  po AS (SELECT id, po_number FROM po_master WHERE po_number = '223'),  -- EDIT HERE if Section 3A shows a different PO number text
  po_ln AS (SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po)),
sweep AS (
    -- one row per foreign key into a cleanup parent. Composite keys are handled: cols aggregates EVERY column of the
    -- key (child side and parent side, paired by position), not just the first.
    SELECT n.nspname AS child_schema, cl.relname AS child_table, pcl.relname AS parent_table,
           cols.child_columns, cols.parent_columns, cols.column_count,
           CASE c.confdeltype WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT' WHEN 'c' THEN 'CASCADE'
                              WHEN 'n' THEN 'SET NULL' WHEN 'd' THEN 'SET DEFAULT' END AS on_removal_rule,
           (cl.relname IN ('rejection_dispositions', 'conversions', 'dispatches', 'packing_transactions', 'packing_records', 'nc_records', 'production_movements', 'production_updates', 'stage_wips', 'wo_routes', 'work_orders', 'orders', 'po_lines', 'po_master')) AS child_in_cleanup_set,
           CASE pcl.relname WHEN 'work_orders' THEN 'SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')' WHEN 'orders' THEN 'SELECT id FROM orders WHERE oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')'
                            WHEN 'nc_records' THEN 'SELECT id FROM nc_records WHERE work_order_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008''))' WHEN 'conversions' THEN 'SELECT c.id FROM conversions c WHERE c.source_wo_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')) OR c.conversion_wo_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')) OR c.destination_order_id IN (SELECT id FROM orders WHERE oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008''))'
                            WHEN 'rejection_dispositions' THEN 'SELECT id FROM rejection_dispositions WHERE nc_record_id IN (SELECT id FROM nc_records WHERE work_order_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008''))) OR conversion_id IN (SELECT c.id FROM conversions c WHERE c.source_wo_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')) OR c.conversion_wo_id IN (SELECT w.id FROM work_orders w JOIN orders o ON o.id = w.order_id WHERE o.oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')) OR c.destination_order_id IN (SELECT id FROM orders WHERE oar_number IN (''OAR-0001'', ''OAR-0002'', ''OAR-0003'', ''OAR-0004'', ''OAR-0005'', ''OAR-0006'', ''OAR-0007'', ''OAR-0008'')))'
                            WHEN 'po_lines' THEN 'SELECT id FROM po_lines WHERE po_id IN (SELECT id FROM po_master WHERE po_number = ''223'')' WHEN 'po_master' THEN 'SELECT id FROM po_master WHERE po_number = ''223''' END AS parent_scope_sql
    FROM pg_constraint c
    JOIN pg_class cl ON cl.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = cl.relnamespace
    JOIN pg_class pcl ON pcl.oid = c.confrelid
    JOIN pg_namespace pn ON pn.oid = pcl.relnamespace
    CROSS JOIN LATERAL (
      SELECT string_agg(format('%I', ca.attname), ', ' ORDER BY k.ord) AS child_columns,
             string_agg(format('%I', pa.attname), ', ' ORDER BY k.ord) AS parent_columns,
             count(*) AS column_count
      FROM unnest(c.conkey, c.confkey) WITH ORDINALITY AS k(child_attnum, parent_attnum, ord)
      JOIN pg_attribute ca ON ca.attrelid = c.conrelid AND ca.attnum = k.child_attnum
      JOIN pg_attribute pa ON pa.attrelid = c.confrelid AND pa.attnum = k.parent_attnum
    ) cols
    WHERE c.contype = 'f' AND n.nspname = 'public' AND pn.nspname = 'public'
      AND pcl.relname IN ('work_orders', 'orders', 'nc_records', 'conversions', 'rejection_dispositions', 'po_lines', 'po_master')
  ),
  sweep_counts AS (
    -- counts child rows whose whole key (all columns together) points at an in-scope parent row
    SELECT s.*,
           (xpath('/row/c/text()', query_to_xml(
              format('SELECT count(*) AS c FROM %I.%I WHERE (%s) IN (SELECT %s FROM public.%I WHERE id IN (%s))',
                     s.child_schema, s.child_table, s.child_columns, s.parent_columns, s.parent_table, s.parent_scope_sql),
              false, true, '')))[1]::text::bigint AS rows_pointing_into_scope
    FROM sweep s
  ),
checks AS (
  SELECT
    (SELECT count(*) FROM demo_orders) AS oars_found,
    (SELECT count(*) FROM work_orders w WHERE w.source_wo_id IN (SELECT id FROM demo_wos) AND w.id NOT IN (SELECT id FROM demo_wos)) AS outside_wos_pointing_at_demo_wos,
    (SELECT count(*) FROM demo_wos d JOIN work_orders w ON w.id = d.id WHERE w.source_wo_id IS NOT NULL AND w.source_wo_id NOT IN (SELECT id FROM demo_wos)) AS demo_wos_pointing_outside,
    (SELECT count(*) FROM conversions c WHERE c.id IN (SELECT id FROM demo_conv)
        AND NOT (c.source_wo_id IN (SELECT id FROM demo_wos)
                 AND (c.conversion_wo_id IS NULL OR c.conversion_wo_id IN (SELECT id FROM demo_wos))
                 AND c.destination_order_id IN (SELECT id FROM demo_orders))) AS conversions_crossing_boundary,
    (SELECT count(*) FROM conversions c WHERE c.nc_record_id IN (SELECT id FROM demo_nc) AND c.id NOT IN (SELECT id FROM demo_conv)) AS outside_conversions_using_demo_nc,
    (SELECT count(*) FROM sweep_counts WHERE NOT child_in_cleanup_set AND rows_pointing_into_scope > 0) AS unexpected_dependent_rows_tables,
    (SELECT count(*) FROM po) AS po_223_found,
    (SELECT count(*) FROM orders o WHERE o.po_line_id IN (SELECT id FROM po_ln) AND o.id NOT IN (SELECT id FROM demo_orders)) AS po_223_nondemo_line_refs,
    (SELECT count(*) FROM orders o WHERE o.customer_po = '223' AND o.id NOT IN (SELECT id FROM demo_orders)) AS po_223_nondemo_text_refs   -- EDIT HERE with the PO number
)
SELECT c.*,
       CASE WHEN c.oars_found <> 8 THEN 'BLOCKED - expected 8 demo OARs, found ' || c.oars_found
            WHEN c.outside_wos_pointing_at_demo_wos + c.demo_wos_pointing_outside > 0 THEN 'BLOCKED - external work-order reference (Section 2)'
            WHEN c.conversions_crossing_boundary + c.outside_conversions_using_demo_nc > 0 THEN 'BLOCKED - conversion dependency crosses the demo boundary (Section 4)'
            WHEN c.unexpected_dependent_rows_tables > 0 THEN 'BLOCKED - unexpected table depends on demo rows (Section 9B)'
            ELSE 'READY FOR DELETION (orders, work orders and their dependents)' END AS oar_wo_scope_status,
       CASE WHEN c.po_223_found = 0 THEN 'PO 223 NOT FOUND - exclude it'
            WHEN c.po_223_nondemo_line_refs + c.po_223_nondemo_text_refs > 0 THEN 'PO 223 NOT SAFE - shared with a non-demo order; exclude it and report the conflict'
            ELSE 'SAFE DEMO PO' END AS po_223_status
FROM checks c;

ROLLBACK;
