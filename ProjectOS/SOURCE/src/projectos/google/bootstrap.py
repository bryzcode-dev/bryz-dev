from __future__ import annotations

from dataclasses import dataclass

from .contract import WorkbookContract, WorkbookSnapshot


@dataclass(frozen=True)
class BootstrapAction:
    kind: str
    tab: str | None
    detail: str
    blocking: bool = False


@dataclass(frozen=True)
class BootstrapPlan:
    actions: tuple[BootstrapAction, ...]

    @property
    def blocked(self) -> bool:
        return any(action.blocking for action in self.actions)


class WorkbookBootstrapPlanner:
    def plan(
        self, snapshot: WorkbookSnapshot, contract: WorkbookContract
    ) -> BootstrapPlan:
        actions: list[BootstrapAction] = []
        if snapshot.contract_version not in (None, contract.version):
            actions.append(
                BootstrapAction(
                    "BLOCKING_VERSION_DRIFT",
                    None,
                    f"expected contract {contract.version}; observed {snapshot.contract_version}",
                    True,
                )
            )

        expected_names = {tab.name for tab in contract.tabs}
        for name, (_headers, row_count) in snapshot.tabs.items():
            if name not in expected_names:
                actions.append(
                    BootstrapAction(
                        "UNKNOWN_DATA" if row_count else "UNKNOWN_EMPTY_TAB",
                        name,
                        "unknown tab is preserved and never repurposed",
                        bool(row_count),
                    )
                )

        for tab in contract.tabs:
            observed = snapshot.tabs.get(tab.name)
            if observed is None:
                actions.append(
                    BootstrapAction("CREATE_TAB", tab.name, "create with contract headers")
                )
                continue
            headers, row_count = observed
            if tuple(headers) != tab.headers:
                actions.append(
                    BootstrapAction(
                        "BLOCKING_HEADER_DRIFT",
                        tab.name,
                        f"header mismatch on tab with {row_count} data rows",
                        True,
                    )
                )
                continue
            if snapshot.protected_tabs is not None and tab.protected and tab.name not in snapshot.protected_tabs:
                actions.append(BootstrapAction("PROTECT_TAB", tab.name, "apply owner-only protection"))
            if snapshot.formatted_tabs is not None and tab.name not in snapshot.formatted_tabs:
                actions.append(BootstrapAction("FORMAT_TAB", tab.name, "apply contract formatting"))
        return BootstrapPlan(tuple(actions))
