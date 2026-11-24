"""Allow only explicitly approved source paths; inspect staged content for credential patterns."""
import re
import subprocess
from pathlib import PurePosixPath

ROOT_FILES = {'README.md', 'PROJECT_SPEC.md', 'PROGRESS.md', 'CHANGELOG.md', 'DEPLOYMENT.md',
              'ACCEPTANCE.md', 'TEST_RESULTS.txt', 'requirements.txt', 'main.py',
              '.gitignore', '.env.example', 'example_report.json', 'example_report.md'}
NAMED_FILES = {'examples/aliases.json', 'examples/emails.json', 'examples/jobs.json',
               '.github/workflows/ci.yml', 'scripts/validate_repository.py', 'scripts/package_release.py',
               'config/review.example.json'}
DIRECTORIES = {'job_agent', 'tests'}
SECRET = re.compile(rb'(?i)(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|gh[pousr]_[a-z0-9]{32,}|'
                    rb'github_pat_[a-z0-9_]{30,}|ya29\.[\w-]{20,}|(?:secret_|ntn_)[a-z0-9]{40,})')


def allowed(path):
    parts = PurePosixPath(path).parts
    return (path in ROOT_FILES or path in NAMED_FILES
            or len(parts) == 2 and parts[0] in DIRECTORIES
            and bool(re.fullmatch(r'[a-z][a-z0-9_]*\.py', parts[1])))


def main():
    names = subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0')
    problems = []
    for name in filter(None, names):
        if not allowed(name):
            problems.append(f'Path outside repository allowlist: {name}')
            continue
        staged = subprocess.check_output(['git', 'show', ':' + name])
        if SECRET.search(staged):
            problems.append(f'Potential credential in staged file: {name}')
    if problems:
        raise SystemExit('\n'.join(problems))
    print('Tracked paths and staged credential patterns passed')


if __name__ == '__main__':
    main()
