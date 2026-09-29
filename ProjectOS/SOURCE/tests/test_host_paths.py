from __future__ import annotations

import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath

from tests.helpers import TemporaryDirectoryMixin

from projectos.adoption.host import HostFamily
from projectos.adoption.path_policy import HostPathPolicy
from projectos.adoption.paths import PlatformPathOverrides, resolve_platform_paths
from projectos.errors import ValidationError
from projectos.google.config import ProjectOSGoogleConfig


class HostPathTests(TemporaryDirectoryMixin, unittest.TestCase):
    def test_macos_defaults_are_under_supplied_home(self) -> None:
        home = PurePosixPath("/Users/example")

        paths = resolve_platform_paths(HostFamily.MACOS, {}, home)

        self.assertEqual(
            PurePosixPath("/Users/example/Library/Application Support/ProjectOS"),
            paths.runtime_root,
        )
        self.assertEqual(paths.runtime_root / "projectos.db", paths.database_path)
        self.assertEqual(paths.runtime_root / "projectos.toml", paths.config_path)
        self.assertEqual(paths.runtime_root / "projectos.sync.lock", paths.lock_path)
        self.assertEqual(
            PurePosixPath("/Users/example/Library/Logs/ProjectOS"), paths.log_root
        )
        self.assertEqual(paths.runtime_root / "staging", paths.staging_root)
        self.assertFalse(Path(str(paths.runtime_root)).exists())

    def test_windows_defaults_use_localappdata(self) -> None:
        local = r"C:\Users\Example\AppData\Local"

        paths = resolve_platform_paths(
            HostFamily.WINDOWS,
            {"LOCALAPPDATA": local},
            PureWindowsPath(r"C:\Users\Example"),
        )

        self.assertEqual(PureWindowsPath(local) / "ProjectOS", paths.runtime_root)
        self.assertEqual(paths.runtime_root / "projectos.db", paths.database_path)
        self.assertEqual(paths.runtime_root / "projectos.toml", paths.config_path)
        self.assertEqual(paths.runtime_root / "projectos.sync.lock", paths.lock_path)
        self.assertEqual(paths.runtime_root / "logs", paths.log_root)

    def test_windows_missing_localappdata_requires_explicit_runtime(self) -> None:
        with self.assertRaisesRegex(ValidationError, "LOCALAPPDATA"):
            resolve_platform_paths(
                HostFamily.WINDOWS, {}, PureWindowsPath(r"C:\Users\Example")
            )

        paths = resolve_platform_paths(
            HostFamily.WINDOWS,
            {},
            PureWindowsPath(r"C:\Users\Example"),
            PlatformPathOverrides(runtime_root=r"D:\ProjectOS-Local"),
        )
        self.assertEqual(PureWindowsPath(r"D:\ProjectOS-Local"), paths.runtime_root)

    def test_explicit_and_environment_overrides_precede_defaults(self) -> None:
        paths = resolve_platform_paths(
            HostFamily.MACOS,
            {
                "PROJECTOS_HOME": "/environment/home",
                "PROJECTOS_DB": "/environment/database.db",
                "PROJECTOS_CONFIG": "/environment/projectos.toml",
            },
            PurePosixPath("/Users/example"),
            PlatformPathOverrides(
                runtime_root="/explicit/home",
                database_path="/explicit/database.db",
                config_path="/explicit/projectos.toml",
            ),
        )

        self.assertEqual(PurePosixPath("/explicit/home"), paths.runtime_root)
        self.assertEqual(PurePosixPath("/explicit/database.db"), paths.database_path)
        self.assertEqual(PurePosixPath("/explicit/projectos.toml"), paths.config_path)

    def test_windows_normalization_handles_case_mixed_separators_and_dot_segments(self) -> None:
        policy = HostPathPolicy(HostFamily.WINDOWS)

        self.assertEqual(
            r"c:\users\example\projectos",
            policy.normalize(r"C:/Users/EXAMPLE/AppData/../ProjectOS"),
        )
        self.assertTrue(
            policy.is_within(
                r"C:/Users/Example/PROJECTOS/data/projectos.db",
                r"c:\users\example\projectos",
            )
        )

    def test_windows_drive_and_unc_roots_never_compare_as_contained(self) -> None:
        policy = HostPathPolicy(HostFamily.WINDOWS)

        self.assertFalse(
            policy.is_within(r"D:\ProjectOS\projectos.db", r"C:\ProjectOS")
        )
        self.assertFalse(
            policy.is_within(r"\\server\share\ProjectOS", r"C:\ProjectOS")
        )
        self.assertFalse(
            policy.is_within(
                r"\\server-two\share\ProjectOS",
                r"\\server-one\share\ProjectOS",
            )
        )

    def test_component_containment_rejects_string_prefix_collision(self) -> None:
        policy = HostPathPolicy(HostFamily.MACOS)

        self.assertFalse(policy.is_within("/Volumes/shared-backup", "/Volumes/shared"))
        self.assertTrue(policy.is_within("/Volumes/shared/projectos", "/Volumes/shared"))

    def test_runtime_inside_any_shared_root_is_rejected(self) -> None:
        policy = HostPathPolicy(HostFamily.WINDOWS)

        with self.assertRaisesRegex(ValidationError, "runtime path must be local"):
            policy.assert_local_runtime(
                r"Z:\ContextOS\shared\ProjectOS",
                (r"Z:\ContextOS\shared", r"C:\Other"),
            )

    def test_google_config_uses_platform_paths_without_real_identifiers(self) -> None:
        resolved = ProjectOSGoogleConfig.resolve_path(
            None,
            {"LOCALAPPDATA": r"C:\Users\Example\AppData\Local"},
            family=HostFamily.WINDOWS,
            home=PureWindowsPath(r"C:\Users\Example"),
        )

        self.assertEqual(
            PureWindowsPath(r"C:\Users\Example\AppData\Local\ProjectOS\projectos.toml"),
            resolved,
        )


if __name__ == "__main__":
    unittest.main()
