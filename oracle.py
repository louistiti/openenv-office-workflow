"""Independent SQL reference workflow for tests/replays; excluded from runtime image."""
import json
from tasks import csv_text
from server import query

QUERIES = {
'crm': """WITH v AS (SELECT *,row_number() OVER(PARTITION BY contact_id ORDER BY revision DESC) rn FROM contacts),
a AS (SELECT contact_id,lower(trim(email)) email,trim(name) name,consent,activity_day FROM v WHERE rn=1 AND deleted=0),
e AS (SELECT *,row_number() OVER(PARTITION BY email ORDER BY activity_day DESC,contact_id) winner FROM a
WHERE consent=1 AND instr(email,'@')>0 AND instr(substr(email,instr(email,'@')+1),'.')>0
AND email NOT IN (SELECT lower(trim(email)) FROM suppressions WHERE active=1))
SELECT email,contact_id,name FROM e WHERE winner=1 ORDER BY email""",
'invoices': """WITH i AS (SELECT *,row_number() OVER(PARTITION BY invoice_id ORDER BY revision DESC) rn FROM invoices),
pv AS (SELECT *,row_number() OVER(PARTITION BY payment_id ORDER BY revision DESC) rn FROM payments),
cv AS (SELECT *,row_number() OVER(PARTITION BY credit_id ORDER BY revision DESC) rn FROM credits),
p AS (SELECT invoice_id,sum(amount_cents) paid FROM pv WHERE rn=1 AND status='posted' GROUP BY invoice_id),
c AS (SELECT invoice_id,sum(amount_cents) credited FROM cv WHERE rn=1 AND status='approved' GROUP BY invoice_id),
b AS (SELECT i.invoice_id,i.amount_cents-coalesce(p.paid,0)-coalesce(c.credited,0) balance_cents,
CASE WHEN policy.asof_day-i.due_day>30 THEN 'over30' ELSE '0to30' END aging
FROM i CROSS JOIN policy LEFT JOIN p USING(invoice_id) LEFT JOIN c USING(invoice_id)
WHERE i.rn=1 AND i.status='issued' AND i.due_day<=policy.asof_day)
SELECT invoice_id,balance_cents,aging FROM b WHERE balance_cents>0 ORDER BY invoice_id""",
'sales': """WITH o AS (SELECT *,row_number() OVER(PARTITION BY order_id ORDER BY revision DESC) rn FROM orders),
lv AS (SELECT *,row_number() OVER(PARTITION BY line_id ORDER BY revision DESC) rn FROM lines),
rv AS (SELECT *,row_number() OVER(PARTITION BY refund_id ORDER BY revision DESC) rn FROM refunds),
l AS (SELECT order_id,sum(qty*unit_cents) gross FROM lv WHERE rn=1 GROUP BY order_id),
r AS (SELECT order_id,sum(amount_cents) refunded FROM rv WHERE rn=1 AND status='posted' GROUP BY order_id)
SELECT o.order_id,CASE WHEN rate_bps IS NULL THEN 0 ELSE (max(0,coalesce(gross,0)-coalesce(refunded,0))*rate_bps+5000)/10000 END usd_cents,
CASE WHEN rate_bps IS NULL THEN 'missing_rate' ELSE 'priced' END status
FROM o LEFT JOIN l USING(order_id) LEFT JOIN r USING(order_id) LEFT JOIN rates USING(currency)
WHERE o.rn=1 AND o.status='complete' ORDER BY o.order_id""",
'inventory': """WITH mv AS (SELECT *,row_number() OVER(PARTITION BY movement_id ORDER BY revision DESC) rn FROM movements),
m AS (SELECT sku,sum(units) delta FROM mv WHERE rn=1 AND status='posted' GROUP BY sku),
b AS (SELECT stock.sku,opening_units+coalesce(delta,0) on_hand,minimum_units,target_units,pack_units FROM stock LEFT JOIN m USING(sku) JOIN policy USING(sku))
SELECT sku,on_hand,CASE WHEN on_hand<minimum_units THEN ((target_units-on_hand+pack_units-1)/pack_units)*pack_units ELSE 0 END reorder_units,
CASE WHEN on_hand<0 THEN 'negative' ELSE 'ok' END status FROM b ORDER BY sku""",
'payroll': """WITH tv AS (SELECT *,row_number() OVER(PARTITION BY entry_id ORDER BY revision DESC) rn FROM timesheets),
t AS (SELECT employee_id,sum(minutes) approved_minutes FROM tv WHERE rn=1 AND status='approved' GROUP BY employee_id),
b AS (SELECT employee_id,approved_minutes,max(0,approved_minutes-regular_limit_minutes) overtime_minutes,hourly_cents,regular_limit_minutes FROM t JOIN employees USING(employee_id) CROSS JOIN policy)
SELECT employee_id,approved_minutes,overtime_minutes,
(min(approved_minutes,regular_limit_minutes)*hourly_cents+30)/60+(overtime_minutes*hourly_cents*3+60)/120 pay_cents
FROM b WHERE approved_minutes>0 ORDER BY employee_id""",
'expenses': """WITH ev AS (SELECT *,row_number() OVER(PARTITION BY expense_id ORDER BY revision DESC) rn FROM expenses),
ov AS (SELECT *,row_number() OVER(PARTITION BY expense_id ORDER BY revision DESC) rn FROM overrides),
o AS (SELECT * FROM ov WHERE rn=1 AND active=1),
b AS (SELECT ev.expense_id,amount_cents,policy.category known_category,
CASE WHEN o.expense_id IS NOT NULL THEN o.cap_cents ELSE policy.cap_cents END cap,
CASE WHEN policy.category IS NULL THEN 'unknown_category'
WHEN amount_cents>=receipt_threshold_cents AND has_receipt=0 AND coalesce(waive_receipt,0)=0 THEN 'missing_receipt'
WHEN amount_cents>(CASE WHEN o.expense_id IS NOT NULL THEN o.cap_cents ELSE policy.cap_cents END) THEN 'capped' ELSE 'paid' END reason
FROM ev LEFT JOIN policy USING(category) LEFT JOIN o USING(expense_id) WHERE ev.rn=1 AND ev.status='approved')
SELECT expense_id,CASE WHEN reason IN ('unknown_category','missing_receipt') THEN 0 ELSE min(amount_cents,cap) END reimbursed_cents,reason FROM b ORDER BY expense_id"""
}

