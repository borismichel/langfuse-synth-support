"""Include the canonical presenter runbook in installed runtime packages."""
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self):
        super().run()
        self.copy_file(
            str(Path(__file__).parent / "DEMO_SCRIPT.md"),
            str(Path(self.build_lib) / "synth" / "DEMO_SCRIPT.md"),
        )


setup(cmdclass={"build_py": BuildPy})
