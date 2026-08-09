from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DenseQualificationCheckpoint(_StrictModel):
    chunk_count: int = Field(ge=1)
    elapsed_seconds: float = Field(gt=0)
    chunks_per_second: float = Field(gt=0)
    input_characters: int = Field(ge=1)
    vector_bytes: int = Field(ge=1)
    process_peak_rss_bytes: int = Field(ge=1)
    error_count: int = Field(ge=0)


class DenseCapacityDecision(_StrictModel):
    schema_version: str = "enterprise_dense_capacity_decision_v1"
    full_chunk_count: int = Field(ge=1)
    embedding_dimension: int = Field(ge=1)
    dtype_bytes: int = Field(ge=1)
    checkpoints: list[DenseQualificationCheckpoint] = Field(min_length=3)
    projected_embedding_seconds: float = Field(gt=0)
    projected_embedding_hours: float = Field(gt=0)
    raw_vector_bytes: int = Field(ge=1)
    matrix_plus_index_copy_bytes: int = Field(ge=1)
    available_disk_bytes: int = Field(ge=0)
    gates: dict[str, bool]
    decision: str
    reasons: list[str]

    @model_validator(mode="after")
    def validate_decision(self) -> "DenseCapacityDecision":
        expected = "FULL_DENSE_GO" if all(self.gates.values()) else "FULL_DENSE_NO_GO"
        if self.decision != expected:
            raise ValueError("Dense decision does not match gates")
        if (self.decision == "FULL_DENSE_NO_GO") != bool(self.reasons):
            raise ValueError("Dense no-go must have reasons and go must not")
        return self


def decide_full_dense_run(
    checkpoints: Sequence[DenseQualificationCheckpoint],
    *,
    full_chunk_count: int,
    embedding_dimension: int,
    available_disk_bytes: int,
    sharded_builder_ready: bool,
    development_protocol_ready: bool,
    max_hours: float = 8.0,
) -> DenseCapacityDecision:
    rows = list(checkpoints)
    if [item.chunk_count for item in rows] != [1_000, 10_000, 50_000]:
        raise ValueError("Dense checkpoints must be exactly 1k, 10k, and 50k")
    final_rate = rows[-1].chunks_per_second
    projected_seconds = full_chunk_count / final_rate
    dtype_bytes = 4
    raw_vector_bytes = full_chunk_count * embedding_dimension * dtype_bytes
    matrix_plus_index = raw_vector_bytes * 2
    required_with_reserve = int(matrix_plus_index * 1.2)
    gates = {
        "all_checkpoints_zero_errors": all(item.error_count == 0 for item in rows),
        "throughput_retains_80_percent_at_50k": (
            final_rate >= rows[1].chunks_per_second * 0.8
        ),
        "projected_runtime_at_most_8_hours": projected_seconds <= max_hours * 3600,
        "disk_fit_with_20_percent_reserve": available_disk_bytes >= required_with_reserve,
        "resumable_sharded_builder_ready": sharded_builder_ready,
        "development_quality_protocol_ready": development_protocol_ready,
    }
    reasons = [name for name, passed in gates.items() if not passed]
    return DenseCapacityDecision(
        full_chunk_count=full_chunk_count,
        embedding_dimension=embedding_dimension,
        dtype_bytes=dtype_bytes,
        checkpoints=rows,
        projected_embedding_seconds=projected_seconds,
        projected_embedding_hours=projected_seconds / 3600,
        raw_vector_bytes=raw_vector_bytes,
        matrix_plus_index_copy_bytes=matrix_plus_index,
        available_disk_bytes=available_disk_bytes,
        gates=gates,
        decision="FULL_DENSE_GO" if all(gates.values()) else "FULL_DENSE_NO_GO",
        reasons=reasons,
    )


__all__ = [
    "DenseCapacityDecision",
    "DenseQualificationCheckpoint",
    "decide_full_dense_run",
]
