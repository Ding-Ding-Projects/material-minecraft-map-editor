"""The example world ships with every release, and never gates one.

These tests are about the contract, not the terrain: the generator has to be
runnable, its ``--help`` has to work on a machine with no amulet-core, and the
workflow has to attach the world without ever being able to withhold an
installer.  The parts that need amulet-core are guarded so this file still
means something in an environment that does not have it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate_example_world.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "build-windows.yml"
WORKFLOW_TEXT = WORKFLOW_PATH.read_text(encoding="utf-8")
WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)

GENERATOR_REFERENCE = "scripts/generate_example_world.py"
WORLD_ASSET = "example-world.zip"


def _deploy_steps():
    return WORKFLOW["jobs"]["deploy"]["steps"]


def _steps_mentioning(needle: str):
    found = []
    for step in _deploy_steps():
        rendered = yaml.safe_dump(step)
        if needle in rendered:
            found.append(step)
    return found


class GeneratorContractTests(unittest.TestCase):
    def test_the_generator_exists_and_is_executable(self):
        self.assertTrue(GENERATOR.is_file(), f"{GENERATOR} is missing")
        first_line = GENERATOR.read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(
            first_line.startswith("#!") and "python" in first_line,
            f"the generator needs an executable shebang, not {first_line!r}",
        )
        self.assertTrue(os.access(GENERATOR, os.X_OK), f"{GENERATOR} is not executable")

    def test_help_works_without_amulet_core(self):
        """``--help`` must not need the dependency it exists to describe.

        A shadowing package that raises on import is a truthful stand-in for a
        machine with no amulet-core: the import fails, which is exactly what
        the generator has to tolerate before it parses arguments.
        """
        with _blocked_amulet() as environment:
            self._assert_amulet_is_blocked(environment)
            result = subprocess.run(
                [sys.executable, str(GENERATOR), "--help"],
                capture_output=True,
                text=True,
                env=environment,
                cwd=str(ROOT),
                timeout=120,
            )
        self.assertEqual(
            result.returncode,
            0,
            f"--help exited {result.returncode}\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}",
        )
        self.assertIn("--seed", result.stdout)
        self.assertIn("--size", result.stdout)
        self.assertIn("--out", result.stdout)

    def _assert_amulet_is_blocked(self, environment) -> None:
        """Prove the blocker blocks, so the test above cannot pass vacuously."""
        probe = subprocess.run(
            [sys.executable, "-c", "import amulet"],
            capture_output=True,
            text=True,
            env=environment,
            cwd=str(ROOT),
            timeout=120,
        )
        self.assertNotEqual(
            probe.returncode,
            0,
            "the amulet blocker did not block amulet-core, so the --help test "
            "would pass whether or not the generator imports it lazily",
        )

    def test_size_defaults_to_500_and_the_seed_is_a_constant(self):
        source = GENERATOR.read_text(encoding="utf-8")
        self.assertIn("DEFAULT_SIZE = 500", source)
        self.assertRegex(source, r"DEFAULT_SEED = \d+")
        # A clock- or random-derived default would make a release
        # irreproducible, which is the whole point of taking a seed.
        self.assertNotIn("default=time.time", source)
        self.assertNotIn("random.", source)

    def test_invalid_sizes_are_refused(self):
        parser = _load_generator().build_parser()
        for bad in ("0", "-16", "not-a-number", "99999"):
            with self.subTest(size=bad):
                with self.assertRaises(SystemExit):
                    parser.parse_args(["--size", bad])

    def test_defaults_are_what_the_parser_actually_produces(self):
        generator = _load_generator()
        parsed = generator.build_parser().parse_args([])
        self.assertEqual(parsed.size, 500)
        self.assertEqual(parsed.seed, generator.DEFAULT_SEED)


class WorkflowContractTests(unittest.TestCase):
    def test_the_workflow_runs_the_generator(self):
        steps = _steps_mentioning(GENERATOR_REFERENCE)
        self.assertTrue(
            steps,
            f"no step in {WORKFLOW_PATH.name} runs {GENERATOR_REFERENCE}",
        )

    def test_generation_cannot_fail_the_build(self):
        for step in _steps_mentioning(GENERATOR_REFERENCE):
            with self.subTest(step=step.get("name")):
                self.assertTrue(
                    step.get("continue-on-error"),
                    f"the step {step.get('name')!r} runs the generator without "
                    "continue-on-error, so a bonus asset could withhold an "
                    "installer",
                )

    def test_the_world_is_uploaded_as_a_run_artifact_even_on_failure(self):
        uploads = [
            step
            for step in _deploy_steps()
            if str(step.get("uses", "")).startswith("actions/upload-artifact")
            and "example-world" in yaml.safe_dump(step.get("with", {}))
        ]
        self.assertTrue(
            uploads, "the example world is never uploaded as a run artifact"
        )
        for step in uploads:
            with self.subTest(step=step.get("name")):
                self.assertIn(
                    "always()",
                    str(step.get("if", "")),
                    "the evidence has to survive a failed run",
                )
                self.assertTrue(step.get("continue-on-error"))

    def test_the_verdict_is_still_computed_for_whoever_reads_the_run(self):
        outputs = WORKFLOW["jobs"]["deploy"]["outputs"]
        for name in (
            "example_world_verdict",
            "example_world_seed",
            "example_world_size",
        ):
            self.assertIn(name, outputs)

    # RETIRED: test_the_world_is_attached_to_the_release,
    # test_the_release_notes_mention_the_world_with_its_seed_and_size, and
    # test_a_failed_generation_is_stated_in_the_notes_not_omitted.
    #
    # All three asserted things about WORKFLOW["jobs"]["publish"] in
    # build-windows.yml: that the generated world was copied into the
    # Squirrel payload the publish job swept up, and that its seed, size, and
    # failure state were written into that job's release notes.
    #
    # build-windows.yml no longer has a publish job -- build-electron-windows
    # .yml is the only workflow that creates a release now, and it packages
    # the Electron app, not the wxPython/PyInstaller build this generator's
    # world was ever copied alongside. Making the Electron release carry the
    # world too would mean either running amulet-core (a heavy, wx-specific
    # dependency) on the Electron build's plain windows-latest job, or piping
    # a world generated in one independent workflow run into a release
    # published by a different one -- there is no artifact channel between
    # two workflows triggered separately by the same push. Neither is what
    # "attach the example world" meant when this was one workflow.
    #
    # What still holds, and is covered above: the generator itself is a real,
    # runnable, deterministic script; build-windows.yml still runs it on
    # every push and uploads it as a plain CI artifact (continue-on-error, so
    # it can never withhold that build's installer); and its verdict is still
    # a deploy-job output for anyone who wants to read it from that run. It
    # simply reaches no release, because nothing wxPython-related does
    # anymore. If a future task wants the Electron release to ship a bundled
    # example world, that is new work on build-electron-windows.yml, not a
    # test to un-retire.


class GeneratedWorldTests(unittest.TestCase):
    """The parts that need amulet-core actually installed."""

    def setUp(self):
        pytest.importorskip("amulet", reason="amulet-core is not installed")
        pytest.importorskip("numpy", reason="numpy is not installed")
        self.generator = _load_generator()

    def test_the_height_field_is_terrain_rather_than_a_flat_slab(self):
        generator = self.generator
        deps = generator.load_dependencies()
        heights = generator.build_height_field(deps, generator.DEFAULT_SEED, -128, 256)
        self.assertGreater(
            int(heights.max()) - int(heights.min()),
            8,
            "a heightmap with no relief is a flat slab, not terrain",
        )
        self.assertTrue(
            (heights > generator.SEA_LEVEL).any(), "the world has no land in it"
        )
        self.assertTrue(
            (heights <= generator.SEA_LEVEL).any(), "the world has no water in it"
        )

    def test_the_same_seed_gives_the_same_height_field(self):
        generator = self.generator
        deps = generator.load_dependencies()
        first = generator.build_height_field(deps, 4242, -64, 128)
        second = generator.build_height_field(deps, 4242, -64, 128)
        other = generator.build_height_field(deps, 4243, -64, 128)
        self.assertTrue((first == second).all())
        self.assertFalse((first == other).all())

    def test_the_spawn_is_on_dry_land(self):
        generator = self.generator
        deps = generator.load_dependencies()
        origin = -128
        heights = generator.build_height_field(
            deps, generator.DEFAULT_SEED, origin, 256
        )
        spawn_x, spawn_y, spawn_z = generator.choose_spawn(deps, heights, origin)
        ground = int(heights[spawn_x - origin, spawn_z - origin])
        self.assertGreater(
            ground,
            generator.SEA_LEVEL,
            "the world spawn is under water",
        )
        self.assertEqual(spawn_y, ground + 1)


def _load_generator():
    """Import the generator by path; ``scripts`` is not an importable package."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "amulet_example_world_generator", GENERATOR
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _blocked_amulet:
    """A PYTHONPATH entry whose ``amulet`` package refuses to import.

    Built in a temporary directory rather than under ``tests/``: the child
    interpreter leaves a ``__pycache__`` behind, and a fixture that litters the
    checkout is a fixture somebody eventually commits.
    """

    def __enter__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="amulet-blocker-")
        package = Path(self._temporary.name) / "amulet"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(
            textwrap.dedent('''\
                """Stand in for a machine with no amulet-core installed."""

                raise ImportError("amulet-core is not installed (test fixture)")
                '''),
            encoding="utf-8",
        )
        environment = dict(os.environ)
        existing = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = self._temporary.name + (
            os.pathsep + existing if existing else ""
        )
        return environment

    def __exit__(self, *exception):
        self._temporary.cleanup()
        return False


if __name__ == "__main__":
    unittest.main()
