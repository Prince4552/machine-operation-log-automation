from openpyxl import Workbook
from pathlib import Path
from decimal import Decimal
import random, os

ROOT=Path(__file__).resolve().parent/'input'; ROOT.mkdir(parents=True,exist_ok=True)
headers=['expense_id','employee_ref','department','expense_date','category','merchant','project_code','payment_method','reimbursable','receipt_available','quantity','unit_amount','currency','fx_rate_to_reporting','tax_rate','discount_rate','source_reference']
rng=random.Random(20260919)
employees=[f'EMP-{i:04d}' for i in range(1,251)]
deps=['Finance','Sales','HR','Operations','Engineering','Procurement','Legal','IT']
cats=['travel','meal','accommodation','other']
merchants={'travel':['JR East','ANA','JAL','Taxi Network','Railway Services','Airport Shuttle'],'meal':['Restaurant A','Restaurant B','Cafe Central','Business Dining','Catering Co'],'accommodation':['Business Hotel A','Business Hotel B','Hotel Group C','Conference Hotel'],'other':['Office Supply Co','Courier Service','Software Store','Printing Co','Misc Services']}
projects=[f'PRJ-{i:04d}' for i in range(1,121)]
payments=['CorporateCard','BankTransfer','EmployeeReimbursement','Cash']
cur=[('JPY',1.0),('USD',150.0),('EUR',162.0)]

def row(i, anomaly=False):
    cat=cats[(i*7)%4]; emp=employees[(i*13)%len(employees)]; dep=deps[(i*5)%len(deps)]; merchant=merchants[cat][i%len(merchants[cat])]; proj=projects[(i*3)%len(projects)]; pay=payments[i%4]
    month=(i%12)+1; day=(i%27)+1; date=f'2026-{month:02d}-{day:02d}'
    if cat=='travel': qty=1; unit=3000+(i*137)%70000
    elif cat=='meal': qty=(i%4)+1; unit=600+(i*83)%14000
    elif cat=='accommodation': qty=(i%3)+1; unit=6000+(i*101)%28000
    else: qty=(i%5)+1; unit=300+(i*59)%18000
    currency,fx=cur[i%3]; tax=0.10 if cat!='other' else 0.08; disc=0.05 if i%7==0 else 0.0
    receipt=True; reimb=(i%4)!=0
    eid=f'EXP-{i:06d}'; source=f'SRC-{i:08d}'
    if anomaly and i%2000==0: eid='EXP-000001'
    if anomaly and i%3333==0: currency,fx='GBP',190.0
    if anomaly and i%2500==0: receipt=False
    if anomaly and i%1500==0: unit=250000
    if anomaly and i%1800==0: source=''
    return [eid,emp,dep,date,cat,merchant,proj,pay,reimb,receipt,qty,unit,currency,fx,tax,disc,source]

def write_xlsx(path, sheets):
    wb=Workbook(write_only=True)
    for name,rows in sheets.items():
        ws=wb.create_sheet(name);ws.append(headers)
        for r in rows:ws.append(r)
    wb.save(path)

write_xlsx(ROOT/'enterprise_expenses_10000.xlsx', {'Expenses':[row(i) for i in range(1,10001)]})
ms={'Travel':[],'Meals':[],'Other':[]}
for i in range(1,10001):
    r=row(i+20000);ms['Travel' if r[4]=='travel' else ('Meals' if r[4]=='meal' else 'Other')].append(r)
write_xlsx(ROOT/'enterprise_expenses_multi_sheet_10000.xlsx', ms)
write_xlsx(ROOT/'enterprise_expenses_anomalies_10000.xlsx', {'Expenses':[row(i,True) for i in range(1,10001)]})
# Smaller CSV to prove CSV input works too.
with (ROOT/'enterprise_expenses_5000.csv').open('w',encoding='utf-8',newline='') as f:
    import csv
    w=csv.writer(f);w.writerow(headers)
    for i in range(1,5001):w.writerow(row(i+40000))
for p in sorted(ROOT.iterdir()): print(p.name,p.stat().st_size)
