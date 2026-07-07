Review the Git history since the latest published/released version and prepare a version upgrade following SemVer conventions.

Tasks:

1. Identify the latest published/released version:
   - Check existing Git tags.
   - Check package/release metadata if applicable.
   - Use the latest valid SemVer version as the baseline.
   - Detect the repository’s existing version/tag naming convention, for example `v1.2.3` or `1.2.3`.

2. Inspect the Git log from that version up to HEAD:
   - Determine whether the changes require a PATCH, MINOR, or MAJOR version bump.
   - Follow SemVer rules:
     - PATCH for backwards-compatible bug fixes.
     - MINOR for backwards-compatible new features.
     - MAJOR for breaking changes, except for versions below 1.0.0.
   - If there are breaking changes, explain which commits/changes justify the selected bump.

3. Handle pre-1.0.0 versions correctly:
   - If the latest version is below 1.0.0, treat the public API as unstable.
   - Do not bump directly to 1.0.0 unless there is clear evidence that this release is intended to be the first stable release.
   - For versions below 1.0.0:
     - Use PATCH for backwards-compatible bug fixes.
     - Use MINOR for new features or breaking changes.
     - Use MAJOR only to move from 0.x.y to 1.0.0 when the project is explicitly ready for a stable public API.
   - If the repository has an existing pre-1.0 versioning convention, follow that convention and explain it.

4. Update the version everywhere it appears:
   - Primary project metadata files, such as package.json, pyproject.toml, Cargo.toml, composer.json, etc.
   - Lock files, if applicable.
   - Changelog/release notes, if the project has a CHANGELOG or equivalent.
   - Any other files that explicitly contain the current version.

5. If a changelog exists:
   - Add or update the entry for the new version.
   - Summarize the relevant changes from the Git log.
   - Keep the existing changelog format.

6. Create a Git commit for the version bump:
   - Use the repository’s existing commit message convention if there is one.
   - Otherwise use a clear message such as `chore: release vX.Y.Z`.

7. Create a Git tag for the new version:
   - Use the repository’s existing tag naming convention, for example `v1.2.3` or `1.2.3`.
   - Prefer an annotated tag if the repository already uses annotated tags.
   - Use a concise tag message such as `Release vX.Y.Z`.

Important constraints:
- Do not push commits.
- Do not push tags.
- Do not publish or release anything.
- Only prepare the local version bump, commit, and tag.
- Before making changes, briefly explain:
  - The detected latest version.
  - The selected new version.
  - The SemVer bump type.
  - The reasoning behind the bump.
  - Any files that are expected to be updated.