import importlib.util
import os
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "demo.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo_script", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_node_path_puts_node24_first_when_installed(tmp_path: Path) -> None:
    demo = load()
    path = demo.node_path(f"/usr/bin{os.pathsep}/bin", tmp_path)
    assert path.split(os.pathsep) == [str(tmp_path), "/usr/bin", "/bin"]


def test_one_regular_iphone_by_default_overridable() -> None:
    demo = load()
    assert demo.simulator_name({}) == "iPhone 17"
    assert demo.simulator_name({"DEMO_SIMULATOR": "iPhone Air"}) == "iPhone Air"


def test_node_path_unchanged_without_node24(tmp_path: Path) -> None:
    demo = load()
    assert demo.node_path("/usr/bin", tmp_path / "missing") == "/usr/bin"
