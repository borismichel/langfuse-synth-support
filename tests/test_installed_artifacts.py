"""The installed release can deliver its runbook without a source checkout."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


def test_installed_wheel_publishes_unchanged_runbook(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    expected = (repo / "DEMO_SCRIPT.md").read_bytes()
    source = tmp_path / "source"
    shutil.copytree(repo, source, ignore=shutil.ignore_patterns(
        ".git", ".pytest_cache", "__pycache__", "*.egg-info", "build", "dist",
    ))
    distributions = tmp_path / "distributions"
    distributions.mkdir()

    def run(*args, cwd=tmp_path, env=None):
        return subprocess.run(
            [sys.executable, *args], cwd=cwd, env=env,
            check=True, capture_output=True, text=True,
        )

    # Both supported distribution stages must carry the canonical root runbook.
    run("-c", "from setuptools.build_meta import build_sdist; "
        "import sys; build_sdist(sys.argv[1])", str(distributions), cwd=source)
    with tarfile.open(next(distributions.glob("*.tar.gz"))) as archive:
        archive.extractall(tmp_path / "unpacked", filter="data")
    unpacked = next((tmp_path / "unpacked").iterdir())
    run("-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--no-index",
        "--wheel-dir", str(distributions), str(unpacked))
    installed = tmp_path / "installed"
    run("-m", "pip", "install", "--no-deps", "--no-index", "--target", str(installed),
        str(next(distributions.glob("*.whl"))))
    shutil.rmtree(source)
    shutil.rmtree(unpacked)

    # -I -S excludes the working checkout, editable installs and ambient site paths.
    output = tmp_path / "out"
    env = {**os.environ, "SYNTH_OUT_DIR": str(output)}
    run("-I", "-S", "-c",
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from synth.artifacts import publish_runbook; publish_runbook()",
        str(installed), env=env)
    assert (output / "DEMO_SCRIPT.md").read_bytes() == expected


def test_editable_install_publishes_source_runbook(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    source = tmp_path / "source"
    shutil.copytree(repo, source, ignore=shutil.ignore_patterns(
        ".git", ".pytest_cache", "__pycache__", "*.egg-info", "build", "dist",
    ))
    installed = tmp_path / "installed"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
         "--no-build-isolation", "--target", str(installed), "--editable", str(source)],
        cwd=tmp_path, check=True, capture_output=True, text=True,
    )
    # Resolve only this editable install, not another checkout on the test runner's path.
    output = tmp_path / "out"
    subprocess.run(
        [sys.executable, "-I", "-S", "-c",
         "import site,sys; site.addsitedir(sys.argv[1]); "
         "from synth.artifacts import publish_runbook; publish_runbook()", str(installed)],
        cwd=tmp_path, env={**os.environ, "SYNTH_OUT_DIR": str(output)},
        check=True, capture_output=True, text=True,
    )
    assert (output / "DEMO_SCRIPT.md").read_bytes() == (source / "DEMO_SCRIPT.md").read_bytes()
