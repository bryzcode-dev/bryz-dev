from __future__ import annotations

import hashlib
from pathlib import Path

from projectos.adoption.activation import RuntimeActivation
from projectos.adoption.activation_store import ActivationState
from projectos.adoption.bundle import ArtifactPolicy
from projectos.adoption.fixture import FixtureInstallationTarget
from projectos.adoption.profile import MachineProfile
from projectos.adoption.store import AdoptionOperation, LocalAdoptionStore, TransactionState
from projectos.adoption.transaction import AdoptionTransaction
from projectos.errors import ValidationError


class DefinitionAcceptanceController:
    def __init__(
        self,
        target: FixtureInstallationTarget,
        profile: MachineProfile,
        store: LocalAdoptionStore,
        policy: ArtifactPolicy,
        transaction_id: str,
        bundle_path: Path,
    ) -> None:
        self.target = target
        self.profile = profile
        self.store = store
        self.policy = policy
        self.transaction_id = transaction_id
        self.bundle_path = Path(bundle_path)

    def _journal(self):
        try:
            return self.store.load_journal(self.transaction_id)
        except ValidationError:
            return None

    def _assert_bundle_binding(self, journal) -> None:
        try:
            digest = hashlib.sha256(self.bundle_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ValidationError("prepared extension bundle is unavailable") from exc
        if journal.bundle_sha256 != digest:
            raise ValidationError("prepared extension bundle does not match transaction")

    @property
    def active(self) -> bool:
        journal = self._journal()
        if journal is not None:
            self._assert_bundle_binding(journal)
        return journal is not None and journal.state is TransactionState.ADOPTED

    def adopt(self) -> None:
        journal = self._journal()
        if journal is not None:
            self._assert_bundle_binding(journal)
            if journal.state is TransactionState.ADOPTED:
                return
            raise ValidationError("prepared definition transaction cannot be reused")
        transaction = AdoptionTransaction.begin(
            AdoptionOperation.ADOPT,
            self.target,
            self.profile,
            self.store,
            self.policy,
            self.transaction_id,
            self.bundle_path,
        )
        transaction.preflight()
        transaction.snapshot()
        transaction.stage()
        transaction.verify()
        result = transaction.adopt_disabled()
        if result.state is not TransactionState.ADOPTED:
            raise ValidationError("prepared definition adoption did not complete")

    def rollback(self) -> None:
        journal = self._journal()
        if journal is None or journal.state is TransactionState.ROLLED_BACK:
            return
        self._assert_bundle_binding(journal)
        transaction = AdoptionTransaction.resume(
            self.target,
            self.profile,
            self.store,
            self.policy,
            self.transaction_id,
        )
        if journal.state is TransactionState.ADOPTED:
            transaction.rollback()
            return
        if journal.state is TransactionState.FAILED:
            transaction.recover()
            return
        raise ValidationError("prepared definition transaction is not recoverable")


class ActivationAcceptanceController:
    def __init__(
        self,
        activation: RuntimeActivation,
        definition_transaction_id: str,
        activation_id: str,
    ) -> None:
        self.activation = activation
        self.definition_transaction_id = definition_transaction_id
        self.activation_id = activation_id

    def _journal(self):
        try:
            return self.activation.activation_store.load_journal(self.activation_id)
        except ValidationError:
            return None

    @property
    def active(self) -> bool:
        journal = self._journal()
        return journal is not None and journal.state is ActivationState.PROVED

    def activate(self) -> None:
        journal = self._journal()
        if journal is not None:
            if (
                journal.state is ActivationState.PROVED
                and journal.definition_transaction_id == self.definition_transaction_id
            ):
                return
            raise ValidationError("prepared activation cannot be reused")
        result = self.activation.begin(
            self.definition_transaction_id,
            activation_id=self.activation_id,
        )
        if (
            result.state is not ActivationState.PROVED
            or result.activation_id != self.activation_id
        ):
            raise ValidationError("prepared activation did not complete")

    def deactivate(self) -> None:
        journal = self._journal()
        if journal is None or journal.state in {
            ActivationState.DEACTIVATED,
            ActivationState.ROLLED_BACK,
        }:
            return
        if journal.definition_transaction_id != self.definition_transaction_id:
            raise ValidationError("prepared activation definition does not match")
        if journal.state is ActivationState.PROVED:
            self.activation.deactivate(self.activation_id)
            return
        if journal.state is ActivationState.FAILED:
            self.activation.recover(self.activation_id)
            return
        raise ValidationError("prepared activation is not recoverable")
