CREATE TABLE looker_intake_runs(
  intake_run_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  archive_sha256 TEXT NOT NULL UNIQUE,
  source_run_id TEXT NOT NULL UNIQUE,
  source_machine_id TEXT NOT NULL,
  host_family TEXT NOT NULL CHECK(host_family IN ('macos','windows')),
  repository_sha256 TEXT NOT NULL,
  git_head TEXT NOT NULL,
  git_branch TEXT NOT NULL,
  git_dirty INTEGER NOT NULL CHECK(git_dirty IN (0,1)),
  git_behind INTEGER NOT NULL CHECK(git_behind>=0),
  git_ahead INTEGER NOT NULL CHECK(git_ahead>=0),
  legacy_json TEXT NOT NULL,
  credential_refs_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('IMPORTED','RECONCILED','CUTOVER_READY')),
  imported_by TEXT NOT NULL,
  imported_at TEXT NOT NULL
);

CREATE TABLE looker_source_members(
  intake_run_id TEXT NOT NULL REFERENCES looker_intake_runs(intake_run_id),
  member_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size INTEGER NOT NULL CHECK(size>=0),
  PRIMARY KEY(intake_run_id,member_path)
);

CREATE TABLE looker_asset_occurrences(
  intake_run_id TEXT NOT NULL REFERENCES looker_intake_runs(intake_run_id),
  looker_asset_id TEXT NOT NULL REFERENCES looker_assets(looker_asset_id),
  content_sha256 TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  source_line INTEGER NOT NULL CHECK(source_line>=1),
  PRIMARY KEY(intake_run_id,looker_asset_id)
);
CREATE INDEX idx_looker_asset_occurrences_run ON looker_asset_occurrences(intake_run_id,looker_asset_id);

CREATE TABLE looker_relationships(
  relationship_id TEXT PRIMARY KEY,
  intake_run_id TEXT NOT NULL REFERENCES looker_intake_runs(intake_run_id),
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  relationship_type TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_name TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_name TEXT NOT NULL,
  source_path TEXT NOT NULL,
  source_line INTEGER NOT NULL CHECK(source_line>=1),
  provenance_json TEXT NOT NULL
);
CREATE INDEX idx_looker_relationships_source ON looker_relationships(project_id,source_type,source_name);
CREATE INDEX idx_looker_relationships_target ON looker_relationships(project_id,target_type,target_name);

CREATE TABLE looker_findings(
  finding_id TEXT PRIMARY KEY,
  intake_run_id TEXT NOT NULL REFERENCES looker_intake_runs(intake_run_id),
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  severity TEXT NOT NULL CHECK(severity IN ('INFO','WARNING','IMPORTANT','CRITICAL')),
  category TEXT NOT NULL,
  code TEXT NOT NULL,
  subject TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('OPEN','RESOLVED','WAIVED')),
  source_path TEXT NOT NULL,
  source_line INTEGER NOT NULL CHECK(source_line>=1),
  provenance_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_looker_findings_status ON looker_findings(project_id,status,severity);

CREATE TABLE looker_validation_results(
  validation_result_id TEXT PRIMARY KEY,
  intake_run_id TEXT NOT NULL REFERENCES looker_intake_runs(intake_run_id),
  command_id TEXT NOT NULL,
  passed INTEGER NOT NULL CHECK(passed IN (0,1)),
  returncode INTEGER NOT NULL,
  timed_out INTEGER NOT NULL CHECK(timed_out IN (0,1)),
  parser TEXT NOT NULL,
  summary TEXT NOT NULL,
  UNIQUE(intake_run_id,command_id)
);

CREATE TABLE looker_legacy_mappings(
  mapping_id TEXT PRIMARY KEY,
  intake_run_id TEXT NOT NULL REFERENCES looker_intake_runs(intake_run_id),
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  legacy_key TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT,
  status TEXT NOT NULL CHECK(status IN ('MATCHED','UNMATCHED','AMBIGUOUS')),
  provenance_json TEXT NOT NULL,
  UNIQUE(intake_run_id,legacy_key)
);

CREATE TABLE looker_reconciliation_runs(
  reconciliation_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  intake_run_id TEXT NOT NULL REFERENCES looker_intake_runs(intake_run_id),
  analytic_source_run_id TEXT NOT NULL,
  analytic_version INTEGER NOT NULL CHECK(analytic_version>0),
  legacy_sha256 TEXT NOT NULL,
  policy_sha256 TEXT NOT NULL,
  policy_json TEXT NOT NULL,
  parent_reconciliation_id TEXT REFERENCES looker_reconciliation_runs(reconciliation_id),
  status TEXT NOT NULL CHECK(status IN ('READY','BLOCKED')),
  approved_by TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE looker_reconciliation_items(
  reconciliation_id TEXT NOT NULL REFERENCES looker_reconciliation_runs(reconciliation_id),
  dimension TEXT NOT NULL,
  item_key TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK(outcome IN ('MATCH','MISMATCH','MISSING_SOURCE','MISSING_TARGET','WAIVED')),
  source_json TEXT NOT NULL,
  target_json TEXT NOT NULL,
  waiver_reason TEXT,
  waived_by TEXT,
  waived_at TEXT,
  PRIMARY KEY(reconciliation_id,dimension,item_key)
);

CREATE TABLE looker_cutover_packages(
  cutover_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  reconciliation_id TEXT NOT NULL REFERENCES looker_reconciliation_runs(reconciliation_id),
  package_sha256 TEXT NOT NULL UNIQUE,
  rollback_sha256 TEXT NOT NULL,
  ownership_sha256 TEXT NOT NULL,
  status TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);
