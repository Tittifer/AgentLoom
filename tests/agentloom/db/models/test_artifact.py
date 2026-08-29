"""Metadata tests for artifact references."""

from agentloom.db.models.artifact import ArtifactModel


def test_artifact_has_storage_locator() -> None:
    assert ArtifactModel.__table__.c.storage_path.nullable is False
    assert ArtifactModel.__table__.c.checksum.nullable is False
