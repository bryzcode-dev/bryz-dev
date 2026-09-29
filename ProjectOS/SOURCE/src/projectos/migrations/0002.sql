CREATE TABLE users(
  user_id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('OWNER','ADMIN','USER')),
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  protected_owner INTEGER NOT NULL DEFAULT 0 CHECK(protected_owner IN (0,1)),
  notes TEXT NOT NULL DEFAULT '',
  provenance_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_access_at TEXT
);

CREATE UNIQUE INDEX idx_users_single_active_owner
ON users(role) WHERE role='OWNER' AND active=1;

CREATE TABLE google_bindings(
  binding_id TEXT PRIMARY KEY,
  environment TEXT NOT NULL,
  spreadsheet_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  contract_version INTEGER NOT NULL CHECK(contract_version > 0),
  gas_script_id TEXT,
  gas_deployment_id TEXT,
  sharing_policy TEXT NOT NULL DEFAULT 'OWNER_ONLY' CHECK(sharing_policy='OWNER_ONLY'),
  enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
  write_enabled INTEGER NOT NULL DEFAULT 0 CHECK(write_enabled IN (0,1)),
  credential_id TEXT REFERENCES credential_references(credential_id),
  last_preflight_at TEXT,
  last_publication_revision TEXT,
  status TEXT NOT NULL DEFAULT 'DISABLED',
  provenance_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(environment,spreadsheet_id)
);

ALTER TABLE change_requests ADD COLUMN request_schema_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE change_requests ADD COLUMN operation TEXT NOT NULL DEFAULT 'UPDATE' CHECK(operation IN ('CREATE','UPDATE','ARCHIVE'));
ALTER TABLE change_requests ADD COLUMN actor_role_claim TEXT;
ALTER TABLE change_requests ADD COLUMN client_request_hash TEXT;
ALTER TABLE change_requests ADD COLUMN binding_id TEXT REFERENCES google_bindings(binding_id);
ALTER TABLE change_requests ADD COLUMN source_row INTEGER;
ALTER TABLE change_requests ADD COLUMN observed_at TEXT;
ALTER TABLE change_requests ADD COLUMN result_code TEXT;
ALTER TABLE change_requests ADD COLUMN result_message TEXT;
ALTER TABLE change_requests ADD COLUMN current_version INTEGER;
ALTER TABLE change_requests ADD COLUMN publication_revision TEXT;

CREATE UNIQUE INDEX idx_change_requests_client_hash
ON change_requests(client_request_hash) WHERE client_request_hash IS NOT NULL;
CREATE INDEX idx_change_requests_binding_status
ON change_requests(binding_id,status);

CREATE TABLE remote_request_receipts(
  receipt_id TEXT PRIMARY KEY,
  binding_id TEXT NOT NULL REFERENCES google_bindings(binding_id),
  request_id TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  source_row INTEGER NOT NULL,
  observed_at TEXT NOT NULL,
  processing_status TEXT NOT NULL,
  local_request_id TEXT REFERENCES change_requests(request_id),
  conflict_id TEXT REFERENCES conflicts(conflict_id),
  audit_id TEXT REFERENCES audit_events(audit_id),
  processed_at TEXT,
  published_at TEXT,
  UNIQUE(binding_id,request_id),
  UNIQUE(binding_id,payload_hash)
);

CREATE TABLE remote_access_receipts(
  event_id TEXT PRIMARY KEY,
  binding_id TEXT NOT NULL REFERENCES google_bindings(binding_id),
  actor_email TEXT NOT NULL COLLATE NOCASE,
  accessed_at TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  source_row INTEGER NOT NULL,
  observed_at TEXT NOT NULL,
  processing_status TEXT NOT NULL,
  processed_at TEXT,
  UNIQUE(binding_id,payload_hash)
);

CREATE TABLE projection_revisions(
  revision_id TEXT PRIMARY KEY,
  binding_id TEXT NOT NULL REFERENCES google_bindings(binding_id),
  schema_version INTEGER NOT NULL,
  snapshot_hash TEXT NOT NULL,
  entity_counts_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('STAGED','ACTIVE','FAILED','SUPERSEDED')),
  started_at TEXT NOT NULL,
  verified_at TEXT,
  activated_at TEXT,
  failed_at TEXT,
  error_code TEXT,
  error_details TEXT
);

CREATE UNIQUE INDEX idx_projection_one_active
ON projection_revisions(binding_id) WHERE state='ACTIVE';
CREATE INDEX idx_projection_binding_state
ON projection_revisions(binding_id,state,started_at);

ALTER TABLE sync_runs ADD COLUMN binding_id TEXT REFERENCES google_bindings(binding_id);
ALTER TABLE sync_runs ADD COLUMN starting_checkpoint TEXT;
ALTER TABLE sync_runs ADD COLUMN ending_checkpoint TEXT;
ALTER TABLE sync_runs ADD COLUMN error_code TEXT;

ALTER TABLE sync_checkpoints ADD COLUMN binding_id TEXT REFERENCES google_bindings(binding_id);
CREATE INDEX idx_sync_runs_binding_started ON sync_runs(binding_id,started_at);
CREATE INDEX idx_sync_checkpoints_binding ON sync_checkpoints(binding_id);
