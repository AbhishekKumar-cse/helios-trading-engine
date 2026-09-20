"""Tests for the DeepLOB skeleton (step 075).

They check the shapes and the wiring, not accuracy: nothing here is trained, so no claim
about how well it predicts anything can be made yet.
"""

import pytest

torch = pytest.importorskip("torch", reason="PyTorch is not installed yet")

from helios.common.seed import set_seed  # noqa: E402
from helios.ml.deeplob import (  # noqa: E402
    CLASSES,
    FEATURES,
    SNAPSHOTS,
    DeepLOB,
    DeepLOBError,
    Inception,
    count_parameters,
)


def a_batch(n: int = 2, snapshots: int = SNAPSHOTS, features: int = FEATURES) -> "torch.Tensor":
    """Made-up order-book windows: `n` examples of `snapshots` x `features` numbers."""
    return torch.randn(n, 1, snapshots, features)


# ---------------------------------------------------------------- shapes


def test_the_output_is_one_score_per_class() -> None:
    """The step's own check: (N, 1, 100, 40) in, (N, 3) out."""
    model = DeepLOB()
    output = model(a_batch(8))
    assert output.shape == (8, CLASSES)


def test_a_single_example_works() -> None:
    assert DeepLOB()(a_batch(1)).shape == (1, 3)


def test_a_larger_batch_works() -> None:
    assert DeepLOB()(a_batch(32)).shape == (32, 3)


def test_the_number_of_classes_can_be_changed() -> None:
    model = DeepLOB(classes=5)
    assert model(a_batch(4)).shape == (4, 5)


def test_the_inception_module_widens_the_channels() -> None:
    """Three branches of 64 channels each, joined into 192."""
    module = Inception(32, branch_channels=64)
    out = module(torch.randn(2, 32, 50, 1))
    assert out.shape == (2, 192, 50, 1)


# ---------------------------------------------------------------- wrong input


def test_a_wrong_number_of_features_is_refused() -> None:
    with pytest.raises(DeepLOBError, match=r"expected each example to be \(1, 100, 40\)"):
        DeepLOB()(a_batch(2, features=20))


def test_a_wrong_window_length_is_refused() -> None:
    with pytest.raises(DeepLOBError, match="expected each example"):
        DeepLOB()(a_batch(2, snapshots=50))


def test_a_missing_channel_dimension_is_refused() -> None:
    with pytest.raises(DeepLOBError, match="expected 4 dimensions"):
        DeepLOB()(torch.randn(2, SNAPSHOTS, FEATURES))


def test_the_error_says_what_was_expected() -> None:
    with pytest.raises(DeepLOBError) as failure:
        DeepLOB()(torch.randn(3, 2, SNAPSHOTS, FEATURES))
    assert "(1, 100, 40)" in str(failure.value)


# ---------------------------------------------------------------- behaviour


def test_the_same_seed_builds_the_same_model() -> None:
    set_seed(0)
    first = DeepLOB()
    set_seed(0)
    second = DeepLOB()
    batch = a_batch(4)
    first.eval()
    second.eval()
    with torch.no_grad():
        assert torch.allclose(first(batch), second(batch))


def test_different_examples_get_different_scores() -> None:
    """A model that answered the same thing for everything would be useless."""
    set_seed(0)
    model = DeepLOB().eval()
    with torch.no_grad():
        output = model(a_batch(16))
    assert output.std(dim=0).min() > 0


def test_the_model_can_learn_something() -> None:
    """One step of training must move the loss: the gradients reach every layer."""
    set_seed(0)
    model = DeepLOB()
    batch = a_batch(8)
    labels = torch.randint(0, CLASSES, (8,))
    loss_fn = torch.nn.CrossEntropyLoss()
    optimiser = torch.optim.Adam(model.parameters(), lr=1e-3)

    before = loss_fn(model(batch), labels)
    before.backward()
    assert all(p.grad is not None for p in model.parameters() if p.requires_grad)
    optimiser.step()
    optimiser.zero_grad()
    after = loss_fn(model(batch), labels)
    assert after.item() < before.item()


def test_it_has_a_sensible_number_of_parameters() -> None:
    """The paper's model is small: around 140,000 numbers, not millions."""
    total = count_parameters(DeepLOB())
    assert 50_000 < total < 500_000


def test_nothing_is_claimed_about_accuracy() -> None:
    """A reminder in test form: this model is untrained, so it predicts nothing yet."""
    set_seed(0)
    model = DeepLOB().eval()
    with torch.no_grad():
        scores = model(a_batch(64))
    guesses = scores.argmax(dim=1)
    assert guesses.shape == (64,)  # it produces answers; their quality is unmeasured
