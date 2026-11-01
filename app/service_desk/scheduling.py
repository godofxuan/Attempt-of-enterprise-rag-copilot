"""Loan stock is physical state plus half-open date reservations, in the same DB."""
from datetime import date,timedelta
import json
from .store import ServiceError

OPEN_LOANS=('PENDING_APPROVAL','IN_PROGRESS','RESERVED','CHECKED_OUT')

def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS asset_reservations(ticket_id TEXT PRIMARY KEY,tenant TEXT NOT NULL,
        asset_id TEXT NOT NULL,start_date TEXT NOT NULL,end_exclusive TEXT NOT NULL,active INTEGER NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS reservation_dates ON asset_reservations(tenant,asset_id,active,start_date,end_exclusive)')
    db.execute('CREATE TABLE IF NOT EXISTS asset_details(tenant TEXT,asset_id TEXT,payload TEXT,PRIMARY KEY(tenant,asset_id))')
    definition=db.execute("SELECT sql FROM sqlite_master WHERE name='one_open_loan'").fetchone()
    if definition and 'CHECKED_OUT' not in definition[0]:db.execute('DROP INDEX one_open_loan')
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_open_loan ON tickets(tenant,owner) WHERE status IN ('PENDING_APPROVAL','IN_PROGRESS','RESERVED','CHECKED_OUT')")

def interval(facts):
    try:
        start=date.fromisoformat(facts['loan_start']);end=date.fromisoformat(facts['loan_end'])
        if end<start:raise ValueError()
        return start.isoformat(),(end+timedelta(days=1)).isoformat()
    except (ValueError,KeyError,TypeError,OverflowError):raise ServiceError('INVALID_DATES') from None

def available(db,tenant,asset_id,facts,exclude_ticket=None):
    start,end=interval(facts)
    return not db.execute('''SELECT 1 FROM asset_reservations WHERE tenant=? AND asset_id=? AND active=1
        AND start_date<? AND end_exclusive>? AND ticket_id!=?''',(tenant,asset_id,end,start,exclude_ticket or '')).fetchone()

def inventory(db,actor,facts=None):
    details={r['asset_id']:json.loads(r['payload']) for r in db.execute('SELECT * FROM asset_details WHERE tenant=?',(actor.tenant_id,))}
    rows=[dict(r) for r in db.execute('SELECT asset_id,category,available,version FROM assets WHERE tenant=? AND available=1 ORDER BY asset_id',(actor.tenant_id,))]
    if facts is None:return rows
    result=[];dated=bool(facts.get('loan_start') and facts.get('loan_end'))
    for asset in rows:
        info=details.get(asset['asset_id'],{})
        if facts.get('min_memory_gb') and info.get('memory_gb',0)<facts['min_memory_gb']:continue
        if facts.get('pickup_location') and info.get('pickup_location')!=facts['pickup_location']:continue
        if dated and not available(db,actor.tenant_id,asset['asset_id'],facts):continue
        result.append({**asset,'details':info})
    return result

def check_resource(db,actor,asset_id,facts,exclude_ticket=None):
    asset=db.execute('SELECT * FROM assets WHERE tenant=? AND asset_id=? AND available=1',(actor.tenant_id,asset_id)).fetchone()
    if not asset or asset['category']!='laptop':raise ServiceError('RESOURCE_CHANGED')
    if not available(db,actor.tenant_id,asset_id,facts,exclude_ticket):raise ServiceError('SCHEDULE_CONFLICT')
    if not any(a['asset_id']==asset_id for a in inventory(db,actor,{k:v for k,v in facts.items() if k not in ('loan_start','loan_end')})):
        raise ServiceError('RESOURCE_PREFERENCE_MISMATCH')
    return dict(asset)

def reserve(db,actor,ticket):
    check_resource(db,actor,ticket['asset_id'],ticket['parameters'],ticket['ticket_id'])
    start,end=interval(ticket['parameters'])
    db.execute('INSERT INTO asset_reservations VALUES(?,?,?,?,?,1) ON CONFLICT(ticket_id) DO UPDATE SET start_date=excluded.start_date,end_exclusive=excluded.end_exclusive,active=1',
        (ticket['ticket_id'],actor.tenant_id,ticket['asset_id'],start,end))
