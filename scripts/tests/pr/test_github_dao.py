"""Unit tests for the GitHub DAO Python wrapper.

These tests verify that the GitHubDAO wrapper correctly handles initialization,
GraphQL API calls, JSON parsing, and error handling without making actual API calls.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.pr.github_dao import (
    GhNotFoundError,
    GraphQLError,
    _get_gh_exe,
    create_pr,
    fetch_comment_thumbs_up_reactions,
    fetch_thread_comments,
    fetch_unresolved_threads,
    get_pr_changed_files,
    get_pr_for_branch,
    get_pr_info,
    merge_pr,
    post_pr_comment,
    post_reply_to_comment,
    resolve_thread,
    run_gh_command,
    run_graphql_mutation,
    run_graphql_query,
)


class TestExceptions:
    """Test exception classes."""

    def test_gh_not_found_error_message(self) -> None:
        """GhNotFoundError has correct default message."""
        error = GhNotFoundError()
        assert "gh executable not found on PATH" in str(error)

    def test_graphql_error_message(self) -> None:
        """GraphQLError stores the provided message."""
        error = GraphQLError("Test error message")
        assert "Test error message" in str(error)


class TestGetGhExe:
    """Test _get_gh_exe helper."""

    def test_returns_path_when_found(self) -> None:
        """Return path to gh when it exists."""
        with patch("shutil.which", return_value="/usr/local/bin/gh"):
            result = _get_gh_exe()
            assert result == "/usr/local/bin/gh"

    def test_raises_when_not_found(self) -> None:
        """Raise GhNotFoundError when gh is not on PATH."""
        with patch("shutil.which", return_value=None), pytest.raises(GhNotFoundError):
            _get_gh_exe()


class TestRunGhCommand:
    """Test run_gh_command function."""

    def test_success_returns_stdout(self) -> None:
        """Return stdout on successful command."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "command output"

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = run_gh_command(["api", "test"])
            assert result == "command output"

    def test_failure_raises_graphql_error(self) -> None:
        """Raise GraphQLError on command failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error message"

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            with pytest.raises(GraphQLError) as exc_info:
                run_gh_command(["api", "test"])
            assert "error message" in str(exc_info.value)


class TestRunGraphqlQuery:
    """Test run_graphql_query function."""

    def test_success_returns_parsed_json(self) -> None:
        """Return parsed JSON on success."""
        expected = {"data": {"viewer": {"id": "123"}}}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(expected)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = run_graphql_query("query { viewer { id } }")
            assert result == expected

    def test_invalid_json_raises_graphql_error(self) -> None:
        """Raise GraphQLError on invalid JSON response."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not valid json"

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            with pytest.raises(GraphQLError) as exc_info:
                run_graphql_query("query { viewer { id } }")
            assert "Invalid JSON" in str(exc_info.value)


