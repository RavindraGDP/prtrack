# PR Tracker

PR Tracker is a terminal-based application for tracking GitHub pull requests across multiple repositories. Built with Python and Textual, it provides an intuitive text-based user interface to monitor PRs assigned to you or your team, with features like filtering, pagination, and real-time updates.

![PR Tracker TUI](https://raw.githubusercontent.com/Textualize/textual/main/imgs/textual.png)  <!-- Replace with actual screenshot when available -->

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
```

### Using pip

```bash
# Clone the repository
git clone https://github.com/RavindraGDP/prtrack.git
cd prtrack

## Usage

After installation, you can run PR Tracker using the following command:

```bash
uv run prtrack
```

Or if you installed with pip:

```bash
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

4. For development, you can also run the application directly:
   ```bash
   python -m main
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
- `r`: Refresh current view
- `]`: Next page (when viewing PRs)
- `[`: Previous page (when viewing PRs)

### Test Coverage

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

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

# Create a virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install .
```
