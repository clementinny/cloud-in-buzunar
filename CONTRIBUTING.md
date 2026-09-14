# Contributing

CloudInBuzunar is a personal engineering project, but focused bug reports and
small improvements are welcome.

## Before opening an issue

- Check the existing issues first.
- Do not include passwords, pairing tokens, private IP addresses or personal
  files in screenshots and logs.
- Mention the Android version, Termux version and phone model when the problem
  is device-specific.
- For crashes, include the exact steps that reproduce the problem and the
  relevant sanitized log excerpt.

## Proposing a change

1. Fork the repository and create a short feature branch.
2. Keep the change focused and preserve the separation between source code and
   `~/cloud-in-buzunar-data`.
3. Add or update tests when behaviour changes.
4. Run the local verification commands from the README.
5. Open a pull request explaining the problem, the solution and how it was
   tested.

Hardware-dependent behaviour should be described as tested only when it has
actually been verified on a physical phone.
