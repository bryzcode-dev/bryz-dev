"""Portable ContextOS adoption contracts for ProjectOS."""

from .host import HostFamily, HostIdentity, detect_host_family
from .fixture import (
    FIXTURE_MARKER,
    FixtureInstallationTarget,
    FixtureReceipt,
    assert_fixture_separation,
    issue_empty_fixture,
)
from .path_policy import HostPathPolicy
from .paths import (
    PlatformPathOverrides,
    PlatformPaths,
    default_database_path,
    resolve_platform_paths,
)
from .registry import (
    REGISTRY_VERSION,
    ExtensionRegistry,
    ProjectOSExtensionEntry,
    plan_disabled_entry,
    plan_projectos_entry,
)
from .skill import SKILL_DESCRIPTION, render_projectos_skill, verify_projectos_skill
from .scheduler import (
    EXECUTION_LIMIT_SECONDS,
    SCHEDULE_INTERVAL_SECONDS,
    SchedulerAction,
    SchedulerAdapter,
    SchedulerDefinition,
    SchedulerInspection,
    SchedulerRunner,
    SchedulerState,
    adapter_for,
)
from .scheduler_macos import LaunchdSchedulerAdapter
from .scheduler_windows import WindowsTaskSchedulerAdapter
from .scheduler_fixture import FixtureSchedulerRunner
from .discovery import (
    AdapterInvocation,
    DiscoveredSkill,
    DiscoveryDiagnostic,
    InstalledProjectOSExtension,
    SkillDiscoveryResult,
    SkillDiscoveryService,
    load_installed_extension,
)
from .activation_store import (
    ActivationJournal,
    ActivationProofResult,
    ActivationState,
    LocalActivationStore,
)
from .activation import ActivationProof, ActivationResult, RuntimeActivation
from .store import (
    AdoptionOperation,
    AdoptionSnapshot,
    LocalAdoptionStore,
    SnapshotEntry,
    TransactionJournal,
    TransactionState,
)
from .staging import (
    StagedExtension,
    check_extension_compatibility,
    copy_verified_version,
    expected_extension_inventory,
    inventory_extension,
    load_staged_extension,
    stage_extension,
    verify_staged_extension,
)
from .transaction import AdoptionTransaction, TransactionResult

__all__ = [
    "AdoptionOperation",
    "AdoptionSnapshot",
    "AdoptionTransaction",
    "ActivationJournal",
    "ActivationProof",
    "ActivationProofResult",
    "ActivationResult",
    "ActivationState",
    "AdapterInvocation",
    "DiscoveredSkill",
    "DiscoveryDiagnostic",
    "HostFamily",
    "HostIdentity",
    "HostPathPolicy",
    "InstalledProjectOSExtension",
    "LocalAdoptionStore",
    "LocalActivationStore",
    "FIXTURE_MARKER",
    "FixtureInstallationTarget",
    "FixtureReceipt",
    "FixtureSchedulerRunner",
    "PlatformPathOverrides",
    "PlatformPaths",
    "ProjectOSExtensionEntry",
    "REGISTRY_VERSION",
    "RuntimeActivation",
    "SKILL_DESCRIPTION",
    "SnapshotEntry",
    "SkillDiscoveryResult",
    "SkillDiscoveryService",
    "StagedExtension",
    "TransactionJournal",
    "TransactionResult",
    "TransactionState",
    "ExtensionRegistry",
    "EXECUTION_LIMIT_SECONDS",
    "SCHEDULE_INTERVAL_SECONDS",
    "SchedulerAction",
    "SchedulerAdapter",
    "SchedulerDefinition",
    "SchedulerInspection",
    "SchedulerRunner",
    "SchedulerState",
    "LaunchdSchedulerAdapter",
    "WindowsTaskSchedulerAdapter",
    "adapter_for",
    "assert_fixture_separation",
    "check_extension_compatibility",
    "copy_verified_version",
    "default_database_path",
    "detect_host_family",
    "issue_empty_fixture",
    "expected_extension_inventory",
    "inventory_extension",
    "load_installed_extension",
    "load_staged_extension",
    "plan_disabled_entry",
    "plan_projectos_entry",
    "render_projectos_skill",
    "resolve_platform_paths",
    "stage_extension",
    "verify_staged_extension",
    "verify_projectos_skill",
]
