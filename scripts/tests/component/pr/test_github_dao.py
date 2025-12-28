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
    def test_gh_not_found_error_message(self) -> None:
        """GhNotFoundError has correct default message."""
        error = GhNotFoundError()
        assert "gh executable not found on PATH" in str(error)

    def test_graphql_error_message(self) -> None:
        """GraphQLError stores the provided message."""
        error = GraphQLError("Test error message")
        assert "Test error message" in str(error)