class TestRunGraphqlMutation:
    """Test run_graphql_mutation function."""

    def test_success_returns_parsed_json(self) -> None:
        """Return parsed JSON on success."""
        expected = {"data": {"createIssue": {"id": "123"}}}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(expected)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = run_graphql_mutation("mutation { createIssue { id } }")
            assert result == expected

    def test_invalid_json_raises_graphql_error(self) -> None:
        """Raise GraphQLError on invalid JSON response."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "{invalid json"

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            with pytest.raises(GraphQLError) as exc_info:
                run_graphql_mutation("mutation { createIssue { id } }")
            assert "Invalid JSON" in str(exc_info.value)


class TestFetchThreadComments:
    """Test fetch_thread_comments function."""

    def test_single_page_returns_comments(self) -> None:
        """Return comments from single page response."""
        response = {
            "data": {
                "node": {
                    "comments": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "id": "comment-1",
                                "databaseId": 123,
                                "body": "Test comment",
                                "author": {"login": "user1"},
                                "createdAt": "2024-01-01T00:00:00Z",
                            }
                        ],
                    }
                }
            }
        }
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = fetch_thread_comments("thread-id-123")
            assert len(result) == 1
            assert result[0]["id"] == "comment-1"

    def test_pagination_fetches_all_pages(self) -> None:
        """Fetch all pages when hasNextPage is True."""
        page1 = {
            "data": {
                "node": {
                    "comments": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                        "nodes": [{"id": "comment-1", "body": "First"}],
                    }
                }
            }
        }
        page2 = {
            "data": {
                "node": {
                    "comments": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{"id": "comment-2", "body": "Second"}],
                    }
                }
            }
        }

        mock_results = [MagicMock(), MagicMock()]
        mock_results[0].returncode = 0
        mock_results[0].stdout = json.dumps(page1)
        mock_results[1].returncode = 0
        mock_results[1].stdout = json.dumps(page2)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", side_effect=mock_results),
        ):
            result = fetch_thread_comments("thread-id-123")
            assert len(result) == 2
            assert result[0]["id"] == "comment-1"
            assert result[1]["id"] == "comment-2"

    def test_empty_node_returns_empty_list(self) -> None:
        """Return empty list when node is empty."""
        response = {"data": {"node": None}}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = fetch_thread_comments("thread-id-123")
            assert result == []

    def test_empty_node_dict_returns_empty_list(self) -> None:
        """Return empty list when node is empty dict."""
        response = {"data": {"node": {}}}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = fetch_thread_comments("thread-id-123")
            assert result == []


class TestFetchCommentThumbsUpReactions:
    """Test fetch_comment_thumbs_up_reactions function."""

    def test_single_page_returns_reactions(self) -> None:
        """Return reactions from single page response."""
        response = {
            "data": {
                "node": {
                    "reactions": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{"content": "THUMBS_UP", "user": {"login": "user1"}}],
                    }
                }
            }
        }
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = fetch_comment_thumbs_up_reactions("comment-id-123")
            assert len(result) == 1
            assert result[0]["content"] == "THUMBS_UP"

    def test_pagination_fetches_all_pages(self) -> None:
        """Fetch all pages when hasNextPage is True."""
        page1 = {
            "data": {
                "node": {
                    "reactions": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                        "nodes": [{"content": "THUMBS_UP", "user": {"login": "user1"}}],
                    }
                }
            }
        }
        page2 = {
            "data": {
                "node": {
                    "reactions": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{"content": "THUMBS_UP", "user": {"login": "user2"}}],
                    }
                }
            }
        }

        mock_results = [MagicMock(), MagicMock()]
        mock_results[0].returncode = 0
        mock_results[0].stdout = json.dumps(page1)
        mock_results[1].returncode = 0
        mock_results[1].stdout = json.dumps(page2)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", side_effect=mock_results),
        ):
            result = fetch_comment_thumbs_up_reactions("comment-id-123")
            assert len(result) == 2

    def test_empty_node_returns_empty_list(self) -> None:
        """Return empty list when node is empty."""
        response = {"data": {"node": None}}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = fetch_comment_thumbs_up_reactions("comment-id-123")
            assert result == []

    def test_empty_node_dict_returns_empty_list(self) -> None:
        """Return empty list when node is empty dict."""
        response = {"data": {"node": {}}}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = fetch_comment_thumbs_up_reactions("comment-id-123")
            assert result == []


class TestFetchUnresolvedThreads:
    """Test fetch_unresolved_threads function."""

    def test_returns_unresolved_threads_with_comments_and_reactions(self) -> None:
        """Return unresolved threads with comments and reactions."""
        # Page of threads
        threads_response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "id": "thread-1",
                                    "isResolved": False,
                                    "path": "file.py",
                                    "line": 10,
                                    "startLine": None,
                                    "originalLine": 10,
                                    "originalStartLine": None,
                                },
                                {
                                    "id": "thread-2",
                                    "isResolved": True,  # This one is resolved
                                    "path": "other.py",
                                    "line": 20,
                                    "startLine": None,
                                    "originalLine": 20,
                                    "originalStartLine": None,
                                },
                            ],
                        }
                    }
                }
            }
        }

        # Comments for unresolved thread
        comments_response = {
            "data": {
                "node": {
                    "comments": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "id": "comment-1",
                                "databaseId": 123,
                                "body": "Test comment",
                                "author": {"login": "user1"},
                                "createdAt": "2024-01-01T00:00:00Z",
                            }
                        ],
                    }
                }
            }
        }

        # Reactions for comment
        reactions_response = {
            "data": {
                "node": {
                    "reactions": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{"content": "THUMBS_UP", "user": {"login": "user1"}}],
                    }
                }
            }
        }

        mock_results = [MagicMock(), MagicMock(), MagicMock()]
        mock_results[0].returncode = 0
        mock_results[0].stdout = json.dumps(threads_response)
        mock_results[1].returncode = 0
        mock_results[1].stdout = json.dumps(comments_response)
        mock_results[2].returncode = 0
        mock_results[2].stdout = json.dumps(reactions_response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", side_effect=mock_results),
        ):
            result = fetch_unresolved_threads(123)
            # Only unresolved threads returned
            assert len(result) == 1
            assert result[0]["id"] == "thread-1"
            assert result[0]["isResolved"] is False
            # Comments are populated
            assert "comments" in result[0]
            assert len(result[0]["comments"]["nodes"]) == 1

    def test_pagination_for_threads(self) -> None:
        """Handle pagination for threads."""
        page1 = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                            "nodes": [
                                {
                                    "id": "thread-1",
                                    "isResolved": True,
                                    "path": "file.py",
                                    "line": 10,
                                    "startLine": None,
                                    "originalLine": 10,
                                    "originalStartLine": None,
                                }
                            ],
                        }
                    }
                }
            }
        }
        page2 = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "id": "thread-2",
                                    "isResolved": True,
                                    "path": "other.py",
                                    "line": 20,
                                    "startLine": None,
                                    "originalLine": 20,
                                    "originalStartLine": None,
                                }
                            ],
                        }
                    }
                }
            }
        }

        mock_results = [MagicMock(), MagicMock()]
        mock_results[0].returncode = 0
        mock_results[0].stdout = json.dumps(page1)
        mock_results[1].returncode = 0
        mock_results[1].stdout = json.dumps(page2)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", side_effect=mock_results),
        ):
            result = fetch_unresolved_threads(123)
            # All threads are resolved so empty list
            assert len(result) == 0

    def test_empty_pr_data_returns_empty_list(self) -> None:
        """Return empty list when PR data is empty."""
        response = {"data": {"repository": {"pullRequest": None}}}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = fetch_unresolved_threads(123)
            assert result == []

    def test_empty_repository_returns_empty_list(self) -> None:
        """Return empty list when repository is empty."""
        response = {"data": {"repository": {}}}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = fetch_unresolved_threads(123)
            assert result == []

    def test_thread_without_id_is_skipped(self) -> None:
        """Skip thread without id in second pass."""
        threads_response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    # Missing 'id'
                                    "isResolved": False,
                                    "path": "file.py",
                                    "line": 10,
                                    "startLine": None,
                                    "originalLine": 10,
                                    "originalStartLine": None,
                                }
                            ],
                        }
                    }
                }
            }
        }
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(threads_response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = fetch_unresolved_threads(123)
            # Thread is unresolved but has no id, so no comments fetched
            assert len(result) == 1
            # No comments key since thread_id was None
            assert "comments" not in result[0]

    def test_comment_without_id_skips_reaction_fetch(self) -> None:
        """Skip reaction fetch for comment without id."""
        threads_response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "id": "thread-1",
                                    "isResolved": False,
                                    "path": "file.py",
                                    "line": 10,
                                    "startLine": None,
                                    "originalLine": 10,
                                    "originalStartLine": None,
                                }
                            ],
                        }
                    }
                }
            }
        }
        comments_response = {
            "data": {
                "node": {
                    "comments": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                # Missing 'id'
                                "databaseId": 123,
                                "body": "Test comment",
                                "author": {"login": "user1"},
                                "createdAt": "2024-01-01T00:00:00Z",
                            }
                        ],
                    }
                }
            }
        }

        mock_results = [MagicMock(), MagicMock()]
        mock_results[0].returncode = 0
        mock_results[0].stdout = json.dumps(threads_response)
        mock_results[1].returncode = 0
        mock_results[1].stdout = json.dumps(comments_response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", side_effect=mock_results),
        ):
            result = fetch_unresolved_threads(123)
            assert len(result) == 1
            # Comments should be populated but no reactions key
            assert "comments" in result[0]
            assert "reactions" not in result[0]["comments"]["nodes"][0]


class TestResolveThread:
    """Test resolve_thread function."""

    def test_success_returns_true(self) -> None:
        """Return True when thread is resolved."""
        response = {"data": {"resolveReviewThread": {"thread": {"isResolved": True}}}}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = resolve_thread("thread-id-123")
            assert result is True

    def test_failure_returns_false(self) -> None:
        """Return False when thread resolution fails."""
        response = {"data": {"resolveReviewThread": {"thread": {"isResolved": False}}}}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = resolve_thread("thread-id-123")
            assert result is False

    def test_missing_thread_returns_false(self) -> None:
        """Return False when thread is missing from response."""
        response = {"data": {"resolveReviewThread": {}}}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = resolve_thread("thread-id-123")
            assert result is False


class TestGetPrInfo:
    """Test get_pr_info function."""

    def test_success_returns_pr_info(self) -> None:
        """Return PR info dictionary."""
        response = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "baseRefName": "main",
                        "headRefName": "feature-branch",
                        "state": "OPEN",
                        "title": "Test PR",
                    }
                }
            }
        }
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = get_pr_info(123)
            assert result["base_branch"] == "main"
            assert result["head_branch"] == "feature-branch"
            assert result["state"] == "OPEN"
            assert result["title"] == "Test PR"

    def test_empty_pr_returns_none_values(self) -> None:
        """Return None values when PR fields are missing."""
        response = {"data": {"repository": {"pullRequest": {}}}}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(response)

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = get_pr_info(123)
            assert result["base_branch"] is None
            assert result["head_branch"] is None
            assert result["state"] is None
            assert result["title"] is None


class TestGetPrChangedFiles:
    """Test get_pr_changed_files function."""

    def test_success_returns_file_list(self) -> None:
        """Return list of changed files."""
        output = "file1.py\nfile2.py\nfile3.py"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = output

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = get_pr_changed_files(123)
            assert result == ["file1.py", "file2.py", "file3.py"]

    def test_filters_empty_lines(self) -> None:
        """Filter out empty lines from output."""
        output = "file1.py\n\nfile2.py\n  \n"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = output

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = get_pr_changed_files(123)
            assert result == ["file1.py", "file2.py"]


class TestPostPrComment:
    """Test post_pr_comment function."""

    def test_success_does_not_raise(self) -> None:
        """Complete without error on success."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            post_pr_comment(123, "Test comment")
            # Verify the command was called correctly
            call_args = mock_run.call_args[0][0]
            assert "pr" in call_args
            assert "comment" in call_args
            assert "123" in call_args
            assert "Test comment" in call_args


