### Automated review (confidence 58%)

This PR adds a `priority` field to tasks, allowing users to specify the priority level when adding a task. The changes include updates to the CLI for task addition, modifications to the Task model, and adjustments to the database schema to store the priority information.

- **[issue]** `tasktrack/storage.py:10` — The addition of the `priority` field in the `Task` model and its integration into the `add` method of the `Storage` class appears to be implemented correctly. However, the database schema in `storage.py` has been modified to include the `priority` column, which may require a migration for existing databases. Please ensure that there is a migration strategy in place to handle existing data.
- **[suggestion]** `tasktrack/cli.py:8` — The `main` function in `cli.py` has been updated to accept a `--priority` argument when adding a task. This change is straightforward, but it would be beneficial to validate the priority input to ensure it falls within the expected range (0-2). Consider adding validation logic to prevent invalid priority values.
- **[suggestion]** `tasktrack/cli.py:23` — In the `list` command of `cli.py`, the priority is displayed using the `PRIORITY_LABEL` mapping. Ensure that this mapping is comprehensive and handles all possible values of priority correctly. If a priority outside of the defined range is passed, it defaults to '?', which may not be user-friendly. Consider providing feedback for invalid priority values.

**Risks:**
- Potential data loss if existing databases are not migrated correctly to include the new priority field.
- User experience issues if invalid priority values are not handled properly in the CLI.
