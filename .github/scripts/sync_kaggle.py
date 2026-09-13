#!/usr/bin/env python3
"""Upload this repo's notebook to the existing Kaggle kernel.

GitHub is the source of truth. Automatic uploads use `kaggle kernels push --no-run`
(Quick Save). A Kaggle run is started only when --run-notebook is passed explicitly.
This script never falls back to a push that executes cells.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
METADATA_NAME = "kernel-metadata.json"
NOTEBOOK_NAME = "kaggle-llm-ngrok.ipynb"
KERNEL_TITLE = "Kaggle-LLM-Ngrok"
PLACEHOLDER_ID_RE = re.compile(
    r"(?i)^(set_|your_|replace_|insert_|todo|changeme|placeholder)"
)
KERNEL_ID_RE = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+$")


class SyncError(SystemExit):
    pass


def fail(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SyncError(code)


def run_kaggle(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Keep the CLI from printing credential material if it debug-logs config.
    env.setdefault("PYTHONUNBUFFERED", "1")
    cmd = ["kaggle", *args]
    result = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if check and result.returncode != 0:
        stderr = redact(result.stderr.strip() or result.stdout.strip() or "kaggle command failed")
        fail(f"Command failed ({result.returncode}): kaggle {' '.join(args)}\n{stderr}")
    return result


def redact(text: str) -> str:
    key = os.environ.get("KAGGLE_KEY", "")
    token = os.environ.get("KAGGLE_API_TOKEN", "")
    if key:
        text = text.replace(key, "***")
    if token:
        text = text.replace(token, "***")
    return text


def require_kaggle_cli_with_no_run() -> None:
    kaggle = shutil.which("kaggle")
    if not kaggle:
        fail(
            "kaggle CLI is not installed. The workflow must pin a CLI that "
            "supports `kaggle kernels push --no-run` (Quick Save)."
        )
    help_result = run_kaggle(["kernels", "push", "-h"], check=False)
    help_text = f"{help_result.stdout}\n{help_result.stderr}"
    if help_result.returncode != 0 or "--no-run" not in help_text:
        version = run_kaggle(["--version"], check=False)
        fail(
            "This kaggle CLI does not support `kaggle kernels push --no-run`.\n"
            "Refusing to push, because the default `kaggle kernels push` starts a run.\n"
            f"Installed: {(version.stdout or version.stderr).strip() or 'unknown'}\n"
            "Install the pinned kaggle-cli git revision from the workflow file."
        )
    print("Verified: `kaggle kernels push --no-run` is available.")


def load_metadata(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"Missing {path}. Commit kernel-metadata.json next to the notebook.")
    except json.JSONDecodeError as exc:
        fail(f"Invalid JSON in {path}: {exc}")
    if not isinstance(data, dict):
        fail(f"{path} must contain a JSON object.")
    return data


def is_placeholder_id(kernel_id: str) -> bool:
    if not kernel_id or "/" not in kernel_id:
        return True
    owner, _, slug = kernel_id.partition("/")
    return (not owner) or (not slug) or bool(PLACEHOLDER_ID_RE.match(owner)) or bool(PLACEHOLDER_ID_RE.match(slug))


def parse_kernel_id(value: str) -> str:
    value = value.strip().rstrip("/")
    value = re.sub(r"^https?://(?:www\.)?kaggle\.com/code/", "", value)
    if not KERNEL_ID_RE.match(value):
        fail(
            f"Invalid Kaggle notebook id {value!r}. Expected owner/slug from "
            "https://www.kaggle.com/code/OWNER/SLUG"
        )
    return value


def require_credentials() -> None:
    username = os.environ.get("KAGGLE_USERNAME", "").strip()
    key = os.environ.get("KAGGLE_KEY", "").strip()
    token = os.environ.get("KAGGLE_API_TOKEN", "").strip()
    if token:
        return
    if username and key:
        return
    fail(
        "Missing Kaggle credentials.\n"
        "Add GitHub Actions repository secrets (Settings → Secrets and variables → Actions):\n"
        "  KAGGLE_USERNAME  — the `username` field from kaggle.json\n"
        "  KAGGLE_KEY       — the `key` field from kaggle.json\n"
        "Create the token at https://www.kaggle.com/settings/account → API → Create New Token.\n"
        "Do not commit kaggle.json."
    )


def kernel_exists(kernel_id: str) -> bool:
    listed = list_my_kernels(strict=False)
    if any(item["ref"] == kernel_id for item in listed):
        return True
    status = run_kaggle(["kernels", "status", kernel_id], check=False)
    combined = f"{status.stdout}\n{status.stderr}".lower()
    if status.returncode == 0:
        return True
    # A kernel that has never been executed can 404 on status; list is authoritative.
    if "404" in combined or "not found" in combined or "was denied" in combined:
        return False
    return False


def list_my_kernels(*, strict: bool = True) -> list[dict[str, str]]:
    result = run_kaggle(
        [
            "kernels",
            "list",
            "--mine",
            "--search",
            KERNEL_TITLE,
            "--page-size",
            "50",
            "--format",
            "json",
        ],
        check=False,
    )
    if result.returncode != 0:
        csv_result = run_kaggle(
            [
                "kernels",
                "list",
                "--mine",
                "--search",
                KERNEL_TITLE,
                "--page-size",
                "50",
                "--csv",
            ],
            check=False,
        )
        if csv_result.returncode != 0:
            if not strict:
                return []
            fail(
                "Could not list your Kaggle notebooks to resolve the existing kernel id.\n"
                + redact(csv_result.stderr or result.stderr or "")
            )
        return parse_kernel_csv(csv_result.stdout)
    text = result.stdout.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return parse_kernel_csv(text)
    rows = payload if isinstance(payload, list) else payload.get("kernels") or payload.get("data") or []
    kernels = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ref = str(row.get("ref") or row.get("id") or "").strip()
        title = str(row.get("title") or "").strip()
        if ref:
            kernels.append({"ref": ref, "title": title})
    return kernels


def parse_kernel_csv(text: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    header = [part.strip() for part in lines[0].split(",")]
    try:
        ref_idx = header.index("ref")
    except ValueError:
        ref_idx = 0
    title_idx = header.index("title") if "title" in header else None
    kernels = []
    for line in lines[1:]:
        parts = [part.strip() for part in line.split(",")]
        if ref_idx >= len(parts):
            continue
        ref = parts[ref_idx]
        title = parts[title_idx] if title_idx is not None and title_idx < len(parts) else ""
        if ref:
            kernels.append({"ref": ref, "title": title})
    return kernels


def resolve_kernel_id(metadata: dict[str, Any]) -> str:
    explicit = os.environ.get("KAGGLE_KERNEL_ID", "").strip()
    if explicit:
        kernel_id = parse_kernel_id(explicit)
        print(f"Using KAGGLE_KERNEL_ID={kernel_id}")
        return kernel_id

    configured = str(metadata.get("id") or "").strip()
    if configured and not is_placeholder_id(configured):
        kernel_id = parse_kernel_id(configured)
        print(f"Using kernel-metadata.json id={kernel_id}")
        return kernel_id

    print("kernel-metadata.json has no existing Kaggle id; searching your notebooks.")
    matches = [row for row in list_my_kernels() if row.get("title") == KERNEL_TITLE]
    if len(matches) == 1:
        kernel_id = parse_kernel_id(matches[0]["ref"])
        print(f"Resolved existing notebook from title {KERNEL_TITLE!r}: {kernel_id}")
        return kernel_id
    if len(matches) > 1:
        refs = ", ".join(row["ref"] for row in matches)
        fail(
            "Multiple Kaggle notebooks share the title "
            f"{KERNEL_TITLE!r}: {refs}\n"
            "Set KAGGLE_KERNEL_ID to the owner/slug from the notebook URL."
        )
    fail(
        "Could not find the existing Kaggle notebook.\n"
        f"Looked for title {KERNEL_TITLE!r} under the authenticated Kaggle account.\n"
        "This workflow will not create a new kernel and will not guess an id "
        "from the GitHub username or repository name.\n\n"
        "Set one of:\n"
        "  • kernel-metadata.json `id` to owner/slug\n"
        "  • GitHub Actions variable/secret KAGGLE_KERNEL_ID=owner/slug\n"
        "Get owner/slug from the notebook URL: https://www.kaggle.com/code/OWNER/SLUG"
    )
    raise AssertionError("unreachable")


def write_resolved_metadata(path: Path, metadata: dict[str, Any], kernel_id: str) -> None:
    metadata = dict(metadata)
    metadata["id"] = kernel_id
    metadata["code_file"] = NOTEBOOK_NAME
    metadata["title"] = metadata.get("title") or KERNEL_TITLE
    path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote resolved metadata id={kernel_id} code_file={NOTEBOOK_NAME}")


def confirm_existing_kernel(kernel_id: str) -> None:
    if kernel_exists(kernel_id):
        print(f"Confirmed existing Kaggle notebook: {kernel_id}")
        return
    fail(
        f"Kaggle notebook {kernel_id!r} was not found on the authenticated account.\n"
        "Refusing to push, because that would create a new kernel.\n"
        "Set KAGGLE_KERNEL_ID to the owner/slug from https://www.kaggle.com/code/OWNER/SLUG"
    )


def push_kernel(*, run_notebook: bool) -> str:
    if run_notebook:
        args = ["kernels", "push", "-p", str(REPO_ROOT)]
        print("Uploading and starting a Kaggle run (explicit --run-notebook).")
    else:
        args = ["kernels", "push", "-p", str(REPO_ROOT), "--no-run"]
        print("Uploading with --no-run (Quick Save; no cell execution).")
    if not run_notebook and "--no-run" not in args:
        fail("Internal error: attempted a no-run push without --no-run.")
    result = run_kaggle(args)
    output = redact((result.stdout or "") + (result.stderr or "")).strip()
    if output:
        print(output)
    return output


def report_status(kernel_id: str, *, run_notebook: bool) -> None:
    url = f"https://www.kaggle.com/code/{kernel_id}"
    print(f"Notebook URL: {url}")
    status = run_kaggle(["kernels", "status", kernel_id], check=False)
    text = redact((status.stdout or status.stderr or "").strip())
    if text:
        print(text)
    if run_notebook:
        print(
            "Run submitted. This notebook may stay up indefinitely (LLM + ngrok); "
            "the workflow does not wait for it to finish."
        )
    else:
        print("Upload complete. No Kaggle execution was requested.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-cli",
        action="store_true",
        help="Verify the pinned kaggle CLI supports --no-run, then exit.",
    )
    parser.add_argument(
        "--run-notebook",
        action="store_true",
        help="Upload and start a Kaggle run. Default is upload without running.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve configuration and validate CLI options without pushing.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_kaggle_cli_with_no_run()
    if args.check_cli:
        return

    notebook = REPO_ROOT / NOTEBOOK_NAME
    metadata_path = REPO_ROOT / METADATA_NAME
    if not notebook.is_file():
        fail(f"Notebook not found: {notebook}")
    metadata = load_metadata(metadata_path)

    if args.dry_run:
        print(f"Notebook: {notebook}")
        print(f"Title: {metadata.get('title')}")
        print(f"code_file: {metadata.get('code_file')}")
        print(f"is_private: {metadata.get('is_private')}")
        print(f"enable_gpu: {metadata.get('enable_gpu')}")
        print(f"enable_internet: {metadata.get('enable_internet')}")
        print(f"machine_shape: {metadata.get('machine_shape')}")
        print(f"dataset_sources: {metadata.get('dataset_sources')}")
        print(f"model_sources: {metadata.get('model_sources')}")
        print("Dry run: not authenticating and not pushing.")
        return

    require_credentials()
    kernel_id = resolve_kernel_id(metadata)
    confirm_existing_kernel(kernel_id)
    write_resolved_metadata(metadata_path, metadata, kernel_id)
    push_kernel(run_notebook=args.run_notebook)
    report_status(kernel_id, run_notebook=args.run_notebook)


if __name__ == "__main__":
    try:
        main()
    except SyncError:
        raise
    except KeyboardInterrupt:
        fail("Interrupted.", 130)
