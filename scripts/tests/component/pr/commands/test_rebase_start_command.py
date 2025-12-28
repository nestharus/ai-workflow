from scripts.pr.commands.rebase_start_command import (
    _find_existing_branch_for_ticket,
    _get_expected_branch_name,
    _looks_like_pr_id,
    _looks_like_ticket_id,
    rebase_start_command,
)


class TestLooksLikePrId:
    def test_matches_plain_number(self) -> None:
        """Should return int for plain number."""
        assert _looks_like_pr_id("42") == 42

    def test_matches_hash_prefixed_number(self) -> None:
        """Should return int for hash-prefixed number."""
        assert _looks_like_pr_id("#123") == 123

    def test_returns_none_for_text(self) -> None:
        """Should return None for non-numeric text."""
        assert _looks_like_pr_id("feature") is None

    def test_returns_none_for_ticket_id(self) -> None:
        """Should return None for ticket ID."""
        assert _looks_like_pr_id("NES-87") is None


class TestLooksLikeTicketId:
    def test_matches_uppercase_ticket(self) -> None:
        """Should return True for uppercase ticket ID."""
        assert _looks_like_ticket_id("NES-87") is True

    def test_matches_lowercase_ticket(self) -> None:
        """Should return True for lowercase ticket ID."""
        assert _looks_like_ticket_id("proj-123") is True

    def test_returns_false_for_number(self) -> None:
        """Should return False for plain number."""
        assert _looks_like_ticket_id("42") is False

    def test_returns_false_for_branch_name(self) -> None:
        """Should return False for branch name."""
        assert _looks_like_ticket_id("feature-branch") is False


class TestGetExpectedBranchName:
    def test_returns_name_if_within_limit(self) -> None:
        """Should return name unchanged if within limit."""
        assert _get_expected_branch_name("short-name") == "short-name"

    def test_truncates_long_name(self) -> None:
        """Should truncate name to 50 characters."""
        long_name = "a" * 60
        result = _get_expected_branch_name(long_name)
        assert len(result) == 50
        assert result == "a" * 50
