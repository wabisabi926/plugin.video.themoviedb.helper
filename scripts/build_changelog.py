"""Build a grouped changelog from git history for a release."""

import argparse
import re
import subprocess
import sys

CATEGORIES = (
    ('sparkles', '新功能'),
    ('bug', '修复'),
    ('zap', '优化'),
    ('globe_with_meridians', '翻译'),
    ('lipstick', '界面'),
    ('memo', '文档'),
    ('wastebasket', '移除'),
)
FALLBACK = '其他'
SKIP = ('bookmark', 'robot', 'twisted_rightwards_arrows', 'construction')
DEFAULT_MATCH = 'douban-*'


def git(*args):
    return subprocess.check_output(('git',) + args, text=True).strip()


def get_previous_tag(match=DEFAULT_MATCH):
    """Return the most recent matching tag reachable from HEAD, or None."""
    try:
        return git('describe', '--tags', '--abbrev=0', '--match', match)
    except subprocess.CalledProcessError:
        return None


def get_repo_slug():
    """Return 'owner/repo' parsed from the origin remote, or None."""
    try:
        url = git('config', '--get', 'remote.origin.url')
    except subprocess.CalledProcessError:
        return None
    match = re.search(r'github\.com[:/]([^/]+)/(.+?)(?:\.git)?$', url)
    return f'{match.group(1)}/{match.group(2)}' if match else None


def get_subjects(start, end):
    revision = f'{start}..{end}' if start else end
    output = git('log', '--no-merges', '--first-parent', '--format=%s', revision)
    return [line.strip() for line in output.splitlines() if line.strip()]


def split_subject(subject):
    """Split ':shortcode: description' into (shortcode, description)."""
    if not subject.startswith(':'):
        return None, subject
    end = subject.find(':', 1)
    if end < 0:
        return None, subject
    return subject[1:end], subject[end + 1:].strip()


def group_subjects(subjects):
    buckets = {name: [] for _, name in CATEGORIES}
    buckets[FALLBACK] = []
    for subject in subjects:
        shortcode, description = split_subject(subject)
        if shortcode in SKIP:
            continue
        for key, name in CATEGORIES:
            if shortcode == key:
                buckets[name].append(description)
                break
        else:
            buckets[FALLBACK].append(description)
    return buckets


def render(buckets, start, end, slug=None, compare_to=None):
    if not any(buckets.values()):
        return ''
    lines = []
    if start:
        lines.extend((f'自 `{start}` 以来的变更：', ''))
    for _, name in CATEGORIES:
        items = buckets[name]
        if not items:
            continue
        lines.append(f'### {name}')
        lines.extend(f'- {item}' for item in items)
        lines.append('')
    if buckets[FALLBACK]:
        lines.append(f'### {FALLBACK}')
        lines.extend(f'- {item}' for item in buckets[FALLBACK])
        lines.append('')
    target = compare_to or end
    if start and slug:
        lines.extend((f'**完整变更**: https://github.com/{slug}/compare/{start}...{target}', ''))
    return '\n'.join(lines).rstrip() + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from', dest='start', help='Start revision (default: previous douban-* tag)')
    parser.add_argument('--to', dest='end', default='HEAD', help='End revision (default: HEAD)')
    parser.add_argument('--match', default=DEFAULT_MATCH, help='Tag glob used to find the start revision')
    parser.add_argument('--compare-to', help='Right-hand side of the compare link (default: --to)')
    parser.add_argument('--output', help='Write to this file instead of stdout')
    args = parser.parse_args()

    start = args.start or get_previous_tag(args.match)
    text = render(
        group_subjects(get_subjects(start, args.end)),
        start, args.end,
        slug=get_repo_slug(),
        compare_to=args.compare_to,
    )

    if args.output:
        with open(args.output, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
        return
    sys.stdout.write(text)


if __name__ == '__main__':
    main()
