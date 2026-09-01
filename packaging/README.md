# Desktop builds

PhotoVault uses the same Python application entry point on macOS and Windows. Build on the target operating system so PyInstaller bundles that platform's Qt and filesystem behavior.

```bash
cd <project-root>
python3 -m pip install -e '.[desktop,packaging]'
python3 scripts/build_app.py --clean
```

PyInstaller writes `dist/PhotoVault` as a macOS app/bundle or Windows executable. The build includes no catalog or media; the app creates/opens the catalog selected by the user. Before distribution, add code signing/notarization on macOS and signing/installer validation on Windows.

On macOS the verified output is `dist/PhotoVault.app`; the current local build is arm64 and ad hoc signed. Test it with `dist/PhotoVault.app/Contents/MacOS/PhotoVault --help` before signing a release build.
