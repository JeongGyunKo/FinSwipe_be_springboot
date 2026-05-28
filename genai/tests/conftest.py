from __future__ import annotations

import math
import sys
import types
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))


def _install_numpy_stub() -> None:
    if "numpy" in sys.modules:
        return

    numpy_module = types.ModuleType("numpy")
    numpy_module.ndarray = list
    numpy_module.array = lambda value, dtype=None: value
    sys.modules["numpy"] = numpy_module


def _install_torch_stub() -> None:
    if "torch" in sys.modules:
        return

    class _NoGrad:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Tensor:
        def __init__(self, values):
            self._values = values

        def tolist(self):
            return list(self._values)

    def softmax(values, dim=0):
        exponentials = [math.exp(value) for value in values]
        total = sum(exponentials) or 1.0
        return _Tensor([value / total for value in exponentials])

    torch_module = types.ModuleType("torch")
    torch_module.no_grad = _NoGrad
    torch_module.softmax = softmax
    sys.modules["torch"] = torch_module


def _install_transformers_stub() -> None:
    if "transformers" in sys.modules:
        return

    class _FakeTokenizer:
        @classmethod
        def from_pretrained(cls, model_name):
            return cls()

        def __call__(self, text, **kwargs):
            if kwargs.get("return_tensors") == "pt":
                return {"input_ids": [[1, 2, 3]]}
            return {"input_ids": list(range(max(1, len(str(text).split()))))}

        def decode(self, token_ids, skip_special_tokens=True):
            return "decoded text"

    class _FakeModel:
        @classmethod
        def from_pretrained(cls, model_name):
            return cls()

        def eval(self):
            return None

        def __call__(self, **kwargs):
            return types.SimpleNamespace(logits=[[0.6, 0.1, 0.3]])

    transformers_module = types.ModuleType("transformers")
    transformers_module.AutoTokenizer = _FakeTokenizer
    transformers_module.AutoModelForSequenceClassification = _FakeModel
    sys.modules["transformers"] = transformers_module


_install_numpy_stub()
_install_torch_stub()
_install_transformers_stub()