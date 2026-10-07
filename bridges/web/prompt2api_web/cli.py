import argparse
import asyncio
from pathlib import Path

from .app import create_app
from .browser import BrowserProvider
from .config import load_settings
from .providers import SPECS
from .providers.base import BrowserSettings


async def prepare(args):
    # User reviews website notices directly; Grok can remain signed out.
    provider = BrowserProvider(
        SPECS[args.provider],
        BrowserSettings(
            profile_root=Path(args.profile_root).expanduser(),
            headless=False,
            channel=args.channel,
            executable_path=args.executable_path,
        ),
    )
    try:
        await provider.start()
        page = (
            provider.context.pages[0]
            if provider.context.pages
            else await provider.context.new_page()
        )
        await page.goto(provider.spec.url, wait_until="domcontentloaded")
        if args.provider in ("grok", "chatgpt"):
            print(
                f"Use {args.provider} signed out. No account or sign-in is required by this bridge."
            )
            print("Review any website notices and check that the anonymous chat box is available.")
        else:
            print(f"Review website notices and account requirements in the {args.provider} window.")
        print(
            "The profile is stored locally. Do not run serve/prepare against the same profile together."
        )
        await asyncio.to_thread(input, "Press Enter here when finished: ")
    finally:
        await provider.close()


def main():
    parser = argparse.ArgumentParser(description="Prompt2API local web-chat provider bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--config")
    auth = sub.add_parser(
        "prepare",
        aliases=["login"],
        help="Open the website for setup; Grok/ChatGPT can stay signed out",
    )
    auth.add_argument("provider", choices=list(SPECS))
    auth.add_argument("--profile-root", default="~/.prompt2api-web/profiles")
    auth.add_argument("--channel", help="Use an installed browser channel, e.g. chrome")
    auth.add_argument("--executable-path", help="Path to a locally installed Chromium browser")
    args = parser.parse_args()
    if args.command in ("prepare", "login"):
        asyncio.run(prepare(args))
    else:
        import uvicorn

        settings = load_settings(args.config)
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
