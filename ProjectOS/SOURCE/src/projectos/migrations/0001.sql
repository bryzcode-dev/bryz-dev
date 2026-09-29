CREATE TABLE schema_migrations(
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL
);

CREATE TABLE projects(
  project_id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  project_type TEXT NOT NULL CHECK(project_type IN ('GAS','SHEET_GCP','LOOKER','GIT','LOCAL','MIXED','OTHER')),
  status TEXT NOT NULL CHECK(status IN ('PROPOSED','ACTIVE','PAUSED','ARCHIVED')),
  visibility TEXT NOT NULL CHECK(visibility IN ('PUBLIC','PRIVATE')),
  context_os_registered INTEGER NOT NULL DEFAULT 0 CHECK(context_os_registered IN (0,1)),
  context_os_project_id TEXT,
  owner_notes TEXT NOT NULL DEFAULT '',
  tags_json TEXT NOT NULL DEFAULT '[]',
  provenance_json TEXT NOT NULL DEFAULT '{}',
  source_key TEXT UNIQUE,
  version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  archived_at TEXT
);

CREATE TABLE project_locations(
  location_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  machine_id TEXT NOT NULL,
  original_path TEXT,
  normalized_path TEXT,
  repository_root TEXT,
  drive_folder_id TEXT,
  drive_folder_url TEXT,
  location_type TEXT NOT NULL,
  environment TEXT NOT NULL DEFAULT '',
  discovery_status TEXT NOT NULL DEFAULT 'VERIFIED',
  provenance_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_discovered_at TEXT,
  last_verified_at TEXT,
  UNIQUE(project_id,machine_id,location_type,normalized_path,drive_folder_id)
);

CREATE TABLE resources(
  resource_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  resource_type TEXT NOT NULL,
  provider TEXT NOT NULL,
  external_id TEXT,
  name TEXT NOT NULL,
  url TEXT,
  environment TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'USES',
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  provenance_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_verified_at TEXT,
  UNIQUE(project_id,provider,resource_type,external_id)
);

CREATE TABLE deployments(
  deployment_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  resource_id TEXT REFERENCES resources(resource_id),
  environment TEXT NOT NULL CHECK(environment IN ('DEVELOPMENT','STAGING','PRODUCTION','OTHER')),
  script_id TEXT,
  external_deployment_id TEXT,
  deployment_url TEXT,
  active_version TEXT,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  notes TEXT NOT NULL DEFAULT '',
  provenance_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_discovered_at TEXT,
  last_verified_at TEXT,
  UNIQUE(project_id,environment,external_deployment_id)
);

CREATE TABLE connections(
  connection_id TEXT PRIMARY KEY,
  source_project_id TEXT REFERENCES projects(project_id),
  source_resource_id TEXT REFERENCES resources(resource_id),
  target_project_id TEXT REFERENCES projects(project_id),
  target_resource_id TEXT REFERENCES resources(resource_id),
  connection_type TEXT NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('DIRECTED','BIDIRECTIONAL')),
  implementation_method TEXT NOT NULL,
  purpose TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  health_status TEXT NOT NULL DEFAULT 'UNKNOWN',
  provenance_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_verified_at TEXT,
  CHECK(source_project_id IS NOT NULL OR source_resource_id IS NOT NULL),
  CHECK(target_project_id IS NOT NULL OR target_resource_id IS NOT NULL)
);

CREATE TABLE credential_references(
  credential_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  label TEXT NOT NULL,
  credential_type TEXT NOT NULL,
  purpose TEXT NOT NULL,
  scope_description TEXT NOT NULL DEFAULT '',
  storage_system TEXT NOT NULL,
  storage_reference TEXT NOT NULL,
  owner_project_id TEXT REFERENCES projects(project_id),
  rotation_due_at TEXT,
  last_verified_at TEXT,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  notes TEXT NOT NULL DEFAULT '',
  provenance_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(provider,label,storage_system,storage_reference)
);

CREATE TABLE credential_usage(
  usage_id TEXT PRIMARY KEY,
  credential_id TEXT NOT NULL REFERENCES credential_references(credential_id),
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  resource_id TEXT REFERENCES resources(resource_id),
  purpose TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(credential_id,project_id,resource_id,purpose)
);

CREATE TABLE looker_assets(
  looker_asset_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  asset_type TEXT NOT NULL,
  file_path TEXT NOT NULL,
  name TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  provenance_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id,asset_type,file_path,name)
);

CREATE TABLE looker_analytics(
  analytic_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  analytic_type TEXT NOT NULL,
  value_json TEXT NOT NULL,
  source_run_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE change_requests(
  request_id TEXT PRIMARY KEY,
  actor_email TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  base_version INTEGER NOT NULL,
  changes_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('PENDING','ACCEPTED','CONFLICT','REJECTED')),
  reason TEXT,
  submitted_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE TABLE conflicts(
  conflict_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES change_requests(request_id),
  current_version INTEGER NOT NULL,
  current_json TEXT NOT NULL,
  proposed_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'OPEN',
  created_at TEXT NOT NULL,
  resolved_at TEXT,
  resolution_json TEXT
);

CREATE TABLE sync_runs(
  run_id TEXT PRIMARY KEY,
  trigger TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  summary_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE sync_checkpoints(
  checkpoint_key TEXT PRIMARY KEY,
  checkpoint_value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE audit_events(
  audit_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  actor TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE discovery_runs(
  run_id TEXT PRIMARY KEY,
  adapter TEXT NOT NULL,
  source_run_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  summary_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE discovery_findings(
  finding_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES discovery_runs(run_id),
  finding_key TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  proposed_json TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '[]',
  provenance_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL CHECK(status IN ('CANDIDATE','APPLIED','REJECTED','ERROR')),
  created_at TEXT NOT NULL,
  resolved_at TEXT,
  resolution_reason TEXT,
  UNIQUE(finding_key,content_hash)
);

CREATE TABLE extension_adoptions(
  adoption_id TEXT PRIMARY KEY,
  extension_version TEXT NOT NULL,
  context_os_version TEXT NOT NULL,
  machine_id TEXT NOT NULL,
  status TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE backup_manifests(
  backup_id TEXT PRIMARY KEY,
  manifest_path TEXT NOT NULL UNIQUE,
  snapshot_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  byte_size INTEGER NOT NULL,
  schema_version INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  verification_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_locations_project ON project_locations(project_id);
CREATE INDEX idx_resources_project ON resources(project_id);
CREATE INDEX idx_resources_external ON resources(provider,external_id);
CREATE INDEX idx_deployments_project ON deployments(project_id);
CREATE INDEX idx_connections_source_project ON connections(source_project_id);
CREATE INDEX idx_connections_target_project ON connections(target_project_id);
CREATE INDEX idx_credential_usage_project ON credential_usage(project_id);
CREATE INDEX idx_discovery_findings_status ON discovery_findings(status);
