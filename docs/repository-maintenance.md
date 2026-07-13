# Repository Maintenance

## Public Repository Rules

- Keep the default branch named `main`.
- Use the maintainer's configured Git credential helper; never store a token in this repository.
- Keep the bundled portfolio synthetic and clearly labelled as demonstration data.
- Never copy a private operational database or account snapshot into a commit, fixture, issue, or release artifact.

## Upload Procedure

Preferred target repo name for this project:

- `https://github.com/ddbbiii/semi-auto-trading-assistant`

If this repo is recloned or remote setup is lost, bind and push:

```powershell
git remote add origin <target-repo-url>
git push -u origin main
```

Before pushing:

```powershell
git status --short --branch
python -m unittest discover -s tests
```

Do not commit `.env`, local databases, logs, broker credentials, account exports, cookies, tokens, or OpenD runtime files.

Before publishing, scan the full reachable history and generated release artifacts for secrets, local paths, account values, holdings and broker exports.