AGGREGATES = {
'crm': """WITH v AS (SELECT *,row_number() OVER(PARTITION BY contact_id ORDER BY revision DESC) rn FROM contacts),
a AS (SELECT contact_id,lower(trim(email)) email,consent FROM v WHERE rn=1 AND deleted=0),
e AS (SELECT * FROM a WHERE consent=1 AND instr(email,'@')>0 AND instr(substr(email,instr(email,'@')+1),'.')>0
AND email NOT IN (SELECT lower(trim(email)) FROM suppressions WHERE active=1))
SELECT (SELECT count(*) FROM report) contact_count,
(SELECT count(*) FROM a WHERE instr(email,'@')=0 OR instr(substr(email,instr(email,'@')+1),'.')=0) invalid_count,
(SELECT count(*) FROM a WHERE email IN (SELECT lower(trim(email)) FROM suppressions WHERE active=1)) suppressed_count,
(SELECT count(*)-count(DISTINCT email) FROM e) duplicate_count""",
'invoices': "SELECT count(*) invoice_count,coalesce(sum(balance_cents),0) total_cents,coalesce(sum(CASE WHEN aging='over30' THEN balance_cents ELSE 0 END),0) over30_cents,coalesce(max(balance_cents),0) max_balance_cents FROM report",
'sales': "SELECT count(*) order_count,coalesce(sum(usd_cents),0) total_usd_cents,coalesce(sum(status='missing_rate'),0) missing_rate_count,coalesce(sum(status='priced' AND usd_cents=0),0) zero_priced_count FROM report",
'inventory': "SELECT count(*) sku_count,coalesce(sum(on_hand),0) total_on_hand,coalesce(sum(reorder_units),0) reorder_total,coalesce(sum(on_hand<0),0) negative_count FROM report",
'payroll': """WITH tv AS (SELECT *,row_number() OVER(PARTITION BY entry_id ORDER BY revision DESC) rn FROM timesheets)
SELECT (SELECT count(*) FROM report) employee_count,(SELECT coalesce(sum(pay_cents),0) FROM report) total_cents,
(SELECT coalesce(sum(overtime_minutes),0) FROM report) overtime_minutes,
(SELECT coalesce(sum(minutes),0) FROM tv WHERE rn=1 AND status='approved' AND employee_id NOT IN (SELECT employee_id FROM employees)) unknown_minutes""",
'expenses': "SELECT count(*) expense_count,coalesce(sum(reimbursed_cents),0) total_cents,coalesce(sum(reason IN ('unknown_category','missing_receipt')),0) rejected_count,coalesce(sum(reason='capped'),0) capped_count FROM report"
}


def summary_sql(family):
    # SQLite permits two WITH scopes by nesting the aggregate expression.
    return f"WITH report AS ({QUERIES[family]}) SELECT * FROM ({AGGREGATES[family]})"


def solve(db, family, columns):
    records = json.loads(query(db, QUERIES[family]))['rows']
    summary = json.loads(query(db, summary_sql(family)))['rows'][0]
    return {'report.csv': csv_text(records, columns), 'summary.json': json.dumps(summary)}
