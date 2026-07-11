"""GitHubプロフィールREADMEの最低限の品質を検証する。"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

REQUIRED_HEADINGS = (
    "Open Source",
    "NiAkaDo / NiAka堂",
    "Web Development",
    "Web × VRChat",
    "VRChat Worlds",
    "About",
)

REQUIRED_LINKS = (
    "https://github.com/niaka3dayo/agent-skills-vrc-udon",
    "https://niaka.booth.pm/",
    "https://vpm.2aka.io/",
    "https://vrc-aquelia.com/",
)

FORBIDDEN_TEXT = (
    "NiAka / なゆ",
    "コードと世界の境界を設計する",
    "TODO",
    "TBD",
    "_private",
)

ASSET_PATTERN = re.compile(
    r"(?:src|srcset)=[\"']([^\"']+)[\"']|!\[[^\]]*\]\(([^)\s]+)",
    re.IGNORECASE,
)


def find_local_assets(markdown: str) -> set[str]:
    """Markdown/HTML内のローカル画像参照を抽出する。"""
    assets: set[str] = set()
    for match in ASSET_PATTERN.finditer(markdown):
        raw = match.group(1) or match.group(2)
        if not raw:
            continue
        value = unquote(raw.split("#", 1)[0].split("?", 1)[0])
        if value.startswith(("./assets/", "assets/")):
            assets.add(value.removeprefix("./"))
    return assets


def main() -> int:
    errors: list[str] = []

    if not README.exists():
        print("ERROR: README.md がありません。", file=sys.stderr)
        return 1

    text = README.read_text(encoding="utf-8")

    for heading in REQUIRED_HEADINGS:
        if not re.search(rf"^##\s+{re.escape(heading)}\s*$", text, re.MULTILINE):
            errors.append(f"必須見出しがありません: {heading}")

    for link in REQUIRED_LINKS:
        if link not in text:
            errors.append(f"必須リンクがありません: {link}")

    for forbidden in FORBIDDEN_TEXT:
        if forbidden.casefold() in text.casefold():
            errors.append(f"公開READMEに含めない文字列があります: {forbidden}")

    email_pattern = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
    if email_pattern.search(text):
        errors.append("メールアドレスらしき文字列があります。公開前に確認してください。")

    assets = find_local_assets(text)
    if not assets:
        errors.append("ローカル画像が参照されていません。")

    root_resolved = ROOT.resolve()
    for relative in sorted(assets):
        path = (ROOT / relative).resolve()
        if root_resolved not in path.parents:
            errors.append(f"リポジトリ外を参照しています: {relative}")
            continue
        if not path.is_file():
            errors.append(f"画像がありません: {relative}")
            continue
        if path.stat().st_size > 500 * 1024:
            errors.append(f"画像が500KBを超えています: {relative}")

    if errors:
        print("プロフィールREADMEの検証に失敗しました:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"OK: README.md と画像 {len(assets)} 件を検証しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