class TestPostReplyToComment:
    """Test post_reply_to_comment function."""

    def test_success_does_not_raise(self) -> None:
        """Complete without error on success."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            post_reply_to_comment(123, 456, "Reply text")
            # Verify the command was called correctly
            call_args = mock_run.call_args[0][0]
            assert "api" in call_args


class TestMergePr:
    """Test merge_pr function."""

    def test_success_returns_true(self) -> None:
        """Return True on successful merge."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            result = merge_pr(123)
            assert result is True

    def test_failure_returns_false(self) -> None:
        """Return False on failed merge."""
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            result = merge_pr(123)
            assert result is False

    def test_squash_flag_added(self) -> None:
        """Add --squash flag when squash=True."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            merge_pr(123, squash=True)
            call_args = mock_run.call_args[0][0]
            assert "--squash" in call_args

    def test_squash_flag_not_added_when_false(self) -> None:
        """Do not add --squash flag when squash=False."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            merge_pr(123, squash=False)
            call_args = mock_run.call_args[0][0]
            assert "--squash" not in call_args

    def test_auto_flag_added(self) -> None:
        """Add --auto flag when auto=True."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            merge_pr(123, auto=True)
            call_args = mock_run.call_args[0][0]
            assert "--auto" in call_args

    def test_auto_flag_not_added_when_false(self) -> None:
        """Do not add --auto flag when auto=False."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            merge_pr(123, auto=False)
            call_args = mock_run.call_args[0][0]
            assert "--auto" not in call_args


