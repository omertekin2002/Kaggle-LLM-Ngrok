# Kaggle-LLM-Ngrok

GitHub is the source of truth for this notebook. Kaggle receives copies from GitHub Actions. Do not treat a Kaggle Quick Save as the latest code.

The notebook serves an LLM through ngrok and may run indefinitely. Automatic GitHub → Kaggle sync **uploads without executing cells** and must not start another GPU session.

Target notebook: [omert3kin/kaggle-llm-ngrok](https://www.kaggle.com/code/omert3kin/kaggle-llm-ngrok) (private). That id is in `kernel-metadata.json`.

## One-time setup

Kaggle’s current API page copies a token. It does **not** download `kaggle.json` unless you use the legacy button.

1. Open [https://www.kaggle.com/settings/api](https://www.kaggle.com/settings/api).
2. If you already generated a token, copy that string. If not, click **Generate New Token**.
3. In this GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**.
   - Name: `KAGGLE_API_TOKEN`
   - Value: the token you copied (one long string)
4. Commit and push this workflow to `main`. Leave **Run notebook on Kaggle after upload** unchecked.

Optional legacy path: on the same Kaggle API page, **Create Legacy API Key** downloads `kaggle.json`. Then add secrets `KAGGLE_USERNAME` and `KAGGLE_KEY` instead. Do not commit `kaggle.json`.

## Automatic sync

Pushes to `main` that change `kaggle-llm-ngrok.ipynb` or `kernel-metadata.json` upload to the **existing** Kaggle notebook with:

```text
kaggle kernels push --no-run
```

That is Kaggle Quick Save: a new version is stored, cells do not run, and a GPU instance is not started. The job does not wait for execution.

## Manual run

**Actions → Sync notebook to Kaggle → Run workflow**. Set **Run notebook on Kaggle after upload** to `true` only when you want Kaggle to execute the notebook (GPU + ngrok server). The workflow submits the job, prints the notebook URL and current status, and exits. It does not wait for the long-running server to finish.

Any other trigger, including a manual run with the checkbox left false, uses `--no-run`.

## Avoid overwriting GitHub

Kaggle can still push an older copy back to this repo if GitHub integration is connected.

- After you edit on GitHub, wait for the sync workflow to finish before opening the notebook on Kaggle, then **refresh** so Kaggle shows the new version.
- Do not Quick Save from Kaggle onto GitHub unless Kaggle is showing the version you just synced. Saving an older Kaggle buffer will overwrite `main`.
- If that happens, restore the GitHub commit and let the workflow upload it to Kaggle again.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| Job fails: missing credentials | Add GitHub secret `KAGGLE_API_TOKEN` from [kaggle.com/settings/api](https://www.kaggle.com/settings/api). Never paste it into the notebook or this repo. |
| Job fails: could not find the existing notebook | Confirm `kernel-metadata.json` `id` is `omert3kin/kaggle-llm-ngrok` and that `KAGGLE_USERNAME` is the Kaggle user `omert3kin`, not the GitHub user `omertekin2002`. |
| Job fails: CLI does not support `--no-run` | The workflow pins kaggle-cli git SHA `c1c33512`. PyPI `kaggle==2.2.4` still starts a run on push, and `kaggle --version` may still print 2.2.4 even from that SHA. Do not switch the install to unpinned `pip install kaggle`. |
| GPU session appeared after a GitHub push | The automatic path must use `--no-run`. Check the Actions log for that flag. A manual run with the checkbox set to true is the only path that starts execution. |
| Kaggle still has old code | Confirm the workflow ran on the commit you care about. On Kaggle, reload the notebook from **File** / versions rather than an open interactive session. |

`kernel-metadata.json` keeps the notebook private, internet on, GPU T4 (`NvidiaTeslaT4`), and no attached datasets or models — matching the last Kaggle export. Edit that file if those settings should change, then push.
