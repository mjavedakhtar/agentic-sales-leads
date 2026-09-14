"""Small transactional repository. Decisions and pipeline writes are idempotent."""
import json
from contextlib import contextmanager
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, path):
        self.path=str(path)
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reviews (run_id TEXT, lead_id TEXT, data TEXT NOT NULL, PRIMARY KEY(run_id,lead_id));
                CREATE TABLE IF NOT EXISTS pipeline (id TEXT PRIMARY KEY, run_id TEXT, lead_id TEXT, data TEXT NOT NULL, UNIQUE(run_id,lead_id));
                CREATE TABLE IF NOT EXISTS evaluations (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS buyer_checks (run_id TEXT PRIMARY KEY, id TEXT NOT NULL UNIQUE, data TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        conn=sqlite3.connect(self.path,timeout=20)
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def save_run(self,run):
        with self.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO runs VALUES (?,?)',(run['id'],json.dumps(run)))
        return run

    def get_run(self,run_id):
        with self.connect() as conn:
            row=conn.execute('SELECT data FROM runs WHERE id=?',(run_id,)).fetchone()
            if not row:return None
            run=json.loads(row['data'])
            reviews={r['lead_id']:json.loads(r['data']) for r in conn.execute('SELECT lead_id,data FROM reviews WHERE run_id=?',(run_id,))}
        for lead in run['leads']: lead['review']=reviews.get(lead['id'])
        return run

    def runs(self):
        with self.connect() as conn:
            return sorted([json.loads(x['data']) for x in conn.execute('SELECT data FROM runs')],key=lambda x:x['created_at'],reverse=True)

    def review(self,run_id,lead_id):
        with self.connect() as conn:
            row=conn.execute('SELECT data FROM reviews WHERE run_id=? AND lead_id=?',(run_id,lead_id)).fetchone()
        return json.loads(row['data']) if row else None

    def save_decision(self,run_id,lead_id,decision,note):
        if decision not in {'approve','reject','needs_research'} or len(note.strip()) < 3:
            raise Conflict('Select a valid decision and include an explanatory note.')
        run=self.get_run(run_id)
        lead=next(x for x in run['leads'] if x['id']==lead_id)
        if lead['gate']['status']=='blocked' and decision=='approve':
            raise Conflict('This product has a hard technical mismatch and cannot be approved.')
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old=conn.execute('SELECT data FROM reviews WHERE run_id=? AND lead_id=?',(run_id,lead_id)).fetchone()
            if old:
                review=json.loads(old['data'])
                if review['decision']!=decision or review['note']!=note:
                    raise Conflict('This lead already has a final decision. Start a new research run to reassess it with new evidence.')
                return review
            at=now()
            review={'decision':decision,'note':note,'at':at}
            conn.execute('INSERT INTO reviews VALUES (?,?,?)',(run_id,lead_id,json.dumps(review)))
            # Decision, pipeline side effect and audit event commit as one transaction.
            run['updated_at']=at
            run['trace'].append({'node':'human_decision','label':'Human qualification recorded','status':'completed','detail':f"{lead['name']}: {decision.replace('_',' ')}. Decision and required note persisted atomically.",'at':at,'duration_ms':0})
            conn.execute('UPDATE runs SET data=? WHERE id=?',(json.dumps(run),run_id))
            if decision=='approve':
                lead['review']=review
                item={'id':uuid4().hex,'lead':lead,'run_id':run_id,'product_name':run['scope']['product_name'],'status':'qualified','notes':[{'text':note,'at':at}], 'history':[{'event':'qualified','detail':'Human approved this research lead. '+note,'at':at}], 'refresh':{'status':'saved_capture','checked_at':None,'captured_at':lead['evidence'][0]['captured_at']}}
                conn.execute('INSERT INTO pipeline VALUES (?,?,?,?)',(item['id'],run_id,lead_id,json.dumps(item)))
        return review

    def pipeline(self):
        with self.connect() as conn:
            return [json.loads(x['data']) for x in conn.execute('SELECT data FROM pipeline ORDER BY rowid DESC')]

    def pipeline_item(self,item_id):
        with self.connect() as conn:
            row=conn.execute('SELECT data FROM pipeline WHERE id=?',(item_id,)).fetchone()
        return json.loads(row['data']) if row else None

    def update_pipeline(self,item_id,status=None,note=None,refresh=False):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT data FROM pipeline WHERE id=?',(item_id,)).fetchone()
            if not row:raise KeyError(item_id)
            item=json.loads(row['data']); at=now()
            if status and status!=item['status']:
                allowed={'qualified':{'contacted','closed'},'contacted':{'discovery','closed'},'discovery':{'closed'},'closed':set()}
                if status not in allowed[item['status']]:
                    raise Conflict(f"Cannot move from {item['status']} to {status}. Follow qualified, contacted, discovery, then closed, or close an active lead.")
                if not note:raise Conflict('A note is required to explain a pipeline transition.')
                item['history'].append({'event':'status_changed','detail':f"{item['status']} to {status}: {note}",'at':at})
                item['status']=status
            if note:
                item['notes'].append({'text':note,'at':at})
                item['history'].append({'event':'note_added','detail':note,'at':at})
            if refresh:
                item['refresh'].update(status='saved_evidence_checked',checked_at=at)
                item['history'].append({'event':'saved_evidence_checked','detail':'Rechecked the stored capture reference. No web fetch was performed; capture date and company facts are unchanged.','at':at})
            conn.execute('UPDATE pipeline SET data=? WHERE id=?',(json.dumps(item),item_id))
        return item

    def save_eval(self,result):
        with self.connect() as conn: conn.execute('INSERT INTO evaluations VALUES (?,?)',(uuid4().hex,json.dumps(result)))
        return result

    def latest_eval(self):
        with self.connect() as conn: row=conn.execute('SELECT data FROM evaluations ORDER BY rowid DESC LIMIT 1').fetchone()
        return json.loads(row['data']) if row else None

    def save_buyer_check(self, check):
        """Store the optional comparison independently from the original run."""
        with self.connect() as conn:
            conn.execute('INSERT INTO buyer_checks (run_id,id,data) VALUES (?,?,?) '
                         'ON CONFLICT(run_id) DO UPDATE SET id=excluded.id,data=excluded.data',
                         (check['run_id'], check['id'], json.dumps(check)))
        return check

    def get_buyer_check(self, run_id):
        with self.connect() as conn:
            row = conn.execute('SELECT data FROM buyer_checks WHERE run_id=?', (run_id,)).fetchone()
        return json.loads(row['data']) if row else None

    def buyer_checks(self):
        with self.connect() as conn:
            return [json.loads(row['data']) for row in conn.execute('SELECT data FROM buyer_checks')]
