"""Fresh seeded synthetic office tasks; expected outcomes never exposed to agent tools."""
import csv
import io
import random
from dataclasses import dataclass

FAMILIES = ('crm', 'invoices', 'sales', 'inventory', 'payroll', 'expenses')
TASK_IDS = tuple(f'{family}-{level}' for family in FAMILIES for level in ('standard', 'advanced'))

@dataclass
class Task:
    task_id: str
    tables: dict
    instructions: str
    columns: list
    rows: list
    summary: dict

    @property
    def files(self):
        return {**{name + '.csv': csv_text(rows) for name, rows in self.tables.items()},
                'brief.txt': self.instructions}


def csv_text(rows, columns=None):
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=columns or list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def latest(rows, key):
    result = {}
    for row in rows:
        if row[key] not in result or row['revision'] > result[row[key]]['revision']:
            result[row[key]] = row
    return list(result.values())


def half_up(n, d):
    return (2 * n + d) // (2 * d)


def make_task(task_id, seed=0):
    if task_id not in TASK_IDS:
        raise ValueError('Unknown task_id')
    family, level = task_id.split('-')
    rng = random.Random(f'office-v1:{task_id}:{seed}')
    hard = level == 'advanced'
    n = rng.randint(22, 35) if hard else rng.randint(10, 17)
    tables = {}
    rows = []
    if family == 'crm':
        contacts = []
        suppressions = []
        for i in range(n):
            email = f' Client{i // 2}@EXAMPLE.COM ' if i % 3 else f'client{i}@example.net'
            contacts.append(dict(contact_id=f'C{i:03}', revision=1, email=email,
                                 name=f' Person {i} ', consent=int(i % 4 != 0), deleted=0,
                                 activity_day=rng.randint(1, 100)))
            if i % 5 == 0:
                contacts.append({**contacts[-1], 'revision': 2, 'consent': int(i % 10 == 0),
                                 'deleted': int(hard and i % 10 == 0), 'activity_day': 101 + i})
            if i % 7 == 0:
                suppressions.append(dict(email=email.lower().strip(), active=1))
        if hard:
            contacts.extend([dict(contact_id='BAD', revision=1, email='missing-at', name='Bad', consent=1, deleted=0, activity_day=300),
                             dict(contact_id='EMPTY', revision=1, email='  ', name='Blank', consent=1, deleted=0, activity_day=400)])
            suppressions.append(dict(email='Client1@example.com', active=0))
        tables = dict(contacts=contacts, suppressions=suppressions)
        blocked = {x['email'].strip().lower() for x in suppressions if x['active'] == 1}
        active = [x for x in latest(contacts, 'contact_id') if not x['deleted']]
        invalid = sum('@' not in x['email'].strip() or '.' not in x['email'].split('@')[-1] for x in active)
        groups = {}
        for x in active:
            e = x['email'].strip().lower()
            if '@' not in e or '.' not in e.split('@')[-1] or not x['consent'] or e in blocked:
                continue
            groups.setdefault(e, []).append(x)
        for e, group in groups.items():
            winner = sorted(group, key=lambda x: (-x['activity_day'], x['contact_id']))[0]
            rows.append(dict(email=e, contact_id=winner['contact_id'], name=winner['name'].strip()))
        summary = dict(contact_count=len(rows), invalid_count=invalid,
                       suppressed_count=sum(x['email'].strip().lower() in blocked for x in active),
                       duplicate_count=sum(len(g) - 1 for g in groups.values()))
        rules = 'Use latest revision per contact_id BEFORE all other filters. Discard deleted contacts. Trim and lowercase email; valid means it contains @ and its part after @ contains a dot. Count invalid contacts before consent/suppression filtering. Keep consent=1 and exclude normalized emails with active=1 suppression. Deduplicate remaining emails by greatest activity_day, tie by lexicographically smallest contact_id; trim name. suppressed_count counts all nondeleted latest contacts whose normalized email is actively suppressed, independent of consent/validity. duplicate_count counts eligible rows removed by email deduplication.'
        columns = ['email', 'contact_id', 'name']
    elif family == 'invoices':
        invoices, payments, credits = [], [], []
        asof = rng.randint(70, 110)
        for i in range(n):
            ident = f'I{i:03}'
            invoices.append(dict(invoice_id=ident, revision=1, amount_cents=rng.randint(10, 150) * 100,
                                 due_day=rng.randint(1, 130), status='issued'))
            if i % 4 == 0:
                invoices.append({**invoices[-1], 'revision': 2, 'status': 'void' if i % 8 == 0 else 'issued',
                                 'amount_cents': invoices[-1]['amount_cents'] + 137})
            payments.append(dict(payment_id=f'P{i:03}', revision=1, invoice_id=ident,
                                 amount_cents=rng.randint(0, 160) * 100, status='posted'))
            if i % 3 == 0:
                payments.append({**payments[-1], 'revision': 2, 'status': 'pending' if i % 6 == 0 else 'posted',
                                 'amount_cents': rng.randint(0, 20) * (-100 if hard else 100)})
            credits.append(dict(credit_id=f'K{i:03}', revision=1, invoice_id=ident,
                                amount_cents=rng.randint(0, 10) * 100, status='approved' if i % 5 else 'draft'))
        if hard:
            credits.append({**credits[1], 'revision': 2, 'amount_cents': 39})
            payments.append(dict(payment_id='ORPHAN', revision=1, invoice_id='MISSING', amount_cents=99999, status='posted'))
        tables = dict(invoices=invoices, payments=payments, credits=credits, policy=[dict(asof_day=asof)])
        p, c = {}, {}
        for x in latest(payments, 'payment_id'):
            if x['status'] == 'posted': p[x['invoice_id']] = p.get(x['invoice_id'], 0) + x['amount_cents']
        for x in latest(credits, 'credit_id'):
            if x['status'] == 'approved': c[x['invoice_id']] = c.get(x['invoice_id'], 0) + x['amount_cents']
        for x in latest(invoices, 'invoice_id'):
            bal = x['amount_cents'] - p.get(x['invoice_id'], 0) - c.get(x['invoice_id'], 0)
            if x['status'] == 'issued' and x['due_day'] <= asof and bal > 0:
                rows.append(dict(invoice_id=x['invoice_id'], balance_cents=bal,
                                 aging='over30' if asof - x['due_day'] > 30 else '0to30'))
        summary = dict(invoice_count=len(rows), total_cents=sum(x['balance_cents'] for x in rows),
                       over30_cents=sum(x['balance_cents'] for x in rows if x['aging'] == 'over30'),
                       max_balance_cents=max((x['balance_cents'] for x in rows), default=0))
        rules = 'Use latest revision independently per invoice_id, payment_id and credit_id. Only posted payments and approved credits count. Payments may be negative (refunds): preserve the sign. Balance = invoice amount - summed payments - summed credits; avoid payment/credit fanout when joining. Ignore orphan transactions. Output only issued invoices due on or before policy.asof_day with positive balance. aging=over30 if asof_day-due_day>30, else 0to30.'
        columns = ['invoice_id', 'balance_cents', 'aging']
    elif family == 'sales':
        orders, lines, refunds = [], [], []
        rates = [dict(currency='USD', rate_bps=10000), dict(currency='EUR', rate_bps=rng.randint(10500, 12500)), dict(currency='JPY', rate_bps=70)]
        for i in range(n):
            ident = f'O{i:03}'
            orders.append(dict(order_id=ident, revision=1, currency=rng.choice(['USD', 'EUR', 'JPY'] + (['XYZ'] if hard else [])), status='complete'))
            if i % 5 == 0: orders.append({**orders[-1], 'revision': 2, 'status': 'canceled'})
            for j in range(1 + i % 3):
                lines.append(dict(line_id=f'L{i:03}-{j}', revision=1, order_id=ident, qty=1 + j, unit_cents=rng.randint(50, 900)))
                if hard and j == 1: lines.append({**lines[-1], 'revision': 2, 'qty': 1})
            refunds.append(dict(refund_id=f'R{i:03}', revision=1, order_id=ident, amount_cents=rng.randint(0, 200), status='posted' if i % 4 else 'pending'))
            if hard and i % 7 == 0: refunds.append({**refunds[-1], 'revision': 2, 'amount_cents': 1999})
        tables = dict(orders=orders, lines=lines, refunds=refunds, rates=rates)
        gross, refund = {}, {}
        for x in latest(lines, 'line_id'): gross[x['order_id']] = gross.get(x['order_id'], 0) + x['qty'] * x['unit_cents']
        for x in latest(refunds, 'refund_id'):
            if x['status'] == 'posted': refund[x['order_id']] = refund.get(x['order_id'], 0) + x['amount_cents']
        rate = {x['currency']: x['rate_bps'] for x in rates}
        for x in latest(orders, 'order_id'):
            if x['status'] != 'complete': continue
            net = max(0, gross.get(x['order_id'], 0) - refund.get(x['order_id'], 0))
            rows.append(dict(order_id=x['order_id'], usd_cents=half_up(net * rate[x['currency']], 10000) if x['currency'] in rate else 0,
                             status='priced' if x['currency'] in rate else 'missing_rate'))
        summary = dict(order_count=len(rows), total_usd_cents=sum(x['usd_cents'] for x in rows),
                       missing_rate_count=sum(x['status'] == 'missing_rate' for x in rows),
                       zero_priced_count=sum(x['status'] == 'priced' and x['usd_cents'] == 0 for x in rows))
        rules = 'Use latest revisions per order_id, line_id, refund_id. Only complete orders; only posted refunds. Sum qty*unit_cents per order BEFORE joining refund totals. Net native cents=max(0,gross-refunds). Convert using rates.rate_bps/10000 and round half up ONCE per order to integer USD cents. Missing currency rate: retain row with usd_cents=0,status=missing_rate, never silently assume parity. Otherwise status=priced. Zero_priced_count excludes missing rates.'
        columns = ['order_id', 'usd_cents', 'status']
    elif family == 'inventory':
        stock, movements, policy = [], [], []
        for i in range(n):
            sku = f'S{i:03}'
            stock.append(dict(sku=sku, opening_units=rng.randint(0, 25)))
            policy.append(dict(sku=sku, minimum_units=rng.randint(5, 15), target_units=rng.randint(20, 35), pack_units=rng.choice([1, 4, 6, 10])))
            for j in range(2 + i % 3):
                movements.append(dict(movement_id=f'M{i:03}-{j}', revision=1, sku=sku, units=rng.randint(-18, 12), status='posted' if j % 3 else 'pending'))
                if hard and j == 1: movements.append({**movements[-1], 'revision': 2, 'units': rng.randint(-25, 5), 'status': 'posted'})
        if hard: movements.append(dict(movement_id='ORPHAN', revision=1, sku='UNKNOWN', units=-999, status='posted'))
        tables = dict(stock=stock, movements=movements, policy=policy)
        delta = {}
        for x in latest(movements, 'movement_id'):
            if x['status'] == 'posted': delta[x['sku']] = delta.get(x['sku'], 0) + x['units']
        bysku = {x['sku']: x for x in policy}
        for x in stock:
            p = bysku[x['sku']]
            onhand = x['opening_units'] + delta.get(x['sku'], 0)
            reorder = ((p['target_units'] - onhand + p['pack_units'] - 1) // p['pack_units']) * p['pack_units'] if onhand < p['minimum_units'] else 0
            rows.append(dict(sku=x['sku'], on_hand=onhand, reorder_units=reorder, status='negative' if onhand < 0 else 'ok'))
        summary = dict(sku_count=len(rows), total_on_hand=sum(x['on_hand'] for x in rows),
                       reorder_total=sum(x['reorder_units'] for x in rows), negative_count=sum(x['on_hand'] < 0 for x in rows))
        rules = 'Output every stock SKU, including zero movements. Use latest revision per movement_id BEFORE filtering status=posted; ignore unknown SKUs. On_hand=opening_units+sum signed units; preserve negative balances, do not clamp. Reorder only when on_hand<minimum_units (strict): target-on_hand rounded UP to a multiple of pack_units. status=negative when on_hand<0 else ok.'
        columns = ['sku', 'on_hand', 'reorder_units', 'status']
    elif family == 'payroll':
        employees, timesheets = [], []
        limit = rng.choice([1800, 2100, 2400])
        for i in range(n):
            ident = f'E{i:03}'
            employees.append(dict(employee_id=ident, hourly_cents=rng.randint(12, 40) * 100 + rng.randint(0, 99)))
            for j in range(2 + i % 4):
                timesheets.append(dict(entry_id=f'T{i:03}-{j}', revision=1, employee_id=ident,
                                       minutes=rng.randint(300, 950), status='approved' if j % 3 else 'pending'))
                if hard and j == 1: timesheets.append({**timesheets[-1], 'revision': 2, 'minutes': 47 + i, 'status': 'approved' if i % 3 else 'rejected'})
        if hard: timesheets.append(dict(entry_id='UNKNOWN', revision=1, employee_id='MISSING', minutes=317, status='approved'))
        tables = dict(employees=employees, timesheets=timesheets, policy=[dict(regular_limit_minutes=limit)])
        minutes = {}
        for x in latest(timesheets, 'entry_id'):
            if x['status'] == 'approved': minutes[x['employee_id']] = minutes.get(x['employee_id'], 0) + x['minutes']
        known = {x['employee_id'] for x in employees}
        for x in employees:
            m = minutes.get(x['employee_id'], 0)
            if m == 0: continue
            overtime = max(0, m - limit)
            pay = half_up(min(m, limit) * x['hourly_cents'], 60) + half_up(overtime * x['hourly_cents'] * 3, 120)
            rows.append(dict(employee_id=x['employee_id'], approved_minutes=m, overtime_minutes=overtime, pay_cents=pay))
        summary = dict(employee_count=len(rows), total_cents=sum(x['pay_cents'] for x in rows),
                       overtime_minutes=sum(x['overtime_minutes'] for x in rows), unknown_minutes=sum(v for k, v in minutes.items() if k not in known))
        rules = 'All entries belong to one pay week. Use latest revision per entry_id BEFORE filtering approved. Sum approved minutes per employee before applying policy.regular_limit_minutes. Overtime=max(0,total-limit). Pay=round_half_up(regular_minutes*hourly_cents/60)+round_half_up(overtime_minutes*hourly_cents*1.5/60); round the two components SEPARATELY. Output known employees with positive approved minutes. Exclude unknown employees from pay, but sum their approved minutes into unknown_minutes.'
        columns = ['employee_id', 'approved_minutes', 'overtime_minutes', 'pay_cents']
    else:
        expenses, overrides = [], []
        policies = [dict(category='meal', cap_cents=rng.randint(20, 40) * 100, receipt_threshold_cents=1500),
                    dict(category='travel', cap_cents=rng.randint(80, 150) * 100, receipt_threshold_cents=0),
                    dict(category='office', cap_cents=rng.randint(30, 60) * 100, receipt_threshold_cents=2500)]
        for i in range(n):
            ident = f'X{i:03}'
            expenses.append(dict(expense_id=ident, revision=1, category=rng.choice(['meal', 'travel', 'office', 'unknown']),
                                 amount_cents=rng.randint(5, 180) * 100, has_receipt=int(i % 3 != 0), status='approved'))
            if i % 5 == 0: expenses.append({**expenses[-1], 'revision': 2, 'status': 'void' if i % 10 else 'approved', 'amount_cents': 2901})
            if hard and i % 4 == 0:
                overrides.append(dict(expense_id=ident, revision=1, active=1, waive_receipt=1, cap_cents=12345))
                if i % 8 == 0: overrides.append({**overrides[-1], 'revision': 2, 'active': 0})
        if not overrides: overrides = [dict(expense_id='NONE', revision=1, active=0, waive_receipt=0, cap_cents=0)]
        tables = dict(expenses=expenses, policy=policies, overrides=overrides)
        p = {x['category']: x for x in policies}
        o = {x['expense_id']: x for x in latest(overrides, 'expense_id') if x['active']}
        for x in latest(expenses, 'expense_id'):
            if x['status'] != 'approved': continue
            rule, amendment = p.get(x['category']), o.get(x['expense_id'])
            if rule is None: amount, reason = 0, 'unknown_category'
            elif x['amount_cents'] >= rule['receipt_threshold_cents'] and not x['has_receipt'] and not (amendment and amendment['waive_receipt']): amount, reason = 0, 'missing_receipt'
            else:
                cap = amendment['cap_cents'] if amendment else rule['cap_cents']
                amount = min(x['amount_cents'], cap)
                reason = 'capped' if amount < x['amount_cents'] else 'paid'
            rows.append(dict(expense_id=x['expense_id'], reimbursed_cents=amount, reason=reason))
        summary = dict(expense_count=len(rows), total_cents=sum(x['reimbursed_cents'] for x in rows),
                       rejected_count=sum(x['reason'] in ('unknown_category', 'missing_receipt') for x in rows),
                       capped_count=sum(x['reason'] == 'capped' for x in rows))
        rules = 'Use latest revision per expense_id and override expense_id BEFORE filtering. Output only approved expenses. Unknown categories are always rejected, even with an override. At amount>=receipt_threshold_cents a receipt is required, unless the latest active override waives it. Active overrides REPLACE cap_cents; inactive latest overrides cancel prior amendments. Reimbursement=min(amount,applicable cap). reason precedence: unknown_category, missing_receipt, capped, paid.'
        columns = ['expense_id', 'reimbursed_cents', 'reason']
    for records in tables.values(): rng.shuffle(records)
    rows.sort(key=lambda x: x[columns[0]])
    instructions = f'Office Workflow Lab v1 / {task_id}\nAll files are synthetic. Perform the complete requested workflow using source CSVs and SQLite tables of the same names.\n{rules}\nCreate report.csv with exactly these columns: {",".join(columns)}. Include one row per output entity, no duplicate keys, order irrelevant. Numbers must be integers in the specified units.\nCreate summary.json with exactly these integer keys: {", ".join(summary)}. Values summarize report rows except explicitly documented source exception counts.\nBoth artifacts are required for full credit. Do not invent absent data. SQL is read-only SELECT/CTE with SQLite functions; no Python, shell or external files. Read/query sources, write artifacts, then submit. Tools never reveal target values. The episode ends after 24 actions; submit earlier when complete.'
    return Task(task_id, tables, instructions, columns, rows, summary)
