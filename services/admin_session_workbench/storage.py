import json
import sqlite3
import time
import uuid
from pathlib import Path


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.root / 'queue.sqlite', isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, owner INTEGER, account TEXT,
        source TEXT, config TEXT, mode TEXT, state TEXT, stage TEXT, result TEXT,
        created REAL, cancelled INTEGER DEFAULT 0, delivered INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS cooldowns(account TEXT PRIMARY KEY, until REAL);
        CREATE TABLE IF NOT EXISTS aliases(fingerprint TEXT PRIMARY KEY, account TEXT);
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, paused INTEGER DEFAULT 0);
        CREATE UNIQUE INDEX IF NOT EXISTS account_lock ON jobs(account) WHERE state='running';''')
        self.recover_new_sessions()
        # Interrupted destructive operations must never be replayed automatically.
        self.db.execute("UPDATE jobs SET state='interrupted',stage='Прервано перезапуском; создайте новую задачу' WHERE state='running'")

    def recover_new_sessions(self, owner=None):
        query = "SELECT id,owner FROM jobs WHERE mode='migrate_clean' AND result IS NULL"
        params = ()
        if owner is not None:
            query += ' AND owner=?'
            params = (owner,)
        for row in self.db.execute(query, params).fetchall():
            for phase in ('after_cleanup', 'before_cleanup'):
                archive = self.root / 'new_sessions' / str(row['owner']) / row['id'] / phase / 'account.zip'
                if archive.is_file() and not archive.is_symlink():
                    self.update(row['id'], result=str(archive))
                    break

    def add(self, owner, account, source, config, mode, *, state="queued"):
        if state not in {"queued", "draft"}:
            raise ValueError("Invalid initial job state")
        alias = self.db.execute('SELECT account FROM aliases WHERE fingerprint=?', (account,)).fetchone()
        if alias:
            account = alias[0]
        ident = uuid.uuid4().hex[:16]
        self.db.execute('INSERT INTO jobs(id,owner,account,source,config,mode,state,stage,created) VALUES(?,?,?,?,?,?,?,\'Ожидание\',?)',
                        (ident, owner, account, str(source), json.dumps(config), mode, state, time.time()))
        return ident

    def update(self, ident, **values):
        allowed = {'state', 'stage', 'result', 'cancelled', 'delivered'}
        assert set(values) <= allowed
        self.db.execute('UPDATE jobs SET '+','.join(f'{k}=?' for k in values)+' WHERE id=?', (*values.values(), ident))

    def get(self, ident, owner=None):
        row = self.db.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone()
        return dict(row) if row and (owner is None or row['owner'] == owner) else None

    def rows(self, owner):
        return [dict(r) for r in self.db.execute('SELECT * FROM jobs WHERE owner=? ORDER BY created DESC', (owner,))]

    def pause(self, owner, value):
        self.db.execute('INSERT INTO users VALUES(?,?) ON CONFLICT(id) DO UPDATE SET paused=excluded.paused', (owner, int(value)))

    def claim(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute("SELECT * FROM jobs j WHERE state='queued' AND cancelled=0 AND NOT EXISTS(SELECT 1 FROM cooldowns c WHERE c.account=j.account AND c.until>strftime('%s','now')) AND NOT EXISTS(SELECT 1 FROM users u WHERE u.id=j.owner AND paused=1) AND NOT EXISTS(SELECT 1 FROM jobs a WHERE a.account=j.account AND a.state='running') ORDER BY created LIMIT 1").fetchone()
            if row:
                self.db.execute("UPDATE jobs SET state='running' WHERE id=?", (row['id'],))
            self.db.execute('COMMIT')
            return dict(row) if row else None
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def cooldown(self, account, seconds):
        self.db.execute('INSERT INTO cooldowns VALUES(?,?) ON CONFLICT(account) DO UPDATE SET until=MAX(until,excluded.until)',
                        (account, time.time() + seconds))

    def remaining(self, account):
        row = self.db.execute('SELECT until FROM cooldowns WHERE account=?', (account,)).fetchone()
        return max(0, int(row[0] - time.time()) + 1) if row else 0
