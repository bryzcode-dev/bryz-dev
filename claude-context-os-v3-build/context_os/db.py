from __future__ import annotations
import json
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 3

class ContextDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.fts5 = False

    def initialize(self):
        c = self.conn
        c.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS knowledge(
          id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
          status TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0, confidence REAL NOT NULL DEFAULT 0.5,
          project_id TEXT, domain TEXT, tags_json TEXT NOT NULL DEFAULT '[]', evidence_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL, verified_at TEXT, last_used_at TEXT, last_verified_at TEXT,
          valid_from TEXT, valid_until TEXT, superseded_by TEXT, source_path TEXT,
          provenance_json TEXT NOT NULL DEFAULT '{}', applicability_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS projects(
          project_id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL, types_json TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'active', updated_at TEXT NOT NULL, meta_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS resources(
          id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, type TEXT NOT NULL,
          value TEXT NOT NULL, relation TEXT NOT NULL DEFAULT 'uses', meta_json TEXT NOT NULL DEFAULT '{}',
          UNIQUE(project_id,type,value,relation)
        );
        CREATE TABLE IF NOT EXISTS dependencies(
          src_project TEXT NOT NULL, dst_project TEXT NOT NULL, relation TEXT NOT NULL,
          meta_json TEXT NOT NULL DEFAULT '{}', UNIQUE(src_project,dst_project,relation)
        );
        CREATE TABLE IF NOT EXISTS tasks(
          id TEXT PRIMARY KEY, project_id TEXT, title TEXT NOT NULL, status TEXT NOT NULL,
          constraints_json TEXT NOT NULL DEFAULT '[]', journal_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, meta_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS events(
          id TEXT PRIMARY KEY, event_type TEXT NOT NULL, created_at TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS assistant_preferences(
          id TEXT PRIMARY KEY, text TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, last_used_at TEXT
        );
        CREATE TABLE IF NOT EXISTS assistant_conversations(
          id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, summary TEXT NOT NULL DEFAULT ''
        );
        ''')
        try:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(id UNINDEXED,title,summary,tags,project_id,domain)")
            self.fts5 = True
        except sqlite3.OperationalError:
            self.fts5 = False
        cols={r['name'] for r in c.execute('PRAGMA table_info(knowledge)').fetchall()}
        if 'provenance_json' not in cols: c.execute("ALTER TABLE knowledge ADD COLUMN provenance_json TEXT NOT NULL DEFAULT '{}'")
        if 'applicability_json' not in cols: c.execute("ALTER TABLE knowledge ADD COLUMN applicability_json TEXT NOT NULL DEFAULT '{}'")
        c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
        c.commit()
        return self

    def close(self):
        self.conn.close()
