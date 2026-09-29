from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO_ROOT

if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))


FIXTURE = REPO_ROOT / "tests/fixtures/looker/repository"


class LookerParserTests(unittest.TestCase):
    def test_models_views_explores_dashboards_and_references_are_inventory_items(self) -> None:
        from projectos.looker.lookml import parse_repository

        result = parse_repository(FIXTURE)
        assets = {(item.asset_type, item.name) for item in result.assets}
        self.assertTrue({("project", "commerce"), ("model", "commerce"), ("view", "orders"), ("explore", "orders"), ("dashboard", "sales")} <= assets)
        edges = {(item.relationship_type, item.source_name, item.target_name) for item in result.relationships}
        self.assertIn(("model_connection", "commerce", "warehouse"), edges)
        self.assertIn(("explore_view", "orders", "orders"), edges)
        self.assertIn(("join_view", "orders", "customers"), edges)
        self.assertIn(("dashboard_explore", "sales", "orders"), edges)
        self.assertIn(("view_extends", "orders", "base_order"), edges)

    def test_duplicate_missing_malformed_unsupported_and_cycles_become_findings(self) -> None:
        from projectos.looker.lookml import parse_repository

        codes = {item.code for item in parse_repository(FIXTURE).findings}
        self.assertTrue({"DUPLICATE_ASSET", "UNRESOLVED_REFERENCE", "MALFORMED_LOOKML", "UNSUPPORTED_CONSTRUCT", "REFERENCE_CYCLE"} <= codes)

    def test_results_are_deterministic_and_bind_path_hash_parser_and_line(self) -> None:
        from projectos.looker.lookml import PARSER_VERSION, parse_repository

        first = parse_repository(FIXTURE)
        second = parse_repository(FIXTURE)
        self.assertEqual(first, second)
        self.assertTrue(all(item.source_path and len(item.content_sha256) == 64 and item.parser_version == PARSER_VERSION and item.line >= 1 for item in first.assets))
        self.assertEqual(tuple(sorted(first.assets, key=lambda item: item.sort_key)), first.assets)

    def test_parser_rejects_symlinks_and_never_executes_file_content(self) -> None:
        from projectos.errors import ValidationError
        from projectos.looker.lookml import parse_repository

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "real.view.lkml").write_text('view: safe { sql: ${{ dangerous() }} ;; }')
            (root / "linked.view.lkml").symlink_to(root / "real.view.lkml")
            with self.assertRaisesRegex(ValidationError, "symlink"):
                parse_repository(root)

    def test_nested_explore_blocks_preserve_every_join(self) -> None:
        from projectos.looker.lookml import parse_repository
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/"commerce.model.lkml").write_text('''explore: orders {\n  join: users { sql_on: ${orders.user_id} = ${users.id} ;; }\n  join: products { sql_on: ${orders.product_id} = ${products.id} ;; }\n}\n''')
            (root/"views.view.lkml").write_text("view: orders {}\nview: users {}\nview: products {}\n")
            joins={(item.source_name,item.target_name) for item in parse_repository(root).relationships if item.relationship_type=="join_view"}
            self.assertEqual({("orders","users"),("orders","products")},joins)

    def test_declared_looker_constructs_have_assets_and_dependency_edges(self) -> None:
        from projectos.looker.lookml import parse_repository
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/"commerce.model.lkml").write_text('''datagroup: hourly { max_cache_age: "1 hour" }\nexplore: base_orders {}\nexplore: orders { extends: [base_orders] persist_with: hourly }\n''')
            (root/"sales.dashboard.lookml").write_text('''- dashboard: sales\n  model: commerce\n  explore: orders\n  elements:\n  - name: order_count\n    model: commerce\n    explore: orders\n''')
            parsed=parse_repository(root)
            assets={(item.asset_type,item.name) for item in parsed.assets}
            self.assertTrue({("file","commerce.model.lkml"),("datagroup","hourly"),("dashboard_element","sales:order_count")} <= assets)
            edges={(item.relationship_type,item.source_type,item.source_name,item.target_type,item.target_name) for item in parsed.relationships}
            self.assertIn(("explore_extends","explore","orders","explore","base_orders"),edges)
            self.assertIn(("persist_with","explore","orders","datagroup","hourly"),edges)
            self.assertIn(("dashboard_element_explore","dashboard_element","sales:order_count","explore","orders"),edges)
            self.assertIn(("asset_file","datagroup","hourly","file","commerce.model.lkml"),edges)


if __name__ == "__main__":
    unittest.main()
