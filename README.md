# PR Tracker

PR Tracker is a terminal-based application for tracking GitHub pull requests across multiple repositories. Built with Python and Textual, it provides an intuitive text-based user interface to monitor PRs assigned to you or your team, with features like filtering, pagination, and real-time updates.

<img width="821" height="390" alt="PR Tracker UI" src="https://github.com/user-attachments/assets/6058a42c-ddeb-4e5e-9d6a-35a490e3397a" />

## Prerequisites

- Python 3.11 or higher
- A GitHub account and personal access token (for accessing private repositories)
- [`uv`](https://docs.astral.sh/uv/) package manager (recommended)

## Installation

### Using uv (Recommended)

```bash
# Clone the repository
git clone https://github.com/RavindraGDP/prtrack.git
cd prtrack

# Install dependencies using uv
uv sync

# Install as uv tool
uv tool install .

# use it anywhere
prtrack
```

On first run, the application will create a configuration file at `~/.config/prtrack/config.json`.

### Initial Setup

1. When you first run the application, you'll need to configure it:
## Features

- **Multi-repository tracking**: Monitor pull requests across multiple GitHub repositories
- **User filtering**: Filter PRs by author or assignee to focus on relevant PRs
- **Real-time updates**: Automatic refresh of PR data with configurable staleness threshold
- **Pagination**: Navigate through PRs with page-by-page navigation
- **PR details**: View comprehensive PR information including title, author, assignees, branch, and approval status
- **Direct browser access**: Open PRs directly in your default web browser
- **Individual PR refresh**: Refresh specific PRs without reloading all data
- **Local caching**: Stores PR data locally for faster access and offline viewing
- **Intuitive TUI**: Clean, text-based interface with keyboard navigation
- **Configuration management**: Easily add/remove repositories and configure settings through the UI
 - **Save to Markdown**: Select PRs and export them as a numbered Markdown list in the format `N. [n/2 Approval] [Title](URL)`

   - Press `Enter` to access the main menu
   - Select "Adjust config"
## Configuration

PR Tracker stores its configuration in `~/.config/prtrack/config.json`. You can manage all configuration options through the application's UI:

### Configuration Options

- **Repositories**: Add repositories in `owner/repo` format (e.g., `textualize/textual`)
- **Global users**: Track PRs by specific users across all repositories
- **Per-repository users**: Track PRs by specific users in individual repositories
- **GitHub token**: Personal access token for accessing private repositories
- **Staleness threshold**: Time in seconds before cached data is considered stale (default: 300 seconds)
- **PRs per page**: Number of PRs displayed per page (default: 10)
 - **Key mapping (optional)**: Override default keys for navigation and actions (see Key Customization)

### GitHub Personal Access Token

To access private repositories, you'll need to generate a GitHub personal access token:

1. Go to GitHub Settings > Developer settings > Personal access tokens > Tokens (classic)
## Development Setup

To set up PR Tracker for development:

1. Clone the repository:
   ```bash
   git clone https://github.com/RavindraGDP/prtrack.git
   cd prtrack
   ```

2. Install dependencies using uv (recommended):
   ```bash
   uv sync
   ```

3. Run the application in development mode:
   ```bash
   uv run prtrack
   ```

### Project Structure

- `prtrack/`: Main application package
  - `cli.py`: Command-line interface entry point
  - `tui.py`: Textual TUI application
  - `github.py`: GitHub API client
  - `config.py`: Configuration management
  - `storage.py`: Local data caching
  - `ui/`: UI components
    - `pr_table.py`: Pull request table widget
  - `utils/`: Utility functions
- `tests/`: Unit and integration tests
## Testing

PR Tracker includes a suite of tests to ensure functionality and prevent regressions.

### Running Tests

To run the test suite:

```bash
# Using uv (recommended)
uv run pytest

# Or using pytest directly
pytest
```

## Keyboard Shortcuts

While using PR Tracker, you can navigate and interact with the application using these keyboard shortcuts:

- `↑` / `↓`: Navigate through menu items and PR lists
- `Enter`: Select menu items or open PRs
- `q`: Quit the application
- `Escape`: Return to the main menu
- `Backspace`: Go back (close overlays, return from selection views)
- `r`: Refresh current view
- `]`: Next page (when viewing PRs)
- `[`: Previous page (when viewing PRs)
- `m`: Mark/unmark PR for Markdown while in selection mode

### Markdown Export Flow

1. From the main menu, choose "Save PRs to Markdown".
2. Select by Repo or Account to enter selection mode (you can repeat to add from multiple scopes).
3. In selection mode, move the cursor and press `m` to mark/unmark PRs.
4. Press `Enter` to return to the Markdown menu.
5. Use "Review Selection" to view and deselect (select an item to remove it).
6. Choose "Save Selected to Markdown" and confirm the output path (default: `./pr-track.md`).

The output format per PR is:

```
1. [n/2 Approval] [Title](URL)
```

Where `n` is the current number of approvals (0 if none).

### Key Customization

You can optionally override certain keys via `~/.config/prtrack/config.json` under `keymap`. Defaults live in code and are safe; only your overrides are stored in the file. Supported keys:

- `next_page` (default: "]")
- `prev_page` (default: "[")
- `open_pr` (default: "enter")
- `mark_markdown` (default: "m")
- `back` (default: "backspace")

Example:

```json
{
  "keymap": {
    "mark_markdown": "enter",
    "next_page": "l",
    "prev_page": "h"
  }
}
```

Notes:

- When in Markdown selection mode, mapping `mark_markdown` to `enter` will toggle mark/unmark with Enter. The default Enter action to accept is suppressed while marking, so it works as expected.
- `Escape` always returns to Home; `Backspace` navigates back contextually.

### Test Coverage

To generate a coverage report:

```bash
# Using uv
uv run coverage run -m pytest
uv run coverage report

# Or using coverage directly
coverage run -m pytest
coverage report
```

- `pyproject.toml`: Project configuration and dependencies

2. Generate a new token with `repo` scope
3. Copy the token and add it in PR Tracker through the configuration menu

   - Add repositories you want to track
   - (Optional) Add GitHub personal access token for private repositories
   - (Optional) Add accounts to filter PRs by author or assignee
