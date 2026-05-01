"""Integration tests for Python runtime error wrapping (Item 4)."""

from __future__ import annotations

from zephyr_cli.schemas.build import parse_build_output


class TestPythonVersionErrorParsing:
    """Verify parse_build_output extracts structured errors from real-world CMake output."""

    def test_cmake_find_package_unsuitable_version(self):
        """Simulates CMake's find_package(Python3 3.10 REQUIRED) failure."""
        stderr = (
            "-- The C compiler identification is GNU 12.3.0\n"
            "-- Detecting C compiler ABI info\n"
            'CMake Error at /zephyr/cmake/modules/python.cmake:17 (find_package):\n'
            '  Could NOT find Python3: Found unsuitable version "3.8.10", '
            'minimum required is "3.10" (found /usr/bin/python3)\n'
            "-- Configuring incomplete, errors occurred!\n"
        )
        errors, _ = parse_build_output(stderr)
        py_errors = [e for e in errors if e.error_type == "python_version"]
        assert len(py_errors) == 1
        assert "3.10" in py_errors[0].message
        assert py_errors[0].remediation is not None
        assert "3.10" in py_errors[0].remediation

    def test_zephyr_python_version_check(self):
        """Simulates Zephyr's own Python version check."""
        stderr = "Python version 3.9.2 is less than minimum required version 3.10\n"
        errors, _ = parse_build_output(stderr)
        py_errors = [e for e in errors if e.error_type == "python_version"]
        assert len(py_errors) == 1

    def test_missing_module_during_build(self):
        """Simulates a missing Python package during build."""
        stderr = (
            "Traceback (most recent call last):\n"
            "  File \"/zephyr/scripts/gen_kobject_list.py\", line 5, in <module>\n"
            "    No module named 'elftools'\n"
        )
        errors, _ = parse_build_output(stderr)
        pkg_errors = [e for e in errors if e.error_type == "missing_package"]
        assert len(pkg_errors) == 1
        assert "elftools" in pkg_errors[0].message
        assert pkg_errors[0].remediation == "pip install elftools"

    def test_mixed_errors_all_captured(self):
        """Build output with both Python version and compiler errors."""
        stderr = (
            '/src/main.c:10:5: error: unknown type name "foo"\n'
            "Python version 3.8.0 is less than minimum required version 3.10\n"
        )
        errors, _ = parse_build_output(stderr)
        assert len(errors) == 2
        types = {e.error_type for e in errors}
        assert "error" in types
        assert "python_version" in types
