#!/usr/bin/env python3
"""
Syncs real-time module count, commit count, and skill count into docs/index.html.
Updates placeholders <!-- MODULE_COUNT -->, <!-- COMMIT_COUNT -->, <!-- SKILL_COUNT -->.
"""
import os
import subprocess
import glob

# Path to the HTML file
HTML_PATH = os.path.join('docs', 'index.html')

def count_modules():
    """Count all .py files in the project root directory."""
    # Get all .py files in the current directory (project root)
    py_files = glob.glob('*.py')
    return len(py_files)

def count_commits():
    """Get the total number of git commits in the repository."""
    try:
        result = subprocess.run(
            ['git', 'rev-list', '--count', 'HEAD'],
            capture_output=True, text=True, check=True
        )
        return int(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        # Fallback: return 0 if git not available or error
        return 0

def count_skills():
    """Get the number of skills from the skillgraph module."""
    try:
        import skillgraph
        # Try common attributes for skill count
        if hasattr(skillgraph, 'skills'):
            return len(skillgraph.skills)
        elif hasattr(skillgraph, 'get_skills'):
            return len(skillgraph.get_skills())
        else:
            return 0
    except ImportError:
        return 0

def update_html():
    """Read HTML, replace placeholders with counts, and write back."""
    if not os.path.exists(HTML_PATH):
        print(f"Error: {HTML_PATH} not found.")
        return

    with open(HTML_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    module_count = count_modules()
    commit_count = count_commits()
    skill_count = count_skills()

    # Replace placeholders
    content = content.replace('<!-- MODULE_COUNT -->', str(module_count))
    content = content.replace('<!-- COMMIT_COUNT -->', str(commit_count))
    content = content.replace('<!-- SKILL_COUNT -->', str(skill_count))

    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"Synced docs/index.html: modules={module_count}, commits={commit_count}, skills={skill_count}")

if __name__ == '__main__':
    update_html()
