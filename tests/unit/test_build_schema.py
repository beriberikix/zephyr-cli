"""Unit tests for build schema parsing."""

from __future__ import annotations

from zephyr_cli.schemas.build import (
    parse_build_output,
)


class TestParseBuildOutput:
    def test_empty_stderr_returns_empty_lists(self):
        errors, warnings = parse_build_output("")
        assert errors == []
        assert warnings == []

    def test_parses_gcc_error(self):
        stderr = "src/main.c:42:10: error: 'foo' undeclared (first use in this function)"
        errors, _warnings = parse_build_output(stderr)
        assert len(errors) == 1
        e = errors[0]
        assert e.file == "src/main.c"
        assert e.line == 42
        assert e.column == 10
        assert "foo" in e.message
        assert e.error_type == "error"

    def test_parses_gcc_warning(self):
        stderr = "src/main.c:10:5: warning: unused variable 'x'"
        errors, warnings = parse_build_output(stderr)
        assert errors == []
        assert len(warnings) == 1
        w = warnings[0]
        assert w.file == "src/main.c"
        assert w.line == 10
        assert "unused" in w.message

    def test_parses_fatal_error(self):
        stderr = "src/main.c:1:10: fatal error: nonexistent.h: No such file or directory"
        errors, _warnings = parse_build_output(stderr)
        assert len(errors) == 1
        assert errors[0].error_type == "fatal error"

    def test_parses_cmake_error(self):
        stderr = "CMake Error at CMakeLists.txt:5 (message): Board not found."
        errors, _warnings = parse_build_output(stderr)
        assert len(errors) == 1
        assert errors[0].error_type == "cmake"

    def test_mixed_output(self):
        stderr = (
            "src/a.c:5:1: warning: implicit declaration of function 'bar'\n"
            "src/a.c:10:1: error: expected ';' before '}' token\n"
            "ninja: build stopped: subcommand failed.\n"
        )
        errors, warnings = parse_build_output(stderr)
        assert len(errors) == 1
        assert len(warnings) == 1

    def test_ignores_blank_lines(self):
        stderr = "\n\n\n"
        errors, warnings = parse_build_output(stderr)
        assert errors == []
        assert warnings == []

    def test_no_column_parsed_correctly(self):
        stderr = "src/main.c:7: error: something went wrong"
        errors, _warnings = parse_build_output(stderr)
        assert len(errors) == 1
        assert errors[0].column is None
