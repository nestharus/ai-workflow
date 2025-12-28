class TestMain:
    def test_main_function_is_callable(self) -> None:
        """Test that main function can be imported and is callable."""
        from scripts.dev.markdown.convert_docs_plans_plan import main

        assert callable(main)