class TestCreatePr:
    """Test create_pr function."""

    def test_success_returns_true_and_output(self) -> None:
        """Return (True, url) on success."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/owner/repo/pull/123\n"

        with patch("subprocess.run", return_value=mock_result):
            success, output = create_pr("/path/to/repo", "Title", "Body", "feature")
            assert success is True
            assert output == "https://github.com/owner/repo/pull/123"

    def test_failure_returns_false_and_error(self) -> None:
        """Return (False, error) on failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error message"

        with patch("subprocess.run", return_value=mock_result):
            success, output = create_pr("/path/to/repo", "Title", "Body", "feature")
            assert success is False
            assert output == "error message"


class TestGetPrForBranch:
    """Test get_pr_for_branch function."""

    def test_returns_pr_info_when_found(self) -> None:
        """Return PR info dict when PR exists."""
        output = json.dumps(
            [
                {
                    "number": 123,
                    "url": "https://github.com/owner/repo/pull/123",
                    "baseRefName": "main",
                }
            ]
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = output

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = get_pr_for_branch("feature-branch")
            assert result is not None
            assert result["pr_number"] == 123
            assert result["pr_url"] == "https://github.com/owner/repo/pull/123"
            assert result["base_branch"] == "main"

    def test_returns_none_when_no_pr(self) -> None:
        """Return None when no PR exists for branch."""
        output = "[]"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = output

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = get_pr_for_branch("feature-branch")
            assert result is None

    def test_invalid_json_raises_error(self) -> None:
        """Raise GraphQLError on invalid JSON."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not json"

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("subprocess.run", return_value=mock_result),
        ):
            with pytest.raises(GraphQLError) as exc_info:
                get_pr_for_branch("feature-branch")
            assert "Invalid JSON" in str(exc_info.value)
