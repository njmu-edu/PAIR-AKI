"""Reject private workspace material from the public tree and every reachable Git commit."""
from pathlib import Path
import re
import ipaddress
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_PARTS = {'docs','.codex','.claude','.codebuddy','node_modules','__pycache__','data','models','checkpoints','outputs'}
BLOCKED_NAMES = {'agents.md','todo.md','steps.md','decisions.md','.env'}
BLOCKED_SUFFIXES = {'.pt','.safetensors','.sqlite','.sqlite3','.log','.pem','.key'}
CONTENT_RULES = [
    re.compile(r'/(?:Users|home|srv)/[^\s"\'<>]+'),
    re.compile(r'gh[opusr]_[A-Za-z0-9]{30,}'),
    re.compile(r'github_pat_[A-Za-z0-9_]{30,}'),
    re.compile(r'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----'),
    re.compile(r'\b(?:TD-\d{2,}|D-COMP-\d+)\b'),
    re.compile(r'(?im)^\s*(?:password|api_key|access_token)\s*[:=]\s*["\']?[A-Za-z0-9_/-]{16,}'),
]


def check(name, raw):
    parts=Path(name).parts
    if (set(parts)&BLOCKED_PARTS or Path(name).name.lower() in BLOCKED_NAMES or Path(name).suffix in BLOCKED_SUFFIXES):
        raise ValueError('Forbidden publication path: '+name)
    if raw.startswith(b'version https://git-lfs.github.com/spec'):
        raise ValueError('Unexpected LFS pointer: '+name)
    if name.endswith('.png'):
        if len(raw)>2_000_000:raise ValueError('Oversized image')
        return
    text=raw.decode('utf8')
    # Scanner definitions are not application data or credentials.
    if name=='tools/check_publication.py':return
    for match in re.finditer(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', text):
        try:
            address = ipaddress.ip_address(match.group())
        except ValueError:
            continue
        if not address.is_loopback and not address.is_unspecified:
            raise ValueError('Non-example network endpoint: '+name)
    for rule in CONTENT_RULES:
        if rule.search(text):raise ValueError('Private content pattern: '+name)


def main():
    files=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    files=[f for f in files if f]
    if not files:raise ValueError('Stage the explicit publication files before scanning')
    for name in files:
        p=ROOT/name
        if p.is_symlink():raise ValueError('Symlink is not a publication input: '+name)
        check(name,p.read_bytes())
    commits=subprocess.run(['git','rev-list','--all'],cwd=ROOT,capture_output=True,text=True)
    for commit in commits.stdout.splitlines():
        entries=subprocess.check_output(['git','ls-tree','-r','--name-only',commit],cwd=ROOT,text=True).splitlines()
        for name in entries:
            check(name,subprocess.check_output(['git','show',commit+':'+name],cwd=ROOT))
    print(f'Publication scan passed: {len(files)} tracked files; {len(commits.stdout.splitlines())} reachable commits.')


if __name__=='__main__':main()
