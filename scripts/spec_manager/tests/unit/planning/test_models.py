"""Tests for planning.models data structures."""

from __future__ import annotations

from spec_manager.planning.models import (
    AdjacentDetail,
    CodeFile,
    CommentKind,
    FunctionInfo,
    InsertionPlan,
    InsertionPoint,
    PseudocodeComment,
    ReversePlan,
)


class TestCommentKind:
    """Tests for CommentKind enum."""

    def test_plan_value(self) -> None:
        assert CommentKind.PLAN.value == "plan"

    def test_reverse_value(self) -> None:
        assert CommentKind.REVERSE.value == "reverse"

    def test_annotation_value(self) -> None:
        assert CommentKind.ANNOTATION.value == "annotation"

    def test_string_enum(self) -> None:
        """CommentKind is a str enum."""
        assert isinstance(CommentKind.PLAN, str)
        assert CommentKind.PLAN == "plan"


class TestPseudocodeComment:
    """Tests for PseudocodeComment dataclass."""

    def test_creation(self) -> None:
        comment = PseudocodeComment(
            file_path="/test/file.py",
            line_no=10,
            text="validate input parameters",
            kind=CommentKind.PLAN,
            indent_level=4,
            function_name="process",
            class_name=None,
        )
        assert comment.file_path == "/test/file.py"
        assert comment.line_no == 10
        assert comment.text == "validate input parameters"
        assert comment.kind == CommentKind.PLAN
        assert comment.indent_level == 4
        assert comment.function_name == "process"
        assert comment.class_name is None

    def test_frozen(self) -> None:
        """PseudocodeComment is frozen (immutable)."""
        comment = PseudocodeComment(
            file_path="/test/file.py",
            line_no=10,
            text="test",
            kind=CommentKind.PLAN,
            indent_level=0,
            function_name=None,
            class_name=None,
        )
        try:
            comment.text = "modified"  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except AttributeError:
            pass


class TestInsertionPoint:
    """Tests for InsertionPoint dataclass."""

    def test_creation(self) -> None:
        point = InsertionPoint(
            file_path="/test/file.py",
            line_no=15,
            indent_level=8,
            function_name="process",
            preceding_code="x = compute()",
            following_code="return x",
            rationale="Between assignment and return",
        )
        assert point.line_no == 15
        assert point.indent_level == 8
        assert point.function_name == "process"

    def test_frozen(self) -> None:
        point = InsertionPoint(
            file_path="/test/file.py",
            line_no=1,
            indent_level=0,
            function_name=None,
            preceding_code="",
            following_code="",
            rationale="test",
        )
        try:
            point.line_no = 2  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except AttributeError:
            pass


class TestFunctionInfo:
    """Tests for FunctionInfo dataclass."""

    def test_creation(self) -> None:
        func = FunctionInfo(
            name="process",
            file_path="/test/file.py",
            start_line=1,
            end_line=10,
            indent_level=0,
            parameters=["self", "data"],
            return_annotation="dict",
            docstring="Process data.",
            body_lines=["def process(self, data):", "    return {}"],
            calls=["validate", "transform"],
            comments=[],
            class_name="Handler",
            decorators=["staticmethod"],
        )
        assert func.name == "process"
        assert func.parameters == ["self", "data"]
        assert func.return_annotation == "dict"
        assert func.calls == ["validate", "transform"]
        assert func.class_name == "Handler"

    def test_frozen(self) -> None:
        func = FunctionInfo(
            name="f",
            file_path="/test.py",
            start_line=1,
            end_line=1,
            indent_level=0,
            parameters=[],
            return_annotation=None,
            docstring=None,
            body_lines=[],
            calls=[],
            comments=[],
            class_name=None,
            decorators=[],
        )
        try:
            func.name = "g"  # type: ignore[misc]
            assert False, "Should have raised"
        except AttributeError:
            pass


class TestCodeFile:
    """Tests for CodeFile dataclass."""

    def test_creation(self) -> None:
        cf = CodeFile(
            file_path="/test/file.py",
            functions=[],
            top_level_comments=[],
            imports=["os", "sys"],
            classes=["MyClass"],
        )
        assert cf.file_path == "/test/file.py"
        assert cf.imports == ["os", "sys"]
        assert cf.classes == ["MyClass"]

    def test_mutable(self) -> None:
        """CodeFile is mutable (not frozen)."""
        cf = CodeFile(
            file_path="/test.py",
            functions=[],
            top_level_comments=[],
            imports=[],
            classes=[],
        )
        cf.imports.append("json")
        assert "json" in cf.imports


class TestInsertionPlan:
    """Tests for InsertionPlan dataclass."""

    def test_creation(self) -> None:
        point = InsertionPoint(
            file_path="/test.py",
            line_no=5,
            indent_level=4,
            function_name="f",
            preceding_code="x = 1",
            following_code="return x",
            rationale="test",
        )
        plan = InsertionPlan(
            file_path="/test.py",
            insertions=[(point, "validate input")],
            source_intention="add validation",
            evidence_refs=["LIB-001"],
        )
        assert len(plan.insertions) == 1
        assert plan.source_intention == "add validation"
        assert plan.evidence_refs == ["LIB-001"]


class TestReversePlan:
    """Tests for ReversePlan dataclass."""

    def test_creation(self) -> None:
        plan = ReversePlan(
            file_path="/test.py",
            function_name="process",
            start_line=5,
            end_line=10,
            generated_comments=[],
            original_code="x = 1\nreturn x",
        )
        assert plan.function_name == "process"
        assert plan.start_line == 5
        assert plan.end_line == 10


class TestAdjacentDetail:
    """Tests for AdjacentDetail dataclass."""

    def test_creation(self) -> None:
        detail = AdjacentDetail(
            source_function="module.process",
            related_function="module.validate",
            relationship="calls",
            store_or_event=None,
            has_test_coverage=True,
            needs_plan=False,
        )
        assert detail.source_function == "module.process"
        assert detail.relationship == "calls"
        assert detail.has_test_coverage is True
        assert detail.needs_plan is False

    def test_shared_store(self) -> None:
        detail = AdjacentDetail(
            source_function="module.writer",
            related_function="module.reader",
            relationship="shared_store",
            store_or_event="database",
            has_test_coverage=False,
            needs_plan=True,
        )
        assert detail.store_or_event == "database"
        assert detail.needs_plan is True
