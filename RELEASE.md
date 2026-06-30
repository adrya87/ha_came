# Release Process

Use this checklist for each public release.

1. Update the version in:
   - `custom_components/came/manifest.json`
   - `custom_components/came/const.py`
   - `hacs.json`
   - `custom_components/came/hacs.json`
2. Update `CHANGELOG.md` with the release date and summary.
3. Run local validation:
   - `git diff --check`
   - Home Assistant restart or reload test on a real CAME plant when available
4. Commit the release changes.
5. Create an annotated tag:

   ```bash
   git tag -a v1.1.0 -m "Release v1.1.0"
   ```

6. Push the branch and tag:

   ```bash
   git push
   git push origin v1.1.0
   ```

7. The GitHub Actions release workflow will build `came.zip`, publish it on the GitHub Release, and generate release notes.

For HACS users, releases should use tags in the `vMAJOR.MINOR.PATCH` format.
