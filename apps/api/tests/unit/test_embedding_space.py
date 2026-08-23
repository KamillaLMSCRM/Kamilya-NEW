from dataclasses import FrozenInstanceError

import pytest

from app.modules.ai.embedding_space import (
    Embedding,
    EmbeddingSpace,
    IncompatibleEmbeddingSpaceError,
    InvalidEmbeddingSpaceError,
    InvalidEmbeddingVectorError,
    require_compatible,
)


def make_space(**overrides) -> EmbeddingSpace:
    values = {
        "provider": "voyage",
        "model": "voyage-4-lite",
        "revision": "2026-08-23-v1",
        "dimensions": 2,
    }
    values.update(overrides)
    return EmbeddingSpace(**values)


def make_embedding(*, space: EmbeddingSpace | None = None, values=(0.25, 0.75)) -> Embedding:
    return Embedding(space or make_space(), values)


def test_valid_embedding_is_immutable_and_normalized() -> None:
    item = make_embedding(values=(1, 0.5))

    assert item.values == (1.0, 0.5)
    with pytest.raises(FrozenInstanceError):
        item.values = (0.0, 0.0)


@pytest.mark.parametrize("field", ["provider", "model", "revision"])
@pytest.mark.parametrize("value", ["", " ", " leading", "trailing ", "bad\nvalue", "https://host", "../secret"])
def test_space_rejects_unsafe_identifiers(field: str, value: str) -> None:
    with pytest.raises(InvalidEmbeddingSpaceError) as error:
        make_space(**{field: value})

    assert error.value.code == f"invalid_space_{field}"
    assert str(error.value) == f"invalid_space_{field}"


def test_space_accepts_namespaced_model_identifier() -> None:
    space = make_space(model="organization/Qwen3-Embedding-8B")

    assert space.model == "organization/Qwen3-Embedding-8B"


@pytest.mark.parametrize("dimensions", [True, False, 0, -1, 2.0, "2"])
def test_space_requires_exact_positive_integer_dimensions(dimensions) -> None:
    with pytest.raises(InvalidEmbeddingSpaceError) as error:
        make_space(dimensions=dimensions)

    assert error.value.code == "invalid_space_dimensions"


def test_embedding_materializes_a_generator_once() -> None:
    seen: list[int] = []

    def values():
        for number in (1, 2):
            seen.append(number)
            yield number

    item = make_embedding(values=values())

    assert item.values == (1.0, 2.0)
    assert seen == [1, 2]


@pytest.mark.parametrize("values", [(1.0,), (1.0, 2.0, 3.0), ()])
def test_embedding_rejects_wrong_length_without_padding(values) -> None:
    with pytest.raises(InvalidEmbeddingVectorError) as error:
        make_embedding(values=values)

    assert error.value.code == "invalid_embedding_length"


@pytest.mark.parametrize(
    "values",
    [
        (float("nan"), 0.0),
        (float("inf"), 0.0),
        (float("-inf"), 0.0),
        (True, 0.0),
        ("0.5", 0.0),
        (None, 0.0),
    ],
)
def test_embedding_rejects_non_finite_or_non_numeric_values(values) -> None:
    with pytest.raises(InvalidEmbeddingVectorError) as error:
        make_embedding(values=values)

    assert error.value.code == "invalid_embedding_value"
    assert str(values) not in str(error.value)


def test_embedding_rejects_non_iterable_input() -> None:
    with pytest.raises(InvalidEmbeddingVectorError) as error:
        make_embedding(values=None)

    assert error.value.code == "unsupported_embedding_input"


def test_embedding_sanitizes_iterable_failures() -> None:
    class HostileIterable:
        def __iter__(self):
            raise RuntimeError("secret-iteration-error")

    with pytest.raises(InvalidEmbeddingVectorError) as error:
        make_embedding(values=HostileIterable())

    assert error.value.code == "unsupported_embedding_input"
    assert str(error.value) == "unsupported_embedding_input"
    assert "secret-iteration-error" not in str(error.value)


def test_different_vectors_in_the_same_space_are_compatible() -> None:
    space = make_space()

    assert require_compatible(
        make_embedding(space=space, values=(0.0, 1.0)),
        make_embedding(space=space, values=(1.0, 0.0)),
    ) is None


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"provider": "qwen"}, "space_provider_mismatch"),
        ({"model": "Qwen3-Embedding-8B"}, "space_model_mismatch"),
        ({"revision": "2026-08-23-v2"}, "space_revision_mismatch"),
        ({"dimensions": 3}, "space_dimensions_mismatch"),
    ],
)
def test_embedding_space_mismatches_fail_closed(override, code: str) -> None:
    left = make_embedding()
    right_space = make_space(**override)
    right = make_embedding(space=right_space, values=(0.0,) * right_space.dimensions)

    with pytest.raises(IncompatibleEmbeddingSpaceError) as error:
        require_compatible(left, right)

    assert error.value.code == code
    assert str(left.values) not in str(error.value)
    assert str(right.values) not in str(error.value)


def test_multiple_mismatches_have_deterministic_precedence() -> None:
    left = make_embedding()
    right = make_embedding(space=make_space(provider="qwen", model="other"))

    with pytest.raises(IncompatibleEmbeddingSpaceError) as error:
        require_compatible(left, right)

    assert error.value.code == "space_provider_mismatch"


def test_embedding_equality_does_not_define_compatibility() -> None:
    space = make_space()
    left = make_embedding(space=space, values=(0.0, 1.0))
    right = make_embedding(space=space, values=(1.0, 0.0))

    assert left != right
    assert require_compatible(left, right) is None


def test_equal_values_from_different_spaces_are_not_compatible() -> None:
    left = make_embedding()
    right = make_embedding(space=make_space(provider="qwen"))

    assert left != right
    with pytest.raises(IncompatibleEmbeddingSpaceError):
        require_compatible(left, right)
