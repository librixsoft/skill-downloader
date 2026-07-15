# skill-downloader

A Python script that searches for and installs Claude/OpenCode skills from GitHub repositories.

## What it does

This script searches GitHub for skills (directories containing a `SKILL.md` file) that match your specified keywords, and downloads them directly to your local skills directory.

The script works in two main phases:

1. **Discovery Phase**: 
   - Uses GitHub's Search API to find:
     - Code files (`SKILL.md`) containing your keywords
     - Repositories whose name/description/topics match your keywords plus "skill"
   - Searches both specific code matches and repository matches

2. **Installation Phase**:
   - Downloads complete repository tarballs via codeload.github.com (bypassing API rate limits)
   - Scans downloaded repositories for directories containing `SKILL.md`
   - Installs matching skill directories to your local skills folder

## Usage

```bash
# Basic usage with keywords
python3 find_and_install_skills.py spring "spring boot" "spring data jpa" "spring security"

# Specify custom installation directory
python3 find_and_install_skills.py --dest /ruta/a/tus/skills spring angular

# Scan specific repository in addition to discovered ones
python3 find_and_install_skills.py --repo tuorg/tus-skills spring

# Recommended: use GitHub token to avoid rate limits
GITHUB_TOKEN=ghp_xxx python3 find_and_install_skills.py spring
```

## Requirements

- Python 3.x
- Internet connection
- Optional: GitHub Personal Access Token (recommended to avoid API rate limits)

## Notes

By default, this script installs skills to the OpenCode skills directory (`~/.config/opencode/skills`), but it works with Claude Code and other agents that use the same skill structure.

## Features

- Search by multiple keywords
- Install to custom destination folder
- Support for scanning specific repositories
- Rate limit handling with token support
- Automatic installation and conflict resolution (won't overwrite existing skills)