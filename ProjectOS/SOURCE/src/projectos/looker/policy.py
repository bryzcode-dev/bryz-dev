from __future__ import annotations

from pathlib import Path

from projectos.acceptance.authority import HostSession
from projectos.errors import ValidationError

from .model import CollectorPaths, LookerIntake


def validate_collector_environment(intake: LookerIntake, session: HostSession) -> CollectorPaths:
    if session.elevated or not session.standard_user:
        raise ValidationError("Looker collection requires a standard-user non-elevated session")
    if session.host_family is not intake.host_family:
        raise ValidationError("Looker intake host does not match the current host")
    repository_input = Path(intake.repository_root)
    output_input = Path(intake.output_root)
    if repository_input.is_symlink() or output_input.is_symlink():
        raise ValidationError("Looker collector roots cannot use a symlink")
    repository = repository_input.expanduser().resolve(strict=False)
    output = output_input.expanduser().resolve(strict=False)
    if not repository.is_dir() or not output.is_dir():
        raise ValidationError("Looker collector roots must be existing directories")
    if repository == output or repository in output.parents or output in repository.parents:
        raise ValidationError("Looker repository and output roots must be separate")
    return CollectorPaths(repository, output)
