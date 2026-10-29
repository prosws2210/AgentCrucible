import argparse

import anyio
from pr_reviewer.review import review_pull_request


def cli() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("repo")
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--build", type=int, required=True)
    args = p.parse_args()
    print(anyio.run(review_pull_request, args.repo, args.pr, args.build))


if __name__ == "__main__":
    cli()
